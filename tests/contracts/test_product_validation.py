from dataclasses import replace

import pytest
from test_product_models import populated_product, sv

from insarforge.products.models import ProductDraft
from insarforge.products.nodata import NoDataKind, NoDataSpec
from insarforge.products.semantics import SemanticStatus, SemanticValue
from insarforge.products.validation import (
    ProductValidationReport,
    ValidationIssue,
    ValidationIssueKind,
    validate_product_structure,
)


def test_validation_report_semantics():
    issue = ValidationIssue(
        ValidationIssueKind.UNVERIFIED, "validation:test", "x[0]", {"a": []}
    )
    report = ProductValidationReport([issue])
    assert report.is_valid
    assert not report.is_fully_verified
    assert report.unverified == (issue,)
    assert report.errors == ()


def test_wrong_product_type_rejected():
    try:
        validate_product_structure(object())
    except TypeError:
        pass
    else:
        raise AssertionError("expected TypeError")


def with_nodata(nodata):
    product = populated_product()
    return replace(
        product, layers=(replace(product.layers[0], nodata=nodata), *product.layers[1:])
    )


@pytest.mark.parametrize("as_draft", [False, True])
@pytest.mark.parametrize(
    "target,valid", [("mask:a", True), ("synthetic:missing", False)]
)
def test_mask_target_must_exist_in_same_product(target, valid, as_draft):
    product = with_nodata(sv(NoDataSpec(NoDataKind.MASK, None, target)))
    if as_draft:
        product = ProductDraft(
            product.schema_version,
            product.product_kind,
            product.profile_id,
            product.profile_version,
            product.lineage,
            product.assets,
            product.geometries,
            product.layers,
            product.extensions,
        )
    report = validate_product_structure(product)
    assert report.is_valid is valid
    if not valid:
        assert len(report.errors) == 1
        issue = report.errors[0]
        assert issue.kind is ValidationIssueKind.ERROR
        assert issue.code == "validation:missing-mask-layer-reference"
        assert issue.location == "layers[0].nodata.mask_layer_ref"


def test_self_mask_still_rejected_locally():
    with pytest.raises(ValueError, match="owning layer"):
        with_nodata(sv(NoDataSpec(NoDataKind.MASK, None, "layer:x")))


@pytest.mark.parametrize(
    "nodata",
    [
        sv(NoDataSpec(NoDataKind.NONE, None, None)),
        sv(NoDataSpec(NoDataKind.FINITE_VALUE, 7, None)),
        sv(NoDataSpec(NoDataKind.NAN, None, None)),
        SemanticValue(SemanticStatus.UNKNOWN, None, "synthetic:reason", ()),
        SemanticValue(SemanticStatus.NOT_APPLICABLE, None, "synthetic:reason", ()),
    ],
)
def test_other_nodata_states_do_not_request_mask_lookup(nodata):
    product = with_nodata(nodata)
    product = replace(product, layers=product.layers[:1])
    assert validate_product_structure(product).is_fully_verified


def alignment_product():
    product = populated_product()
    original = product.geometries[0]
    axes = (
        replace(original.axes[0], axis_id="axis:test-z", role="role:test-first"),
        replace(original.axes[0], axis_id="axis:test-a", role="role:test-second"),
    )
    geometry = replace(original, axes=axes, shape=(5, 2))
    layer = replace(product.layers[0], dimensions=("axis:test-z", "axis:test-a"))
    return replace(product, geometries=(geometry,), layers=(layer,))


def corrupt(value, **changes):
    """Bypass frozen constructors on a fresh test-only copy."""
    from copy import copy

    value = copy(value)
    for name, replacement in changes.items():
        object.__setattr__(value, name, replacement)
    return value


def codes(report):
    return [issue.code for issue in report.errors]


def test_exact_ordered_alignment_is_valid_and_does_not_mutate():
    product = alignment_product()
    before = (product.geometries, product.layers)
    assert validate_product_structure(product).is_fully_verified
    assert (product.geometries, product.layers) == before


@pytest.mark.parametrize(
    "dimensions",
    [
        ("axis:test-z",),
        ("axis:test-z", "axis:test-a", "axis:test-extra"),
        ("axis:test-a", "axis:test-z"),
        ("axis:test-z", "axis:test-other"),
        ("role:test-first", "role:test-second"),
        (),
    ],
)
def test_dimensions_require_exact_axis_ids_and_order(dimensions):
    product = alignment_product()
    product = replace(
        product, layers=(replace(product.layers[0], dimensions=dimensions),)
    )
    report = validate_product_structure(product)
    assert codes(report) == ["validation:layer-dimensions-geometry-mismatch"]
    issue = report.errors[0]
    assert issue.kind is ValidationIssueKind.ERROR
    assert issue.location == "layers[0].dimensions"
    assert issue.details == {
        "layer_id": product.layers[0].layer_id,
        "geometry_id": product.geometries[0].geometry_id,
        "layer_dimensions": dimensions,
        "geometry_axis_ids": ("axis:test-z", "axis:test-a"),
    }
    with pytest.raises(TypeError):
        issue.details["layer_id"] = "layer:other"
    with pytest.raises(TypeError):
        issue.details["geometry_axis_ids"][0] = "axis:other"


