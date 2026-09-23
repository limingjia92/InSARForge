from insarforge.products.asset_validation import validate_product_assets
from insarforge.products.models import ProductDraft


def test_zero_asset_draft_is_fully_verified():
    draft = ProductDraft(
        product_kind="generic",
        profile_id="profile",
        profile_version=1,
        assets=(),
        layers=(),
        geometries=(),
        acquisition_refs=(),
        semantic_metadata={},
        extensions={},
    )
    report = validate_product_assets(draft)
    assert report.is_valid and report.is_fully_verified
