from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

from insarforge.contracts.identity import PluginKind, PluginRef
from insarforge.contracts.values import ArtifactRef, FrozenJSON, freeze_json
from insarforge.products.assets import (
    AssetKind,
    AssetLocation,
    AssetLocationKind,
    NativeAsset,
)
from insarforge.products.geometry import AxisDescriptor, GeometryDescriptor
from insarforge.products.layers import DataLayer, LayerSelector
from insarforge.products.models import Product
from insarforge.products.semantics import (
    PhysicalQuantity,
    SemanticStatus,
    SemanticValue,
    SignSpec,
    UnitSpec,
)

PRODUCT_MANIFEST_SCHEMA_ID = "insarforge:product-manifest"
PRODUCT_MANIFEST_SCHEMA_VERSION = 1


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
        if any(not isinstance(k, str) for k in v):
            raise TypeError("keys")
        return {k: _plain(x) for k, x in v.items()}
    if isinstance(v, (tuple, list)):
        return [_plain(x) for x in v]
    if isinstance(v, (str, int, float, bool)) or v is None:
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
    if isinstance(x, NativeAsset):
        return {
            "asset_id": x.asset_id,
            "role": x.role,
            "kind": x.kind.value,
            "location": _e(x.location),
            "media_type": x.media_type,
            "size_bytes": x.size_bytes,
            "checksum_algorithm": x.checksum_algorithm,
            "checksum": x.checksum,
            "extensions": _plain(x.extensions),
        }
    if isinstance(x, AxisDescriptor):
        return {
            "axis_id": x.axis_id,
            "role": x.role,
            "size": x.size,
            "unit": _e(x.unit),
            "direction": _e(x.direction),
            "extensions": _plain(x.extensions),
        }
    if isinstance(x, GeometryDescriptor):
        return {
            "geometry_id": x.geometry_id,
            "domain_id": x.domain_id,
            "shape": list(x.shape),
            "axes": [_e(y) for y in x.axes],
            "registration": _e(x.registration),
            "coordinate_reference": _e(x.coordinate_reference),
            "extensions": _plain(x.extensions),
        }
    if isinstance(x, LayerSelector):
        return {"selector_kind": x.selector_kind, "parameters": _plain(x.parameters)}
    if isinstance(x, DataLayer):
        return {
            "layer_id": x.layer_id,
            "role": x.role,
            "asset_id": x.asset_id,
            "selector": _e(x.selector),
            "quantity_kind": _e(x.quantity_kind),
            "unit": _e(x.unit),
            "sign": _e(x.sign),
            "geometry_ref": _e(x.geometry_ref),
            "extensions": _plain(x.extensions),
        }
    if isinstance(x, Product):
        return {
            k: _e(getattr(x, k))
            for k in (
                "product_id",
                "schema_version",
                "product_kind",
                "profile_id",
                "profile_version",
                "producer",
                "producer_implementation_version",
                "provenance_ref",
                "lineage",
                "assets",
                "geometries",
                "layers",
                "extensions",
            )
        }
    if isinstance(x, (tuple, list)):
        return [_e(y) for y in x]
    if isinstance(x, (str, int, float, bool)) or x is None:
        return x
    raise TypeError("unsupported")


def product_to_manifest_value(product):
    if not isinstance(product, Product):
        raise TypeError("product")
    return freeze_json(
        {
            "schema_id": PRODUCT_MANIFEST_SCHEMA_ID,
            "schema_version": 1,
            "product": _e(product),
        }
    )


def product_to_manifest_bytes(product):
    return canonical_json_bytes(product_to_manifest_value(product))


