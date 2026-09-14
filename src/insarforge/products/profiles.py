from __future__ import annotations

from dataclasses import dataclass

from insarforge.contracts.values import FrozenJSON, freeze_json, validate_identifier
from insarforge.products.assets import AssetKind
from insarforge.products.models import Product, ProductDraft
from insarforge.products.semantics import SemanticStatus, SignSpec, UnitSpec
from insarforge.products.validation import (
    ProductValidationReport,
    ValidationIssue,
    ValidationIssueKind,
)


def _card(min_count, max_count):
    if isinstance(min_count, bool) or not isinstance(min_count, int) or min_count < 0:
        raise ValueError("min_count")
    if max_count is not None and (
        isinstance(max_count, bool)
        or not isinstance(max_count, int)
        or max_count < min_count
    ):
        raise ValueError("max_count")


def _ids(values, name):
    values = tuple(values)
    if any(not isinstance(v, str) for v in values):
        raise TypeError(name)
    for v in values:
        validate_identifier(v)
    if len(set(values)) != len(values):
        raise ValueError(name)
    return values


@dataclass(frozen=True)
class AssetRequirement:
    requirement_id: str
    allowed_kinds: tuple[AssetKind, ...]
    min_count: int
    max_count: int | None
    extensions: FrozenJSON

    def __post_init__(self):
        validate_identifier(self.requirement_id)
        kinds = tuple(self.allowed_kinds)
        if any(not isinstance(k, AssetKind) for k in kinds) or len(set(kinds)) != len(
            kinds
        ):
            raise ValueError("allowed_kinds")
        _card(self.min_count, self.max_count)
        object.__setattr__(self, "allowed_kinds", kinds)
        object.__setattr__(self, "extensions", freeze_json(self.extensions))


@dataclass(frozen=True)
class GeometryRequirement:
    requirement_id: str
    domain_id: str | None
    required_axis_roles: tuple[str, ...]
    require_known_registration: bool
    require_known_coordinate_reference: bool
    min_count: int
    max_count: int | None
    extensions: FrozenJSON

    def __post_init__(self):
        validate_identifier(self.requirement_id)
        if self.domain_id is not None:
            validate_identifier(self.domain_id)
        if not isinstance(self.require_known_registration, bool) or not isinstance(
            self.require_known_coordinate_reference, bool
        ):
            raise TypeError("known flags")
        _card(self.min_count, self.max_count)
        object.__setattr__(
            self, "required_axis_roles", _ids(self.required_axis_roles, "axis roles")
        )
        object.__setattr__(self, "extensions", freeze_json(self.extensions))


@dataclass(frozen=True)
class LayerRequirement:
    requirement_id: str
    role: str | None
    selector_kind: str | None
    geometry_domain_id: str | None
    quantity_kind: str | None
    unit_id: str | None
    sign_convention_id: str | None
    require_known_quantity: bool
    require_known_unit: bool
    require_known_sign: bool
    require_known_geometry: bool
    min_count: int
    max_count: int | None
    extensions: FrozenJSON

    def __post_init__(self):
        validate_identifier(self.requirement_id)
        for v in (
            self.role,
            self.selector_kind,
            self.geometry_domain_id,
            self.quantity_kind,
            self.unit_id,
            self.sign_convention_id,
        ):
            if v is not None:
                validate_identifier(v)
        if not all(
            isinstance(v, bool)
            for v in (
                self.require_known_quantity,
                self.require_known_unit,
                self.require_known_sign,
                self.require_known_geometry,
            )
        ):
            raise TypeError("known flags")
        _card(self.min_count, self.max_count)
        object.__setattr__(self, "extensions", freeze_json(self.extensions))


@dataclass(frozen=True)
class ProductProfile:
    profile_id: str
    profile_version: int
    allowed_product_kinds: tuple[str, ...]
    asset_requirements: tuple[AssetRequirement, ...]
    geometry_requirements: tuple[GeometryRequirement, ...]
    layer_requirements: tuple[LayerRequirement, ...]
    extensions: FrozenJSON

    def __post_init__(self):
        validate_identifier(self.profile_id)
        if (
            isinstance(self.profile_version, bool)
            or not isinstance(self.profile_version, int)
            or self.profile_version < 1
        ):
            raise ValueError("profile_version")
        kinds = _ids(self.allowed_product_kinds, "product kinds")
        ar = tuple(self.asset_requirements)
        gr = tuple(self.geometry_requirements)
        lr = tuple(self.layer_requirements)
        if (
            any(not isinstance(x, AssetRequirement) for x in ar)
            or any(not isinstance(x, GeometryRequirement) for x in gr)
            or any(not isinstance(x, LayerRequirement) for x in lr)
        ):
            raise TypeError("requirements")
        if len({x.requirement_id for x in ar + gr + lr}) != len(ar + gr + lr):
            raise ValueError("requirement ids")
        object.__setattr__(self, "allowed_product_kinds", kinds)
        object.__setattr__(self, "asset_requirements", ar)
        object.__setattr__(self, "geometry_requirements", gr)
        object.__setattr__(self, "layer_requirements", lr)
        object.__setattr__(self, "extensions", freeze_json(self.extensions))