def test_missing_geometry_has_no_alignment_cascade():
    product = alignment_product()
    product = corrupt(
        product, geometries=(), layers=(replace(product.layers[0], dimensions=()),)
    )
    report = validate_product_structure(product)
    assert codes(report) == ["validation:missing-geometry-reference"]
    assert report.errors[0].location == "layers[0].geometry_ref"


@pytest.mark.parametrize(
    "status", [SemanticStatus.UNKNOWN, SemanticStatus.NOT_APPLICABLE]
)
@pytest.mark.parametrize("dimensions", [(), ("dimension:independent",)])
def test_nonknown_geometry_skips_alignment_without_requiring_geometry(
    status, dimensions
):
    product = alignment_product()
    layer = replace(
        product.layers[0],
        geometry_ref=SemanticValue(status, None, "reason:test", ()),
        dimensions=dimensions,
    )
    product = replace(product, layers=(layer,), geometries=())
    assert validate_product_structure(product).is_fully_verified


def test_each_layer_resolves_its_own_geometry():
    product = alignment_product()
    original = product.geometries[0]
    other = replace(
        original, geometry_id="geometry:other", axes=original.axes[::-1], shape=(2, 5)
    )
    layer = replace(
        product.layers[0],
        layer_id="layer:other",
        geometry_ref=sv(other.geometry_id),
        dimensions=("axis:test-a", "axis:test-z"),
    )
    product = replace(
        product, geometries=(other, original), layers=(*product.layers, layer)
    )
    assert validate_product_structure(product).is_fully_verified


def test_corrupt_axis_shape_count_is_detected():
    product = alignment_product()
    geometry = corrupt(product.geometries[0], shape=(5,))
    product = corrupt(product, geometries=(geometry,))
    assert codes(validate_product_structure(product)) == [
        "validation:geometry-axis-count-mismatch"
    ]


def test_corrupt_duplicate_axis_ids_are_detected():
    product = alignment_product()
    geometry = product.geometries[0]
    geometry = corrupt(geometry, axes=(geometry.axes[0], geometry.axes[0]))
    product = corrupt(product, geometries=(geometry,))
    assert codes(validate_product_structure(product)) == [
        "validation:duplicate-axis-id"
    ]


@pytest.mark.parametrize("value", [True, False, 0, -1, 1.0, "5", None, {}])
def test_corrupt_shape_values_are_detected(value):
    product = alignment_product()
    geometry = corrupt(product.geometries[0], shape=(value, 2))
    product = corrupt(product, geometries=(geometry,))
    report = validate_product_structure(product)
    assert codes(report) == ["validation:invalid-geometry-shape"]
    assert report.errors[0].location == "geometries[0].shape[0]"


def test_corrupt_empty_geometry_is_detected():
    product = alignment_product()
    geometry = corrupt(product.geometries[0], axes=(), shape=())
    product = corrupt(product, geometries=(geometry,))
    assert codes(validate_product_structure(product)) == ["validation:empty-geometry"]


@pytest.mark.parametrize("field", ["axes", "shape"])
@pytest.mark.parametrize("value", [None, 5, "invalid", {}])
def test_corrupt_geometry_collections_are_reported(field, value):
    product = alignment_product()
    geometry = corrupt(product.geometries[0], **{field: value})
    product = corrupt(product, geometries=(geometry,))
    report = validate_product_structure(product)
    assert codes(report) == ["validation:wrong-element-type"]
    assert report.errors[0].location == f"geometries[0].{field}"


@pytest.mark.parametrize("field", ["assets", "geometries", "layers", "axes"])
def test_wrong_collection_elements_are_reported_without_crashing(field):
    product = alignment_product()
    if field == "axes":
        geometry = corrupt(
            product.geometries[0], axes=(object(), product.geometries[0].axes[1])
        )
        product = corrupt(product, geometries=(geometry,))
        location = "geometries[0].axes[0]"
    else:
        product = corrupt(product, **{field: (*getattr(product, field), object())})
        location = f"{field}[1]"
    report = validate_product_structure(product)
    assert codes(report) == ["validation:wrong-element-type"]
    assert report.errors[0].location == location


@pytest.mark.parametrize(
    "field,code",
    [
        ("assets", "duplicate-asset-id"),
        ("geometries", "duplicate-geometry-id"),
        ("layers", "duplicate-layer-id"),
    ],
)
def test_duplicate_collection_ids_remain_detected(field, code):
    product = alignment_product()
    product = corrupt(
        product, **{field: (*getattr(product, field), getattr(product, field)[0])}
    )
    assert codes(validate_product_structure(product)) == [f"validation:{code}"]


def test_missing_asset_validation_is_preserved():
    product = corrupt(alignment_product(), assets=())
    assert codes(validate_product_structure(product)) == [
        "validation:missing-asset-reference"
    ]


def test_mask_and_alignment_errors_are_independent():
    product = alignment_product()
    layer = replace(
        product.layers[0],
        dimensions=(),
        nodata=sv(NoDataSpec(NoDataKind.MASK, None, "mask:missing")),
    )
    report = validate_product_structure(replace(product, layers=(layer,)))
    assert codes(report) == [
        "validation:missing-mask-layer-reference",
        "validation:layer-dimensions-geometry-mismatch",
    ]
