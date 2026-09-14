import ast
import inspect
from collections import UserDict
from collections.abc import Mapping
from types import MappingProxyType

import pytest

from insarforge.contracts import _extensions
from insarforge.contracts._extensions import _freeze_extensions, _validate_extension_key
from insarforge.contracts.values import freeze_json, validate_identifier


@pytest.mark.parametrize(
    "key",
    [
        "vendor-x:flag",
        "future-tool:metadata",
        "insarforge:test-value",
        "Vendor:flag",
        "vendor:flag",
        "synthetic.example:local.name",
        "synthetic/tool:local/name",
        "équipe:échantillon",
        "e\u0301quipe:e\u0301chantillon",
        "synthetic_1:flag+value@2",
    ],
)
def test_valid_extension_keys_preserve_spelling(key):
    namespace, local_name = key.split(":")
    assert validate_identifier(namespace) == namespace
    assert validate_identifier(local_name) == local_name
    assert _validate_extension_key(key) == key
    assert _freeze_extensions({key: 1}) == {key: 1}


@pytest.mark.parametrize(
    "key", [None, 1, True, 1.5, b"vendor:flag", ("vendor", "flag")]
)
def test_non_string_extension_keys_raise_type_error(key):
    with pytest.raises(TypeError):
        _validate_extension_key(key)
    with pytest.raises(TypeError):
        _freeze_extensions({key: 1})


@pytest.mark.parametrize("key", ["", "local", ":local", "namespace:", "a:b:c", ":"])
def test_malformed_extension_keys_raise_value_error(key):
    with pytest.raises(ValueError):
        _validate_extension_key(key)
    with pytest.raises(ValueError):
        _freeze_extensions({key: 1})


@pytest.mark.parametrize(
    "component",
    [
        " x",
        "x ",
        "x y",
        "x\t",
        "x\n",
        "x\x00",
        "x\x7f",
        "x\u200b",
        "x\ue000",
        "x\ud800",
    ],
)
@pytest.mark.parametrize("namespace_invalid", [True, False])
def test_each_component_obeys_existing_identifier_rejections(
    component, namespace_invalid
):
    key = f"{component}:valid" if namespace_invalid else f"valid:{component}"
    with pytest.raises(ValueError):
        validate_identifier(component)
    with pytest.raises(ValueError):
        _validate_extension_key(key)
    with pytest.raises(ValueError):
        _freeze_extensions({key: 1})


def test_unknown_and_builtin_namespaces_need_no_owner_context():
    # Generic extension grammar validation does not authenticate namespace owner.
    source = {"unregistered-synthetic-tool-42:future": None, "insarforge:test": True}
    assert _freeze_extensions(source) == source
    assert _validate_extension_key("insarforge:test") == "insarforge:test"


def test_case_and_unicode_spellings_coexist_without_normalization():
    source = {"Vendor:flag": 1, "vendor:flag": 2, "é:flag": 3, "e\u0301:flag": 4}
    frozen = _freeze_extensions(source)
    assert len(frozen) == 4
    assert dict(frozen) == source


@pytest.mark.parametrize("source", [None, "text", 1, 1.5, True, [], (), set()])
def test_non_mapping_containers_raise_type_error(source):
    with pytest.raises(TypeError):
        _freeze_extensions(source)


@pytest.mark.parametrize("mapping_type", [dict, UserDict, MappingProxyType])
@pytest.mark.parametrize(
    "source",
    [{}, {"vendor-x:a": 1}, {"vendor-x:a": {"nested": [1, 2]}, "future-tool:b": None}],
)
def test_mapping_inputs_return_canonical_object_shape(mapping_type, source):
    frozen = _freeze_extensions(mapping_type(source))
    canonical = freeze_json(source)
    assert isinstance(frozen, Mapping)
    assert type(frozen) is type(canonical)
    assert frozen == canonical


@pytest.mark.parametrize("invalid_key", ["plain", "a:b:c", 1, None])
def test_all_keys_are_validated_before_any_snapshot(monkeypatch, invalid_key):
    def unexpected_freeze(value):
        pytest.fail("snapshot started before all extension keys were validated")

    monkeypatch.setattr(_extensions, "freeze_json", unexpected_freeze)
    source = {"vendor-x:first": object(), invalid_key: 1}
    error = ValueError if isinstance(invalid_key, str) else TypeError
    with pytest.raises(error):
        _freeze_extensions(source)


