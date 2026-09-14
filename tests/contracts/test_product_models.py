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
    d = draft(lineage=tuple(src), extensions={"x": [1]})
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
