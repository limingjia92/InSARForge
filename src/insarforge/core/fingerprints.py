"""Pure task recipes and prepared execution identity, never plan-hash caching."""

import hashlib
from collections.abc import Mapping

from insarforge.contracts._persistence import _validate_persistence_value
from insarforge.contracts.context import ResourceAllocation
from insarforge.contracts.errors import ContractError
from insarforge.contracts.execution import TaskSpec
from insarforge.contracts.fingerprints import FingerprintResult, is_digest, unresolved
from insarforge.contracts.operations import OperationBinding, PreparedExecution
from insarforge.contracts.values import (
    ArtifactRef,
    FrozenJSON,
    freeze_json,
    validate_identifier,
)
from insarforge.products.semantics import SemanticStatus, SemanticValue
from insarforge.products.serialization import canonical_json_bytes

TASK_RECIPE_DOMAIN = b"insarforge.task.recipe.v1\0"
EXECUTION_IDENTITY_DOMAIN = b"insarforge.execution.identity.v1\0"


def digest_projection(domain: bytes, projection: FrozenJSON) -> FingerprintResult:
    try:
        projection = freeze_json(projection)
        _validate_persistence_value(projection)
        payload = canonical_json_bytes(projection)
    except (TypeError, ValueError, RecursionError, UnicodeError):
        raise ContractError("IDENTITY_PROJECTION") from None
    return FingerprintResult(hashlib.sha256(domain + payload).hexdigest(), True)


def input_identities(
    inputs: Mapping[str, tuple[ArtifactRef, ...]],
) -> FrozenJSON | None:
    if not isinstance(inputs, Mapping):
        raise ContractError("IDENTITY_INPUTS")
    result = []
    weak = False
    for port in inputs:
        if type(port) is not str:
            raise ContractError("IDENTITY_PORT")
        try:
            validate_identifier(port)
        except (TypeError, ValueError):
            raise ContractError("IDENTITY_PORT") from None
    for port in sorted(inputs):
        refs = inputs[port]
        if type(refs) not in (tuple, list) or any(
            type(ref) is not ArtifactRef for ref in refs
        ):
            raise ContractError("IDENTITY_INPUTS")
        if any(not is_digest(ref.semantic_digest) for ref in refs):
            weak = True
        result.append(
            {"port": port, "semantic_digests": [ref.semantic_digest for ref in refs]}
        )
    return None if weak else freeze_json(result)


def execution_identity(
    prepared: PreparedExecution,
    allocation: ResourceAllocation,
) -> FingerprintResult:
    """Consume a complete v1 identity projection; never call prepare or probe.

    Native/external maps may be explicitly empty for an operation using none.
    Each native component has executable and dependency content digests.
    Composition is responsible for the completeness/truth of supplied material.
    """
    if type(allocation) is not ResourceAllocation:
        raise ContractError("IDENTITY_ALLOCATION")
    try:
        value = prepared.semantic_execution_identity
    except Exception:
        raise ContractError("IDENTITY_PREPARED_ACCESS") from None
    if type(value) is not SemanticValue:
        raise ContractError("IDENTITY_PREPARED_TYPE")
    if value.status is SemanticStatus.UNKNOWN:
        return unresolved("EXECUTION_IDENTITY_UNKNOWN")
    if value.status is not SemanticStatus.KNOWN:
        return unresolved("EXECUTION_IDENTITY_INCOMPLETE")
    data = value.value
    keys = {
        "schema_version",
        "wrapper_digest",
        "native_components",
        "settings",
        "external_resource_digests",
    }
    if not isinstance(data, Mapping) or set(data) != keys:
        return unresolved("EXECUTION_IDENTITY_INCOMPLETE")
    if type(data["schema_version"]) is not int or data["schema_version"] != 1:
        return unresolved("EXECUTION_IDENTITY_VERSION")
    if not is_digest(data["wrapper_digest"]):
        return unresolved("WRAPPER_IDENTITY_WEAK")
    for name in ("native_components", "settings", "external_resource_digests"):
        if not isinstance(data[name], Mapping):
            return unresolved("EXECUTION_IDENTITY_INCOMPLETE")
    for component in data["native_components"].values():
        if not isinstance(component, Mapping) or set(component) != {
            "executable_digest",
            "dependency_digests",
        }:
            return unresolved("NATIVE_IDENTITY_WEAK")
        if not is_digest(component["executable_digest"]) or not isinstance(
            component["dependency_digests"], Mapping
        ):
            return unresolved("NATIVE_IDENTITY_WEAK")
        if any(not is_digest(d) for d in component["dependency_digests"].values()):
            return unresolved("NATIVE_IDENTITY_WEAK")
    if any(not is_digest(d) for d in data["external_resource_digests"].values()):
        return unresolved("RESOURCE_IDENTITY_WEAK")
    if any(not is_digest(ref.semantic_digest) for ref in value.evidence_refs):
        return unresolved("EXECUTION_EVIDENCE_WEAK")
    if (
        type(allocation.cpu_cores) is not int
        or allocation.cpu_cores < 1
        or type(allocation.gpu_count) is not int
        or allocation.gpu_count < 0
    ):
        raise ContractError("IDENTITY_ALLOCATION")
    return digest_projection(
        EXECUTION_IDENTITY_DOMAIN,
        {
            "prepared": data,
            "cpu_cores": allocation.cpu_cores,
            "gpu_count": allocation.gpu_count,
            "evidence_semantic_digests": [
                ref.semantic_digest for ref in value.evidence_refs
            ],
        },
    )


