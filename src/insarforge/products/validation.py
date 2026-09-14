from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from insarforge.contracts.values import FrozenJSON, freeze_json, validate_identifier
from insarforge.products.assets import NativeAsset
from insarforge.products.geometry import AxisDescriptor, GeometryDescriptor
from insarforge.products.layers import DataLayer
from insarforge.products.models import Product, ProductDraft
from insarforge.products.nodata import NoDataKind
from insarforge.products.semantics import SemanticStatus


class ValidationIssueKind(Enum):
    ERROR = "error"
    UNVERIFIED = "unverified"


@dataclass(frozen=True)
class ValidationIssue:
    kind: ValidationIssueKind
    code: str
    location: str
    details: FrozenJSON

    def __post_init__(self):
        if not isinstance(self.kind, ValidationIssueKind):
            raise TypeError("kind")
        validate_identifier(self.code)
        if (
            not isinstance(self.location, str)
            or not self.location
            or self.location != self.location.strip()
        ):
            raise ValueError("location")
        object.__setattr__(self, "details", freeze_json(self.details))


@dataclass(frozen=True)
class ProductValidationReport:
    issues: tuple[ValidationIssue, ...]

    def __post_init__(self):
        issues = tuple(self.issues)
        if any(not isinstance(i, ValidationIssue) for i in issues):
            raise TypeError("issues")
        object.__setattr__(self, "issues", issues)

    @property
    def errors(self):
        return tuple(i for i in self.issues if i.kind is ValidationIssueKind.ERROR)

    @property
    def unverified(self):
        return tuple(i for i in self.issues if i.kind is ValidationIssueKind.UNVERIFIED)

    @property
    def is_valid(self):
        return not self.errors

    @property
    def is_fully_verified(self):
        return not self.issues


def _issue(code, location, details=None):
    return ValidationIssue(ValidationIssueKind.ERROR, code, location, details or {})


def validate_product_structure(
    product: ProductDraft | Product,
) -> ProductValidationReport:
    if not isinstance(product, (ProductDraft, Product)):
        raise TypeError("product")
    issues = []
    assets, geometries, layers = product.assets, product.geometries, product.layers
    seen = set()
    for i, asset in enumerate(assets):
        if not isinstance(asset, NativeAsset):
            issues.append(_issue("validation:wrong-element-type", f"assets[{i}]"))
        elif asset.asset_id in seen:
            issues.append(_issue("validation:duplicate-asset-id", f"assets[{i}]"))
        else:
            seen.add(asset.asset_id)
    seen = set()
    for i, geometry in enumerate(geometries):
        if not isinstance(geometry, GeometryDescriptor):
            issues.append(_issue("validation:wrong-element-type", f"geometries[{i}]"))
        elif geometry.geometry_id in seen:
            issues.append(
                _issue("validation:duplicate-geometry-id", f"geometries[{i}]")
            )
        else:
            seen.add(geometry.geometry_id)
    seen = set()
    for i, layer in enumerate(layers):
        if not isinstance(layer, DataLayer):
            issues.append(_issue("validation:wrong-element-type", f"layers[{i}]"))
        elif layer.layer_id in seen:
            issues.append(_issue("validation:duplicate-layer-id", f"layers[{i}]"))
        else:
            seen.add(layer.layer_id)
    geometry_ids = {
        g.geometry_id for g in geometries if isinstance(g, GeometryDescriptor)
    }
    asset_ids = {a.asset_id for a in assets if isinstance(a, NativeAsset)}
    layer_ids = {layer.layer_id for layer in layers if isinstance(layer, DataLayer)}
    for i, geometry in enumerate(geometries):
        if not isinstance(geometry, GeometryDescriptor):
            continue
        if len(geometry.shape) != len(geometry.axes):
            issues.append(
                _issue("validation:geometry-axis-count-mismatch", f"geometries[{i}]")
            )
        axis_ids = set()
        for j, axis in enumerate(geometry.axes):
            if not isinstance(axis, AxisDescriptor):
                issues.append(
                    _issue(
                        "validation:wrong-element-type", f"geometries[{i}].axes[{j}]"
                    )
                )
            elif axis.axis_id in axis_ids:
                issues.append(
                    _issue("validation:duplicate-axis-id", f"geometries[{i}].axes[{j}]")
                )
            else:
                axis_ids.add(axis.axis_id)
            if (
                isinstance(axis, AxisDescriptor)
                and j < len(geometry.shape)
                and axis.size != geometry.shape[j]
            ):
                issues.append(
                    _issue(
                        "validation:geometry-axis-size-mismatch",
                        f"geometries[{i}].axes[{j}]",
                    )
                )
    for i, layer in enumerate(layers):
        if not isinstance(layer, DataLayer):
            continue
        if (
            layer.nodata.status is SemanticStatus.KNOWN
            and layer.nodata.value.kind is NoDataKind.MASK
            and layer.nodata.value.mask_layer_ref not in layer_ids
        ):
            issues.append(
                _issue(
                    "validation:missing-mask-layer-reference",
                    f"layers[{i}].nodata.mask_layer_ref",
                )
            )
        if layer.asset_id not in asset_ids:
            issues.append(
                _issue("validation:missing-asset-reference", f"layers[{i}].asset_id")
            )
        if (
            layer.geometry_ref.status is SemanticStatus.KNOWN
            and layer.geometry_ref.value not in geometry_ids
        ):
            issues.append(
                _issue(
                    "validation:missing-geometry-reference", f"layers[{i}].geometry_ref"
                )
            )
    return ProductValidationReport(tuple(issues))
