"""Static operation validation and explicit plan-file I/O; no execution."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from insarforge.contracts.errors import ContractError, WorkspaceError
from insarforge.contracts.execution import OutputRef, WorkflowPlan
from insarforge.contracts.values import ArtifactRef
from insarforge.core.registry import PluginRegistry
from insarforge.products.validation import (
    ProductValidationReport,
    ValidationIssue,
    ValidationIssueKind,
)


def validate_plan(
    plan: WorkflowPlan, registry: PluginRegistry
) -> ProductValidationReport:
    """Validate static declarations; UNVERIFIED entries identify runtime obligations.

    Malformed registry/API lookups raise the existing domain errors. A returned
    report is valid only when it has no ERROR; UNVERIFIED never means verified.
    Only the declared pure handler.validate_spec callback is invoked.
    """
    if type(plan) is not WorkflowPlan:
        raise ContractError("PLAN_TYPE")
    if type(registry) is not PluginRegistry or not registry.is_sealed:
        raise ContractError("PLAN_REGISTRY_UNSEALED")
    issues = []

    def issue(kind, code, location):
        issues.append(ValidationIssue(kind, code, location, {}))

    error, pending = ValidationIssueKind.ERROR, ValidationIssueKind.UNVERIFIED
    for task in plan.tasks:
        registration = registry.resolve(task.plugin_ref)
        binding = registry.resolve_binding(
            task.plugin_ref, task.operation_id, task.operation_api_version
        )
        if not set(binding.required_capabilities).issubset(
            registration.descriptor.capabilities
        ):
            issue(error, "PLAN_CAPABILITY", task.task_id)
        inputs = {port.port_id: port for port in binding.inputs}
        outputs = {port.port_id: port for port in binding.outputs}
        if set(inputs) != set(task.inputs) or set(outputs) != {
            port.port for port in task.outputs
        }:
            issue(error, "PLAN_PORT_SET", task.task_id)
        for out in task.outputs:
            if out.port not in outputs:
                continue
            expected = outputs[out.port]
            profile = (
                None
                if expected.profile is None
                else (expected.profile.profile_id, expected.profile.profile_version)
            )
            declared = (
                None
                if out.profile_id is None
                else (out.profile_id, out.profile_version)
            )
            if (
                (out.schema_id, out.schema_version)
                != (expected.schema.schema_id, expected.schema.schema_version)
                or out.count != expected.count
                or declared != profile
            ):
                issue(error, "PLAN_OUTPUT_CONTRACT", task.task_id)
        for name, sources in task.inputs.items():
            if name not in inputs:
                continue
            expected = inputs[name]
            count = 0
            for source in sources:
                if type(source) is OutputRef:
                    declaration = next(
                        out
                        for out in plan.task(source.task_id).outputs
                        if out.port == source.port
                    )
                    schema = declaration.schema_id, declaration.schema_version
                    count += declaration.count
                    if expected.profile is not None and (
                        declaration.profile_id,
                        declaration.profile_version,
                    ) != (
                        expected.profile.profile_id,
                        expected.profile.profile_version,
                    ):
                        issue(error, "PLAN_INPUT_PROFILE", task.task_id)
                elif type(source) is ArtifactRef:
                    schema = source.schema_id, source.schema_version
                    count += 1
                    issue(pending, "PLAN_EXTERNAL_RECORD_UNVERIFIED", task.task_id)
                    if expected.profile is not None:
                        issue(pending, "PLAN_EXTERNAL_PROFILE_UNVERIFIED", task.task_id)
                if schema != (
                    expected.schema.schema_id,
                    expected.schema.schema_version,
                ):
                    issue(error, "PLAN_INPUT_SCHEMA", task.task_id)
            if count < expected.min_count or (
                expected.max_count is not None and count > expected.max_count
            ):
                issue(error, "PLAN_INPUT_COUNT", task.task_id)
        try:
            report = binding.handler.validate_spec(
                task.semantic_parameters, binding.inputs, binding.outputs
            )
        except Exception:
            # An adapter failure is never success or a retry decision. Suppress
            # arbitrary callback text at this explicit extension boundary.
            raise ContractError("PLAN_HANDLER_VALIDATION") from None
        if type(report) is not ProductValidationReport:
            raise ContractError("PLAN_HANDLER_REPORT")
        # Preserve actual ERROR and UNVERIFIED distinctions, not report truthiness.
        issues.extend(report.issues)
        issue(pending, "PLAN_RUNTIME_ENVIRONMENT_UNVERIFIED", task.task_id)
    return ProductValidationReport(tuple(issues))


def save_plan(plan: WorkflowPlan, path: str | Path) -> None:
    """Write only the explicit plan file, after all structural/secret checks."""
    if type(plan) is not WorkflowPlan:
        raise ContractError("PLAN_TYPE")
    payload = plan.to_json()
    temporary = None
    try:
        target = Path(path)
        with tempfile.NamedTemporaryFile(
            dir=target.parent, prefix=".plan-", delete=False
        ) as handle:
            temporary = handle.name
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
        temporary = None
    except (OSError, TypeError, ValueError):
        raise WorkspaceError("PLAN_WRITE_FAILED") from None
    finally:
        if temporary is not None:
            try:
                os.unlink(temporary)
            except OSError:
                pass


def load_plan(path: str | Path, registry: PluginRegistry) -> WorkflowPlan:
    """Read one file, verify its digest, then validate with the supplied registry."""
    try:
        payload = Path(path).read_bytes()
    except (OSError, TypeError, ValueError):
        raise WorkspaceError("PLAN_READ_FAILED") from None
    plan = WorkflowPlan.from_json(payload)
    report = validate_plan(plan, registry)
    if not report.is_valid:
        raise ContractError("PLAN_STATIC_VALIDATION_FAILED")
    return plan
