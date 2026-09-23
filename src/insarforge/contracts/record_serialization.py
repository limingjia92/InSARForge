"""Explicit finite record codecs for runtime manifests; no dynamic type lookup."""

from collections.abc import Mapping

from insarforge.contracts._persistence import _validate_persistence_value
from insarforge.contracts.errors import ContractError
from insarforge.contracts.identity import PluginKind, PluginRef
from insarforge.contracts.records import (
    AccessStatus,
    AcquisitionMetadata,
    CatalogEntry,
    CatalogSnapshot,
    ProviderAvailability,
    ProviderDelivery,
    QCFinding,
    QCMetric,
    QCReport,
    QCStatus,
)
from insarforge.contracts.values import ArtifactRef, freeze_json
from insarforge.products.models import Product
from insarforge.products.semantics import UnitSpec
from insarforge.products.serialization import (
    _d,
    _e,
    _sv,
    canonical_json_bytes,
    product_from_manifest_bytes,
    product_to_manifest_bytes,
    strict_json_loads,
)


def _fields(value, names):
    if not isinstance(value, Mapping) or set(value) != set(names.split()):
        raise ContractError("RECORD_FIELDS")
    return value


def _plugin(p):
    return {
        "kind": p.kind.value,
        "plugin_id": p.plugin_id,
        "api_version": p.api_version,
    }


def _decode_plugin(p):
    _fields(p, "kind plugin_id api_version")
    return PluginRef(PluginKind(p["kind"]), p["plugin_id"], p["api_version"])


def record_to_bytes(record):
    if type(record) is Product:
        return product_to_manifest_bytes(record)
    common = dict(
        record_id=record.record_id,
        schema_id=record.schema_id,
        schema_version=record.schema_version,
        extensions=record.extensions,
    )
    if type(record) is CatalogSnapshot:
        value = common | dict(
            record_type="catalog",
            provider=_plugin(record.provider),
            query_schema_id=record.query_schema_id,
            query_schema_version=record.query_schema_version,
            selectors=record.selectors,
            entries=[
                dict(
                    entry_id=e.entry_id,
                    access=dict(
                        availability=e.access.availability.value,
                        delivery=e.access.delivery.value,
                        access_required=e.access.authentication_required,
                        reason_code=e.access.reason_code,
                    ),
                    attributes=e.attributes,
                    evidence_refs=[_e(r) for r in e.evidence_refs],
                )
                for e in record.entries
            ],
        )
    elif type(record) is AcquisitionMetadata:
        value = common | dict(
            record_type="acquisition",
            source_ref=_e(record.source_ref),
            mission=_plugin(record.mission),
            attributes={k: _e(v) for k, v in record.attributes.items()},
            evidence_refs=[_e(r) for r in record.evidence_refs],
        )
    elif type(record) is QCReport:
        value = common | dict(
            record_type="qc",
            status=record.status.value,
            method_id=record.method_id,
            method_version=record.method_version,
            input_refs=[_e(r) for r in record.input_refs],
            metrics=[
                dict(
                    metric_id=m.metric_id,
                    value=_e(m.value),
                    unit=_e(m.unit),
                    details=m.details,
                )
                for m in record.metrics
            ],
            findings=[
                dict(finding_code=f.finding_code, details=f.details)
                for f in record.findings
            ],
        )
    else:
        raise ContractError("RECORD_TYPE")
    value = freeze_json(value)
    _validate_persistence_value(value)
    return canonical_json_bytes(value)


def record_from_bytes(ref, raw):
    """Strict complete codec, also usable by P4.2-02 candidate validation."""
    try:
        if ref.schema_id == "insarforge:product":
            record = product_from_manifest_bytes(raw)
            identity = record.product_id
        else:
            v = strict_json_loads(raw)
            _validate_persistence_value(v)
            common = "record_id schema_id schema_version extensions record_type"
            kind = v["record_type"]
            base = {
                k: v[k]
                for k in ("record_id", "schema_id", "schema_version", "extensions")
            }
            if kind == "catalog":
                _fields(
                    v,
                    common
                    + " provider query_schema_id query_schema_version selectors entries",
                )
                entries = []
                for e in v["entries"]:
                    _fields(e, "entry_id access attributes evidence_refs")
                    a = _fields(
                        e["access"], "availability delivery access_required reason_code"
                    )
                    entries.append(
                        CatalogEntry(
                            e["entry_id"],
                            AccessStatus(
                                ProviderAvailability(a["availability"]),
                                ProviderDelivery(a["delivery"]),
                                a["access_required"],
                                a["reason_code"],
                            ),
                            e["attributes"],
                            tuple(_d(r, ArtifactRef) for r in e["evidence_refs"]),
                        )
                    )
                record = CatalogSnapshot(
                    **base,
                    provider=_decode_plugin(v["provider"]),
                    query_schema_id=v["query_schema_id"],
                    query_schema_version=v["query_schema_version"],
                    selectors=v["selectors"],
                    entries=tuple(entries),
                )
            elif kind == "acquisition":
                _fields(v, common + " source_ref mission attributes evidence_refs")
                record = AcquisitionMetadata(
                    **base,
                    source_ref=_d(v["source_ref"], ArtifactRef),
                    mission=_decode_plugin(v["mission"]),
                    attributes={
                        k: _sv(a, json_payload=True) for k, a in v["attributes"].items()
                    },
                    evidence_refs=tuple(_d(r, ArtifactRef) for r in v["evidence_refs"]),
                )
            elif kind == "qc":
                _fields(
                    v,
                    common
                    + " status method_id method_version input_refs metrics findings",
                )
                metrics = []
                findings = []
                for m in v["metrics"]:
                    _fields(m, "metric_id value unit details")
                    metrics.append(
                        QCMetric(
                            m["metric_id"],
                            _sv(m["value"], json_payload=True),
                            _sv(m["unit"], UnitSpec),
                            m["details"],
                        )
                    )
                for f in v["findings"]:
                    _fields(f, "finding_code details")
                    findings.append(QCFinding(f["finding_code"], f["details"]))
                record = QCReport(
                    **base,
                    status=QCStatus(v["status"]),
                    method_id=v["method_id"],
                    method_version=v["method_version"],
                    input_refs=tuple(_d(r, ArtifactRef) for r in v["input_refs"]),
                    metrics=tuple(metrics),
                    findings=tuple(findings),
                )
            else:
                raise ValueError()
            identity = record.record_id
        if (record.schema_id, record.schema_version, identity) != (
            ref.schema_id,
            ref.schema_version,
            ref.record_id,
        ):
            raise ValueError()
        if record_to_bytes(record) != raw:
            # Canonical runtime wire format: also rejects bool versions, unused
            # fields and coercions that a permissive value constructor might accept.
            raise ValueError()
        return record
    except Exception:
        raise ContractError("RECORD_MANIFEST_INVALID") from None
