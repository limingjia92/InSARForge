"""Final ADR 0007 layer models; all example semantics are synthetic."""

import ast
import inspect
from dataclasses import FrozenInstanceError, fields, replace

import pytest

from insarforge.contracts.values import ArtifactRef
from insarforge.products import layers
from insarforge.products.layers import DataLayer, LayerSelector
from insarforge.products.nodata import NoDataKind, NoDataSpec
from insarforge.products.semantics import (
    SemanticStatus,
    SemanticValue,
    SignSpec,
    UnitSpec,
)


def known(value):
    return SemanticValue(SemanticStatus.KNOWN, value, None, ())


def make_layer(**changes):
    values = dict(
        layer_id="synthetic:layer",
        role="synthetic:role",
        asset_id="synthetic:asset",
        selector=None,
        quantity=known("synthetic:quantity"),
        unit=known(UnitSpec("synthetic:unit", "synthetic:quantity", None)),
        sign=known(
            SignSpec(
                "synthetic:sign",
                "synthetic:observable",
                "synthetic:direction",
                None,
                None,
                (),
            )
        ),
        geometry_ref=known("synthetic:geometry"),
        nodata=known(NoDataSpec(NoDataKind.NONE, None, None)),
        dimensions=(),
    )
    values.update(changes)
    return DataLayer(**values)


def test_selector_exact_fields_without_compatibility_aliases():
    assert [f.name for f in fields(LayerSelector)] == ["format_id", "selector_string"]
    selector = LayerSelector("synthetic:format", "opaque content")
    for name in ("selector_kind", "parameters"):
        assert not hasattr(selector, name)
    with pytest.raises(TypeError):
        LayerSelector(selector_kind="synthetic:format", parameters={})


@pytest.mark.parametrize(
    "value", ["", " ", " bad", "bad ", "bad id", "bad\x00id", "bad\u200bid"]
)
def test_selector_rejects_invalid_format_identifier(value):
    with pytest.raises(ValueError):
        LayerSelector(value, "opaque")


@pytest.mark.parametrize("value", [None, 7, {}])
def test_selector_rejects_non_string_format_identifier(value):
    with pytest.raises(TypeError):
        LayerSelector(value, "opaque")


@pytest.mark.parametrize("value", ["", " ", " opaque", "opaque ", "opaque\n"])
def test_selector_rejects_empty_or_surrounding_whitespace(value):
    with pytest.raises(ValueError):
        LayerSelector("synthetic:format", value)


@pytest.mark.parametrize("value", [None, 7, {}])
def test_selector_requires_string_payload(value):
    with pytest.raises(TypeError):
        LayerSelector("synthetic:format", value)


