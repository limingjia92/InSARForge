from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

from insarforge.contracts._persistence import _validate_persistence_value
from insarforge.contracts.identity import PluginKind, PluginRef
from insarforge.contracts.values import ArtifactRef, FrozenJSON, freeze_json
from insarforge.products.assets import (
    AssetIntegrity,
    AssetKind,
    AssetLocation,
    AssetLocationKind,
    NativeAsset,
)
from insarforge.products.geometry import AxisDescriptor, GeometryDescriptor
from insarforge.products.grid import GridDefinition
from insarforge.products.layers import DataLayer, LayerSelector
from insarforge.products.models import LineageEntry, ProducerRef, Product, ProductionRef
from insarforge.products.nodata import NoDataKind, NoDataSpec
from insarforge.products.semantics import (
    PhysicalQuantity,
    SemanticStatus,
    SemanticValue,
    SignSpec,
    UnitSpec,
)

PRODUCT_MANIFEST_SCHEMA_ID = "insarforge:product"
PRODUCT_MANIFEST_SCHEMA_VERSION = 2
_PRODUCT_FIELDS = (
    "product_kind",
    "profile_id",
    "profile_version",
    "assets",
    "layers",
    "geometries",
    "acquisition_refs",
    "semantic_metadata",
    "extensions",
    "schema_id",
    "schema_version",
    "product_id",
    "producer",
    "produced_by",
    "lineage",
    "provenance_ref",
)


def _require_mapping_fields(value, expected, name):
    if not isinstance(value, Mapping) or any(not isinstance(k, str) for k in value):
        raise TypeError(name)
    if set(value) != set(expected):
        raise ValueError(f"{name} fields")
    return value


def _seq(value, name):
    if not isinstance(value, (tuple, list)):
        raise TypeError(name)
    return value


def _plain(v):
    if isinstance(v, Mapping):
        if any(type(k) is not str for k in v):
            raise TypeError("keys")
        return {k: _plain(x) for k, x in v.items()}
    if isinstance(v, (tuple, list)):
        return [_plain(x) for x in v]
    if type(v) in (str, int, float, bool) or v is None:
        return v
    raise TypeError("unsupported JSON value")


