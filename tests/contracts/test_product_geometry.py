"""Final geometry model contracts with synthetic values only."""

import ast
import builtins
import io
import os
import socket
from dataclasses import MISSING, FrozenInstanceError, fields, replace
from pathlib import Path
from typing import get_type_hints

import pytest

from insarforge.contracts.values import ArtifactRef
from insarforge.products.geometry import AxisDescriptor, GeometryDescriptor
from insarforge.products.grid import GridDefinition
from insarforge.products.semantics import SemanticStatus, SemanticValue, UnitSpec


def known(value):
    return SemanticValue(SemanticStatus.KNOWN, value, None, ())


def absent(status=SemanticStatus.UNKNOWN):
    return SemanticValue(status, None, "synthetic:reason", ())


def artifact():
    return ArtifactRef(
        "record:test",
        "schema:unrecognized-v7",
        7,
        None,
        "synthetic:manifest",
        "synthetic://unresolved/record",
    )


def axis(**changes):
    values = dict(
        axis_id="axis:test-a",
        role="role:test",
        unit=known(UnitSpec("unit:test", "quantity:test", None)),
        direction=known("direction:test"),
    )
    return AxisDescriptor(**(values | changes))


def geometry(**changes):
    values = dict(
        geometry_id="geometry:test",
        domain="domain:test",
        coordinate_reference=known("synthetic coordinate text"),
        axes=(axis(),),
        shape=(2,),
        grid_definition=known(GridDefinition("grid:test-v1", {"arbitrary": [1, 2]})),
        registration=known("registration:test"),
        reference=known(artifact()),
    )
    return GeometryDescriptor(**(values | changes))


@pytest.mark.parametrize(
    "cls,expected",
    [
        (
            AxisDescriptor,
            {
                "axis_id": str,
                "role": str,
                "unit": SemanticValue[UnitSpec],
                "direction": SemanticValue[str],
            },
        ),
        (
            GeometryDescriptor,
            {
                "geometry_id": str,
                "domain": str,
                "coordinate_reference": SemanticValue[str],
                "axes": tuple[AxisDescriptor, ...],
                "shape": tuple[int, ...],
                "grid_definition": SemanticValue[GridDefinition],
                "registration": SemanticValue[str],
                "reference": SemanticValue[ArtifactRef],
            },
        ),
    ],
)
def test_exact_fields_and_types(cls, expected):
    assert tuple(field.name for field in fields(cls)) == tuple(expected)
    assert get_type_hints(cls) == expected
    assert all(field.default is MISSING for field in fields(cls))
    assert all(field.default_factory is MISSING for field in fields(cls))


@pytest.mark.parametrize("name", ["size", "length", "count", "extensions"])
def test_axis_has_no_transitional_fields_or_aliases(name):
    assert not hasattr(axis(), name)
    with pytest.raises(TypeError):
        axis(**{name: 2})


@pytest.mark.parametrize("name", ["domain_id", "extensions"])
def test_geometry_has_no_transitional_fields_or_aliases(name):
    assert not hasattr(geometry(), name)
    with pytest.raises(TypeError):
        geometry(**{name: "synthetic:test"})


@pytest.mark.parametrize(
    "factory,field",
    [
        (axis, "axis_id"),
        (axis, "role"),
        (geometry, "geometry_id"),
        (geometry, "domain"),
    ],
)
def test_identifiers_are_open_and_preserved(factory, field):
    value = "synthetic:测试-V7"
    assert getattr(factory(**{field: value}), field) == value


@pytest.mark.parametrize(
    "factory,field",
    [
        (axis, "axis_id"),
        (axis, "role"),
        (geometry, "geometry_id"),
        (geometry, "domain"),
    ],
)
@pytest.mark.parametrize("value", [None, True, 1, b"synthetic:test"])
def test_identifier_types(factory, field, value):
    with pytest.raises(TypeError):
        factory(**{field: value})


@pytest.mark.parametrize(
    "factory,field",
    [
        (axis, "axis_id"),
        (axis, "role"),
        (geometry, "geometry_id"),
        (geometry, "domain"),
    ],
)
@pytest.mark.parametrize(
    "value", ["", " ", " test", "test ", "test id", "test\x00id", "test\u200bid"]
)
def test_identifier_grammar(factory, field, value):
    with pytest.raises(ValueError):
        factory(**{field: value})


