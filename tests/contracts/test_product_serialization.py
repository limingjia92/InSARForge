import json
import math
from dataclasses import replace

import pytest
from test_product_models import populated_product, sv, unknown

from insarforge.products.layers import LayerSelector
from insarforge.products.nodata import NoDataKind, NoDataSpec
from insarforge.products.semantics import SemanticStatus, SemanticValue
from insarforge.products.serialization import (
    canonical_json_bytes,
    product_from_manifest_bytes,
    product_from_manifest_value,
    product_to_manifest_bytes,
    product_to_manifest_value,
    strict_json_loads,
)


def test_canonical_order_unicode():
    assert canonical_json_bytes({"b": 1, "a": "é"}) == '{"a":"é","b":1}'.encode()


def test_strict_json():
    assert strict_json_loads(b'{"a":[1]}')["a"] == (1,)
    with pytest.raises(ValueError):
        strict_json_loads('{"a":1,"a":2}')
    with pytest.raises(ValueError):
        strict_json_loads('{"a":NaN}')


def test_unsupported():
    with pytest.raises(TypeError):
        canonical_json_bytes({1: "x"})
    with pytest.raises(TypeError):
        canonical_json_bytes({"x": object()})
    with pytest.raises(TypeError):
        canonical_json_bytes({"x": math.nan})


# Populated coverage migrates the shared downstream DataLayer fixture.


def layer_product(**changes):
    product = populated_product()
    return replace(
        product, layers=(replace(product.layers[0], **changes), *product.layers[1:])
    )


