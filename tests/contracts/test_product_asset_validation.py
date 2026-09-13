from insarforge.products.asset_validation import validate_product_assets
from insarforge.products.models import ProductDraft


def test_zero_asset_draft_is_fully_verified():
    draft = ProductDraft(1, "generic", "profile", 1, (), (), (), (), {})
    report = validate_product_assets(draft)
    assert report.is_valid and report.is_fully_verified
