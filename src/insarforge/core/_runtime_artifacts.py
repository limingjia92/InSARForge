"""Coordinator-side validation/finalization and committed candidate reconstruction."""

import hashlib
import os
import re
import stat
import uuid
from dataclasses import fields
from pathlib import Path

from insarforge.contracts.errors import InputValidationError, OutputValidationError
from insarforge.contracts.execution import _artifact_dict, _artifact_from_dict
from insarforge.contracts.operations import ResolvedInput, TaskOutcome
from insarforge.contracts.record_serialization import record_from_bytes, record_to_bytes
from insarforge.contracts.values import ArtifactRef
from insarforge.core.cache import (
    AssetEvidence,
    CacheCandidate,
    CachedOutput,
    CommitEvidence,
)
from insarforge.core.content_identity import verify_asset_content
from insarforge.core.result_identity import artifact_semantic_digest
from insarforge.products.asset_validation import validate_product_assets
from insarforge.products.assets import AssetKind, AssetLocationKind
from insarforge.products.models import (
    LineageEntry,
    ProducerRef,
    Product,
    ProductDraft,
    ProductionRef,
)
from insarforge.products.semantics import SemanticStatus, SemanticValue
from insarforge.products.serialization import _e
from insarforge.products.validation import ProductValidationReport
from insarforge.provenance.workspace import safe_path


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def semantic(identity):
    return (
        SemanticValue(SemanticStatus.KNOWN, identity.value, None, ())
        if identity.reusable
        else SemanticValue(
            SemanticStatus.UNKNOWN, None, "runtime:identity-unresolved", ()
        )
    )


def asset_path(asset):
    if asset.location.kind is AssetLocationKind.REMOTE_REFERENCE:
        return None
    if asset.location.kind is AssetLocationKind.MANIFEST_RELATIVE:
        return asset.location.anchor / asset.location.value
    return Path(asset.location.value)


def read_local(path):
    safe_path(path)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as f:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise OutputValidationError("ASSET_UNSAFE")
        return f.read()