def canonical_json_bytes(value: FrozenJSON) -> bytes:
    try:
        return json.dumps(
            _plain(value),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    except (TypeError, ValueError) as e:
        raise TypeError("unsupported JSON value") from e


def strict_json_loads(data):
    if isinstance(data, bytes):
        data = data.decode("utf-8", "strict")
    if not isinstance(data, str):
        raise TypeError("data")

    def dup(pairs):
        d = {}
        for k, v in pairs:
            if k in d:
                raise ValueError("duplicate key")
            d[k] = v
        return d

    return freeze_json(
        json.loads(
            data,
            object_pairs_hook=dup,
            parse_constant=lambda x: (_ for _ in ()).throw(ValueError("nonfinite")),
        )
    )


def _e(x):
    if isinstance(x, Mapping):
        return {k: _e(v) for k, v in x.items()}
    if isinstance(x, ArtifactRef):
        return {
            "record_id": x.record_id,
            "schema_id": x.schema_id,
            "schema_version": x.schema_version,
            "semantic_digest": x.semantic_digest,
            "manifest_digest": x.manifest_digest,
            "locator": x.locator,
        }
    if isinstance(x, PluginRef):
        return {
            "kind": x.kind.value,
            "plugin_id": x.plugin_id,
            "api_version": x.api_version,
        }
    if isinstance(x, SemanticValue):
        return {
            "status": x.status.value,
            "value": _e(x.value),
            "reason_code": x.reason_code,
            "evidence_refs": [_e(y) for y in x.evidence_refs],
        }
    if isinstance(x, ProducerRef):
        return {
            "plugin": _e(x.plugin),
            "implementation_version": x.implementation_version,
            "implementation_identity_digest": _e(x.implementation_identity_digest),
            "execution_identity_digest": _e(x.execution_identity_digest),
        }
    if isinstance(x, ProductionRef):
        return {
            "task_fingerprint": _e(x.task_fingerprint),
            "output_port": x.output_port,
            "attempt_id": x.attempt_id,
        }
    if isinstance(x, LineageEntry):
        return {"role": x.role, "artifact": _e(x.artifact)}
    if isinstance(x, UnitSpec):
        return {
            "unit_id": x.unit_id,
            "quantity_kind": x.quantity_kind,
            "definition_ref": x.definition_ref,
        }
    if isinstance(x, SignSpec):
        return {
            "convention_id": x.convention_id,
            "observable": x.observable,
            "positive_direction": x.positive_direction,
            "minuend_ref": x.minuend_ref,
            "subtrahend_ref": x.subtrahend_ref,
            "evidence_refs": [_e(y) for y in x.evidence_refs],
        }
    if isinstance(x, PhysicalQuantity):
        return {
            "value": x.value,
            "unit": _e(x.unit),
            "source_ref": _e(x.source_ref),
            "evidence_refs": [_e(y) for y in x.evidence_refs],
        }
    if isinstance(x, AssetLocation):
        return {
            "kind": x.kind.value,
            "value": x.value,
            "anchor": str(x.anchor) if x.anchor else None,
        }
    if isinstance(x, AssetIntegrity):
        return {"algorithm": x.algorithm, "digest": x.digest}
    if isinstance(x, NativeAsset):
        return {
            "asset_id": x.asset_id,
            "asset_kind": x.asset_kind.value,
            "location": _e(x.location),
            "media_type": x.media_type,
            "size_bytes": x.size_bytes,
            "integrity": _e(x.integrity),
            "member_manifest_ref": _e(x.member_manifest_ref),
        }
    if isinstance(x, AxisDescriptor):
        return {
            "axis_id": x.axis_id,
            "role": x.role,
            "unit": _e(x.unit),
            "direction": _e(x.direction),
        }
    if isinstance(x, GridDefinition):
        return {"format_id": x.format_id, "parameters": _plain(x.parameters)}
    if isinstance(x, GeometryDescriptor):
        return {
            "geometry_id": x.geometry_id,
            "domain": x.domain,
            "coordinate_reference": _e(x.coordinate_reference),
            "axes": [_e(y) for y in x.axes],
            "shape": list(x.shape),
            "grid_definition": _e(x.grid_definition),
            "registration": _e(x.registration),
            "reference": _e(x.reference),
        }
    if isinstance(x, NoDataSpec):
        return {
            "kind": x.kind.value,
            "value": x.value,
            "mask_layer_ref": x.mask_layer_ref,
        }
    if isinstance(x, LayerSelector):
        return {"format_id": x.format_id, "selector_string": x.selector_string}
    if isinstance(x, DataLayer):
        return {
            "layer_id": x.layer_id,
            "role": x.role,
            "asset_id": x.asset_id,
            "selector": _e(x.selector),
            "quantity": _e(x.quantity),
            "unit": _e(x.unit),
            "sign": _e(x.sign),
            "geometry_ref": _e(x.geometry_ref),
            "nodata": _e(x.nodata),
            "dimensions": list(x.dimensions),
        }
    if isinstance(x, Product):
        return {k: _e(getattr(x, k)) for k in _PRODUCT_FIELDS}
    if isinstance(x, (tuple, list)):
        return [_e(y) for y in x]
    if isinstance(x, (str, int, float, bool)) or x is None:
        return x
    raise TypeError("unsupported")


def product_to_manifest_value(product):
    if not isinstance(product, Product):
        raise TypeError("product")
    value = freeze_json(_e(product))
    _validate_persistence_value(value)
    return value


def product_to_manifest_bytes(product):
    return canonical_json_bytes(product_to_manifest_value(product))


def _sv(v, typ=None, *, json_payload=False):
    if not isinstance(v, Mapping):
        raise TypeError("semantic")
    if set(v) != {"status", "value", "reason_code", "evidence_refs"}:
        raise ValueError("semantic fields")
    status = SemanticStatus(v["status"])
    value = v["value"]
    if status is not SemanticStatus.KNOWN:
        if value is not None:
            raise ValueError("non-null semantic value")
    elif json_payload:
        # Only explicit metadata envelopes admit a JSON payload from the wire.
        value = freeze_json(value)
    elif typ:
        if typ is str:
            if not isinstance(value, str):
                raise TypeError("semantic type")
            value = value
        else:
            value = _d(value, typ)
    return SemanticValue(
        status,
        value,
        v["reason_code"],
        tuple(_d(a, ArtifactRef) for a in _seq(v["evidence_refs"], "evidence_refs")),
    )


def _d(v, typ):
    fields = {
        ArtifactRef: {
            "record_id",
            "schema_id",
            "schema_version",
            "semantic_digest",
            "manifest_digest",
            "locator",
        },
        PluginRef: {"kind", "plugin_id", "api_version"},
        ProducerRef: {
            "plugin",
            "implementation_version",
            "implementation_identity_digest",
            "execution_identity_digest",
        },
        ProductionRef: {"task_fingerprint", "output_port", "attempt_id"},
        LineageEntry: {"role", "artifact"},
        UnitSpec: {"unit_id", "quantity_kind", "definition_ref"},
        SignSpec: {
            "convention_id",
            "observable",
            "positive_direction",
            "minuend_ref",
            "subtrahend_ref",
            "evidence_refs",
        },
        AssetLocation: {"kind", "value", "anchor"},
        NativeAsset: {
            "asset_id",
            "asset_kind",
            "location",
            "media_type",
            "size_bytes",
            "integrity",
            "member_manifest_ref",
        },
        AssetIntegrity: {"algorithm", "digest"},
        AxisDescriptor: {"axis_id", "role", "unit", "direction"},
        GridDefinition: {"format_id", "parameters"},
        GeometryDescriptor: {
            "geometry_id",
            "domain",
            "coordinate_reference",
            "axes",
            "shape",
            "grid_definition",
            "registration",
            "reference",
        },
        NoDataSpec: {"kind", "value", "mask_layer_ref"},
        LayerSelector: {"format_id", "selector_string"},
        DataLayer: {
            "layer_id",
            "role",
            "asset_id",
            "selector",
            "quantity",
            "unit",
            "sign",
            "geometry_ref",
            "nodata",
            "dimensions",
        },
    }
    if typ in fields:
        _require_mapping_fields(v, fields[typ], typ.__name__)
    if typ is ArtifactRef:
        return ArtifactRef(**dict(v))
    if typ is PluginRef:
        return PluginRef(PluginKind(v["kind"]), v["plugin_id"], v["api_version"])
    if typ is ProducerRef:
        return ProducerRef(
            plugin=_d(v["plugin"], PluginRef),
            implementation_version=v["implementation_version"],
            implementation_identity_digest=_sv(
                v["implementation_identity_digest"], str
            ),
            execution_identity_digest=_sv(v["execution_identity_digest"], str),
        )
    if typ is ProductionRef:
        return ProductionRef(
            task_fingerprint=_sv(v["task_fingerprint"], str),
            output_port=v["output_port"],
            attempt_id=v["attempt_id"],
        )
    if typ is LineageEntry:
        return LineageEntry(role=v["role"], artifact=_d(v["artifact"], ArtifactRef))
    if typ is UnitSpec:
        return UnitSpec(**dict(v))
    if typ is SignSpec:
        return SignSpec(
            v["convention_id"],
            v["observable"],
            v["positive_direction"],
            v["minuend_ref"],
            v["subtrahend_ref"],
            tuple(
                _d(a, ArtifactRef) for a in _seq(v["evidence_refs"], "evidence_refs")
            ),
        )
    if typ is PhysicalQuantity:
        return PhysicalQuantity(
            v["value"],
            _d(v["unit"], UnitSpec),
            _d(v["source_ref"], ArtifactRef) if v["source_ref"] else None,
            tuple(_d(a, ArtifactRef) for a in v["evidence_refs"]),
        )
    if typ is AssetLocation:
        anchor = v["anchor"]
        if anchor is not None:
            if not isinstance(anchor, str):
                raise TypeError("anchor")
            if not anchor:
                raise ValueError("anchor")
        return AssetLocation(
            AssetLocationKind(v["kind"]),
            v["value"],
            Path(anchor) if anchor is not None else None,
        )
    if typ is NativeAsset:
        return NativeAsset(
            v["asset_id"],
            AssetKind(v["asset_kind"]),
            _d(v["location"], AssetLocation),
            v["media_type"],
            v["size_bytes"],
            _d(v["integrity"], AssetIntegrity) if v["integrity"] is not None else None,
            _d(v["member_manifest_ref"], ArtifactRef)
            if v["member_manifest_ref"] is not None
            else None,
        )
    if typ is AssetIntegrity:
        return AssetIntegrity(v["algorithm"], v["digest"])
    if typ is AxisDescriptor:
        return AxisDescriptor(
            v["axis_id"],
            v["role"],
            _sv(v["unit"], UnitSpec),
            _sv(v["direction"], str),
        )
    if typ is GridDefinition:
        return GridDefinition(v["format_id"], v["parameters"])
    if typ is GeometryDescriptor:
        return GeometryDescriptor(
            v["geometry_id"],
            v["domain"],
            _sv(v["coordinate_reference"], str),
            tuple(_d(a, AxisDescriptor) for a in _seq(v["axes"], "axes")),
            tuple(_seq(v["shape"], "shape")),
            _sv(v["grid_definition"], GridDefinition),
            _sv(v["registration"], str),
            _sv(v["reference"], ArtifactRef),
        )
    if typ is LayerSelector:
        return LayerSelector(v["format_id"], v["selector_string"])
    if typ is NoDataSpec:
        return NoDataSpec(NoDataKind(v["kind"]), v["value"], v["mask_layer_ref"])
    if typ is DataLayer:
        return DataLayer(
            v["layer_id"],
            v["role"],
            v["asset_id"],
            None if v["selector"] is None else _d(v["selector"], LayerSelector),
            _sv(v["quantity"], str),
            _sv(v["unit"], UnitSpec),
            _sv(v["sign"], SignSpec),
            _sv(v["geometry_ref"], str),
            _sv(v["nodata"], NoDataSpec),
            tuple(_seq(v["dimensions"], "dimensions")),
        )


def product_from_manifest_value(value):
    p = _require_mapping_fields(value, _PRODUCT_FIELDS, "product")
    if (
        type(p["schema_id"]) is not str
        or p["schema_id"] != PRODUCT_MANIFEST_SCHEMA_ID
        or not isinstance(p["schema_version"], int)
        or isinstance(p["schema_version"], bool)
        or p["schema_version"] != PRODUCT_MANIFEST_SCHEMA_VERSION
    ):
        raise ValueError("envelope")
    if not isinstance(p["semantic_metadata"], Mapping):
        raise TypeError("semantic_metadata")
    return Product(
        product_kind=p["product_kind"],
        profile_id=p["profile_id"],
        profile_version=p["profile_version"],
        assets=tuple(_d(x, NativeAsset) for x in _seq(p["assets"], "assets")),
        layers=tuple(_d(x, DataLayer) for x in _seq(p["layers"], "layers")),
        geometries=tuple(
            _d(x, GeometryDescriptor) for x in _seq(p["geometries"], "geometries")
        ),
        acquisition_refs=tuple(
            _d(x, ArtifactRef) for x in _seq(p["acquisition_refs"], "acquisition_refs")
        ),
        semantic_metadata={
            key: _sv(entry, json_payload=True)
            for key, entry in p["semantic_metadata"].items()
        },
        extensions=p["extensions"],
        schema_id=p["schema_id"],
        schema_version=p["schema_version"],
        product_id=p["product_id"],
        producer=_d(p["producer"], ProducerRef),
        produced_by=_d(p["produced_by"], ProductionRef),
        lineage=tuple(_d(x, LineageEntry) for x in _seq(p["lineage"], "lineage")),
        provenance_ref=p["provenance_ref"],
    )


def product_from_manifest_bytes(data):
    return product_from_manifest_value(strict_json_loads(data))
