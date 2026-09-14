"""ADR 0009 GridDefinition contract, using synthetic payloads only."""

import ast
from collections import UserDict
from collections.abc import Mapping
from dataclasses import MISSING, FrozenInstanceError, fields
from pathlib import Path
from types import MappingProxyType

import pytest

from insarforge.contracts.values import FrozenJSON
from insarforge.products.grid import GridDefinition


def test_exact_public_fields():
    public_fields = fields(GridDefinition)
    assert tuple(field.name for field in public_fields) == ("format_id", "parameters")
    assert tuple(field.type for field in public_fields) == (str, FrozenJSON)
    assert all(field.default is MISSING for field in public_fields)
    assert all(field.default_factory is MISSING for field in public_fields)
    assert not hasattr(GridDefinition("grid:test-v1", {}), "extensions")


@pytest.mark.parametrize("format_id", ["grid:test-v1", "grid:TEST-v2", "grid:测试-v3"])
def test_format_id_is_open_and_preserved(format_id):
    assert GridDefinition(format_id, {}).format_id == format_id


@pytest.mark.parametrize("format_id", [None, True, 1, 1.0, [], {}, b"grid:test-v1"])
def test_format_id_rejects_invalid_type(format_id):
    with pytest.raises(TypeError, match="identifier must be a string"):
        GridDefinition(format_id, {})


@pytest.mark.parametrize(
    "format_id",
    [
        "",
        " ",
        " grid:test-v1",
        "grid:test-v1 ",
        "grid:test v1",
        "grid:test\tv1",
        "grid:test\nv1",
        "grid:test\u00a0v1",
        "grid:test\x00v1",
        "grid:test\u200bv1",
        "grid:test\ud800v1",
    ],
)
def test_format_id_rejects_invalid_grammar(format_id):
    with pytest.raises(ValueError, match="identifier"):
        GridDefinition(format_id, {})


@pytest.mark.parametrize(
    "field,value", [("format_id", "grid:test-v2"), ("parameters", {})]
)
def test_fields_are_frozen(field, value):
    grid = GridDefinition("grid:test-v1", {})
    with pytest.raises(FrozenInstanceError):
        setattr(grid, field, value)


@pytest.mark.parametrize(
    "parameters,expected",
    [
        ({}, {}),
        ({"a": 1}, {"a": 1}),
        ({"nested": {"b": 2}}, {"nested": {"b": 2}}),
        ({"values": [3, 1, 2]}, {"values": (3, 1, 2)}),
        ({"values": (2, 1)}, {"values": (2, 1)}),
        (
            {"nested": [{"a": [None, True, 1, 1.5, "测试 🌐"]}, []]},
            {"nested": ({"a": (None, True, 1, 1.5, "测试 🌐")}, ())},
        ),
        ({" key ": " unchanged ", "": "é"}, {" key ": " unchanged ", "": "é"}),
    ],
)
def test_json_content_is_preserved(parameters, expected):
    grid = GridDefinition("grid:test-v1", parameters)
    assert isinstance(grid.parameters, Mapping)
    assert grid.parameters == expected


@pytest.mark.parametrize("value", [None, True, False, 1, 0, 1.0, -0.0, "测试"])
def test_nested_scalar_types_are_preserved(value):
    stored = GridDefinition("grid:test-v1", {"value": value}).parameters["value"]
    assert type(stored) is type(value)
    assert stored == value
    if isinstance(value, float):
        assert stored.hex() == value.hex()


@pytest.mark.parametrize("parameters", [None, True, 1, 1.0, "text", [1, 2], (1, 2)])
def test_parameters_require_top_level_mapping(parameters):
    with pytest.raises(TypeError, match="parameters must be a Mapping"):
        GridDefinition("grid:test-v1", parameters)


@pytest.mark.parametrize("factory", [dict, UserDict, MappingProxyType])
def test_mapping_inputs_are_defensively_frozen(factory):
    source = {"nested": {"values": [1, 2]}}
    parameters = factory(source)
    grid = GridDefinition("grid:test-v1", parameters)
    assert grid.parameters is not parameters
    assert grid.parameters["nested"] is not source["nested"]
    source["nested"]["values"].append(3)
    source["nested"]["new"] = True
    source["extra"] = 4
    source["nested"] = {}
    assert grid.parameters == {"nested": {"values": (1, 2)}}


def test_stored_containers_are_deeply_immutable():
    grid = GridDefinition("grid:test-v1", {"nested": {"values": [1, 2]}})
    with pytest.raises(TypeError):
        grid.parameters["new"] = 3
    with pytest.raises(TypeError):
        grid.parameters["nested"]["new"] = 3
    with pytest.raises(TypeError):
        grid.parameters["nested"]["values"][0] = 3
    with pytest.raises(AttributeError):
        grid.parameters["nested"]["values"].append(3)


@pytest.mark.parametrize("key", [1, True, None, ("a",)])
@pytest.mark.parametrize("nested", [False, True])
def test_mapping_keys_must_be_strings(key, nested):
    parameters = {key: "value"}
    if nested:
        parameters = {"nested": [parameters]}
    with pytest.raises(TypeError, match="mapping keys must be strings"):
        GridDefinition("grid:test-v1", parameters)


@pytest.mark.parametrize("value", [object(), {1, 2}, b"text", complex(1, 2)])
def test_unsupported_values_are_not_coerced(value):
    with pytest.raises(TypeError, match="unsupported JSON value"):
        GridDefinition("grid:test-v1", {"nested": [{"value": value}]})


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_nonfinite_floats_are_rejected(value):
    with pytest.raises(ValueError, match="float must be finite"):
        GridDefinition("grid:test-v1", {"nested": [value]})


def test_generic_constructor_does_not_interpret_parameters():
    parameters = {"arbitrary:test": {"unrecognized": ["opaque", 7]}, "other": False}
    grid = GridDefinition("grid:unrecognized-v97", parameters)
    assert grid.parameters == {
        "arbitrary:test": {"unrecognized": ("opaque", 7)},
        "other": False,
    }
    assert not {"spacing", "origin", "transform", "CRS"}.intersection(grid.parameters)


def test_grid_import_boundary():
    path = (
        Path(__file__).resolve().parents[2]
        / "src"
        / "insarforge"
        / "products"
        / "grid.py"
    )
    tree = ast.parse(path.read_text(encoding="utf-8"))
    allowed = {
        "collections.abc": {"Mapping"},
        "dataclasses": {"dataclass"},
        "insarforge.contracts.values": {
            "FrozenJSON",
            "freeze_json",
            "validate_identifier",
        },
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            pytest.fail(f"Unexpected module import: {ast.unparse(node)}")
        if isinstance(node, ast.ImportFrom):
            assert node.level == 0
            assert node.module in allowed
            assert {alias.name for alias in node.names} <= allowed[node.module]
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id not in {"__import__", "eval", "exec", "open"}
