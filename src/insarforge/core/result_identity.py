"""Actual typed semantic results, distinct from both recipe and manifest bytes."""

from collections.abc import Mapping
from dataclasses import fields, is_dataclass

from insarforge.contracts.errors import ContractError
from insarforge.contracts.fingerprints import FingerprintResult, is_digest, unresolved
from insarforge.contracts.records import AcquisitionMetadata, CatalogSnapshot, QCReport
from insarforge.contracts.values import ArtifactRef, FrozenJSON, validate_identifier
from insarforge.core.fingerprints import digest_projection, input_identities
from insarforge.products.digests import _semantic, _value, product_semantic_material
from insarforge.products.models import Product
from insarforge.products.validation import validate_product_structure

ARTIFACT_DOMAIN = b"insarforge.artifact.semantic.v1\0"


class _WeakReference(ValueError):
    pass


def _ref(ref: ArtifactRef) -> str:
    if not is_digest(ref.semantic_digest):
        raise _WeakReference()
    return ref.semantic_digest


def _plugin(ref):
    return {
        "kind": ref.kind.value,
        "plugin_id": ref.plugin_id,
        "api_version": ref.api_version,
    }


def _check_references(value):
    if type(value) is ArtifactRef:
        _ref(value)
    elif isinstance(value, Mapping):
        for item in value.values():
            _check_references(item)
    elif isinstance(value, (tuple, list)):
        for item in value:
            _check_references(item)
    elif is_dataclass(value):
        for field in fields(value):
            _check_references(getattr(value, field.name))


def record_semantic_material(
    record: Product | CatalogSnapshot | AcquisitionMetadata | QCReport,
    asset_content_identities: Mapping[str, str | None],
) -> FrozenJSON | None:
    """Explicit typed projection; opaque extension/semantic JSON stays semantic."""
    if not isinstance(asset_content_identities, Mapping):
        raise ContractError("RESULT_ASSETS")
    if any(not is_digest(v) for v in asset_content_identities.values()):
        return None
    try:
        if type(record) is Product:
            for component in (
                record.acquisition_refs,
                record.geometries,
                record.layers,
                record.semantic_metadata,
                record.lineage,
                record.extensions,
            ):
                _check_references(component)
            if not validate_product_structure(record).is_valid:
                raise ContractError("RESULT_PRODUCT_STRUCTURE")
            material = product_semantic_material(
                record, asset_content_identities=asset_content_identities
            )
            if material is None:
                return None
        elif type(record) is CatalogSnapshot:
            _check_references(record)
            if asset_content_identities:
                raise ContractError("RESULT_ASSETS")
            material = {
                "provider": _plugin(record.provider),
                "query_schema_id": record.query_schema_id,
                "query_schema_version": record.query_schema_version,
                "selectors": record.selectors,
                "entries": [
                    {
                        "entry_id": e.entry_id,
                        "access": {
                            "availability": e.access.availability.value,
                            "delivery": e.access.delivery.value,
                            "access_required": e.access.authentication_required,
                            "reason_code": e.access.reason_code,
                        },
                        "attributes": e.attributes,
                        "evidence_semantic_digests": [
                            _ref(ref) for ref in e.evidence_refs
                        ],
                    }
                    for e in record.entries
                ],
                "extensions": record.extensions,
            }
        elif type(record) is AcquisitionMetadata:
            _check_references(record)
            if asset_content_identities:
                raise ContractError("RESULT_ASSETS")
            material = {
                "source_semantic_digest": _ref(record.source_ref),
                "mission": _plugin(record.mission),
                "attributes": {k: _semantic(v) for k, v in record.attributes.items()},
                "evidence_semantic_digests": [
                    _ref(ref) for ref in record.evidence_refs
                ],
                "extensions": record.extensions,
            }
        elif type(record) is QCReport:
            _check_references(record)
            if asset_content_identities:
                raise ContractError("RESULT_ASSETS")
            material = {
                "status": record.status.value,
                "method_id": record.method_id,
                "method_version": record.method_version,
                "input_semantic_digests": [_ref(ref) for ref in record.input_refs],
                "metrics": [
                    {
                        "metric_id": m.metric_id,
                        "value": _semantic(m.value),
                        "unit": _semantic(m.unit),
                        "details": _value(m.details),
                    }
                    for m in record.metrics
                ],
                "findings": [
                    {"finding_code": f.finding_code, "details": f.details}
                    for f in record.findings
                ],
                "extensions": record.extensions,
            }
        else:
            raise ContractError("RESULT_RECORD_TYPE")
        return material
    except _WeakReference:
        return None
    except (TypeError, ValueError):
        raise ContractError("RESULT_SEMANTIC_MATERIAL") from None


def artifact_semantic_digest(
    record: Product | CatalogSnapshot | AcquisitionMetadata | QCReport,
    *,
    producer_fingerprint: FingerprintResult,
    output_port: str,
    ordered_inputs: Mapping[str, tuple[ArtifactRef, ...]],
    asset_content_identities: Mapping[str, str | None],
) -> FingerprintResult:
    if type(producer_fingerprint) is not FingerprintResult:
        raise ContractError("RESULT_RECIPE")
    try:
        validate_identifier(output_port)
    except (TypeError, ValueError):
        raise ContractError("RESULT_OUTPUT_PORT") from None
    if not producer_fingerprint.reusable:
        return unresolved("RESULT_RECIPE_WEAK")
    lineage = input_identities(ordered_inputs)
    if lineage is None:
        return unresolved("RESULT_INPUT_IDENTITY_WEAK")
    material = record_semantic_material(record, asset_content_identities)
    if material is None:
        return unresolved("RESULT_CONTENT_IDENTITY_WEAK")
    return digest_projection(
        ARTIFACT_DOMAIN,
        {
            "schema_id": record.schema_id,
            "schema_version": record.schema_version,
            "profile_id": record.profile_id if type(record) is Product else None,
            "profile_version": record.profile_version
            if type(record) is Product
            else None,
            "producer_task_fingerprint": producer_fingerprint.value,
            "output_port": output_port,
            "typed_semantic_projection": material,
            "scientific_asset_content_identities": asset_content_identities,
            "ordered_input_lineage": lineage,
        },
    )
