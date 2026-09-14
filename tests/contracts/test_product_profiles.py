from dataclasses import replace

import pytest
from test_product_models import populated_product, sv

from insarforge.products.layers import LayerSelector
from insarforge.products.models import ProductDraft
from insarforge.products.profiles import (
    LayerRequirement,
    ProductProfile,
    validate_product_profile,
)
from insarforge.products.semantics import SemanticStatus, SemanticValue


def test_empty_profile_matches_draft():
    product = ProductDraft(1, "kind:test", "profile:test", 1, (), (), (), (), {})
    profile = ProductProfile("profile:test", 1, (), (), (), (), {})
    report = validate_product_profile(product, profile)
    assert report.is_valid and report.is_fully_verified


def requirement(**changes):
    fields = dict(
        requirement_id="synthetic:requirement",
        role=None,
        selector_kind=None,
        geometry_domain_id=None,
        quantity_kind=None,
        unit_id=None,
        sign_convention_id=None,
        require_known_quantity=False,
        require_known_unit=False,
        require_known_sign=False,
        require_known_geometry=False,
        min_count=1,
        max_count=None,
        extensions={},
    )
    fields.update(changes)
    return LayerRequirement(**fields)


def matches(product, req):
    profile = ProductProfile("profile:test", 1, (), (), (), (req,), {})
    return validate_product_profile(product, profile).is_valid


@pytest.mark.parametrize(
    "constraint",
    [
        dict(role="role:test"),
        dict(selector_kind="selector:test"),
        dict(quantity_kind="quantity:x"),
        dict(unit_id="unit:x"),
        dict(sign_convention_id="sign:x"),
        dict(require_known_quantity=True),
        dict(require_known_unit=True),
        dict(require_known_sign=True),
    ],
)
def test_layer_requirements_match_final_fields(constraint):
    product = populated_product()
    assert matches(product, requirement(**constraint))
    for key, value in constraint.items():
        if isinstance(value, str):
            assert not matches(product, requirement(**{key: "synthetic:other"}))


def test_selector_requirement_rejects_whole_asset_and_cardinality_preserved():
    product = populated_product()
    whole = replace(
        product, layers=tuple(replace(layer, selector=None) for layer in product.layers)
    )
    assert not matches(whole, requirement(selector_kind="selector:test"))
    assert matches(whole, requirement())
    assert matches(product, requirement(min_count=3, max_count=3))
    assert not matches(product, requirement(min_count=4))
    assert not matches(product, requirement(max_count=2))
    explicit = replace(
        whole,
        layers=(
            replace(whole.layers[0], selector=LayerSelector("synthetic:new", "opaque")),
            *whole.layers[1:],
        ),
    )
    assert matches(explicit, requirement(selector_kind="synthetic:new", max_count=1))


@pytest.mark.parametrize(
    "name,flag,match_field",
    [
        ("quantity", "require_known_quantity", "quantity_kind"),
        ("unit", "require_known_unit", "unit_id"),
        ("sign", "require_known_sign", "sign_convention_id"),
        ("geometry_ref", "require_known_geometry", "geometry_domain_id"),
    ],
)
@pytest.mark.parametrize(
    "status", [SemanticStatus.UNKNOWN, SemanticStatus.NOT_APPLICABLE]
)
def test_unknown_and_not_applicable_fail_declared_known_requirements(
    name, flag, match_field, status
):
    product = populated_product()
    value = SemanticValue(status, None, "synthetic:reason", ())
    product = replace(
        product,
        layers=tuple(replace(layer, **{name: value}) for layer in product.layers),
    )
    assert matches(product, requirement())
    assert not matches(product, requirement(**{flag: True}))
    assert not matches(product, requirement(**{match_field: "synthetic:expected"}))


def test_geometry_requirement_uses_existing_transitional_geometry_without_alignment():
    from insarforge.products.geometry import AxisDescriptor, GeometryDescriptor
    from insarforge.products.semantics import UnitSpec

    product = populated_product()
    unknown = SemanticValue(SemanticStatus.UNKNOWN, None, "synthetic:reason", ())
    geometry = GeometryDescriptor(
        "synthetic:geometry",
        "synthetic:domain",
        (2,),
        (
            AxisDescriptor(
                "synthetic:axis",
                "synthetic:role",
                2,
                sv(UnitSpec("synthetic:unit", "synthetic:quantity", None)),
                unknown,
                {},
            ),
        ),
        unknown,
        unknown,
        {},
    )
    product = replace(
        product,
        geometries=(geometry,),
        layers=tuple(
            replace(layer, geometry_ref=sv(geometry.geometry_id))
            for layer in product.layers
        ),
    )
    assert matches(
        product,
        requirement(require_known_geometry=True, geometry_domain_id="synthetic:domain"),
    )
    assert not matches(product, requirement(geometry_domain_id="synthetic:other"))
