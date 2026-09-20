"""Pure supplied-candidate validation; no cache index, receipt writes or executor."""

import hashlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType

from insarforge.contracts._persistence import _validate_persistence_value
from insarforge.contracts.errors import ContractError
from insarforge.contracts.execution import CachePolicy, TaskSpec
from insarforge.contracts.fingerprints import FingerprintResult, is_digest
from insarforge.contracts.operations import InputRecord, OperationBinding
from insarforge.contracts.values import ArtifactRef, freeze_json
from insarforge.core.fingerprints import input_identities
from insarforge.core.result_identity import artifact_semantic_digest
from insarforge.products.assets import NativeAsset
from insarforge.products.models import Product
from insarforge.products.semantics import SemanticStatus
from insarforge.products.serialization import (
    product_from_manifest_bytes,
    strict_json_loads,
)
from insarforge.products.validation import ProductValidationReport


def _validate_manifest_safety(value):
    # Frozen Catalog AccessStatus contains a boolean, not authentication material.
    # Only this exact key/type is exempt from the generic recognizable-key guard.
    if isinstance(value, Mapping):
        for key, item in value.items():
            if key == "authentication_required" and (
                item is None or type(item) is bool
            ):
                continue
            _validate_persistence_value({key: None})
            _validate_manifest_safety(item)
    elif isinstance(value, (tuple, list)):
        for item in value:
            _validate_manifest_safety(item)
    else:
        _validate_persistence_value(value)


@dataclass(frozen=True)
class AssetEvidence:
    """Caller-supplied observation for this exact immutable asset declaration."""

    asset: NativeAsset
    identity: FingerprintResult

    def __post_init__(self):
        if (
            type(self.asset) is not NativeAsset
            or type(self.identity) is not FingerprintResult
        ):
            raise ContractError("CACHE_ASSET_EVIDENCE")


@dataclass(frozen=True)
class CachedOutput:
    artifact: ArtifactRef
    manifest_bytes: bytes
    assets: tuple[AssetEvidence, ...] = ()

    def __post_init__(self):
        if (
            type(self.artifact) is not ArtifactRef
            or type(self.manifest_bytes) is not bytes
            or type(self.assets) not in (list, tuple)
        ):
            raise ContractError("CACHE_OUTPUT")
        assets = tuple(self.assets)
        if any(type(a) is not AssetEvidence for a in assets) or len(
            {a.asset.asset_id for a in assets}
        ) != len(assets):
            raise ContractError("CACHE_OUTPUT_ASSETS")
        object.__setattr__(self, "assets", assets)


def _output_map(value, member_type):
    if not isinstance(value, Mapping):
        raise ContractError("CACHE_OUTPUT_MAP")
    result = {}
    for key, items in value.items():
        if type(key) is not str or not key or type(items) not in (list, tuple):
            raise ContractError("CACHE_OUTPUT_MAP")
        items = tuple(items)
        if any(type(item) is not member_type for item in items):
            raise ContractError("CACHE_OUTPUT_MAP")
        result[key] = items
    return MappingProxyType(dict(sorted(result.items())))


@dataclass(frozen=True)
class CommitEvidence:
    """Trusted caller assertion from a validated committed receipt, bound to outputs.

    P4.2-03 must authenticate/load that receipt and supply CURRENT asset observations.
    This value is not a proof of commit by itself and does not publish any receipt.
    """

    receipt_digest: str
    output_manifest_digests: Mapping[str, tuple[str, ...]]

    def __post_init__(self):
        if not is_digest(self.receipt_digest):
            raise ContractError("CACHE_RECEIPT")
        outputs = _output_map(self.output_manifest_digests, str)
        if any(not is_digest(d) for values in outputs.values() for d in values):
            raise ContractError("CACHE_RECEIPT_OUTPUT")
        object.__setattr__(self, "output_manifest_digests", outputs)


