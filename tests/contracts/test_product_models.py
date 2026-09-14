from dataclasses import fields, replace
from typing import get_type_hints

import pytest

import insarforge.contracts.plugins as plugins
from insarforge.contracts.identity import PluginKind, PluginRef
from insarforge.contracts.plugins import Analyzer, Correction, Processor, Provider
from insarforge.products.assets import (
    AssetKind,
    AssetLocation,
    AssetLocationKind,
    NativeAsset,
)
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
    g = __import__(
        "insarforge.products.geometry", fromlist=["GeometryDescriptor"]
    ).GeometryDescriptor(
        "geometry:x",
        "domain:test",
        (2,),
        (
            __import__(
                "insarforge.products.geometry", fromlist=["AxisDescriptor"]
            ).AxisDescriptor(
                "axis:x",
                "role:test",
                2,
                sv(UnitSpec("unit:x", "quantity:x", None)),
                sv("direction:x"),
                {},
            ),
        ),
        unknown(),
        unknown(),
        {},
    )
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


def populated_product():
    """Final DataLayer fixture with one native asset and no geometric dependency."""
    source = layer(None)
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
        (),
        (
            source,
            replace(source, layer_id="mask:a"),
            replace(source, layer_id="mask:b"),
        ),
        {},
    )