@pytest.mark.parametrize("mapping_type", [dict, UserDict, MappingProxyType])
def test_snapshot_isolates_all_mutable_source_layers(mapping_type):
    items = [1, 2]
    nested = {"values": items}
    backing = {"vendor-x:data": nested}
    source = mapping_type(backing)
    frozen = _freeze_extensions(source)
    items.append(3)
    nested["added"] = True
    nested["values"] = [99]
    backing["vendor-x:new"] = 1
    backing["vendor-x:data"] = None
    if isinstance(source, UserDict):
        source["vendor-x:new"] = 2
        source["vendor-x:data"] = None
    assert frozen == {"vendor-x:data": {"values": (1, 2)}}


def test_nested_readonly_views_do_not_retain_backing_aliases():
    items = [3, 1, 2]
    inner = {"items": items}
    outer = {"vendor-x:data": (MappingProxyType(inner),)}
    frozen = _freeze_extensions(MappingProxyType(outer))
    items.reverse()
    inner.clear()
    outer.clear()
    assert frozen == {"vendor-x:data": ({"items": (3, 1, 2)},)}


def test_returned_state_is_deeply_immutable():
    frozen = _freeze_extensions({"vendor-x:data": {"items": [1, 2]}})
    with pytest.raises(TypeError):
        frozen["vendor-x:new"] = 1
    with pytest.raises(TypeError):
        frozen["vendor-x:data"]["new"] = 1
    sequence = frozen["vendor-x:data"]["items"]
    assert isinstance(sequence, tuple)
    with pytest.raises(AttributeError):
        sequence.append(3)
    with pytest.raises(TypeError):
        sequence[0] = 9


@pytest.mark.parametrize("sequence", [[1, 2, 3], [3, 1, 2], (3, 1, 2)])
def test_array_order_is_preserved(sequence):
    assert _freeze_extensions({"vendor-x:data": sequence})["vendor-x:data"] == tuple(
        sequence
    )


def test_mapping_order_is_not_semantic_and_is_not_manually_sorted():
    source = {"vendor-x:z": {"z": 1, "a": 2}, "vendor-x:a": 3}
    reversed_source = dict(reversed(source.items()))
    frozen = _freeze_extensions(source)
    assert frozen == _freeze_extensions(reversed_source)
    assert list(frozen) == list(source)
    assert list(frozen["vendor-x:z"]) == ["z", "a"]


@pytest.mark.parametrize(
    "value, error",
    [
        (object(), TypeError),
        ({1}, TypeError),
        ({1: "x"}, TypeError),
        (float("nan"), ValueError),
        (float("inf"), ValueError),
    ],
)
def test_value_domain_failures_remain_canonical(value, error):
    with pytest.raises(error):
        _freeze_extensions({"vendor-x:data": {"nested": [value]}})


def test_json_scalars_and_nested_ordinary_keys_are_preserved():
    source = {"vendor-x:data": {"plain nested key": [None, True, 1, 1.0, "text"]}}
    scalars = _freeze_extensions(source)["vendor-x:data"]["plain nested key"]
    assert scalars == (None, True, 1, 1.0, "text")
    assert tuple(type(value) for value in scalars) == (
        type(None),
        bool,
        int,
        float,
        str,
    )


def test_helper_imports_only_leaf_dependencies_and_defines_private_functions():
    tree = ast.parse(inspect.getsource(_extensions))
    allowed = {
        "collections.abc": {"Mapping"},
        "insarforge.contracts.values": {
            "FrozenJSON",
            "freeze_json",
            "validate_identifier",
        },
    }
    for node in ast.walk(tree):
        assert not isinstance(node, (ast.Import, ast.ClassDef))
        if isinstance(node, ast.ImportFrom):
            assert node.level == 0
            assert node.module in allowed
            assert {alias.name for alias in node.names} <= allowed[node.module]
        if isinstance(node, ast.FunctionDef):
            assert node.name.startswith("_")
    assert _extensions.freeze_json is freeze_json
    assert _extensions.validate_identifier is validate_identifier