@dataclass(frozen=True)
class CacheCandidate:
    schema_version: int
    fingerprint: str
    execution_identity: str
    input_semantics: object
    outputs: Mapping[str, tuple[CachedOutput, ...]]
    commit: CommitEvidence | None

    def __post_init__(self):
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise ContractError("CACHE_SCHEMA_VERSION")
        if not is_digest(self.fingerprint) or not is_digest(self.execution_identity):
            raise ContractError("CACHE_IDENTITY")
        if self.commit is not None and type(self.commit) is not CommitEvidence:
            raise ContractError("CACHE_COMMIT")
        try:
            inputs = freeze_json(self.input_semantics)
        except (TypeError, ValueError, RecursionError):
            raise ContractError("CACHE_INPUT_METADATA") from None
        if type(inputs) is not tuple:
            raise ContractError("CACHE_INPUT_METADATA")
        ports = []
        for row in inputs:
            if (
                not isinstance(row, Mapping)
                or set(row) != {"port", "semantic_digests"}
                or type(row["port"]) is not str
                or not row["port"]
                or type(row["semantic_digests"]) is not tuple
            ):
                raise ContractError("CACHE_INPUT_METADATA")
            if any(not is_digest(d) for d in row["semantic_digests"]):
                raise ContractError("CACHE_INPUT_METADATA")
            ports.append(row["port"])
        if ports != sorted(set(ports)):
            raise ContractError("CACHE_INPUT_METADATA")
        object.__setattr__(self, "input_semantics", inputs)
        object.__setattr__(self, "outputs", _output_map(self.outputs, CachedOutput))


@dataclass(frozen=True)
class CacheDecision:
    accepted: bool
    reasons: tuple[str, ...]

    def __post_init__(self):
        if type(self.accepted) is not bool or type(self.reasons) not in (list, tuple):
            raise ContractError("CACHE_DECISION")
        reasons = tuple(self.reasons)
        if self.accepted == bool(reasons) or any(
            type(r) is not str or not r for r in reasons
        ):
            raise ContractError("CACHE_DECISION")
        object.__setattr__(self, "reasons", reasons)


def can_publish_cache(policy: CachePolicy, recipe: FingerprintResult) -> bool:
    if type(policy) is not CachePolicy or type(recipe) is not FingerprintResult:
        raise ContractError("CACHE_POLICY")
    return policy is CachePolicy.AUTO and recipe.reusable