def test_selector_is_opaque_frozen_and_does_not_execute_or_open(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("selector construction attempted execution or I/O")

    with monkeypatch.context() as patch:
        for name in ("open", "eval", "exec"):
            patch.setattr("builtins." + name, forbidden)
        text = "open('synthetic:missing'); opaque [a, b] / ../ e\u0301"
        selector = LayerSelector("synthetic:format", text)
    assert selector.selector_string == text
    for field in fields(selector):
        with pytest.raises(FrozenInstanceError):
            setattr(selector, field.name, "replacement")


def test_datalayer_exact_fields_without_compatibility_aliases():
    assert [f.name for f in fields(DataLayer)] == [
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
    ]
    layer = make_layer()
    for name in ("quantity_kind", "extensions"):
        assert not hasattr(layer, name)
        with pytest.raises(TypeError):
            make_layer(**{name: {}})


@pytest.mark.parametrize("name", ["layer_id", "role", "asset_id"])
@pytest.mark.parametrize(
    "value", ["", " bad", "bad ", "bad id", "bad\x00id", "bad\u200bid"]
)
def test_layer_identifiers_use_existing_grammar(name, value):
    with pytest.raises(ValueError):
        make_layer(**{name: value})


@pytest.mark.parametrize("name", ["layer_id", "role", "asset_id"])
def test_layer_identifiers_require_strings_without_normalization(name):
    with pytest.raises(TypeError):
        make_layer(**{name: 7})
    value = "synthetic:e\u0301"
    assert getattr(make_layer(**{name: value}), name) == value


def test_none_and_explicit_selector_are_distinct_stored_states():
    whole = make_layer()
    selector = LayerSelector("synthetic:format", "opaque")
    selected = make_layer(selector=selector)
    assert whole.selector is None
    assert selected.selector is selector
    assert whole != selected


@pytest.mark.parametrize("value", ["opaque", {}, 7])
def test_selector_wrong_non_none_type_rejected(value):
    with pytest.raises(TypeError, match="selector"):
        make_layer(selector=value)


@pytest.mark.parametrize("name", ["quantity", "unit", "sign", "geometry_ref", "nodata"])
def test_semantic_fields_require_wrappers_and_correct_known_types(name):
    with pytest.raises(TypeError, match=name):
        make_layer(**{name: None})
    with pytest.raises(TypeError, match=name):
        make_layer(**{name: known(7)})
    layer = make_layer()
    assert getattr(layer, name).status is SemanticStatus.KNOWN


@pytest.mark.parametrize("name", ["quantity", "unit", "sign", "geometry_ref", "nodata"])
@pytest.mark.parametrize(
    "status", [SemanticStatus.UNKNOWN, SemanticStatus.NOT_APPLICABLE]
)
def test_semantic_unknown_and_not_applicable_preserve_metadata(name, status):
    evidence = ArtifactRef(
        "synthetic:record",
        "synthetic:schema",
        1,
        None,
        "synthetic:digest",
        "synthetic:locator",
    )
    value = SemanticValue(status, None, "synthetic:reason", (evidence,))
    stored = getattr(make_layer(**{name: value}), name)
    assert stored is value
    assert stored.status is status
    assert stored.reason_code == "synthetic:reason"
    assert stored.evidence_refs == (evidence,)


@pytest.mark.parametrize("name", ["quantity", "geometry_ref"])
@pytest.mark.parametrize("value", ["", " bad", "bad id", "bad\u200bid"])
def test_known_semantic_identifiers_reject_invalid_grammar(name, value):
    with pytest.raises(ValueError):
        make_layer(**{name: known(value)})


@pytest.mark.parametrize("name", ["quantity", "geometry_ref"])
def test_known_identifier_validation_preserves_caller_semanticvalue(name):
    evidence = ArtifactRef(
        "synthetic:record",
        "synthetic:schema",
        1,
        None,
        "synthetic:digest",
        "synthetic:locator",
    )
    value = SemanticValue(
        SemanticStatus.KNOWN, "synthetic:e\u0301", "synthetic:reason", (evidence,)
    )
    snapshot = (value.status, value.value, value.reason_code, value.evidence_refs)
    stored = getattr(make_layer(**{name: value}), name)
    assert stored is value
    assert (
        value.status,
        value.value,
        value.reason_code,
        value.evidence_refs,
    ) == snapshot


@pytest.mark.parametrize(
    "spec",
    [
        NoDataSpec(NoDataKind.NONE, None, None),
        NoDataSpec(NoDataKind.FINITE_VALUE, 7, None),
        NoDataSpec(NoDataKind.NAN, None, None),
        NoDataSpec(NoDataKind.MASK, None, "synthetic:other_layer"),
    ],
)
def test_known_nodata_kinds_preserved(spec):
    assert make_layer(nodata=known(spec)).nodata.value is spec


def test_nodata_none_unknown_and_not_applicable_are_distinct():
    values = [
        known(NoDataSpec(NoDataKind.NONE, None, None)),
        SemanticValue(SemanticStatus.UNKNOWN, None, "synthetic:reason", ()),
        SemanticValue(SemanticStatus.NOT_APPLICABLE, None, "synthetic:reason", ()),
    ]
    assert len({make_layer(nodata=value).nodata for value in values}) == 3


def test_local_mask_self_reference_rejected_without_target_lookup():
    with pytest.raises(ValueError, match="owning layer"):
        make_layer(nodata=known(NoDataSpec(NoDataKind.MASK, None, "synthetic:layer")))
    # No Product collection is passed; target existence and cycles are downstream.


@pytest.mark.parametrize(
    "dimensions", [(), ("synthetic:a",), ("synthetic:z", "synthetic:a")]
)
def test_dimensions_preserve_order_including_empty(dimensions):
    assert make_layer(dimensions=dimensions).dimensions == dimensions


def test_dimensions_defensively_copy_list_and_accept_iterable():
    dimensions = ["synthetic:z", "synthetic:a"]
    layer = make_layer(dimensions=dimensions)
    dimensions.append("synthetic:b")
    assert layer.dimensions == ("synthetic:z", "synthetic:a")
    assert isinstance(layer.dimensions, tuple)
    assert make_layer(dimensions=iter(dimensions)).dimensions == tuple(dimensions)
    assert layer != replace(layer, dimensions=tuple(reversed(layer.dimensions)))


@pytest.mark.parametrize(
    "dimensions", [("synthetic:a", "synthetic:a"), ("bad id",), ("",), ("bad\u200bid",)]
)
def test_dimensions_reject_duplicate_and_invalid_identifiers(dimensions):
    with pytest.raises(ValueError):
        make_layer(dimensions=dimensions)


@pytest.mark.parametrize("dimensions", [(7,), (None,), (True,), None])
def test_dimensions_reject_non_strings_or_non_iterable(dimensions):
    with pytest.raises(TypeError):
        make_layer(dimensions=dimensions)


def test_datalayer_is_frozen():
    layer = make_layer(dimensions=["synthetic:a"])
    for field in fields(layer):
        with pytest.raises(FrozenInstanceError):
            setattr(layer, field.name, None)
    assert layer == make_layer(dimensions=("synthetic:a",))
    assert hash(layer) == hash(make_layer(dimensions=("synthetic:a",)))


def test_import_boundary_has_no_downstream_or_io_dependencies():
    allowed = {
        "__future__",
        "dataclasses",
        "insarforge.contracts.values",
        "insarforge.products.semantics",
        "insarforge.products.nodata",
    }
    for node in ast.walk(ast.parse(inspect.getsource(layers))):
        if isinstance(node, ast.Import):
            assert all(alias.name in allowed for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0 and node.module in allowed
            if node.module == "insarforge.contracts.values":
                assert [alias.name for alias in node.names] == ["validate_identifier"]
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id not in {"open", "eval", "exec", "__import__"}