SEMANTIC_FIELDS = [
    (axis, "unit", UnitSpec("unit:test", "quantity:test", None)),
    (axis, "direction", "direction:test"),
    (geometry, "coordinate_reference", "synthetic coordinate text"),
    (geometry, "grid_definition", GridDefinition("grid:test-v1", {})),
    (geometry, "registration", "registration:test"),
    (geometry, "reference", artifact()),
]


@pytest.mark.parametrize("factory,field,payload", SEMANTIC_FIELDS)
@pytest.mark.parametrize("status", list(SemanticStatus))
def test_semantic_states_and_evidence_preserved(factory, field, payload, status):
    evidence = (artifact(),)
    semantic = SemanticValue(
        status,
        payload if status is SemanticStatus.KNOWN else None,
        "synthetic:reason",
        evidence,
    )
    result = factory(**{field: semantic})
    stored = getattr(result, field)
    assert stored is semantic
    assert stored.status is status
    assert stored.value is (payload if status is SemanticStatus.KNOWN else None)
    assert stored.reason_code == "synthetic:reason"
    assert stored.evidence_refs == evidence


@pytest.mark.parametrize("factory,field,payload", SEMANTIC_FIELDS)
@pytest.mark.parametrize("raw", [None, "synthetic:raw", 1, {}])
def test_semantic_wrapper_required(factory, field, payload, raw):
    with pytest.raises(TypeError):
        factory(**{field: raw})


@pytest.mark.parametrize("factory,field,payload", SEMANTIC_FIELDS)
@pytest.mark.parametrize("wrong", [True, 3, [], {}])
def test_wrong_known_payload_rejected(factory, field, payload, wrong):
    with pytest.raises(TypeError):
        factory(**{field: known(wrong)})


@pytest.mark.parametrize("field", ["unit", "grid_definition", "reference"])
def test_typed_payload_is_not_replaced_by_string(field):
    factory = axis if field == "unit" else geometry
    with pytest.raises(TypeError):
        factory(**{field: known("synthetic:wrong-type")})


@pytest.mark.parametrize("text", ["synthetic:text", "synthetic text with spaces"])
def test_coordinate_reference_is_opaque_text(text):
    assert geometry(coordinate_reference=known(text)).coordinate_reference.value == text


@pytest.mark.parametrize("text", ["", " ", " synthetic", "synthetic ", "synthetic\n"])
def test_coordinate_reference_requires_nonempty_trimmed_text(text):
    with pytest.raises(ValueError):
        geometry(coordinate_reference=known(text))


@pytest.mark.parametrize(
    "factory,field", [(axis, "direction"), (geometry, "registration")]
)
@pytest.mark.parametrize(
    "text", ["", " ", " test", "test ", "test id", "test\x00id", "test\u200bid"]
)
def test_known_identifier_semantics(factory, field, text):
    with pytest.raises(ValueError):
        factory(**{field: known(text)})


def test_valid_one_dimensional_geometry():
    result = geometry()
    assert result.shape == (2,)
    assert tuple(item.axis_id for item in result.axes) == ("axis:test-a",)
    assert result.axes[0].axis_id != result.axes[0].role


def test_multidimensional_order_and_defensive_copying():
    first, second = axis(axis_id="axis:test-z"), axis(axis_id="axis:test-a")
    axes = [first, second]
    shape = [5, 2]
    result = geometry(axes=axes, shape=shape)
    axes.reverse()
    axes.append(axis(axis_id="axis:test-b"))
    shape[0] = 99
    shape.append(4)
    assert result.axes == (first, second)
    assert result.shape == (5, 2)
    assert isinstance(result.axes, tuple)
    assert isinstance(result.shape, tuple)
    assert tuple(zip(result.axes, result.shape)) == ((first, 5), (second, 2))
    with pytest.raises(TypeError):
        result.axes[0] = second
    with pytest.raises(TypeError):
        result.shape[0] = 3


@pytest.mark.parametrize("axes,shape", [((), ()), ((), (1,)), ((axis(),), ())])
def test_empty_geometry_is_invalid(axes, shape):
    with pytest.raises(ValueError, match="non-empty"):
        geometry(axes=axes, shape=shape)