@pytest.mark.parametrize(
    "selector", [None, LayerSelector("synthetic:format", "opaque [a, b]")]
)
@pytest.mark.parametrize(
    "quantity",
    [
        sv("synthetic:quantity"),
        unknown(),
        SemanticValue(SemanticStatus.NOT_APPLICABLE, None, "synthetic:reason", ()),
    ],
)
@pytest.mark.parametrize(
    "nodata",
    [
        sv(NoDataSpec(NoDataKind.NONE, None, None)),
        sv(NoDataSpec(NoDataKind.FINITE_VALUE, 7, None)),
        sv(NoDataSpec(NoDataKind.FINITE_VALUE, 7.0, None)),
        sv(NoDataSpec(NoDataKind.NAN, None, None)),
        sv(NoDataSpec(NoDataKind.MASK, None, "mask:a")),
        unknown(),
        SemanticValue(SemanticStatus.NOT_APPLICABLE, None, "synthetic:reason", ()),
    ],
)
def test_populated_final_layer_roundtrip(selector, quantity, nodata):
    product = layer_product(
        selector=selector,
        quantity=quantity,
        nodata=nodata,
        dimensions=("synthetic:z", "synthetic:a"),
    )
    value = product_to_manifest_value(product)
    data = product_to_manifest_bytes(product)
    assert product_from_manifest_value(value) == product
    decoded = product_from_manifest_bytes(data)
    assert decoded == product
    assert product_to_manifest_bytes(decoded) == data
    assert decoded.layers[0].dimensions == ("synthetic:z", "synthetic:a")
    if nodata.status is SemanticStatus.KNOWN:
        assert type(decoded.layers[0].nodata.value.value) is type(nodata.value.value)
    assert set(value["product"]["layers"][0]) == {
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
    if selector is not None:
        assert set(value["product"]["layers"][0]["selector"]) == {
            "format_id",
            "selector_string",
        }


@pytest.mark.parametrize(
    "target,key",
    [
        ("layer", "quantity_kind"),
        ("layer", "extensions"),
        ("selector", "selector_kind"),
        ("selector", "parameters"),
    ],
)
def test_legacy_layer_and_selector_fields_rejected(target, key):
    value = json.loads(
        product_to_manifest_bytes(
            layer_product(selector=LayerSelector("synthetic:format", "opaque"))
        )
    )
    obj = value["product"]["layers"][0]
    if target == "selector":
        obj = obj["selector"]
    obj[key] = "synthetic:legacy"
    with pytest.raises(ValueError, match="fields"):
        product_from_manifest_value(value)


@pytest.mark.parametrize("target", ["layer", "selector", "nodata"])
def test_final_nested_fields_are_strict(target):
    original = json.loads(
        product_to_manifest_bytes(
            layer_product(selector=LayerSelector("synthetic:format", "opaque"))
        )
    )
    obj = original["product"]["layers"][0]
    if target == "selector":
        obj = obj["selector"]
    if target == "nodata":
        obj = obj["nodata"]["value"]
    keys = list(obj)
    for key in keys:
        saved = obj.pop(key)
        with pytest.raises(ValueError, match="fields"):
            product_from_manifest_value(original)
        obj[key] = saved
    obj["extra"] = None
    with pytest.raises(ValueError, match="fields"):
        product_from_manifest_value(original)


@pytest.mark.parametrize(
    "kind,value,mask",
    [
        ("unknown", None, None),
        ("finite_value", True, None),
        ("finite_value", None, None),
        ("nan", 7, None),
        ("none", None, "mask:a"),
        ("mask", None, "bad id"),
    ],
)
def test_nodata_decoder_enforces_spec(kind, value, mask):
    manifest = json.loads(product_to_manifest_bytes(populated_product()))
    manifest["product"]["layers"][0]["nodata"]["value"] = dict(
        kind=kind, value=value, mask_layer_ref=mask
    )
    with pytest.raises((ValueError, TypeError)):
        product_from_manifest_value(manifest)


def test_pluginref_direct_producer_roundtrip():
    product = replace(populated_product(), assets=(), geometries=(), layers=())
    value = product_to_manifest_value(product)
    producer = value["product"]["producer"]
    assert set(producer) == {"kind", "plugin_id", "api_version"}
    assert "asset_kind" not in producer
    assert producer["kind"] == product.producer.kind.value
    assert product_from_manifest_value(value) == product
    data = product_to_manifest_bytes(product)
    assert product_from_manifest_bytes(data) == product
    assert product_to_manifest_bytes(product_from_manifest_bytes(data)) == data


def test_current_geometry_final_asset_and_layer_roundtrip():
    from insarforge.products.assets import AssetIntegrity
    from insarforge.products.geometry import AxisDescriptor, GeometryDescriptor

    product = populated_product()
    axis = AxisDescriptor(
        "axis:x", "synthetic:role", 2, unknown(), unknown(), {"synthetic:axis": [1]}
    )
    geometry = GeometryDescriptor(
        "geometry:x",
        "synthetic:domain",
        (2,),
        (axis,),
        unknown(),
        unknown(),
        {"synthetic:geometry": [2]},
    )
    product = replace(
        product,
        assets=(
            replace(
                product.assets[0],
                integrity=AssetIntegrity("synthetic:algorithm", "synthetic:digest"),
            ),
        ),
        geometries=(geometry,),
        layers=(replace(product.layers[0], geometry_ref=sv(geometry.geometry_id)),),
    )
    value = product_to_manifest_value(product)
    assert product_from_manifest_value(value) == product
    data = product_to_manifest_bytes(product)
    decoded = product_from_manifest_bytes(data)
    assert decoded == product
    assert product_to_manifest_bytes(decoded) == data


@pytest.mark.parametrize(
    "target", ["producer", "asset", "integrity", "geometry", "axis"]
)
def test_current_model_nested_fields_remain_strict(target):
    from insarforge.products.assets import AssetIntegrity
    from insarforge.products.geometry import AxisDescriptor, GeometryDescriptor

    product = populated_product()
    geometry = GeometryDescriptor(
        "geometry:x",
        "synthetic:domain",
        (2,),
        (AxisDescriptor("axis:x", "synthetic:role", 2, unknown(), unknown(), {}),),
        unknown(),
        unknown(),
        {},
    )
    product = replace(
        product,
        geometries=(geometry,),
        assets=(
            replace(
                product.assets[0],
                integrity=AssetIntegrity("synthetic:algorithm", "synthetic:digest"),
            ),
        ),
    )
    value = json.loads(product_to_manifest_bytes(product))
    objects = {
        "producer": value["product"]["producer"],
        "asset": value["product"]["assets"][0],
        "integrity": value["product"]["assets"][0]["integrity"],
        "geometry": value["product"]["geometries"][0],
        "axis": value["product"]["geometries"][0]["axes"][0],
    }
    obj = objects[target]
    for key in list(obj):
        saved = obj.pop(key)
        with pytest.raises(ValueError, match="fields"):
            product_from_manifest_value(value)
        obj[key] = saved
    obj["asset_kind" if target == "producer" else "extra"] = None
    with pytest.raises(ValueError, match="fields"):
        product_from_manifest_value(value)
