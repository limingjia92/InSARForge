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

    product = populated_product()
    product = replace(
        product,
        assets=(
            replace(
                product.assets[0],
                integrity=AssetIntegrity("synthetic:algorithm", "synthetic:digest"),
            ),
        ),
    )
    value = product_to_manifest_value(product)
    assert product_from_manifest_value(value) == product
    data = product_to_manifest_bytes(product)
    decoded = product_from_manifest_bytes(data)
    assert decoded == product
    assert product_to_manifest_bytes(decoded) == data


@pytest.mark.parametrize(
    "target",
    ["producer", "asset", "integrity", "geometry", "axis", "grid", "reference"],
)
def test_current_model_nested_fields_remain_strict(target):
    from insarforge.products.assets import AssetIntegrity

    product = populated_product()
    product = replace(
        product,
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
        "grid": value["product"]["geometries"][0]["grid_definition"]["value"],
        "reference": value["product"]["geometries"][0]["reference"]["value"],
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


def geometry_manifest():
    return json.loads(product_to_manifest_bytes(populated_product()))


def test_final_geometry_codec_field_symmetry_and_alignment():
    from dataclasses import fields

    product = populated_product()
    geometry = product.geometries[0]
    encoded = product_to_manifest_value(product)["product"]["geometries"][0]
    for model, obj in (
        (geometry, encoded),
        (geometry.axes[0], encoded["axes"][0]),
        (geometry.grid_definition.value, encoded["grid_definition"]["value"]),
        (geometry.reference.value, encoded["reference"]["value"]),
    ):
        assert set(obj) == {field.name for field in fields(model)}
    assert all(
        layer.dimensions == tuple(axis.axis_id for axis in geometry.axes)
        for layer in product.layers
    )


@pytest.mark.parametrize(
    "target,key",
    [
        ("axis", "size"),
        ("axis", "extensions"),
        ("geometry", "domain_id"),
        ("geometry", "extensions"),
    ],
)
def test_legacy_geometry_fields_are_rejected(target, key):
    value = geometry_manifest()
    obj = value["product"]["geometries"][0]
    if target == "axis":
        obj = obj["axes"][0]
    obj[key] = 2 if key == "size" else "synthetic:legacy"
    with pytest.raises(ValueError, match="fields"):
        product_from_manifest_value(value)
    if key == "domain_id":
        obj.pop("domain")
        with pytest.raises(ValueError, match="fields"):
            product_from_manifest_value(value)


@pytest.mark.parametrize(
    "field", ["grid_definition", "reference", "coordinate_reference", "registration"]
)
@pytest.mark.parametrize("status", list(SemanticStatus))
def test_geometry_semantic_envelopes_roundtrip(field, status):
    product = populated_product()
    geometry = product.geometries[0]
    evidence = (replace(geometry.reference.value, record_id="record:evidence"),)
    semantic = SemanticValue(
        status,
        getattr(geometry, field).value if status is SemanticStatus.KNOWN else None,
        "synthetic:reason",
        evidence,
    )
    product = replace(product, geometries=(replace(geometry, **{field: semantic}),))
    value = product_to_manifest_value(product)
    assert product_from_manifest_value(value) == product
    data = product_to_manifest_bytes(product)
    decoded = product_from_manifest_bytes(data)
    assert getattr(decoded.geometries[0], field) == semantic
    assert product_to_manifest_bytes(decoded) == data


@pytest.mark.parametrize("field", ["grid_definition", "reference"])
@pytest.mark.parametrize("status", ["unknown", "not_applicable"])
def test_nonknown_geometry_payload_must_be_null(field, status):
    value = geometry_manifest()
    obj = value["product"]["geometries"][0][field]
    obj.update(status=status, reason_code="synthetic:reason")
    with pytest.raises(ValueError, match="non-null"):
        product_from_manifest_value(value)


@pytest.mark.parametrize("field", ["grid_definition", "reference"])
@pytest.mark.parametrize("payload", [None, 1, "synthetic:wrong", [], {}])
def test_known_geometry_payload_is_strictly_typed(field, payload):
    value = geometry_manifest()
    value["product"]["geometries"][0][field]["value"] = payload
    with pytest.raises((ValueError, TypeError)):
        product_from_manifest_value(value)


@pytest.mark.parametrize("field", ["grid_definition", "reference"])
def test_geometry_semantic_envelope_fields_are_strict(field):
    value = geometry_manifest()
    obj = value["product"]["geometries"][0][field]
    for key in list(obj):
        saved = obj.pop(key)
        with pytest.raises(ValueError, match="fields"):
            product_from_manifest_value(value)
        obj[key] = saved
    obj["extra"] = None
    with pytest.raises(ValueError, match="fields"):
        product_from_manifest_value(value)


@pytest.mark.parametrize("field", ["grid_definition", "reference"])
def test_geometry_evidence_is_strict_artifact_array(field):
    value = geometry_manifest()
    obj = value["product"]["geometries"][0][field]
    obj["evidence_refs"] = {}
    with pytest.raises(TypeError, match="evidence_refs"):
        product_from_manifest_value(value)
    obj["evidence_refs"] = [{"record_id": "record:incomplete"}]
    with pytest.raises(ValueError, match="ArtifactRef fields"):
        product_from_manifest_value(value)


@pytest.mark.parametrize(
    "payload",
    [
        None,
        True,
        1,
        1.0,
        "text",
        [1, 2],
        (1, 2),
        {1: "bad"},
        {"nested": {1: "bad"}},
        {"value": object()},
        {"value": float("inf")},
    ],
)
def test_grid_parameters_decoder_enforces_frozen_json_mapping(payload):
    value = geometry_manifest()
    value["product"]["geometries"][0]["grid_definition"]["value"]["parameters"] = (
        payload
    )
    with pytest.raises((TypeError, ValueError)):
        product_from_manifest_value(value)


def test_grid_decoder_preserves_types_and_deep_immutability():
    value = geometry_manifest()
    parameters = {" nested ": {"values": [None, True, 7, 7.0, "测试"]}}
    value["product"]["geometries"][0]["grid_definition"]["value"]["parameters"] = (
        parameters
    )
    decoded = product_from_manifest_value(value)
    stored = decoded.geometries[0].grid_definition.value.parameters
    parameters[" nested "]["values"].append(9)
    assert stored == {" nested ": {"values": (None, True, 7, 7.0, "测试")}}
    assert tuple(type(v) for v in stored[" nested "]["values"]) == (
        type(None),
        bool,
        int,
        float,
        str,
    )
    with pytest.raises(TypeError):
        stored["new"] = 1
    with pytest.raises(TypeError):
        stored[" nested "]["new"] = 1
    with pytest.raises(TypeError):
        stored[" nested "]["values"][0] = 1


@pytest.mark.parametrize(
    "field,payload",
    [("shape", []), ("shape", [True]), ("shape", [0]), ("shape", [2, 3]), ("axes", [])],
)
def test_geometry_decoder_uses_final_constructor_invariants(field, payload):
    value = geometry_manifest()
    value["product"]["geometries"][0][field] = payload
    with pytest.raises((TypeError, ValueError)):
        product_from_manifest_value(value)


def test_axis_shape_order_survives_roundtrip():
    product = populated_product()
    original = product.geometries[0]
    axes = (
        replace(original.axes[0], axis_id="axis:z"),
        replace(original.axes[0], axis_id="axis:a"),
    )
    geometry = replace(original, axes=axes, shape=(5, 2))
    product = replace(
        product,
        geometries=(geometry,),
        layers=tuple(
            replace(layer, dimensions=("axis:z", "axis:a")) for layer in product.layers
        ),
    )
    decoded = product_from_manifest_bytes(product_to_manifest_bytes(product))
    assert decoded == product
    assert decoded.geometries[0].axes == axes
    assert decoded.geometries[0].shape == (5, 2)


def test_reference_decoder_does_not_dereference_and_allows_missing_identity(
    monkeypatch,
):
    import builtins
    import io
    import socket

    value = geometry_manifest()
    target = value["product"]["geometries"][0]["reference"]["value"]
    target.update(semantic_digest=None, locator="synthetic://never-fetch/record")

    def forbidden(*args, **kwargs):
        raise AssertionError("Unexpected dereference")

    with monkeypatch.context() as patch:
        patch.setattr(builtins, "open", forbidden)
        patch.setattr(io, "open", forbidden)
        patch.setattr(socket, "socket", forbidden)
        patch.setattr(socket, "create_connection", forbidden)
        decoded = product_from_manifest_value(value)
    assert decoded.geometries[0].reference.value.semantic_digest is None
    assert decoded.geometries[0].reference.value.locator == target["locator"]
    assert product_from_manifest_bytes(product_to_manifest_bytes(decoded)) == decoded
