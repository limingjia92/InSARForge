from dataclasses import fields, replace
from typing import get_type_hints

import pytest

import insarforge.contracts.plugins as plugins
from insarforge.contracts.identity import PluginKind, PluginRef
from insarforge.contracts.plugins import Analyzer, Correction, Processor, Provider
from insarforge.contracts.values import ArtifactRef
from insarforge.products.assets import (
    AssetKind,
    AssetLocation,
    AssetLocationKind,
    NativeAsset,
)
from insarforge.products.geometry import AxisDescriptor, GeometryDescriptor
from insarforge.products.grid import GridDefinition
from insarforge.products.layers import DataLayer, LayerSelector
from insarforge.products.models import Product, ProductDraft
from insarforge.products.nodata import NoDataKind, NoDataSpec
from insarforge.products.semantics import (
    SemanticStatus,
    SemanticValue,
    SignSpec,
    UnitSpec,
)


def sv(value):
    return SemanticValue(SemanticStatus.KNOWN, value, None, ())


def unknown():
    return SemanticValue(SemanticStatus.UNKNOWN, None, "unknown", ())


def asset():
    return NativeAsset(
        "asset:x",
        AssetKind.FILE,
        AssetLocation(AssetLocationKind.ABSOLUTE_LOCAL, "/tmp/x", None),
        None,
        None,
        None,
        None,
    )


def layer(geometry="geometry:x"):
    return DataLayer(
        "layer:x",
        "role:test",
        "asset:x",
        LayerSelector("selector:test", "synthetic:subobject"),
        sv("quantity:x"),
        sv(UnitSpec("unit:x", "quantity:x", None)),
        sv(SignSpec("sign:x", "observable:x", "direction:x", None, None, ())),
        sv(geometry) if geometry else unknown(),
        sv(NoDataSpec(NoDataKind.NONE, None, None)),
        ("axis:x",),
    )


def draft(**kw):
    base = dict(
        schema_version=1,
        product_kind="product:test",
        profile_id="profile:test",
        profile_version=1,
        lineage=(),
        assets=(asset(),),
        geometries=(),
        layers=(),
        extensions={},
    )
    base.update(kw)
    return ProductDraft(**base)


def test_draft_and_cross_references():
    assert draft(layers=()).assets[0].asset_id == "asset:x"
    with pytest.raises(ValueError):
        draft(layers=(layer("geometry:x"),))
    g = final_geometry()
    assert draft(geometries=(g,), layers=(layer(),))
    with pytest.raises(ValueError):
        draft(assets=(asset(), asset()))


def test_immutability_and_product():
    src = []
    d = draft(lineage=tuple(src), extensions={"test-owner:x": [1]})
    assert isinstance(d.lineage, tuple)
    p = Product(
        "product:x",
        1,
        "product:test",
        "profile:test",
        1,
        PluginRef(PluginKind.PROCESSOR, "plugin:x", 1),
        "1.0",
        None,
        (),
        (asset(),),
        (),
        (),
        {},
    )
    assert p.provenance_ref is None
    with pytest.raises(Exception):
        p.product_id = "x"
    names = {f.name for f in fields(Product)}
    assert not names & {
        "unit",
        "sign",
        "geometry",
        "semantic_digest",
        "manifest_digest",
        "cache_key",
        "task_id",
        "run_id",
        "attempt_id",
    }
    with pytest.raises(ValueError):
        Product(
            "bad id",
            1,
            "product:test",
            "profile:test",
            1,
            PluginRef(PluginKind.PROCESSOR, "plugin:x", 1),
            "1.0",
            None,
            (),
            (),
            (),
            (),
            (),
        )


def test_forward_references_resolve():
    for proto, method in (
        (Provider, "acquire"),
        (Processor, "process"),
        (Correction, "correct"),
        (Analyzer, "analyze"),
    ):
        namespace = vars(plugins) | {"ProductDraft": ProductDraft}
        hints = get_type_hints(getattr(proto, method), namespace)
        assert "ProductDraft" in str(hints.get("return"))


