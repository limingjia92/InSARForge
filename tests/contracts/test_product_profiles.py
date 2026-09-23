from dataclasses import MISSING, fields, replace
from types import MappingProxyType

import pytest
from test_product_models import populated_product

from insarforge.contracts.values import freeze_json
from insarforge.products.layers import LayerSelector
from insarforge.products.models import ProductDraft
from insarforge.products.profiles import (
    AssetRequirement,
    GeometryRequirement,
    LayerRequirement,
    ProductProfile,
    validate_product_profile,
)
from insarforge.products.semantics import SemanticStatus, SemanticValue


def test_empty_profile_matches_draft():
    product = ProductDraft(
        product_kind="kind:test",
        profile_id="profile:test",
        profile_version=1,
        assets=(),
        layers=(),
        geometries=(),
        acquisition_refs=(),
        semantic_metadata={},
        extensions={},
    )
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


def test_layer_geometry_requirement_uses_final_domain():
    product = populated_product()
    domain = product.geometries[0].domain
    assert matches(
        product,
        requirement(require_known_geometry=True, geometry_domain_id=domain),
    )
    assert not matches(product, requirement(geometry_domain_id="synthetic:other"))


def geometry_requirement(**changes):
    values = dict(
        requirement_id="requirement:geometry",
        domain_id=None,
        required_axis_roles=(),
        require_known_registration=False,
        require_known_coordinate_reference=False,
        min_count=1,
        max_count=None,
        extensions={},
    )
    return GeometryRequirement(**(values | changes))


def geometry_report(product, **changes):
    profile = ProductProfile(
        "profile:test", 1, (), (), (geometry_requirement(**changes),), (), {}
    )
    return validate_product_profile(product, profile)


def test_geometry_requirement_compares_public_domain_id_to_final_domain():
    product = populated_product()
    assert geometry_report(
        product, domain_id=product.geometries[0].domain
    ).is_fully_verified
    report = geometry_report(product, domain_id="domain:other")
    assert [issue.code for issue in report.errors] == [
        "validation:geometry-requirement-unsatisfied"
    ]
    assert report.errors[0].details["observed_count"] == 0


def test_geometry_role_requirements_ignore_axis_order():
    product = populated_product()
    original = product.geometries[0]
    axes = (
        replace(original.axes[0], axis_id="axis:test-z", role="role:first"),
        replace(original.axes[0], axis_id="axis:test-a", role="role:second"),
    )
    product = replace(
        product, layers=(), geometries=(replace(original, axes=axes, shape=(5, 2)),)
    )
    assert geometry_report(
        product, required_axis_roles=("role:second", "role:first")
    ).is_valid
    assert geometry_report(product, required_axis_roles=("role:first",)).is_valid
    assert not geometry_report(product, required_axis_roles=("role:missing",)).is_valid
    reversed_product = replace(
        product,
        geometries=(replace(product.geometries[0], axes=axes[::-1], shape=(2, 5)),),
    )
    assert geometry_report(
        reversed_product, required_axis_roles=("role:first", "role:second")
    ).is_valid
    assert not geometry_report(product, required_axis_roles=("axis:test-z",)).is_valid


@pytest.mark.parametrize(
    "field,flag",
    [
        ("registration", "require_known_registration"),
        ("coordinate_reference", "require_known_coordinate_reference"),
    ],
)
@pytest.mark.parametrize("status", list(SemanticStatus))
def test_geometry_known_semantics_are_checked_without_interpretation(
    field, flag, status
):
    product = populated_product()
    geometry = product.geometries[0]
    semantic = SemanticValue(
        status,
        getattr(geometry, field).value if status is SemanticStatus.KNOWN else None,
        "reason:synthetic",
        (),
    )
    product = replace(product, geometries=(replace(geometry, **{field: semantic}),))
    assert geometry_report(product).is_valid
    assert geometry_report(product, **{flag: True}).is_valid is (
        status is SemanticStatus.KNOWN
    )


@pytest.mark.parametrize(
    "count,min_count,max_count,valid",
    [
        (0, 0, 0, True),
        (0, 1, None, False),
        (1, 1, 1, True),
        (1, 2, None, False),
        (2, 1, 1, False),
        (2, 1, 2, True),
    ],
)
def test_geometry_cardinality_is_preserved(count, min_count, max_count, valid):
    product = populated_product()
    geometry = product.geometries[0]
    product = replace(
        product,
        layers=(),
        geometries=tuple(
            replace(geometry, geometry_id=f"geometry:test-{i}") for i in range(count)
        ),
    )
    report = geometry_report(product, min_count=min_count, max_count=max_count)
    assert report.is_valid is valid
    if not valid:
        assert report.errors[0].details["observed_count"] == count