def validate_cache_candidate(
    task: TaskSpec,
    binding: OperationBinding,
    recipe: FingerprintResult,
    execution: FingerprintResult,
    inputs: Mapping[str, tuple[ArtifactRef, ...]],
    candidate: CacheCandidate,
    *,
    decode_record: Callable[[ArtifactRef, bytes], InputRecord] | None = None,
) -> CacheDecision:
    """No I/O. Decode only supplied bytes and validate with attached port validators.

    Non-Product typed records require an explicit strict decoder supplied by the
    composition layer, never reflection/import/discovery. A malformed decoder or
    record is a safe rejection, not a reusable result.
    """

    def reject(code):
        return CacheDecision(False, (code,))

    if (
        type(task) is not TaskSpec
        or type(binding) is not OperationBinding
        or type(candidate) is not CacheCandidate
        or type(recipe) is not FingerprintResult
        or type(execution) is not FingerprintResult
    ):
        raise ContractError("CACHE_ARGUMENT")
    if not can_publish_cache(task.cache_policy, recipe):
        return reject("CACHE_POLICY_OR_RECIPE")
    if not execution.reusable:
        return reject("CACHE_EXECUTION_WEAK")
    if candidate.fingerprint != recipe.value:
        return reject("CACHE_RECIPE_MISMATCH")
    if candidate.execution_identity != execution.value:
        return reject("CACHE_EXECUTION_MISMATCH")
    semantic_inputs = input_identities(inputs)
    if semantic_inputs is None or semantic_inputs != candidate.input_semantics:
        return reject("CACHE_INPUT_MISMATCH")
    if set(inputs) != set(task.inputs):
        return reject("CACHE_INPUT_PORTS")
    if candidate.commit is None:
        return reject("CACHE_UNCOMMITTED")
    if (task.operation_id, task.operation_api_version) != (
        binding.operation_id,
        binding.operation_api_version,
    ):
        return reject("CACHE_BINDING")
    expected = {p.port_id: p for p in binding.outputs}
    declared = {p.port: p for p in task.outputs}
    if (
        set(candidate.outputs) != set(expected)
        or set(declared) != set(expected)
        or set(candidate.commit.output_manifest_digests) != set(expected)
    ):
        return reject("CACHE_OUTPUT_PORTS")
    seen_records = set()
    for name, port in expected.items():
        declaration = declared[name]
        profile = (
            None
            if port.profile is None
            else (port.profile.profile_id, port.profile.profile_version)
        )
        if (declaration.schema_id, declaration.schema_version, declaration.count) != (
            port.schema.schema_id,
            port.schema.schema_version,
            port.count,
        ) or (
            None
            if declaration.profile_id is None
            else (declaration.profile_id, declaration.profile_version)
        ) != profile:
            return reject("CACHE_OUTPUT_CONTRACT")
        outputs = candidate.outputs[name]
        if len(outputs) != port.count:
            return reject("CACHE_OUTPUT_COUNT")
        if (
            tuple(o.artifact.manifest_digest for o in outputs)
            != candidate.commit.output_manifest_digests[name]
        ):
            return reject("CACHE_COMMIT_OUTPUTS")
        for output in outputs:
            ref = output.artifact
            if ref.record_id in seen_records:
                return reject("CACHE_DUPLICATE_RECORD")
            seen_records.add(ref.record_id)
            if (ref.schema_id, ref.schema_version) != (
                port.schema.schema_id,
                port.schema.schema_version,
            ):
                return reject("CACHE_SCHEMA")
            if (
                not is_digest(ref.manifest_digest)
                or hashlib.sha256(output.manifest_bytes).hexdigest()
                != ref.manifest_digest
            ):
                return reject("CACHE_MANIFEST_DIGEST")
            try:
                value = strict_json_loads(output.manifest_bytes)
                _validate_manifest_safety(value)
                if (
                    not isinstance(value, Mapping)
                    or value.get("schema_id") != ref.schema_id
                    or type(value.get("schema_version")) is not int
                    or value["schema_version"] != ref.schema_version
                ):
                    return reject("CACHE_MANIFEST_SCHEMA")
                if ref.schema_id == "insarforge:product":
                    record = product_from_manifest_bytes(output.manifest_bytes)
                elif decode_record is not None:
                    record = decode_record(ref, output.manifest_bytes)
                else:
                    return reject("CACHE_DECODER_MISSING")
                if (record.schema_id, record.schema_version) != (
                    ref.schema_id,
                    ref.schema_version,
                ):
                    return reject("CACHE_RECORD_SCHEMA")
                asset_ids = {}
                if type(record) is Product:
                    if (
                        record.product_id != ref.record_id
                        or record.producer.plugin != task.plugin_ref
                    ):
                        return reject("CACHE_PRODUCT_PRODUCER")
                    if (
                        port.profile is not None
                        and (record.profile_id, record.profile_version) != profile
                    ):
                        return reject("CACHE_PROFILE")
                    if tuple(
                        (e.role, e.artifact.semantic_digest) for e in record.lineage
                    ) != tuple(
                        (p, a.semantic_digest)
                        for p in sorted(inputs)
                        for a in inputs[p]
                    ):
                        return reject("CACHE_PRODUCT_LINEAGE")
                    if (
                        record.produced_by.task_fingerprint.status
                        is not SemanticStatus.KNOWN
                        or record.produced_by.task_fingerprint.value != recipe.value
                        or record.produced_by.output_port != name
                        or record.producer.execution_identity_digest.status
                        is not SemanticStatus.KNOWN
                        or record.producer.execution_identity_digest.value
                        != execution.value
                    ):
                        return reject("CACHE_PRODUCT_PRODUCTION")
                    supplied = {a.asset.asset_id: a for a in output.assets}
                    if set(supplied) != {a.asset_id for a in record.assets}:
                        return reject("CACHE_ASSETS_MISSING")
                    for asset in record.assets:
                        evidence = supplied[asset.asset_id]
                        if evidence.asset != asset or not evidence.identity.reusable:
                            return reject("CACHE_ASSET_UNVERIFIED")
                        asset_ids[asset.asset_id] = evidence.identity.value
                elif output.assets or port.profile is not None:
                    return reject("CACHE_RECORD_ASSETS_OR_PROFILE")
                elif record.record_id != ref.record_id:
                    return reject("CACHE_RECORD_ID")
                report = port.validator.validate(record, port.schema, port.profile)
                if (
                    type(report) is not ProductValidationReport
                    or not report.is_fully_verified
                ):
                    return reject("CACHE_RECORD_UNVERIFIED")
                digest = artifact_semantic_digest(
                    record,
                    producer_fingerprint=recipe,
                    output_port=name,
                    ordered_inputs=inputs,
                    asset_content_identities=asset_ids,
                )
                if not digest.reusable or digest.value != ref.semantic_digest:
                    return reject("CACHE_RESULT_IDENTITY")
            except Exception:
                # Explicit untrusted metadata/adapter boundary. Never emit payload
                # or exception text, and never convert failure to a cache hit.
                return reject("CACHE_RECORD_INVALID")
    return CacheDecision(True, ())