def final_geometry():
    return GeometryDescriptor(
        geometry_id="geometry:x",
        domain="domain:test",
        coordinate_reference=sv("synthetic coordinate text"),
        axes=(
            AxisDescriptor(
                "axis:x",
                "role:test",
                sv(UnitSpec("unit:x", "quantity:x", None)),
                sv("direction:test"),
            ),
        ),
        shape=(2,),
        grid_definition=sv(
            GridDefinition(
                "grid:test-v1", {"nested": {"values": [1, 2], "text": "测试"}}
            )
        ),
        registration=sv("registration:test"),
        reference=sv(
            ArtifactRef(
                "record:test",
                "schema:test",
                1,
                "semantic:test",
                "manifest:test",
                "synthetic://unresolved/record",
            )
        ),
    )


def populated_product():
    """Final geometry and layers with matching synthetic dimension identifiers."""
    geometry = final_geometry()
    source = layer(geometry.geometry_id)
    return Product(
        "product:synthetic",
        1,
        "product:test",
        "profile:test",
        1,
        PluginRef(PluginKind.PROCESSOR, "plugin:synthetic", 1),
        "synthetic-v1",
        None,
        (),
        (asset(),),
        (geometry,),
        (
            source,
            replace(source, layer_id="mask:a"),
            replace(source, layer_id="mask:b"),
        ),
        {},
    )


@pytest.mark.parametrize("builder", [draft, populated_product])
@pytest.mark.parametrize(
    "extensions",
    [
        {},
        {"vendor-x:flag": True},
        {"future-tool:data": {"values": [1, 2]}},
        {"insarforge:test-value": 1},
        {"Vendor:flag": 1, "vendor:flag": 2},
    ],
)
def test_extension_namespace_acceptance(builder, extensions):
    from insarforge.contracts.values import freeze_json

    stored = replace(builder(), extensions=extensions).extensions
    assert stored == freeze_json(extensions)
    assert list(stored) == list(extensions)


@pytest.mark.parametrize("builder", [draft, populated_product])
@pytest.mark.parametrize("key", ["flag", "metadata", ":flag", "vendor:", "a:b:c"])
def test_extension_namespace_rejection(builder, key):
    with pytest.raises(ValueError):
        replace(builder(), extensions={key: 1})


@pytest.mark.parametrize("builder", [draft, populated_product])
@pytest.mark.parametrize("extensions", [None, [], (), "text", 1])
def test_extensions_require_mapping(builder, extensions):
    with pytest.raises(TypeError):
        replace(builder(), extensions=extensions)


@pytest.mark.parametrize("builder", [draft, populated_product])
@pytest.mark.parametrize("readonly", [False, True])
def test_extension_snapshot_owns_all_layers(builder, readonly):
    from types import MappingProxyType

    source = {"vendor-x:data": {"values": [1, 2]}}
    supplied = MappingProxyType(source) if readonly else source
    stored = replace(builder(), extensions=supplied).extensions
    source["vendor-x:extra"] = True
    source["vendor-x:data"]["extra"] = 3
    source["vendor-x:data"]["values"].append(3)
    assert stored == {"vendor-x:data": {"values": (1, 2)}}
    with pytest.raises(TypeError):
        stored["vendor-x:extra"] = True
    with pytest.raises(TypeError):
        stored["vendor-x:data"]["extra"] = 3
    with pytest.raises(TypeError):
        stored["vendor-x:data"]["values"][0] = 3


def test_product_and_draft_field_lists_preserve_current_envelope():
    common = (
        "schema_version",
        "product_kind",
        "profile_id",
        "profile_version",
    )
    tail = ("lineage", "assets", "geometries", "layers", "extensions")
    assert tuple(f.name for f in fields(ProductDraft)) == common + tail
    assert tuple(f.name for f in fields(Product)) == (
        "product_id",
        *common,
        "producer",
        "producer_implementation_version",
        "provenance_ref",
        *tail,
    )
