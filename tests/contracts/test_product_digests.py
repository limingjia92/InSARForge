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
from insarforge.products.semantics import SemanticStatus, SemanticValue, UnitSpec


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


def with_geometry(product, **changes):
    return replace(product, geometries=(replace(product.geometries[0], **changes),))


def material(product):
    return product_semantic_material(
        product, asset_content_identities={"asset:x": "synthetic:content"}
    )


def test_exact_final_geometry_semantic_projection():
    from dataclasses import fields

    from insarforge.products.digests import PRODUCT_CONTENT_DIGEST_ALGORITHM_REVISION

    product = populated_product()
    geometry = product.geometries[0]
    projected = material(product)["product"]["geometries"][0]
    assert set(projected) == {f.name for f in fields(geometry)}
    assert set(projected["axes"][0]) == {f.name for f in fields(geometry.axes[0])}
    assert projected["grid_definition"]["value"] == {
        "format_id": geometry.grid_definition.value.format_id,
        "parameters": {"nested": {"values": [1, 2], "text": "测试"}},
    }
    assert projected["reference"] == {
        "status": "known",
        "value": geometry.reference.value.semantic_digest,
        "reason_code": None,
        "evidence_semantic_digests": [],
    }
    assert PRODUCT_CONTENT_DIGEST_ALGORITHM_REVISION == 1


@pytest.mark.parametrize(
    "field,value",
    [
        ("axis_id", "axis:other"),
        ("role", "role:other"),
        ("unit", sv(UnitSpec("unit:other", "quantity:test", None))),
        ("direction", sv("direction:other")),
    ],
)
def test_each_axis_field_affects_content_digest(field, value):
    product = populated_product()
    axis = replace(product.geometries[0].axes[0], **{field: value})
    changed = with_geometry(product, axes=(axis,))
    assert content(product) is not None
    assert content(changed) is not None
    assert content(changed) != content(product)


@pytest.mark.parametrize(
    "field,value",
    [
        ("domain", "domain:other"),
        ("coordinate_reference", sv("other synthetic coordinate text")),
        ("shape", (3,)),
        ("registration", sv("registration:other")),
    ],
)
def test_geometry_fields_affect_content_digest(field, value):
    product = populated_product()
    changed = with_geometry(product, **{field: value})
    assert content(product) is not None
    assert content(changed) is not None
    assert content(changed) != content(product)


def test_geometry_id_remains_semantic():
    product = replace(populated_product(), layers=())
    assert content(product) != content(
        with_geometry(product, geometry_id="geometry:other")
    )


def test_axis_and_shape_order_are_semantic():
    product = populated_product()
    first = product.geometries[0].axes[0]
    axes = (replace(first, axis_id="axis:z"), replace(first, axis_id="axis:a"))
    product = with_geometry(product, axes=axes, shape=(5, 2))
    assert content(product) is not None
    assert content(product) != content(with_geometry(product, axes=axes[::-1]))
    assert content(product) != content(with_geometry(product, shape=(2, 5)))
    assert content(product) != content(
        with_geometry(product, axes=axes[::-1], shape=(2, 5))
    )


@pytest.mark.parametrize(
    "field", ["grid_definition", "reference", "coordinate_reference", "registration"]
)
def test_geometry_semantic_states_reasons_and_evidence(field):
    product = populated_product()
    known = getattr(product.geometries[0], field)
    ref = product.geometries[0].reference.value
    values = [
        known,
        replace(known, reason_code="reason:known"),
        SemanticValue(SemanticStatus.UNKNOWN, None, "reason:a", ()),
        SemanticValue(SemanticStatus.NOT_APPLICABLE, None, "reason:a", ()),
        SemanticValue(SemanticStatus.UNKNOWN, None, "reason:b", ()),
        replace(known, evidence_refs=(ref,)),
        replace(known, evidence_refs=(replace(ref, semantic_digest="semantic:other"),)),
    ]
    digests = [content(with_geometry(product, **{field: value})) for value in values]
    assert None not in digests
    assert len(set(digests)) == len(values)


