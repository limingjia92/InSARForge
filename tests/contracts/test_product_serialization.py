import json
import math
from dataclasses import replace

import pytest
from test_product_models import populated_product, reference_artifact, sv, unknown

from insarforge.contracts.values import freeze_json
from insarforge.products.layers import LayerSelector
from insarforge.products.models import LineageEntry
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
    assert set(value["layers"][0]) == {
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
        assert set(value["layers"][0]["selector"]) == {
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
    obj = value["layers"][0]
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
    obj = original["layers"][0]
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
    manifest["layers"][0]["nodata"]["value"] = dict(
        kind=kind, value=value, mask_layer_ref=mask
    )
    with pytest.raises((ValueError, TypeError)):
        product_from_manifest_value(manifest)


def test_pluginref_nested_producer_roundtrip():
    product = replace(populated_product(), assets=(), geometries=(), layers=())
    value = product_to_manifest_value(product)
    producer = value["producer"]["plugin"]
    assert set(producer) == {"kind", "plugin_id", "api_version"}
    assert "asset_kind" not in producer
    assert producer["kind"] == product.producer.plugin.kind.value
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
        "producer": value["producer"]["plugin"],
        "asset": value["assets"][0],
        "integrity": value["assets"][0]["integrity"],
        "geometry": value["geometries"][0],
        "axis": value["geometries"][0]["axes"][0],
        "grid": value["geometries"][0]["grid_definition"]["value"],
        "reference": value["geometries"][0]["reference"]["value"],
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
    encoded = product_to_manifest_value(product)["geometries"][0]
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
    obj = value["geometries"][0]
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
    obj = value["geometries"][0][field]
    obj.update(status=status, reason_code="synthetic:reason")
    with pytest.raises(ValueError, match="non-null"):
        product_from_manifest_value(value)


@pytest.mark.parametrize("field", ["grid_definition", "reference"])
@pytest.mark.parametrize("payload", [None, 1, "synthetic:wrong", [], {}])
def test_known_geometry_payload_is_strictly_typed(field, payload):
    value = geometry_manifest()
    value["geometries"][0][field]["value"] = payload
    with pytest.raises((ValueError, TypeError)):
        product_from_manifest_value(value)


@pytest.mark.parametrize("field", ["grid_definition", "reference"])
def test_geometry_semantic_envelope_fields_are_strict(field):
    value = geometry_manifest()
    obj = value["geometries"][0][field]
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
    obj = value["geometries"][0][field]
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
    value["geometries"][0]["grid_definition"]["value"]["parameters"] = payload
    with pytest.raises((TypeError, ValueError)):
        product_from_manifest_value(value)


def test_grid_decoder_preserves_types_and_deep_immutability():
    value = geometry_manifest()
    parameters = {" nested ": {"values": [None, True, 7, 7.0, "测试"]}}
    value["geometries"][0]["grid_definition"]["value"]["parameters"] = parameters
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
    value["geometries"][0][field] = payload
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
    target = value["geometries"][0]["reference"]["value"]
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


@pytest.mark.parametrize("via_bytes", [False, True], ids=["value", "bytes"])
@pytest.mark.parametrize(
    "path",
    [
        ("assets", 0, "integrity"),
        ("assets", 0, "member_manifest_ref"),
        ("provenance_ref",),
        ("assets", 0, "location", "anchor"),
    ],
    ids=["integrity", "member-ref", "provenance-ref", "anchor"],
)
@pytest.mark.parametrize("malformed", [{}, [], False, 0, "", True, 1, ["invalid"]])
def test_s1_optional_values_and_required_provenance_do_not_collapse_to_null(
    via_bytes, path, malformed
):
    value = json.loads(product_to_manifest_bytes(populated_product()))
    node = value
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = malformed
    with pytest.raises((TypeError, ValueError)):
        if via_bytes:
            product_from_manifest_bytes(canonical_json_bytes(value))
        else:
            product_from_manifest_value(value)


@pytest.mark.parametrize("via_bytes", [False, True], ids=["value", "bytes"])
@pytest.mark.parametrize("malformed", [{}, "", False, 0, None, {"item": []}, [{}]])
def test_s1_sign_evidence_requires_array_and_typed_elements(via_bytes, malformed):
    value = json.loads(product_to_manifest_bytes(populated_product()))
    value["layers"][0]["sign"]["value"]["evidence_refs"] = malformed
    with pytest.raises((TypeError, ValueError)):
        if via_bytes:
            product_from_manifest_bytes(canonical_json_bytes(value))
        else:
            product_from_manifest_value(value)


def s1_product_with_optional_values():
    from pathlib import Path

    from insarforge.contracts.values import ArtifactRef
    from insarforge.products.assets import (
        AssetIntegrity,
        AssetKind,
        AssetLocation,
        AssetLocationKind,
    )

    product = populated_product()
    first = ArtifactRef("synthetic:z", "synthetic:schema", 1, None, "digest:z", "z")
    second = replace(first, record_id="synthetic:a", manifest_digest="digest:a")
    source = replace(
        product.assets[0],
        location=AssetLocation(
            AssetLocationKind.MANIFEST_RELATIVE,
            "synthetic-file",
            Path("/tmp/synthetic"),
        ),
        integrity=AssetIntegrity("synthetic:algorithm", "synthetic:digest"),
    )
    directory = replace(
        product.assets[0],
        asset_id="synthetic:directory",
        asset_kind=AssetKind.DIRECTORY,
        member_manifest_ref=replace(
            first, schema_id="insarforge:directory-member-manifest"
        ),
    )
    layer = product.layers[0]
    sign = replace(layer.sign.value, evidence_refs=(first, second))
    return replace(
        product,
        assets=(source, directory),
        provenance_ref="synthetic:provenance",
        acquisition_refs=(first,),
        layers=(replace(layer, sign=sv(sign)), *product.layers[1:]),
    )


@pytest.mark.parametrize("populated", [False, True])
def test_s1_optional_nulls_and_present_values_roundtrip_without_io(
    populated, monkeypatch
):
    import builtins
    import io
    import socket

    product = s1_product_with_optional_values() if populated else populated_product()

    def forbidden(*args, **kwargs):
        pytest.fail("record codecs must not dereference assets or references")

    with monkeypatch.context() as patch:
        patch.setattr(builtins, "open", forbidden)
        patch.setattr(io, "open", forbidden)
        patch.setattr(socket, "socket", forbidden)
        value = product_to_manifest_value(product)
        data = product_to_manifest_bytes(product)
        assert product_from_manifest_value(value) == product
        decoded = product_from_manifest_bytes(data)
        assert decoded == product
        assert product_to_manifest_bytes(decoded) == data
    assert (
        decoded.layers[0].sign.value.evidence_refs
        == product.layers[0].sign.value.evidence_refs
    )


@pytest.mark.parametrize("via_bytes", [False, True], ids=["value", "bytes"])
@pytest.mark.parametrize(
    "path",
    [
        ("assets", 0, "integrity"),
        ("assets", 1, "member_manifest_ref"),
        ("acquisition_refs", 0),
        ("assets", 0, "location"),
        ("layers", 0, "sign", "value", "evidence_refs", 0),
    ],
    ids=["integrity", "member-ref", "acquisition-ref", "location", "sign-evidence"],
)
def test_s1_optional_nested_fields_remain_exact(via_bytes, path):
    value = json.loads(product_to_manifest_bytes(s1_product_with_optional_values()))
    node = value
    for key in path:
        node = node[key]

    def reject():
        with pytest.raises(ValueError, match="fields"):
            if via_bytes:
                product_from_manifest_bytes(canonical_json_bytes(value))
            else:
                product_from_manifest_value(value)

    for key in tuple(node):
        saved = node.pop(key)
        reject()
        node[key] = saved
    node["synthetic_extra"] = "synthetic:value"
    reject()


@pytest.mark.parametrize("asset_kind", ["file", "directory"])
def test_s1_optional_decode_preserves_asset_kind_constraints(asset_kind):
    value = json.loads(product_to_manifest_bytes(s1_product_with_optional_values()))
    if asset_kind == "file":
        value["assets"][1]["asset_kind"] = "file"
    else:
        value["assets"][0]["asset_kind"] = "directory"
    with pytest.raises(ValueError):
        product_from_manifest_value(value)


@pytest.mark.parametrize(
    "extensions",
    [
        {},
        {
            "future-tool:data": {
                "values": [None, True, 1, 1.5, "text", {"ordinary key": 2}]
            }
        },
        {"Vendor:flag": 1, "vendor:flag": 2},
        {"insarforge:test-value": 1},
    ],
)
def test_namespaced_extensions_roundtrip(extensions):
    product = replace(populated_product(), extensions=extensions)
    value = product_to_manifest_value(product)
    assert list(value)[8] == "extensions"
    assert value["extensions"] == product.extensions
    assert product_from_manifest_value(value) == product
    data = product_to_manifest_bytes(product)
    decoded = product_from_manifest_bytes(data)
    assert decoded == product
    assert product_to_manifest_bytes(decoded) == data


@pytest.mark.parametrize(
    "extensions,error",
    [
        (None, TypeError),
        ([], TypeError),
        ((), TypeError),
        ("text", TypeError),
        (1, TypeError),
        ({"flag": 1}, ValueError),
        ({"metadata": 1}, ValueError),
        ({":flag": 1}, ValueError),
        ({"vendor:": 1}, ValueError),
        ({"a:b:c": 1}, ValueError),
    ],
)
def test_extension_decode_rejects_invalid_shape_and_keys(extensions, error):
    value = json.loads(product_to_manifest_bytes(populated_product()))
    value["extensions"] = extensions
    with pytest.raises(error):
        product_from_manifest_value(value)
    with pytest.raises(error):
        product_from_manifest_bytes(json.dumps(value))


@pytest.mark.parametrize(
    "payload",
    [
        '{"vendor:data":{"x":1,"x":2}}',
        '{"vendor:data":NaN}',
        '{"vendor:data":Infinity}',
        '{"vendor:data":1e999}',
    ],
)
def test_extension_json_remains_strict(payload):
    data = product_to_manifest_bytes(populated_product()).decode()
    assert '"extensions":{}' in data
    with pytest.raises(ValueError):
        product_from_manifest_bytes(
            data.replace('"extensions":{}', '"extensions":' + payload)
        )


@pytest.mark.parametrize("change", ["missing", "extra"])
def test_extension_migration_preserves_exact_product_fields(change):
    value = json.loads(product_to_manifest_bytes(populated_product()))
    if change == "missing":
        del value["extensions"]
    else:
        value["unexpected"] = {}
    with pytest.raises(ValueError, match="product fields"):
        product_from_manifest_value(value)


@pytest.mark.parametrize("key", ["vendor-x:secret", "vendor-x:data"])
@pytest.mark.parametrize("emit", [product_to_manifest_value, product_to_manifest_bytes])
def test_namespaced_extensions_do_not_bypass_safe_persistence(key, emit):
    from insarforge.contracts.errors import ContractError

    product = replace(
        populated_product(),
        extensions={key: "https://example.invalid/?token=synthetic-marker"},
    )
    with pytest.raises(ContractError, match="PERSISTENCE_SECRET"):
        emit(product)


PRODUCT_FIELDS = (
    "product_kind",
    "profile_id",
    "profile_version",
    "assets",
    "layers",
    "geometries",
    "acquisition_refs",
    "semantic_metadata",
    "extensions",
    "schema_id",
    "schema_version",
    "product_id",
    "producer",
    "produced_by",
    "lineage",
    "provenance_ref",
)
IDENTITY_PATHS = (
    ("producer", "implementation_identity_digest"),
    ("producer", "execution_identity_digest"),
    ("produced_by", "task_fingerprint"),
)


def v2_product():
    first = reference_artifact(None)
    second = replace(
        first, record_id="synthetic:second", semantic_digest="semantic:second"
    )
    return replace(
        populated_product(),
        acquisition_refs=(second, first),
        lineage=(LineageEntry("role:z", first), LineageEntry("role:a", second)),
        semantic_metadata={
            "quality": SemanticValue(
                SemanticStatus.KNOWN,
                freeze_json(
                    {"nested": [None, True, 1, 1.0, "科学"], "status": "opaque-json"}
                ),
                "synthetic:reason",
                (second, first, second),
            ),
            "a:b:c": unknown(),
            "unused": SemanticValue(
                SemanticStatus.NOT_APPLICABLE, None, "synthetic:unused", ()
            ),
        },
        extensions={"future-owner:data": {"array": [1, 2], "unknown": True}},
    )


def v2_wire():
    return json.loads(product_to_manifest_bytes(v2_product()))


def node_at(value, path):
    for key in path:
        value = value[key]
    return value


def decode_wire(value, via_bytes):
    return (
        product_from_manifest_bytes(canonical_json_bytes(value))
        if via_bytes
        else product_from_manifest_value(value)
    )


def test_v2_flat_populated_roundtrip_and_order():
    product = v2_product()
    value = product_to_manifest_value(product)
    assert tuple(value) == PRODUCT_FIELDS
    assert value["schema_id"] == "insarforge:product"
    assert type(value["schema_version"]) is int and value["schema_version"] == 2
    assert "product" not in value
    assert product_from_manifest_value(value) == product
    data = product_to_manifest_bytes(product)
    decoded = product_from_manifest_bytes(data)
    assert decoded == product
    assert product_to_manifest_bytes(decoded) == data
    wire = json.loads(data)
    assert isinstance(wire["lineage"], list)
    assert [entry["role"] for entry in wire["lineage"]] == ["role:z", "role:a"]
    assert [r["record_id"] for r in wire["acquisition_refs"]] == [
        "synthetic:second",
        "synthetic:record",
    ]
    assert decoded.acquisition_refs[1].semantic_digest is None
    assert decoded.lineage[0].artifact.semantic_digest is None
    assert (
        decoded.semantic_metadata["quality"].evidence_refs
        == product.semantic_metadata["quality"].evidence_refs
    )
    assert type(decoded.semantic_metadata["quality"].value["nested"][2]) is int
    assert type(decoded.semantic_metadata["quality"].value["nested"][3]) is float


@pytest.mark.parametrize("name", PRODUCT_FIELDS)
@pytest.mark.parametrize("via_bytes", [False, True])
def test_v2_requires_every_top_level_field(name, via_bytes):
    value = v2_wire()
    del value[name]
    with pytest.raises(ValueError, match="product fields"):
        decode_wire(value, via_bytes)


@pytest.mark.parametrize("name", ["extra", "producer_implementation_version"])
@pytest.mark.parametrize("via_bytes", [False, True])
def test_v2_rejects_extra_or_transitional_fields(name, via_bytes):
    value = v2_wire()
    value[name] = "synthetic:legacy"
    with pytest.raises(ValueError, match="product fields"):
        decode_wire(value, via_bytes)


@pytest.mark.parametrize(
    "field,payload",
    [
        ("schema_id", None),
        ("schema_id", ""),
        ("schema_id", "insarforge:product-manifest"),
        ("schema_id", "Insarforge:product"),
        ("schema_id", " insarforge:product"),
        ("schema_version", 1),
        ("schema_version", 3),
        ("schema_version", True),
        ("schema_version", False),
        ("schema_version", 2.0),
        ("schema_version", "2"),
    ],
)
@pytest.mark.parametrize("via_bytes", [False, True])
def test_v2_rejects_wrong_schema_literal_and_revision(field, payload, via_bytes):
    value = v2_wire()
    value[field] = payload
    with pytest.raises(ValueError, match="envelope"):
        decode_wire(value, via_bytes)


@pytest.mark.parametrize(
    "shape",
    [
        "v1-wrapper",
        "v2-wrapper",
        "flat-legacy",
        "producer",
        "lineage",
        "null-provenance",
        "nested-provenance",
    ],
)
@pytest.mark.parametrize("via_bytes", [False, True])
def test_v2_rejects_legacy_wire_shapes_without_translation(shape, via_bytes):
    value = v2_wire()
    if shape in {"v1-wrapper", "flat-legacy"}:
        for field in (
            "schema_id",
            "produced_by",
            "acquisition_refs",
            "semantic_metadata",
        ):
            del value[field]
        value["schema_version"] = 1
        value["producer_implementation_version"] = value["producer"][
            "implementation_version"
        ]
        value["producer"] = value["producer"]["plugin"]
        value["lineage"] = [entry["artifact"] for entry in value["lineage"]]
        value["provenance_ref"] = None
        if shape == "v1-wrapper":
            value = {
                "schema_id": "insarforge:product-manifest",
                "schema_version": 1,
                "product": value,
            }
    elif shape == "v2-wrapper":
        value = {
            "schema_id": "insarforge:product",
            "schema_version": 2,
            "product": value,
        }
    elif shape == "producer":
        value["producer"] = value["producer"]["plugin"]
    elif shape == "lineage":
        value["lineage"] = [entry["artifact"] for entry in value["lineage"]]
    else:
        value["provenance_ref"] = (
            None if shape == "null-provenance" else value["acquisition_refs"][0]
        )
    with pytest.raises((TypeError, ValueError)):
        decode_wire(value, via_bytes)


@pytest.mark.parametrize(
    "path",
    [
        ("producer",),
        ("produced_by",),
        ("lineage", 0),
        ("producer", "plugin"),
        ("lineage", 0, "artifact"),
        ("acquisition_refs", 0),
        *IDENTITY_PATHS,
        ("semantic_metadata", "quality"),
        ("semantic_metadata", "quality", "evidence_refs", 0),
    ],
)
@pytest.mark.parametrize("via_bytes", [False, True])
def test_v2_nested_objects_require_exact_fields(path, via_bytes):
    value = v2_wire()
    node = node_at(value, path)
    for field in tuple(node):
        saved = node.pop(field)
        with pytest.raises(ValueError, match="fields"):
            decode_wire(value, via_bytes)
        node[field] = saved
    node["extra"] = None
    with pytest.raises(ValueError, match="fields"):
        decode_wire(value, via_bytes)


@pytest.mark.parametrize(
    "known_flags",
    [(a, b, c) for a in (False, True) for b in (False, True) for c in (False, True)],
)
def test_v2_identity_availability_roundtrips(known_flags):
    value = v2_wire()
    for path, known in zip(IDENTITY_PATHS, known_flags):
        node = node_at(value, path)
        node.update(
            status="known" if known else "unknown",
            value="opaque identity / 测试" if known else None,
            reason_code="opaque reason / test",
            evidence_refs=[value["acquisition_refs"][1]] * 2,
        )
    product = product_from_manifest_value(value)
    data = product_to_manifest_bytes(product)
    assert product_from_manifest_bytes(data) == product
    assert product_to_manifest_bytes(product_from_manifest_bytes(data)) == data
    for path, known in zip(IDENTITY_PATHS, known_flags):
        stored = node_at(json.loads(data), path)
        assert stored["status"] == ("known" if known else "unknown")
        assert len(stored["evidence_refs"]) == 2
        assert stored["evidence_refs"][0]["semantic_digest"] is None


@pytest.mark.parametrize("path", IDENTITY_PATHS)
@pytest.mark.parametrize(
    "change",
    [
        {"status": "not_applicable", "value": None, "reason_code": "synthetic:reason"},
        {"status": "unknown", "value": None, "reason_code": None},
        {"status": "unknown", "value": "fake", "reason_code": "synthetic:reason"},
        {"status": "invalid"},
        {"value": 1},
        {"value": None},
        {"value": ""},
        {"evidence_refs": {}},
        {"evidence_refs": [{"record_id": "incomplete"}]},
    ],
)
@pytest.mark.parametrize("via_bytes", [False, True])
def test_v2_identity_semantic_owner_rules_are_strict(path, change, via_bytes):
    value = v2_wire()
    node_at(value, path).update(change)
    with pytest.raises((TypeError, ValueError)):
        decode_wire(value, via_bytes)


@pytest.mark.parametrize("path", IDENTITY_PATHS)
@pytest.mark.parametrize("bare", [None, "synthetic:bare-identity"])
def test_v2_identity_requires_explicit_envelope(path, bare):
    value = v2_wire()
    node_at(value, path[:-1])[path[-1]] = bare
    with pytest.raises(TypeError):
        product_from_manifest_value(value)


@pytest.mark.parametrize("field", ["acquisition_refs", "lineage"])
@pytest.mark.parametrize("malformed", [None, {}, "", 1, ["bare"]])
@pytest.mark.parametrize("via_bytes", [False, True])
def test_v2_reference_collections_require_arrays_of_typed_objects(
    field, malformed, via_bytes
):
    value = v2_wire()
    value[field] = malformed
    with pytest.raises((TypeError, ValueError)):
        decode_wire(value, via_bytes)


@pytest.mark.parametrize("field", ["acquisition_refs", "lineage"])
@pytest.mark.parametrize("via_bytes", [False, True])
def test_v2_duplicate_reference_keys_follow_owner_rules(field, via_bytes):
    value = v2_wire()
    value[field].append(value[field][0])
    if field == "acquisition_refs":
        with pytest.raises(ValueError, match=field):
            decode_wire(value, via_bytes)
    else:
        result = decode_wire(value, via_bytes)
        assert len(result.lineage) == 3
        assert result.lineage[0] == result.lineage[2]


@pytest.mark.parametrize("via_bytes", [False, True])
def test_v2_conflicting_lineage_reference_is_rejected(via_bytes):
    import copy

    value = v2_wire()
    duplicate = copy.deepcopy(value["lineage"][0])
    duplicate["artifact"]["locator"] = "synthetic:conflict"
    value["lineage"].append(duplicate)
    with pytest.raises(ValueError, match="lineage"):
        decode_wire(value, via_bytes)


@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        "raw",
        {"quality": 1},
        {"quality": {"value": 1}},
        {
            "bad key": {
                "status": "unknown",
                "value": None,
                "reason_code": "reason",
                "evidence_refs": [],
            }
        },
    ],
)
@pytest.mark.parametrize("via_bytes", [False, True])
def test_v2_metadata_requires_identifier_map_of_semantic_envelopes(payload, via_bytes):
    value = v2_wire()
    value["semantic_metadata"] = payload
    with pytest.raises((TypeError, ValueError)):
        decode_wire(value, via_bytes)


