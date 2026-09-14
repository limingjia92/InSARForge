import hashlib
from dataclasses import replace

import pytest
from test_product_models import populated_product, sv

from insarforge.contracts.values import ArtifactRef
from insarforge.products.digests import (
    PRODUCT_CONTENT_DIGEST_DOMAIN_TAG,
    product_content_digest,
    product_semantic_material,
    sha256_hex,
)
from insarforge.products.layers import LayerSelector
from insarforge.products.nodata import NoDataKind, NoDataSpec
from insarforge.products.semantics import SemanticStatus, SemanticValue


def test_sha256():
    assert sha256_hex(b"abc") == hashlib.sha256(b"abc").hexdigest()


def test_domain_constant():
    assert (
        PRODUCT_CONTENT_DIGEST_DOMAIN_TAG == b"insarforge:product-content-digest:v1\x00"
    )


def content(product):
    return product_content_digest(
        product, asset_content_identities={"asset:x": "synthetic:content"}
    )


def digest_product():
    product = populated_product()
    source = replace(
        product.layers[0],
        selector=LayerSelector("synthetic:format", "opaque"),
        dimensions=("synthetic:z", "synthetic:a"),
    )
    return replace(product, layers=(source, *product.layers[1:]))


@pytest.mark.parametrize(
    "changes",
    [
        dict(selector=None),
        dict(selector=LayerSelector("synthetic:other", "opaque")),
        dict(selector=LayerSelector("synthetic:format", "other")),
        dict(quantity=sv("synthetic:other")),
        dict(nodata=sv(NoDataSpec(NoDataKind.NAN, None, None))),
        dict(nodata=sv(NoDataSpec(NoDataKind.FINITE_VALUE, 7, None))),
        dict(nodata=sv(NoDataSpec(NoDataKind.MASK, None, "mask:a"))),
        dict(dimensions=("synthetic:z", "synthetic:b")),
        dict(dimensions=("synthetic:a", "synthetic:z")),
    ],
)
def test_final_layer_fields_affect_content_digest(changes):
    product = digest_product()
    changed = replace(
        product, layers=(replace(product.layers[0], **changes), *product.layers[1:])
    )
    assert content(product) is not None
    assert content(product) != content(changed)


@pytest.mark.parametrize(
    "first,second",
    [
        (
            NoDataSpec(NoDataKind.FINITE_VALUE, 7, None),
            NoDataSpec(NoDataKind.FINITE_VALUE, 8, None),
        ),
        (
            NoDataSpec(NoDataKind.FINITE_VALUE, 7, None),
            NoDataSpec(NoDataKind.FINITE_VALUE, 7.0, None),
        ),
        (
            NoDataSpec(NoDataKind.MASK, None, "mask:a"),
            NoDataSpec(NoDataKind.MASK, None, "mask:b"),
        ),
    ],
)
def test_nodata_values_and_mask_identity_affect_digest(first, second):
    product = digest_product()

    def with_spec(spec):
        return replace(
            product,
            layers=(replace(product.layers[0], nodata=sv(spec)), *product.layers[1:]),
        )

    assert content(with_spec(first)) != content(with_spec(second))


def test_nodata_states_reasons_and_evidence_are_semantic():
    product = digest_product()
    ref = ArtifactRef(
        "synthetic:record",
        "synthetic:schema",
        1,
        "semantic:a",
        "manifest:a",
        "locator:a",
    )
    values = [
        sv(NoDataSpec(NoDataKind.NONE, None, None)),
        SemanticValue(SemanticStatus.UNKNOWN, None, "reason:a", ()),
        SemanticValue(SemanticStatus.NOT_APPLICABLE, None, "reason:a", ()),
        SemanticValue(SemanticStatus.UNKNOWN, None, "reason:b", ()),
        SemanticValue(SemanticStatus.UNKNOWN, None, "reason:a", (ref,)),
        SemanticValue(
            SemanticStatus.UNKNOWN,
            None,
            "reason:a",
            (replace(ref, semantic_digest="semantic:b"),),
        ),
    ]
    digests = [
        content(
            replace(
                product,
                layers=(replace(product.layers[0], nodata=v), *product.layers[1:]),
            )
        )
        for v in values
    ]
    assert None not in digests and len(set(digests)) == len(values)
    weak = SemanticValue(
        SemanticStatus.UNKNOWN, None, "reason:a", (replace(ref, semantic_digest=None),)
    )
    assert (
        content(
            replace(
                product,
                layers=(replace(product.layers[0], nodata=weak), *product.layers[1:]),
            )
        )
        is None
    )


def test_final_layer_projection_and_persistence_noise():
    product = digest_product()
    material = product_semantic_material(
        product, asset_content_identities={"asset:x": "synthetic:content"}
    )
    assert set(material["product"]["layers"][0]) == {
        "layer_id",
        "role",
        "asset_id",
        "selector",
        "quantity",
        "unit",
        "sign",
        "geometry_ref",
        "nodata",
        "dimensions",
    }
    assert content(replace(product, product_id="product:other")) == content(product)
    assert content(
        replace(product, extensions={"synthetic:b": 2, "synthetic:a": 1})
    ) == content(replace(product, extensions={"synthetic:a": 1, "synthetic:b": 2}))


def test_final_native_asset_explicit_identity_projection():
    from insarforge.products.assets import (
        AssetIntegrity,
        AssetKind,
        AssetLocation,
        AssetLocationKind,
    )
    from insarforge.products.serialization import canonical_json_bytes

    product = populated_product()
    asset = product.assets[0]
    assert not hasattr(asset, "role")
    identities = {asset.asset_id: "synthetic:content"}
    material = product_semantic_material(product, asset_content_identities=identities)
    assert material["product"]["assets"] == [
        {
            "asset_id": asset.asset_id,
            "asset_kind": asset.asset_kind.value,
            "content_identity": "synthetic:content",
        }
    ]
    original = content(product)
    assert original is not None
    assert (
        original
        == hashlib.sha256(
            PRODUCT_CONTENT_DIGEST_DOMAIN_TAG + canonical_json_bytes(material)
        ).hexdigest()
    )
    assert original != product_content_digest(
        product, asset_content_identities={asset.asset_id: "synthetic:other"}
    )
    directory = replace(asset, asset_kind=AssetKind.DIRECTORY)
    assert original != content(replace(product, assets=(directory,)))
    changed = replace(
        asset,
        location=AssetLocation(
            AssetLocationKind.ABSOLUTE_LOCAL, "/tmp/synthetic-other", None
        ),
        media_type="synthetic/type",
        size_bytes=7,
        integrity=AssetIntegrity("synthetic:algorithm", "synthetic:digest"),
    )
    changed_product = replace(product, assets=(changed,))
    assert content(changed_product) == original
    assert (
        product_content_digest(
            changed_product, asset_content_identities={asset.asset_id: None}
        )
        is None
    )
    assert (
        product_semantic_material(
            changed_product, asset_content_identities={asset.asset_id: None}
        )
        is None
    )
    with pytest.raises(ValueError, match="identities"):
        product_content_digest(changed_product, asset_content_identities={})
    ref = ArtifactRef(
        "synthetic:record",
        "synthetic:schema",
        1,
        "synthetic:semantic",
        "synthetic:manifest",
        "synthetic:locator",
    )
    assert content(replace(product, assets=(directory,))) == content(
        replace(product, assets=(replace(directory, member_manifest_ref=ref),))
    )
