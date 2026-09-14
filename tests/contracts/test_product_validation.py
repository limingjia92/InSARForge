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