@pytest.mark.parametrize(
    "payload", [None, object(), {1: "wrong-key"}, [float("nan")], [float("inf")]]
)
def test_v2_metadata_known_payload_requires_frozen_json_domain(payload):
    value = v2_wire()
    value["semantic_metadata"]["quality"]["value"] = payload
    with pytest.raises((TypeError, ValueError)):
        product_from_manifest_value(value)


def test_v2_metadata_decoding_owns_caller_mapping_payload_and_evidence():
    value = v2_wire()
    original = product_from_manifest_value(value)
    payload = value["semantic_metadata"]["quality"]["value"]
    evidence = value["semantic_metadata"]["quality"]["evidence_refs"]
    decoded = product_from_manifest_value(value)
    payload["nested"].append("caller-change")
    evidence.clear()
    value["semantic_metadata"].clear()
    value["acquisition_refs"].clear()
    value["lineage"].clear()
    assert decoded == original
    with pytest.raises(TypeError):
        decoded.semantic_metadata["new"] = unknown()
    with pytest.raises(TypeError):
        decoded.semantic_metadata["quality"].value["nested"][0] = 2


@pytest.mark.parametrize(
    "replacement", ['{"x":1,"x":2}', "NaN", "Infinity", "-Infinity", "1e999"]
)
def test_v2_metadata_json_rejects_nested_duplicates_and_nonfinite(replacement):
    product = replace(
        v2_product(), semantic_metadata={"quality": sv("S3C2_JSON_MARKER")}
    )
    data = product_to_manifest_bytes(product).decode()
    assert data.count('"S3C2_JSON_MARKER"') == 1
    with pytest.raises(ValueError):
        product_from_manifest_bytes(data.replace('"S3C2_JSON_MARKER"', replacement))


