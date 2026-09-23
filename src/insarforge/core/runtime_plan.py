"""Pure static runtime planning and explicit resource accounting."""

from dataclasses import dataclass
from types import MappingProxyType

from insarforge.contracts.context import ResourceAllocation
from insarforge.contracts.errors import ContractError
from insarforge.contracts.execution import OutputRef, WorkflowPlan
from insarforge.contracts.values import freeze_json
from insarforge.products.validation import ProductValidationReport


def allocation(request, budget):
    if type(budget) is not ResourceAllocation:
        raise ContractError("RESOURCE_BUDGET")
    if (
        request.cpu_cores > budget.cpu_cores
        or request.gpu_count > budget.gpu_count
        or (
            request.memory_bytes is not None
            and (
                budget.memory_bytes is None
                or request.memory_bytes > budget.memory_bytes
            )
        )
    ):
        raise ContractError("RESOURCE_IMPOSSIBLE")
    return ResourceAllocation(
        request.cpu_cores, request.memory_bytes, request.gpu_count
    )


def validate_task(task, registry, budget):
    if not registry.is_sealed:
        raise ContractError("REGISTRY_NOT_SEALED")
    binding = registry.resolve_binding(
        task.plugin_ref, task.operation_id, task.operation_api_version
    )
    allocation(task.resources, budget)
    if set(task.inputs) != {p.port_id for p in binding.inputs}:
        raise ContractError("STATIC_INPUT_PORTS")
    expected = tuple(
        (
            p.port_id,
            p.schema.schema_id,
            p.schema.schema_version,
            p.count,
            None if p.profile is None else p.profile.profile_id,
            None if p.profile is None else p.profile.profile_version,
        )
        for p in binding.outputs
    )
    if expected != tuple(
        (
            p.port,
            p.schema_id,
            p.schema_version,
            p.count,
            p.profile_id,
            p.profile_version,
        )
        for p in task.outputs
    ):
        raise ContractError("STATIC_OUTPUT_PORTS")
    report = binding.handler.validate_spec(
        task.semantic_parameters, binding.inputs, binding.outputs
    )
    if type(report) is not ProductValidationReport or not report.is_valid:
        raise ContractError("STATIC_PARAMETERS")
    return binding


@dataclass(frozen=True)
class PlanReport:
    plan_digest: str
    tasks: object
    runtime_availability: str = "UNCHECKED"

    def __post_init__(self):
        object.__setattr__(self, "tasks", freeze_json(self.tasks))


def dry_run(plan, sealed_registry, *, budget):
    if type(plan) is not WorkflowPlan:
        raise ContractError("PLAN_TYPE")
    reports = []
    for name in plan.topological_order():
        task = plan.task(name)
        b = validate_task(task, sealed_registry, budget)
        for port in b.inputs:
            count = 0
            for source in task.inputs[port.port_id]:
                if type(source) is OutputRef:
                    declared = next(
                        p
                        for p in plan.task(source.task_id).outputs
                        if p.port == source.port
                    )
                    schema = (declared.schema_id, declared.schema_version)
                    profile = (
                        None
                        if declared.profile_id is None
                        else (declared.profile_id, declared.profile_version)
                    )
                    required = (
                        None
                        if port.profile is None
                        else (port.profile.profile_id, port.profile.profile_version)
                    )
                    if required is not None and profile != required:
                        raise ContractError("STATIC_INPUT_PROFILE")
                    count += declared.count
                else:
                    schema = (source.schema_id, source.schema_version)
                    count += 1
                if schema != (port.schema.schema_id, port.schema.schema_version):
                    raise ContractError("STATIC_INPUT_SCHEMA")
            if count < port.min_count or (
                port.max_count is not None and count > port.max_count
            ):
                raise ContractError("STATIC_INPUT_COUNT")
        reasons = ["EXECUTION_IDENTITY_UNPROBED"]
        if any(type(s) is OutputRef for refs in task.inputs.values() for s in refs):
            reasons.append("UPSTREAM_OUTPUT_PENDING")
        reports.append(
            dict(
                task_id=name,
                fingerprint=None,
                identity_status="UNRESOLVED",
                reasons=reasons,
            )
        )
    return PlanReport(plan.digest, reports)


@dataclass(frozen=True)
class RunResult:
    run_id: str
    status: str
    states: object
    outputs: object
    completion_order: tuple[str, ...]

    def __post_init__(self):
        object.__setattr__(self, "states", MappingProxyType(dict(self.states)))
        object.__setattr__(
            self,
            "outputs",
            MappingProxyType(
                {k: MappingProxyType(dict(v)) for k, v in self.outputs.items()}
            ),
        )
        object.__setattr__(self, "completion_order", tuple(self.completion_order))