@pytest.mark.parametrize(
    "axes,shape", [((axis(),), (2, 3)), ((axis(), axis(axis_id="axis:test-b")), (2,))]
)
def test_axis_shape_count_must_match(axes, shape):
    with pytest.raises(ValueError, match="same length"):
        geometry(axes=axes, shape=shape)


@pytest.mark.parametrize("value", [None, "axis:test", {}, 1])
def test_axis_elements_must_be_descriptors(value):
    with pytest.raises(TypeError, match="AxisDescriptor"):
        geometry(axes=(value,))


def test_duplicate_axis_identity_is_invalid_even_with_distinct_roles():
    with pytest.raises(ValueError, match="unique"):
        geometry(axes=(axis(), axis(role="role:other")), shape=(2, 3))


@pytest.mark.parametrize("value", [0, -1, -5])
def test_shape_must_be_positive(value):
    with pytest.raises(ValueError, match="positive"):
        geometry(shape=(value,))


@pytest.mark.parametrize("value", [True, False, 1.0, "1", None])
def test_shape_must_contain_integers_excluding_bool(value):
    with pytest.raises(TypeError, match="integers excluding bool"):
        geometry(shape=(value,))


@pytest.mark.parametrize("field", ["axes", "shape"])
def test_axes_and_shape_require_iterables(field):
    with pytest.raises(TypeError):
        geometry(**{field: None})


@pytest.mark.parametrize("factory", [axis, geometry])
def test_all_fields_are_frozen(factory):
    value = factory()
    for field in fields(value):
        with pytest.raises(FrozenInstanceError):
            setattr(value, field.name, getattr(value, field.name))


@pytest.mark.parametrize("status", list(SemanticStatus))
def test_known_grid_does_not_require_coordinate_reference_or_infer_values(status):
    coordinate_reference = (
        known("synthetic text") if status is SemanticStatus.KNOWN else absent(status)
    )
    grid = GridDefinition("grid:unrecognized-v7", {"uninterpreted": ["opaque", 4]})
    result = geometry(
        coordinate_reference=coordinate_reference,
        grid_definition=known(grid),
        registration=absent(),
        reference=absent(),
    )
    assert result.grid_definition.value is grid
    assert result.grid_definition.value.parameters == {"uninterpreted": ("opaque", 4)}
    assert result.coordinate_reference is coordinate_reference
    assert result.registration.status is SemanticStatus.UNKNOWN
    assert result.reference.status is SemanticStatus.UNKNOWN


@pytest.mark.parametrize(
    "locator", ["synthetic://unresolved/record", "/synthetic-missing/record"]
)
def test_artifact_reference_is_not_inspected_or_dereferenced(monkeypatch, locator):
    reference = replace(artifact(), locator=locator)
    semantic = known(reference)
    source = geometry(reference=semantic)

    def forbidden(*args, **kwargs):
        raise AssertionError(
            "Geometry construction attempted I/O or locator inspection"
        )

    with monkeypatch.context() as patch:
        patch.setattr(builtins, "open", forbidden)
        patch.setattr(io, "open", forbidden)
        patch.setattr(os, "stat", forbidden)
        patch.setattr(os, "lstat", forbidden)
        patch.setattr(os, "open", forbidden)
        patch.setattr(socket, "socket", forbidden)
        patch.setattr(socket, "create_connection", forbidden)
        patch.setattr(ArtifactRef, "locator", property(forbidden), raising=False)
        result = replace(source)
    assert result.reference is semantic
    assert result.reference.value.semantic_digest is None
    assert result.reference.value.schema_id == "schema:unrecognized-v7"


def test_geometry_import_boundary():
    path = Path(__file__).resolve().parents[2] / "src/insarforge/products/geometry.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    allowed = {
        "__future__": {"annotations"},
        "dataclasses": {"dataclass"},
        "insarforge.contracts.values": {"ArtifactRef", "validate_identifier"},
        "insarforge.products.grid": {"GridDefinition"},
        "insarforge.products.semantics": {
            "SemanticStatus",
            "SemanticValue",
            "UnitSpec",
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