def test_v2_nested_codecs_never_dereference_or_compute(monkeypatch):
    import builtins
    import hashlib
    import io
    import socket

    from insarforge.core.registry import PluginRegistry

    product = v2_product()
    data = product_to_manifest_bytes(product)

    def forbidden(*args, **kwargs):
        raise AssertionError("static Product codec attempted lookup or computation")

    with monkeypatch.context() as patch:
        patch.setattr(builtins, "open", forbidden)
        patch.setattr(io, "open", forbidden)
        patch.setattr(socket, "socket", forbidden)
        patch.setattr(hashlib, "sha256", forbidden)
        patch.setattr(PluginRegistry, "resolve", forbidden)
        assert product_from_manifest_bytes(data) == product
        assert product_to_manifest_bytes(product) == data


@pytest.mark.parametrize(
    "path,payload",
    [
        (("producer", "plugin", "kind"), "not-a-plugin-kind"),
        (("producer", "plugin", "plugin_id"), "bad id"),
        (("producer", "plugin", "api_version"), True),
        (("producer", "implementation_version"), ""),
        (("produced_by", "output_port"), "bad port"),
        (("produced_by", "attempt_id"), None),
        (("lineage", 0, "role"), ""),
        (("lineage", 0, "artifact"), None),
        (("provenance_ref",), "bad pointer"),
        (("semantic_metadata", "quality", "evidence_refs"), {}),
        (("semantic_metadata", "a:b:c", "value"), "non-null"),
        (("semantic_metadata", "unused", "reason_code"), None),
    ],
)
@pytest.mark.parametrize("via_bytes", [False, True])
def test_v2_nested_owner_and_semantic_validation(path, payload, via_bytes):
    value = v2_wire()
    node_at(value, path[:-1])[path[-1]] = payload
    with pytest.raises((TypeError, ValueError)):
        decode_wire(value, via_bytes)


def test_v2_metadata_value_decoder_rejects_non_string_keys():
    value = v2_wire()
    value["semantic_metadata"][1] = value["semantic_metadata"]["quality"]
    with pytest.raises(TypeError, match="key"):
        product_from_manifest_value(value)