def _asset_match(a, r):
    return not r.allowed_kinds or a.asset_kind in r.allowed_kinds


def _geom_match(g, r):
    return (
        (r.domain_id is None or g.domain_id == r.domain_id)
        and all(x in [a.role for a in g.axes] for x in r.required_axis_roles)
        and (
            not r.require_known_registration
            or g.registration.status is SemanticStatus.KNOWN
        )
        and (
            not r.require_known_coordinate_reference
            or g.coordinate_reference.status is SemanticStatus.KNOWN
        )
    )


def _layer_match(layer, r, assets, geoms):
    if (
        r.role is not None
        and layer.role != r.role
        or r.selector_kind is not None
        and layer.selector.selector_kind != r.selector_kind
    ):
        return False
    if (
        r.require_known_quantity
        and layer.quantity_kind.status is not SemanticStatus.KNOWN
        or r.quantity_kind is not None
        and (
            layer.quantity_kind.status is not SemanticStatus.KNOWN
            or layer.quantity_kind.value != r.quantity_kind
        )
    ):
        return False
    if (
        r.require_known_unit
        and layer.unit.status is not SemanticStatus.KNOWN
        or r.unit_id is not None
        and (
            layer.unit.status is not SemanticStatus.KNOWN
            or not isinstance(layer.unit.value, UnitSpec)
            or layer.unit.value.unit_id != r.unit_id
        )
    ):
        return False
    if (
        r.require_known_sign
        and layer.sign.status is not SemanticStatus.KNOWN
        or r.sign_convention_id is not None
        and (
            layer.sign.status is not SemanticStatus.KNOWN
            or not isinstance(layer.sign.value, SignSpec)
            or layer.sign.value.convention_id != r.sign_convention_id
        )
    ):
        return False
    g = next(
        (
            x
            for x in geoms
            if layer.geometry_ref.status is SemanticStatus.KNOWN
            and x.geometry_id == layer.geometry_ref.value
        ),
        None,
    )
    return (
        not r.require_known_geometry
        or layer.geometry_ref.status is SemanticStatus.KNOWN
    ) and (
        r.geometry_domain_id is None
        or g is not None
        and g.domain_id == r.geometry_domain_id
    )


def validate_product_profile(product, profile):
    if not isinstance(product, (Product, ProductDraft)) or not isinstance(
        profile, ProductProfile
    ):
        raise TypeError("product/profile")
    issues = []

    def add(code, r, n):
        if n < r.min_count or r.max_count is not None and n > r.max_count:
            issues.append(
                ValidationIssue(
                    ValidationIssueKind.ERROR,
                    code,
                    r.requirement_id,
                    {
                        "requirement_id": r.requirement_id,
                        "observed_count": n,
                        "min_count": r.min_count,
                        "max_count": r.max_count,
                    },
                )
            )

    if product.profile_id != profile.profile_id:
        issues.append(
            ValidationIssue(
                ValidationIssueKind.ERROR,
                "validation:profile-id-mismatch",
                "profile_id",
                {},
            )
        )
    if product.profile_version != profile.profile_version:
        issues.append(
            ValidationIssue(
                ValidationIssueKind.ERROR,
                "validation:profile-version-mismatch",
                "profile_version",
                {},
            )
        )
    if (
        profile.allowed_product_kinds
        and product.product_kind not in profile.allowed_product_kinds
    ):
        issues.append(
            ValidationIssue(
                ValidationIssueKind.ERROR,
                "validation:product-kind-not-allowed",
                "product_kind",
                {},
            )
        )
    for r in profile.asset_requirements:
        add(
            "validation:asset-requirement-unsatisfied",
            r,
            sum(_asset_match(a, r) for a in product.assets),
        )
    for r in profile.geometry_requirements:
        add(
            "validation:geometry-requirement-unsatisfied",
            r,
            sum(_geom_match(g, r) for g in product.geometries),
        )
    for r in profile.layer_requirements:
        add(
            "validation:layer-requirement-unsatisfied",
            r,
            sum(
                _layer_match(layer, r, product.assets, product.geometries)
                for layer in product.layers
            ),
        )
    return ProductValidationReport(tuple(issues))
