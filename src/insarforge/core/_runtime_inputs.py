"""Recompute runtime input identity without changing original references."""

from dataclasses import replace

from insarforge.contracts.errors import InputValidationError
from insarforge.contracts.execution import _artifact_dict, _artifact_from_dict
from insarforge.contracts.fingerprints import FingerprintResult
from insarforge.contracts.record_serialization import record_from_bytes
from insarforge.core.result_identity import artifact_semantic_digest
from insarforge.products.models import Product
from insarforge.products.semantics import SemanticStatus
from insarforge.provenance.runtime_evidence import ArtifactEvidence


def verify(ref, record, proof, observations):
    """Return effective identity only; the caller's ref/lineage is immutable."""
    if proof is None:
        return replace(ref, semantic_digest=None)
    if type(proof) is not ArtifactEvidence or proof.artifact != ref:
        raise InputValidationError("INPUT_EVIDENCE_BINDING")
    if type(record) is Product:
        if (
            record.produced_by.task_fingerprint.status is not SemanticStatus.KNOWN
            or record.produced_by.task_fingerprint.value != proof.producer_fingerprint
            or record.produced_by.output_port != proof.output_port
            or tuple((e.role, e.artifact) for e in record.lineage)
            != tuple(
                (p, r)
                for p in sorted(proof.ordered_inputs)
                for r in proof.ordered_inputs[p]
            )
        ):
            raise InputValidationError("INPUT_PRODUCER_EVIDENCE")
    result = artifact_semantic_digest(
        record,
        producer_fingerprint=FingerprintResult(proof.producer_fingerprint, True, ()),
        output_port=proof.output_port,
        ordered_inputs=proof.ordered_inputs,
        asset_content_identities={
            e.asset.asset_id: e.identity.value for e in observations
        },
    )
    if (
        result.reusable
        and ref.semantic_digest is not None
        and result.value != ref.semantic_digest
    ):
        raise InputValidationError("INPUT_SEMANTIC_CONTRADICTION")
    # Incomplete actual asset identity cannot establish the declared digest.
    return replace(
        ref, semantic_digest=result.value if ref.semantic_digest is not None else None
    )


def local_evidence(store, ref):
    """Only explicit internal manifest layout and a matching committed receipt."""
    parts = ref.locator.split("/")
    if (
        len(parts) != 7
        or parts[0] != "runs"
        or parts[2] != "attempts"
        or parts[5] != "manifests"
    ):
        return None
    prefix = "/".join(parts[:5])
    if not store.path(prefix + "/result.json").is_file():
        return None
    receipt = store.read(prefix + "/result.json", "receipt")
    start = store.read(prefix + "/started.json", "started")
    for k in (
        "attempt_id",
        "task_id",
        "scope_id",
        "fingerprint",
        "execution",
        "inputs",
    ):
        if receipt[k] != start[k]:
            raise InputValidationError("INPUT_RECEIPT_BINDING")
    if start["attempt_id"] != parts[4] or start["run_id"] != parts[1]:
        raise InputValidationError("INPUT_RECEIPT_LOCATION")
    from insarforge.contracts.context import ResourceAllocation
    from insarforge.core.fingerprints import execution_identity
    from insarforge.provenance.runtime_evidence import PreparationEvidence

    allocation = start["allocation"]
    restored = PreparationEvidence.from_dict(start["prepared"])
    if (
        execution_identity(
            restored,
            ResourceAllocation(
                allocation["cpu_cores"],
                allocation["memory_bytes"],
                allocation["gpu_count"],
            ),
        ).value
        != start["execution"]
    ):
        raise InputValidationError("INPUT_EXECUTION_EVIDENCE")
    for port, outputs in receipt["outputs"].items():
        for data in outputs:
            original = _artifact_from_dict(data)
            if original.record_id == ref.record_id:
                if original != ref:
                    raise InputValidationError("INPUT_COMMITTED_REF_CONFLICT")
                if receipt["fingerprint"] is None:
                    return None
                return ArtifactEvidence(
                    ref,
                    receipt["fingerprint"],
                    port,
                    {
                        p: tuple(_artifact_from_dict(v["artifact"]) for v in values)
                        for p, values in start["resolved_inputs"].items()
                    },
                )
    return None


def resolved_entry(ref, location, effective, proof):
    return dict(
        artifact=_artifact_dict(ref),
        manifest_location=location,
        effective_digest=effective.semantic_digest,
        evidence=None if proof is None else proof.to_dict(),
    )


def shared_assets(store, entries):
    """Revalidate original consumed bytes/evidence for read-only asset allowance."""
    from insarforge.core._runtime_artifacts import observe, sha

    assets = []
    for values in entries.values():
        for item in values:
            ref = _artifact_from_dict(item["artifact"])
            raw = store.read_bytes(item["manifest_location"])
            if sha(raw) != ref.manifest_digest:
                raise InputValidationError("SHARED_MANIFEST")
            record = record_from_bytes(ref, raw)
            observations = (
                tuple(observe(a) for a in record.assets)
                if type(record) is Product
                else ()
            )
            proof = (
                None
                if item["evidence"] is None
                else ArtifactEvidence.from_dict(item["evidence"])
            )
            effective = verify(ref, record, proof, observations)
            if effective.semantic_digest != item["effective_digest"]:
                raise InputValidationError("SHARED_IDENTITY_CHANGED")
            if effective.semantic_digest is not None:
                assets.extend(e.asset for e in observations if e.identity.reusable)
    return tuple(assets)
