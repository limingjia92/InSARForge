from __future__ import annotations

import hashlib
from collections.abc import Mapping

from insarforge.contracts.values import ArtifactRef, FrozenJSON, freeze_json
from insarforge.products.grid import GridDefinition
from insarforge.products.models import Product
from insarforge.products.nodata import NoDataSpec
from insarforge.products.semantics import (
    PhysicalQuantity,
    SemanticValue,
    SignSpec,
    UnitSpec,
)
from insarforge.products.serialization import (
    canonical_json_bytes,
    product_to_manifest_bytes,
)

DIGEST_ALGORITHM = "sha256"
PRODUCT_SEMANTIC_MATERIAL_SCHEMA_ID = "insarforge:product-semantic-material"
PRODUCT_SEMANTIC_MATERIAL_SCHEMA_VERSION = 1
PRODUCT_CONTENT_DIGEST_ALGORITHM_REVISION = 1
PRODUCT_CONTENT_DIGEST_DOMAIN_TAG = b"insarforge:product-content-digest:v1\x00"


def sha256_hex(data: bytes) -> str:
    if not isinstance(data, bytes):
        raise TypeError("data must be bytes")
    return hashlib.sha256(data).hexdigest()


def product_manifest_digest(product: Product) -> str:
    return sha256_hex(product_to_manifest_bytes(product))


def _ref(ref):
    if ref.semantic_digest is None or not ref.semantic_digest:
        raise ValueError("missing semantic identity")
    return ref.semantic_digest


def _semantic(value):
    if not isinstance(value, SemanticValue):
        return _value(value)
    return {
        "status": value.status.value,
        "value": None if value.value is None else _value(value.value),
        "reason_code": value.reason_code,
        "evidence_semantic_digests": [_ref(r) for r in value.evidence_refs],
    }


def _value(value):
    if isinstance(value, ArtifactRef):
        return _ref(value)
    if isinstance(value, GridDefinition):
        return {"format_id": value.format_id, "parameters": _value(value.parameters)}
    if isinstance(value, NoDataSpec):
        return {
            "kind": value.kind.value,
            "value": value.value,
            "mask_layer_ref": value.mask_layer_ref,
        }
    if isinstance(value, SemanticValue):
        return _semantic(value)
    if isinstance(value, UnitSpec):
        return freeze_json(
            {
                "unit_id": value.unit_id,
                "quantity_kind": value.quantity_kind,
                "definition_ref": value.definition_ref,
            }
        )
    if isinstance(value, SignSpec):
        return freeze_json(
            {
                "convention_id": value.convention_id,
                "observable": value.observable,
                "positive_direction": value.positive_direction,
                "minuend_ref": value.minuend_ref,
                "subtrahend_ref": value.subtrahend_ref,
                "evidence_semantic_digests": [_ref(r) for r in value.evidence_refs],
            }
        )
    if isinstance(value, PhysicalQuantity):
        return {
            "value": value.value,
            "unit": _value(value.unit),
            "source_semantic_digest": None
            if value.source_ref is None
            else _ref(value.source_ref),
            "evidence_semantic_digests": [_ref(r) for r in value.evidence_refs],
        }
    if isinstance(value, Mapping):
        return {k: _value(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [_value(v) for v in value]
    return value


def product_semantic_material(
    product: Product, *, asset_content_identities: Mapping[str, str | None]
) -> FrozenJSON | None:
    if not isinstance(asset_content_identities, Mapping):
        raise TypeError("asset_content_identities")
    ids = {a.asset_id for a in product.assets}
    if set(asset_content_identities) != ids or any(
        not isinstance(k, str) for k in asset_content_identities
    ):
        raise ValueError("asset identities must match product assets")
    for value in asset_content_identities.values():
        if value is not None and (
            not isinstance(value, str) or not value or value != value.strip()
        ):
            raise ValueError("invalid asset content identity")
    if any(v is None for v in asset_content_identities.values()) or any(
        r.semantic_digest is None for r in product.lineage
    ):
        return None
    try:
        assets = [
            {
                "asset_id": a.asset_id,
                "asset_kind": a.asset_kind.value,
                "content_identity": asset_content_identities[a.asset_id],
            }
            for a in product.assets
        ]
        geometries = []
        for g in product.geometries:
            geometries.append(
                {
                    "geometry_id": g.geometry_id,
                    "domain": g.domain,
                    "coordinate_reference": _semantic(g.coordinate_reference),
                    "axes": [
                        {
                            "axis_id": a.axis_id,
                            "role": a.role,
                            "unit": _semantic(a.unit),
                            "direction": _semantic(a.direction),
                        }
                        for a in g.axes
                    ],
                    "shape": list(g.shape),
                    "grid_definition": _semantic(g.grid_definition),
                    "registration": _semantic(g.registration),
                    "reference": _semantic(g.reference),
                }
            )
        layers = [
            {
                "layer_id": layer.layer_id,
                "role": layer.role,
                "asset_id": layer.asset_id,
                "selector": None
                if layer.selector is None
                else {
                    "format_id": layer.selector.format_id,
                    "selector_string": layer.selector.selector_string,
                },
                "quantity": _semantic(layer.quantity),
                "unit": _semantic(layer.unit),
                "sign": _semantic(layer.sign),
                "geometry_ref": _semantic(layer.geometry_ref),
                "nodata": _semantic(layer.nodata),
                "dimensions": list(layer.dimensions),
            }
            for layer in product.layers
        ]
        return {
            "schema_id": PRODUCT_SEMANTIC_MATERIAL_SCHEMA_ID,
            "schema_version": PRODUCT_SEMANTIC_MATERIAL_SCHEMA_VERSION,
            "product": {
                "product_kind": product.product_kind,
                "profile_id": product.profile_id,
                "profile_version": product.profile_version,
                "product_schema_version": product.schema_version,
                "lineage_semantic_digests": [_ref(r) for r in product.lineage],
                "assets": assets,
                "geometries": geometries,
                "layers": layers,
            },
            "extensions": _value(product.extensions),
        }
    except ValueError:
        return None


def product_content_digest(
    product: Product, *, asset_content_identities: Mapping[str, str | None]
) -> str | None:
    material = product_semantic_material(
        product=product, asset_content_identities=asset_content_identities
    )
    return (
        None
        if material is None
        else sha256_hex(
            PRODUCT_CONTENT_DIGEST_DOMAIN_TAG + canonical_json_bytes(material)
        )
    )