def _sv(v, typ=None):
    if not isinstance(v, Mapping):
        raise TypeError("semantic")
    if set(v) != {"status", "value", "reason_code", "evidence_refs"}:
        raise ValueError("semantic fields")
    status = SemanticStatus(v["status"])
    value = v["value"]
    if status is not SemanticStatus.KNOWN:
        if value is not None:
            raise ValueError("non-null semantic value")
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
        tuple(_d(a, ArtifactRef) for a in v["evidence_refs"]),
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
            "role",
            "kind",
            "location",
            "media_type",
            "size_bytes",
            "checksum_algorithm",
            "checksum",
            "extensions",
        },
        AxisDescriptor: {"axis_id", "role", "size", "unit", "direction", "extensions"},
        GeometryDescriptor: {
            "geometry_id",
            "domain_id",
            "shape",
            "axes",
            "registration",
            "coordinate_reference",
            "extensions",
        },
        LayerSelector: {"selector_kind", "parameters"},
        DataLayer: {
            "layer_id",
            "role",
            "asset_id",
            "selector",
            "quantity_kind",
            "unit",
            "sign",
            "geometry_ref",
            "extensions",
        },
    }
    if typ in fields:
        _require_mapping_fields(v, fields[typ], typ.__name__)
    if typ is ArtifactRef:
        return ArtifactRef(**dict(v))
    if typ is PluginRef:
        return PluginRef(PluginKind(v["kind"]), v["plugin_id"], v["api_version"])
    if typ is UnitSpec:
        return UnitSpec(**dict(v))
    if typ is SignSpec:
        return SignSpec(
            v["convention_id"],
            v["observable"],
            v["positive_direction"],
            v["minuend_ref"],
            v["subtrahend_ref"],
            tuple(_d(a, ArtifactRef) for a in v["evidence_refs"]),
        )
    if typ is PhysicalQuantity:
        return PhysicalQuantity(
            v["value"],
            _d(v["unit"], UnitSpec),
            _d(v["source_ref"], ArtifactRef) if v["source_ref"] else None,
            tuple(_d(a, ArtifactRef) for a in v["evidence_refs"]),
        )
    if typ is AssetLocation:
        return AssetLocation(
            AssetLocationKind(v["kind"]),
            v["value"],
            Path(v["anchor"]) if v["anchor"] else None,
        )
    if typ is NativeAsset:
        return NativeAsset(
            v["asset_id"],
            v["role"],
            AssetKind(v["kind"]),
            _d(v["location"], AssetLocation),
            v["media_type"],
            v["size_bytes"],
            v["checksum_algorithm"],
            v["checksum"],
            v["extensions"],
        )
    if typ is AxisDescriptor:
        return AxisDescriptor(
            v["axis_id"],
            v["role"],
            v["size"],
            _sv(v["unit"], UnitSpec),
            _sv(v["direction"], str),
            v["extensions"],
        )
    if typ is GeometryDescriptor:
        return GeometryDescriptor(
            v["geometry_id"],
            v["domain_id"],
            tuple(_seq(v["shape"], "shape")),
            tuple(_d(a, AxisDescriptor) for a in _seq(v["axes"], "axes")),
            _sv(v["registration"], str),
            _sv(v["coordinate_reference"], str),
            v["extensions"],
        )
    if typ is LayerSelector:
        return LayerSelector(v["selector_kind"], v["parameters"])
    if typ is DataLayer:
        return DataLayer(
            v["layer_id"],
            v["role"],
            v["asset_id"],
            _d(v["selector"], LayerSelector),
            _sv(v["quantity_kind"], str),
            _sv(v["unit"], UnitSpec),
            _sv(v["sign"], SignSpec),
            _sv(v["geometry_ref"], str),
            v["extensions"],
        )


def product_from_manifest_value(value):
    if (
        not isinstance(value, Mapping)
        or set(value) != {"schema_id", "schema_version", "product"}
        or value["schema_id"] != PRODUCT_MANIFEST_SCHEMA_ID
        or not isinstance(value.get("schema_version"), int)
        or isinstance(value.get("schema_version"), bool)
        or value["schema_version"] != 1
    ):
        raise ValueError("envelope")
    p = value["product"]
    if not isinstance(p, Mapping) or set(p) != {
        "product_id",
        "schema_version",
        "product_kind",
        "profile_id",
        "profile_version",
        "producer",
        "producer_implementation_version",
        "provenance_ref",
        "lineage",
        "assets",
        "geometries",
        "layers",
        "extensions",
    }:
        raise ValueError("product fields")
    if isinstance(p["schema_version"], bool) or not isinstance(
        p["schema_version"], int
    ):
        raise ValueError("version")
    if not isinstance(value["schema_version"], int) or isinstance(
        value["schema_version"], bool
    ):
        raise ValueError("version")
    return Product(
        p["product_id"],
        p["schema_version"],
        p["product_kind"],
        p["profile_id"],
        p["profile_version"],
        _d(p["producer"], PluginRef),
        p["producer_implementation_version"],
        _d(p["provenance_ref"], ArtifactRef) if p["provenance_ref"] else None,
        tuple(_d(x, ArtifactRef) for x in _seq(p["lineage"], "lineage")),
        tuple(_d(x, NativeAsset) for x in _seq(p["assets"], "assets")),
        tuple(_d(x, GeometryDescriptor) for x in _seq(p["geometries"], "geometries")),
        tuple(_d(x, DataLayer) for x in _seq(p["layers"], "layers")),
        p["extensions"],
    )


def product_from_manifest_bytes(data):
    return product_from_manifest_value(strict_json_loads(data))