def observe(asset, *, owned=None, shared=(), flush=False):
    path = asset_path(asset)
    if owned is not None and asset in shared:
        # Exact verified read-only input descriptor; never flush/re-own it.
        return observe(asset)
    if owned is not None:
        if path is None or not path.is_relative_to(owned):
            raise OutputValidationError("OUTPUT_NOT_OWNED")
        safe_path(path)
        if not path.exists():
            raise OutputValidationError("OUTPUT_MISSING")
        if asset.asset_kind is AssetKind.FILE:
            if path.stat().st_nlink != 1 or not path.is_file():
                raise OutputValidationError("OUTPUT_UNSAFE")
        else:
            if not path.is_dir():
                raise OutputValidationError("OUTPUT_UNSAFE")
            for directory, dirs, names in os.walk(path, followlinks=False):
                for name in (*dirs, *names):
                    p = Path(directory) / name
                    safe_path(p)
                    info = p.stat()
                    if not stat.S_ISDIR(info.st_mode) and (
                        not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                    ):
                        raise OutputValidationError("OUTPUT_UNSAFE")
    if owned is not None and flush:
        # The adapter must close all writers before returning. Flush the owned
        # bytes before the coordinator publishes the receipt commit point.
        members = (
            [path] if asset.asset_kind is AssetKind.FILE else [path, *path.rglob("*")]
        )
        for member in members:
            safe_path(member)
            fd = os.open(member, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
    raw = None
    if asset.member_manifest_ref is not None:
        location = Path(asset.member_manifest_ref.locator)
        if owned is not None and not location.is_relative_to(owned):
            raise OutputValidationError("MEMBER_MANIFEST_NOT_OWNED")
        raw = read_local(location)
    identity = verify_asset_content(asset, member_manifest_bytes=raw)
    return AssetEvidence(asset, identity)


def validate_record(record, port):
    report = port.validator.validate(record, port.schema, port.profile)
    if type(report) is not ProductValidationReport or not report.is_fully_verified:
        raise OutputValidationError("OUTPUT_CONTRACT")
    if (record.schema_id, record.schema_version) != (
        port.schema.schema_id,
        port.schema.schema_version,
    ):
        raise OutputValidationError("OUTPUT_SCHEMA")
    if type(record) is Product and port.profile is not None:
        if (record.profile_id, record.profile_version) != (
            port.profile.profile_id,
            port.profile.profile_version,
        ):
            raise OutputValidationError("OUTPUT_PROFILE")


def finalize(
    store,
    prefix,
    task,
    binding,
    registration,
    outcome,
    recipe,
    execution,
    implementation,
    inputs,
    context,
    shared=(),
):
    if type(outcome) is not TaskOutcome or set(outcome.outputs) != {
        p.port_id for p in binding.outputs
    }:
        raise OutputValidationError("OUTCOME_PORTS")
    outputs = {}
    # Validate every result before any receipt can be written.
    pending = []
    for port in binding.outputs:
        values = outcome.outputs[port.port_id]
        if len(values) != port.count:
            raise OutputValidationError("OUTCOME_COUNT")
        for i, draft in enumerate(values):
            if draft.schema != port.schema:
                raise OutputValidationError("OUTCOME_SCHEMA")
            record = draft.value
            identifier = "record:" + uuid.uuid4().hex
            if type(record) is ProductDraft:
                record = Product(
                    **{f.name: getattr(record, f.name) for f in fields(ProductDraft)},
                    schema_id="insarforge:product",
                    schema_version=2,
                    product_id=identifier,
                    producer=ProducerRef(
                        task.plugin_ref,
                        registration.descriptor.implementation_version,
                        semantic(implementation),
                        semantic(execution),
                    ),
                    produced_by=ProductionRef(
                        semantic(recipe), port.port_id, context.attempt_id
                    ),
                    lineage=tuple(
                        LineageEntry(p, a) for p in sorted(inputs) for a in inputs[p]
                    ),
                    provenance_ref=prefix + "/started.json",
                )
            else:
                from dataclasses import replace

                record = replace(record, record_id=identifier)
            validate_record(record, port)
            evidence = ()
            if type(record) is Product:
                evidence = tuple(
                    observe(a, owned=context.artifact_dir, shared=shared, flush=True)
                    for a in record.assets
                )
                if not validate_product_assets(record).is_valid:
                    raise OutputValidationError("OUTPUT_ASSET_INVALID")
                # A declared strong identity that mismatches is invalid, not merely weak.
                if any(
                    e.identity.reasons
                    and any(
                        "MISMATCH" in r or "UNVERIFIED" in r for r in e.identity.reasons
                    )
                    for e in evidence
                    if e.asset.integrity is not None
                    or e.asset.member_manifest_ref is not None
                ):
                    raise OutputValidationError("OUTPUT_ASSET_INTEGRITY")
            raw = record_to_bytes(record)
            digest = artifact_semantic_digest(
                record,
                producer_fingerprint=recipe,
                output_port=port.port_id,
                ordered_inputs=inputs,
                asset_content_identities={
                    e.asset.asset_id: e.identity.value for e in evidence
                },
            )
            location = prefix + "/manifests/" + str(len(pending)) + ".json"
            ref = ArtifactRef(
                identifier,
                record.schema_id,
                record.schema_version,
                digest.value,
                sha(raw),
                location,
            )
            pending.append((port.port_id, ref, raw))
    native = []
    for asset in outcome.evidence:
        observe(asset, owned=context.attempt_dir, flush=True)
        _validate_native_evidence(asset)
        native.append(_e(asset))
    for port, ref, raw in pending:
        store.write_bytes(ref.locator, raw)
        outputs.setdefault(port, []).append(ref)
    return {k: tuple(v) for k, v in outputs.items()}, native


def _validate_native_evidence(asset):
    """Check recognizable secrets before registering textual native evidence.

    Plugins own and sanitize files before return. This does not promise secret
    discovery in binary scientific assets or sandbox untrusted plugin code.
    """
    from insarforge.contracts._persistence import (
        _is_secret_key,
        _validate_persistence_value,
    )
    from insarforge.products.serialization import strict_json_loads

    path = asset_path(asset)
    members = (
        [path] if path.is_file() else sorted(p for p in path.rglob("*") if p.is_file())
    )
    for member in members:
        raw = read_local(member)
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            continue
        _validate_persistence_value(text)
        try:
            parsed = strict_json_loads(raw)
        except (ValueError, TypeError):
            parsed = None
        if parsed is not None:
            _validate_persistence_value(parsed)
        for line in text.splitlines():
            _validate_persistence_value(line.strip())
            for url in re.findall(r"[A-Za-z][A-Za-z0-9+.-]*://[^\s<>\"']+", line):
                _validate_persistence_value(url)
            match = re.match(r"\s*([A-Za-z][A-Za-z0-9_.-]*)\s*[:=]", line)
            if match and _is_secret_key(match[1]):
                raise OutputValidationError("NATIVE_EVIDENCE_UNSAFE")


def candidate_from_receipt(store, location, *, commit_only=False):
    receipt = store.read(location, "receipt")
    prefix = location.rsplit("/", 1)[0]
    started = store.read(prefix + "/started.json", "started")
    for key in (
        "attempt_id",
        "task_id",
        "scope_id",
        "fingerprint",
        "execution",
        "inputs",
    ):
        if receipt[key] != started[key]:
            raise InputValidationError("RECEIPT_START_MISMATCH")
    if (
        started["attempt_id"] != prefix.rsplit("/", 1)[-1]
        or started["run_id"] != prefix.split("/")[1]
    ):
        raise InputValidationError("RECEIPT_ATTEMPT")
    from insarforge.contracts.context import ResourceAllocation
    from insarforge.core._runtime_inputs import shared_assets
    from insarforge.core.fingerprints import execution_identity
    from insarforge.provenance.runtime_evidence import PreparationEvidence

    prepared = PreparationEvidence.from_dict(started["prepared"])
    a = started["allocation"]
    allocation = ResourceAllocation(a["cpu_cores"], a["memory_bytes"], a["gpu_count"])
    if execution_identity(prepared, allocation).value != started["execution"]:
        raise InputValidationError("RECEIPT_EXECUTION_EVIDENCE")
    run = store.read("runs/" + started["run_id"] + "/run.json", "run")
    if (
        run["scope_id"] != started["scope_id"]
        or run["plan_digest"] != started["plan_digest"]
    ):
        raise InputValidationError("RECEIPT_RUN_BINDING")
    shared = shared_assets(store, started["resolved_inputs"])
    outputs = {}
    manifest_digests = {}
    for port, refs in receipt["outputs"].items():
        items = []
        for data in refs:
            ref = _artifact_from_dict(data)
            if (
                not ref.locator.startswith(prefix + "/manifests/")
                or len(Path(ref.locator).parts) != len(Path(prefix).parts) + 2
            ):
                raise InputValidationError("RECEIPT_OUTPUT_LOCATION")
            raw = store.read_bytes(ref.locator)
            if sha(raw) != ref.manifest_digest:
                raise InputValidationError("RECEIPT_MANIFEST_HASH")
            record = record_from_bytes(ref, raw)
            if (
                type(record) is Product
                and record.produced_by.attempt_id != started["attempt_id"]
            ):
                raise InputValidationError("RECEIPT_PRODUCING_ATTEMPT")
            evidence = (
                tuple(
                    observe(a, owned=store.path(prefix + "/artifacts"), shared=shared)
                    for a in record.assets
                )
                if type(record) is Product
                else ()
            )
            from insarforge.core._runtime_inputs import verify
            from insarforge.provenance.runtime_evidence import ArtifactEvidence

            if any(
                not e.identity.reusable
                for e in evidence
                if e.asset.integrity is not None
                or e.asset.member_manifest_ref is not None
            ):
                raise InputValidationError("RECEIPT_ASSET_IDENTITY")
            if receipt["fingerprint"] is None and ref.semantic_digest is not None:
                raise InputValidationError("RECEIPT_WEAK_RECIPE")
            if receipt["fingerprint"] is not None:
                proof = ArtifactEvidence(
                    ref,
                    receipt["fingerprint"],
                    port,
                    {
                        p: tuple(_artifact_from_dict(v["artifact"]) for v in values)
                        for p, values in started["resolved_inputs"].items()
                    },
                )
                effective = verify(ref, record, proof, evidence)
                if effective.semantic_digest != ref.semantic_digest:
                    raise InputValidationError("RECEIPT_SEMANTIC_IDENTITY")
            items.append(CachedOutput(ref, raw, evidence))
        outputs[port] = tuple(items)
        manifest_digests[port] = tuple(x.artifact.manifest_digest for x in items)
    if commit_only:
        return receipt
    return CacheCandidate(
        1,
        receipt["fingerprint"],
        receipt["execution"],
        receipt["inputs"],
        outputs,
        CommitEvidence(sha(store.read_bytes(location)), manifest_digests),
    )


def resolve_inputs(
    store, task, binding, produced, external, external_prefix, external_evidence
):
    from insarforge.core._runtime_inputs import local_evidence, resolved_entry, verify

    entries = {}
    effective_refs = {}
    inputs = {}
    from insarforge.contracts.execution import OutputRef

    for port in binding.inputs:
        members = []
        entries[port.port_id] = []
        effective_refs[port.port_id] = []
        for source in task.inputs[port.port_id]:
            sources = (
                produced[source.task_id][source.port]
                if type(source) is OutputRef
                else (source,)
            )
            for ref in sources:
                from insarforge.provenance.workspace import key

                location = (
                    external_prefix + "/external/" + key(ref.record_id) + ".json"
                    if ref.record_id in external
                    else ref.locator
                )
                raw = (
                    external[ref.record_id]
                    if ref.record_id in external
                    else store.read_bytes(location)
                )
                if sha(raw) != ref.manifest_digest:
                    raise InputValidationError("INPUT_MANIFEST_HASH")
                value = port.codec.decode(ref, raw, port.schema)
                if type(value) is not ResolvedInput or value.artifact != ref:
                    raise InputValidationError("INPUT_CODEC")
                validate_record(value.value, port)
                observations = []
                if type(value.value) is Product:
                    if not validate_product_assets(value.value).is_valid:
                        raise InputValidationError("INPUT_ASSET_INVALID")
                    for a in value.value.assets:
                        observation = observe(a)
                        observations.append(observation)
                        if (
                            a.integrity is not None or a.member_manifest_ref is not None
                        ) and not observation.identity.reusable:
                            raise InputValidationError("INPUT_ASSET_INTEGRITY")
                proof = (
                    external_evidence.get(ref.record_id)
                    if ref.record_id in external
                    else local_evidence(store, ref)
                )
                effective = verify(ref, value.value, proof, observations)
                entries[port.port_id].append(
                    resolved_entry(ref, location, effective, proof)
                )
                effective_refs[port.port_id].append(effective)
                members.append(value)
        if len(members) < port.min_count or (
            port.max_count is not None and len(members) > port.max_count
        ):
            raise InputValidationError("INPUT_COUNT")
        inputs[port.port_id] = tuple(members)
    from types import MappingProxyType

    return (
        MappingProxyType(inputs),
        {p: tuple(v) for p, v in effective_refs.items()},
        entries,
    )


def output_data(outputs):
    return {k: [_artifact_dict(r) for r in refs] for k, refs in outputs.items()}
