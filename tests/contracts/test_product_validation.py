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