def task_fingerprint(
    task: TaskSpec,
    binding: OperationBinding,
    *,
    core_semantics_revision: str,
    engine_identity: FingerprintResult,
    implementation_identity: FingerprintResult,
    prepared: PreparedExecution,
    allocation: ResourceAllocation,
    resolved_inputs: Mapping[str, tuple[ArtifactRef, ...]],
) -> FingerprintResult:
    if type(task) is not TaskSpec or type(binding) is not OperationBinding:
        raise ContractError("RECIPE_CONTRACT")
    if type(core_semantics_revision) is not str:
        raise ContractError("RECIPE_REVISION")
    try:
        validate_identifier(core_semantics_revision)
    except (TypeError, ValueError):
        raise ContractError("RECIPE_REVISION") from None
    if (task.operation_id, task.operation_api_version) != (
        binding.operation_id,
        binding.operation_api_version,
    ):
        raise ContractError("RECIPE_BINDING")
    if not isinstance(resolved_inputs, Mapping):
        raise ContractError("RECIPE_INPUTS")
    if set(task.inputs) != {p.port_id for p in binding.inputs} or set(
        task.inputs
    ) != set(resolved_inputs):
        raise ContractError("RECIPE_INPUT_PORTS")
    declared = [
        (
            p.port,
            p.schema_id,
            p.schema_version,
            p.profile_id,
            p.profile_version,
            p.count,
        )
        for p in task.outputs
    ]
    expected = [
        (
            p.port_id,
            p.schema.schema_id,
            p.schema.schema_version,
            None if p.profile is None else p.profile.profile_id,
            None if p.profile is None else p.profile.profile_version,
            p.count,
        )
        for p in binding.outputs
    ]
    if declared != expected:
        raise ContractError("RECIPE_OUTPUTS")
    inputs = input_identities(resolved_inputs)
    for port in binding.inputs:
        refs = resolved_inputs[port.port_id]
        if len(refs) < port.min_count or (
            port.max_count is not None and len(refs) > port.max_count
        ):
            raise ContractError("RECIPE_INPUT_COUNT")
        if any(
            (ref.schema_id, ref.schema_version)
            != (port.schema.schema_id, port.schema.schema_version)
            for ref in refs
        ):
            raise ContractError("RECIPE_INPUT_SCHEMA")
    execution = execution_identity(prepared, allocation)
    reasons = []
    for name, result in (
        ("ENGINE_IDENTITY_WEAK", engine_identity),
        ("IMPLEMENTATION_IDENTITY_WEAK", implementation_identity),
        ("EXECUTION_IDENTITY_WEAK", execution),
    ):
        if type(result) is not FingerprintResult:
            raise ContractError("RECIPE_IDENTITY")
        if not result.reusable:
            reasons.append(name)
    if inputs is None:
        reasons.append("INPUT_IDENTITY_WEAK")
    if reasons:
        return FingerprintResult(None, False, tuple(reasons))
    # The operation's pure validator owns parameter semantics; an unverified
    # parameter report is insufficient to establish a reusable recipe.
    try:
        report = binding.handler.validate_spec(
            task.semantic_parameters, binding.inputs, binding.outputs
        )
    except Exception:
        raise ContractError("RECIPE_PARAMETER_VALIDATION") from None
    from insarforge.products.validation import ProductValidationReport

    if type(report) is not ProductValidationReport:
        raise ContractError("RECIPE_PARAMETER_REPORT")
    if not report.is_fully_verified:
        return unresolved("PARAMETERS_UNVERIFIED")
    return digest_projection(
        TASK_RECIPE_DOMAIN,
        {
            "core_semantics_revision": core_semantics_revision,
            "engine_code_identity": engine_identity.value,
            "operation_id": binding.operation_id,
            "operation_api_version": binding.operation_api_version,
            "validator_revision": binding.validator_revision,
            "plugin_kind": task.plugin_ref.kind.value,
            "plugin_id": task.plugin_ref.plugin_id,
            "plugin_api_version": task.plugin_ref.api_version,
            "plugin_implementation_identity": implementation_identity.value,
            "semantic_execution_identity": execution.value,
            "validated_semantic_parameters": task.semantic_parameters,
            "ordered_input_ports": inputs,
            "declared_output_contracts": [
                {
                    "port": p.port,
                    "schema_id": p.schema_id,
                    "schema_version": p.schema_version,
                    "profile_id": p.profile_id,
                    "profile_version": p.profile_version,
                    "count": p.count,
                }
                for p in task.outputs
            ],
        },
    )
