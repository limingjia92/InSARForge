from insarforge.products.models import ProductDraft
from insarforge.products.profiles import ProductProfile, validate_product_profile


def test_empty_profile_matches_draft():
    product = ProductDraft(1, "kind:test", "profile:test", 1, (), (), (), (), {})
    profile = ProductProfile("profile:test", 1, (), (), (), (), {})
    report = validate_product_profile(product, profile)
    assert report.is_valid and report.is_fully_verified