@pytest.mark.parametrize(
    "status", [SemanticStatus.UNKNOWN, SemanticStatus.NOT_APPLICABLE]
)
def test_nonknown_layer_geometry_does_not_match_domain(status):
    product = populated_product()
    semantic = SemanticValue(status, None, "reason:synthetic", ())
    product = replace(
        product,
        layers=tuple(replace(layer, geometry_ref=semantic) for layer in product.layers),
    )
    assert matches(product, requirement())
    assert not matches(
        product, requirement(geometry_domain_id=product.geometries[0].domain)
    )


def test_layer_domain_resolves_referenced_geometry_instead_of_first_geometry():
    product = populated_product()
    original = product.geometries[0]
    other = replace(original, geometry_id="geometry:other", domain="domain:other")
    product = replace(product, geometries=(other, original))
    assert matches(product, requirement(geometry_domain_id=original.domain))
    assert not matches(product, requirement(geometry_domain_id=other.domain))


def test_missing_geometry_target_does_not_crash_profile_matching():
    from copy import copy

    product = copy(populated_product())
    # Constructor normally prevents dangling references; simulate external corruption.
    object.__setattr__(product, "geometries", ())
    assert not matches(product, requirement(geometry_domain_id="domain:test"))


def test_profile_public_fields_are_not_renamed():
    assert "domain_id" in {field.name for field in fields(GeometryRequirement)}
    assert "geometry_domain_id" in {field.name for field in fields(LayerRequirement)}
    assert "domain" not in {field.name for field in fields(GeometryRequirement)}


def test_profiles_do_not_inspect_grid_parameters_or_reference_target(monkeypatch):
    from insarforge.contracts.values import ArtifactRef
    from insarforge.products.grid import GridDefinition

    product = populated_product()

    def forbidden(*args):
        raise AssertionError("Unexpected grid/reference interpretation")

    with monkeypatch.context() as patch:
        patch.setattr(GridDefinition, "parameters", property(forbidden), raising=False)
        patch.setattr(ArtifactRef, "locator", property(forbidden), raising=False)
        patch.setattr(
            ArtifactRef, "semantic_digest", property(forbidden), raising=False
        )
        assert geometry_report(product, domain_id=product.geometries[0].domain).is_valid
        assert matches(
            product, requirement(geometry_domain_id=product.geometries[0].domain)
        )


EXTENSION_CONTRACTS = (
    AssetRequirement("requirement:asset", (), 1, None, {}),
    requirement(),
    geometry_requirement(),
    ProductProfile("profile:test", 1, (), (), (), (), {}),
)


@pytest.mark.parametrize(
    "contract", EXTENSION_CONTRACTS, ids=lambda x: type(x).__name__
)
@pytest.mark.parametrize(
    "extensions",
    [
        {},
        {"vendor-x:flag": True},
        {"future-tool:data": {"values": [1, 2]}},
        {"insarforge:test-value": 1},
    ],
)
def test_profile_extension_namespace_acceptance(contract, extensions):
    stored = replace(contract, extensions=extensions).extensions
    assert stored == freeze_json(extensions)
    assert list(stored) == list(extensions)


@pytest.mark.parametrize(
    "contract", EXTENSION_CONTRACTS, ids=lambda x: type(x).__name__
)
@pytest.mark.parametrize("key", ["flag", ":flag", "vendor:", "a:b:c"])
def test_profile_extension_invalid_keys(contract, key):
    with pytest.raises(ValueError):
        replace(contract, extensions={key: 1})


@pytest.mark.parametrize(
    "contract", EXTENSION_CONTRACTS, ids=lambda x: type(x).__name__
)
@pytest.mark.parametrize("extensions", [None, [], (), "text", 1, {1: True}])
def test_profile_extension_invalid_types(contract, extensions):
    with pytest.raises(TypeError):
        replace(contract, extensions=extensions)