@pytest.mark.parametrize("field", ["grid_definition", "reference"])
@pytest.mark.parametrize("status", list(SemanticStatus))
def test_missing_geometry_evidence_identity_disables_content_identity(field, status):
    product = populated_product()
    geometry = product.geometries[0]
    weak = replace(geometry.reference.value, semantic_digest=None)
    semantic = SemanticValue(
        status,
        getattr(geometry, field).value if status is SemanticStatus.KNOWN else None,
        "reason:test",
        (weak,),
    )
    changed = with_geometry(product, **{field: semantic})
    assert material(changed) is None
    assert content(changed) is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("format_id", "grid:test-v2"),
        ("parameters", {"nested": {"values": [1, 3], "text": "测试"}}),
        ("parameters", {"nested": {"values": [1, 2], "text": "other"}}),
        ("parameters", {"nested": {"values": [1, 2], "text": "测试"}, "extra": True}),
    ],
)
def test_grid_format_and_complete_parameters_are_semantic(field, value):
    product = populated_product()
    grid = replace(product.geometries[0].grid_definition.value, **{field: value})
    changed = with_geometry(product, grid_definition=sv(grid))
    assert content(product) is not None
    assert content(changed) is not None
    assert content(product) != content(changed)


def test_grid_mapping_order_is_not_semantic_but_array_order_is():
    product = populated_product()
    grid = product.geometries[0].grid_definition.value

    def with_parameters(parameters):
        return with_geometry(
            product, grid_definition=sv(replace(grid, parameters=parameters))
        )

    first = with_parameters({"b": 2, "a": {"z": [1, 2], "a": 1}})
    reordered = with_parameters({"a": {"a": 1, "z": [1, 2]}, "b": 2})
    changed = with_parameters({"a": {"a": 1, "z": [2, 1]}, "b": 2})
    assert content(first) is not None
    assert content(first) == content(reordered)
    assert content(first) != content(changed)


def test_missing_known_reference_target_disables_semantic_material_and_digest():
    product = populated_product()
    ref = replace(product.geometries[0].reference.value, semantic_digest=None)
    changed = with_geometry(product, reference=sv(ref))
    assert material(changed) is None
    assert content(changed) is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("record_id", "record:other"),
        ("manifest_digest", "manifest:other"),
        ("locator", "synthetic://other/record"),
        ("schema_id", "schema:other"),
        ("schema_version", 2),
    ],
)
def test_reference_persistence_fields_are_not_content_identity(field, value):
    from insarforge.products.digests import product_manifest_digest

    product = populated_product()
    ref = replace(product.geometries[0].reference.value, **{field: value})
    changed = with_geometry(product, reference=sv(ref))
    assert content(product) is not None
    assert material(changed) == material(product)
    assert content(changed) == content(product)
    assert product_manifest_digest(changed) != product_manifest_digest(product)


def test_reference_target_semantic_digest_changes_content():
    product = populated_product()
    ref = replace(
        product.geometries[0].reference.value, semantic_digest="semantic:other"
    )
    changed = with_geometry(product, reference=sv(ref))
    assert content(product) is not None
    assert content(changed) is not None
    assert content(changed) != content(product)


@pytest.mark.parametrize("field", ["grid_definition", "reference"])
def test_geometry_evidence_ignores_persistence_identity(field):
    product = populated_product()
    geometry = product.geometries[0]
    ref = geometry.reference.value
    first = replace(getattr(geometry, field), evidence_refs=(ref,))
    second = replace(
        first,
        evidence_refs=(
            replace(
                ref,
                record_id="record:other",
                manifest_digest="manifest:other",
                locator="synthetic://other",
            ),
        ),
    )
    assert content(with_geometry(product, **{field: first})) is not None
    assert content(with_geometry(product, **{field: first})) == content(
        with_geometry(product, **{field: second})
    )


@pytest.mark.parametrize(
    "changed",
    [
        {"vendor-x:other": {"values": [1, 2]}},
        {"vendor-x:data": {"values": [1, 3]}},
        {"Vendor-x:data": {"values": [1, 2]}},
        {"vendor-x:data": {"values": [2, 1]}},
    ],
)
def test_complete_extensions_are_semantic(changed):
    product = replace(
        populated_product(), extensions={"vendor-x:data": {"values": [1, 2]}}
    )
    assert content(product) is not None
    assert content(product) != content(replace(product, extensions=changed))


def test_extension_mapping_order_and_empty_determinism():
    product = populated_product()
    first = replace(
        product,
        extensions={"future-tool:data": {"z": [1, 2], "a": 1}, "vendor:flag": True},
    )
    second = replace(
        product,
        extensions={"vendor:flag": True, "future-tool:data": {"a": 1, "z": [1, 2]}},
    )
    assert content(first) is not None
    assert content(first) == content(second)
    assert material(first)["extensions"] == {
        "future-tool:data": {"z": [1, 2], "a": 1},
        "vendor:flag": True,
    }
    assert content(product) is not None
    assert content(product) == content(replace(product, extensions={}))