@pytest.mark.parametrize(
    "contract", EXTENSION_CONTRACTS, ids=lambda x: type(x).__name__
)
@pytest.mark.parametrize("view", [False, True], ids=["dict", "backing-view"])
def test_profile_extensions_own_nested_snapshot(contract, view):
    values = [3, 1, 2]
    nested = {"values": values}
    source = {"future-tool:data": nested}
    owned = replace(contract, extensions=MappingProxyType(source) if view else source)
    source["vendor:extra"] = True
    nested["extra"] = False
    values.append(4)
    assert owned.extensions == {"future-tool:data": {"values": (3, 1, 2)}}
    with pytest.raises(TypeError):
        owned.extensions["vendor:extra"] = True
    with pytest.raises(TypeError):
        owned.extensions["future-tool:data"]["extra"] = True
    with pytest.raises(TypeError):
        owned.extensions["future-tool:data"]["values"][0] = 0


@pytest.mark.parametrize(
    "contract", EXTENSION_CONTRACTS, ids=lambda x: type(x).__name__
)
def test_profile_extensions_are_semantic_state(contract):
    original = replace(contract, extensions={"Vendor:flag": 1, "vendor:flag": 2})
    assert original.extensions == {"Vendor:flag": 1, "vendor:flag": 2}
    assert original == replace(
        contract, extensions={"vendor:flag": 2, "Vendor:flag": 1}
    )
    assert original != replace(original, extensions={"vendor:flag": 2})
    assert original != replace(
        original, extensions={"Vendor:flag": 2, "vendor:flag": 2}
    )
    ordered = replace(contract, extensions={"vendor:data": [3, 1, 2]})
    assert ordered != replace(ordered, extensions={"vendor:data": [1, 2, 3]})


@pytest.mark.parametrize(
    "slot,requirement,target_collection",
    [
        ("asset_requirements", EXTENSION_CONTRACTS[0], "assets"),
        ("layer_requirements", EXTENSION_CONTRACTS[1], "layers"),
        ("geometry_requirements", EXTENSION_CONTRACTS[2], "geometries"),
    ],
)
def test_requirement_extensions_are_not_hidden_target_predicates(
    slot, requirement, target_collection
):
    product = populated_product()
    assert all(
        not hasattr(target, "extensions")
        for target in getattr(product, target_collection)
    )
    profile = EXTENSION_CONTRACTS[3]
    for extensions in ({}, {"future-tool:data": {"opaque": [1, 2]}}):
        req = replace(requirement, extensions=extensions)
        assert req.extensions == freeze_json(extensions)
        matching = replace(profile, **{slot: (req,)})
        assert validate_product_profile(product, matching).is_valid
        failing = replace(matching, **{slot: (replace(req, min_count=99),)})
        assert not validate_product_profile(product, failing).is_valid


@pytest.mark.parametrize("profile_extensions", [{}, {"vendor:flag": True}])
@pytest.mark.parametrize(
    "product_extensions", [{}, {"vendor:flag": False}, {"other:data": [1, 2]}]
)
def test_profile_extensions_are_not_product_extension_predicates(
    profile_extensions, product_extensions
):
    product = replace(populated_product(), extensions=product_extensions)
    profile = replace(
        EXTENSION_CONTRACTS[3],
        extensions=profile_extensions,
        allowed_product_kinds=(product.product_kind,),
        layer_requirements=(requirement(),),
    )
    assert validate_product_profile(product, profile).is_valid
    assert not validate_product_profile(
        product, replace(profile, allowed_product_kinds=("synthetic:other",))
    ).is_valid
    assert not validate_product_profile(
        product, replace(profile, layer_requirements=(requirement(min_count=99),))
    ).is_valid


@pytest.mark.parametrize(
    "contract,expected",
    [
        (
            AssetRequirement,
            "requirement_id allowed_kinds min_count max_count extensions",
        ),
        (
            LayerRequirement,
            "requirement_id role selector_kind geometry_domain_id quantity_kind unit_id "
            "sign_convention_id require_known_quantity require_known_unit require_known_sign "
            "require_known_geometry min_count max_count extensions",
        ),
        (
            GeometryRequirement,
            "requirement_id domain_id required_axis_roles require_known_registration "
            "require_known_coordinate_reference min_count max_count extensions",
        ),
        (
            ProductProfile,
            "profile_id profile_version allowed_product_kinds asset_requirements "
            "geometry_requirements layer_requirements extensions",
        ),
    ],
)
def test_exact_profile_public_field_shapes(contract, expected):
    assert [field.name for field in fields(contract)] == expected.split()
    assert all(
        field.default is MISSING and field.default_factory is MISSING
        for field in fields(contract)
    )
