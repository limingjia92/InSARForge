from collections import UserDict, UserList
from collections.abc import Mapping, MutableSet
from dataclasses import dataclass
from types import MappingProxyType

import pytest

from insarforge.contracts.values import ArtifactRef, freeze_json
from insarforge.products import semantics
from insarforge.products.grid import GridDefinition
from insarforge.products.nodata import NoDataKind, NoDataSpec
from insarforge.products.semantics import (
    PhysicalQuantity,
    SemanticStatus,
    SemanticValue,
    SignSpec,
    UnitSpec,
)


class MutableSetExample(MutableSet):
    def __init__(self):
        self.items = set()

    def __contains__(self, value):
        return value in self.items

    def __iter__(self):
        return iter(self.items)

    def __len__(self):
        return len(self.items)

    def add(self, value):
        self.items.add(value)

    def discard(self, value):
        self.items.discard(value)


class ReadOnlyMapping(Mapping):
    def __getitem__(self, key):
        return 1

    def __iter__(self):
        return iter(("x",))

    def __len__(self):
        return 1


class MutableObject:
    def __init__(self):
        self.items = []


@dataclass(frozen=True)
class ExternalFrozen:
    value: object


class ExternalUnit(UnitSpec):
    pass


def test_semantics():
    r = ArtifactRef("r", "s", 1, None, "m", "l")
    assert [x.value for x in SemanticStatus] == ["known", "unknown", "not_applicable"]
    assert SemanticValue(SemanticStatus.KNOWN, 1, None, [r]).evidence_refs == (r,)
    for s, v, reason in [
        (SemanticStatus.KNOWN, None, None),
        (SemanticStatus.UNKNOWN, 1, "x"),
        (SemanticStatus.UNKNOWN, None, None),
        (SemanticStatus.NOT_APPLICABLE, None, None),
    ]:
        with pytest.raises(ValueError):
            SemanticValue(s, v, reason, [])
    u = UnitSpec("test:unit", "length", None)
    assert PhysicalQuantity(2, u, None, []).value == 2.0
    assert (
        SignSpec(
            "convention:test", "observable:test", "direction:a", "m1", "s1", [r]
        ).minuend_ref
        == "m1"
    )
    for x in (True, float("nan"), float("inf")):
        with pytest.raises((TypeError, ValueError)):
            PhysicalQuantity(x, u, None, [])


def known(value):
    return SemanticValue(SemanticStatus.KNOWN, value, None, ())


@pytest.mark.parametrize("value", ["synthetic", True, 7, 1.25])
def test_safe_scalars(value):
    assert known(value).value is value


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
@pytest.mark.parametrize(
    "wrap", [lambda x: x, lambda x: ("a", (x,)), lambda x: MappingProxyType({"x": x})]
)
def test_nonfinite_rejected(value, wrap):
    with pytest.raises(ValueError, match="finite"):
        known(wrap(value))


@pytest.mark.parametrize(
    "value", [[], {}, set(), bytearray(), UserDict(), UserList(), MutableSetExample()]
)
@pytest.mark.parametrize(
    "wrap", [lambda x: x, lambda x: ("a", x), lambda x: MappingProxyType({"x": x})]
)
def test_mutable_nodes_rejected(value, wrap):
    with pytest.raises(TypeError, match="mutable"):
        known(wrap(value))


@pytest.mark.parametrize(
    "value", [(), ("b", "a", "b", 1, True), ("a", (None, 1.25, ("b", "b")))]
)
def test_recursive_safe_tuple_preserves_type_order_duplicates(value):
    result = known(value).value
    assert type(result) is tuple
    assert result == value


@pytest.mark.parametrize(
    "value", [{"a": 1}, {"x": [{"y": [None, True, 1.5]}, 2]}, [1, {"a": [2, 2]}]]
)
def test_canonical_frozenjson_accepted(value):
    frozen = freeze_json(value)
    result = known(frozen).value
    assert result == frozen
    assert result is not frozen


def test_caller_backed_mapping_is_independently_owned():
    source = {"a": 1}
    view = MappingProxyType(source)
    semantic = known(view)
    source["a"] = 2
    assert semantic.value == {"a": 1}
    assert semantic.value is not view
    with pytest.raises(TypeError):
        semantic.value["a"] = 3


def test_nested_views_in_mixed_tuples_are_independently_owned():
    source = {"a": 1}
    view = MappingProxyType(source)
    outer = {"nested": (view, None)}
    unit = UnitSpec("synthetic:unit", "synthetic:quantity", None)
    semantic = known((unit, (view, MappingProxyType(outer)), view))
    source["a"] = 999
    outer.clear()
    assert semantic.value == (unit, ({"a": 1}, {"nested": ({"a": 1}, None)}), {"a": 1})
    assert semantic.value[0] is unit
    assert type(semantic.value) is tuple
    assert type(semantic.value[1]) is tuple


def test_validation_precedes_any_snapshot(monkeypatch):
    calls = []
    original = semantics.freeze_json

    def snapshot(value):
        calls.append(value)
        return original(value)

    monkeypatch.setattr(semantics, "freeze_json", snapshot)
    source = {"x": [1, 2]}
    view = MappingProxyType(source)
    with pytest.raises(TypeError):
        known(view)
    # An earlier valid mapping must not be snapshotted before a later failure.
    with pytest.raises(TypeError):
        known((MappingProxyType({"safe": 1}), view))
    assert calls == []
    canonical = freeze_json(source)
    assert known(canonical).value == {"x": (1, 2)}
    assert len(calls) == 1


@pytest.mark.parametrize(
    "value",
    [
        MappingProxyType({1: "bad"}),
        MappingProxyType({"x": UnitSpec("u", "q", None)}),
        MappingProxyType({"x": SemanticStatus.KNOWN}),
        frozenset({1}),
        iter((1,)),
        ReadOnlyMapping(),
    ],
)
def test_unsupported_structured_domains(value):
    with pytest.raises(TypeError):
        known(value)


@pytest.mark.parametrize(
    "value",
    [
        SemanticStatus.KNOWN,
        UnitSpec("u", "q", None),
        SignSpec("c", "o", "d", None, None, ()),
        ArtifactRef("r", "s", 1, None, "m", "l"),
        NoDataSpec(NoDataKind.NAN, None, None),
        GridDefinition("synthetic:grid", {"x": [1]}),
        PhysicalQuantity(1, UnitSpec("u", "q", None), None, ()),
    ],
)
def test_typed_contracts_and_enum_preserved(value):
    assert known(value).value is value
    assert known((value, value)).value == (value, value)


@pytest.mark.parametrize(
    "value",
    [
        object(),
        MutableObject(),
        ExternalFrozen(1),
        ExternalFrozen([1, 2]),
        ExternalUnit("u", "q", None),
    ],
)
def test_external_objects_not_accepted_by_frozen_appearance(value):
    with pytest.raises(TypeError):
        known(value)


def test_evidence_defensive_ownership_order_and_duplicates():
    a = ArtifactRef("a", "s", 1, None, "m", "never-open:a")
    b = ArtifactRef("b", "s", 1, None, "m", "never-open:b")
    refs = [b, a, b]
    semantic = SemanticValue(SemanticStatus.KNOWN, 1, None, refs)
    refs.clear()
    refs.append(a)
    assert type(semantic.evidence_refs) is tuple
    assert semantic.evidence_refs == (b, a, b)


def test_invalid_evidence_element():
    with pytest.raises(TypeError, match="evidence_refs"):
        SemanticValue(SemanticStatus.KNOWN, 1, None, ["not-an-artifact"])


@pytest.mark.parametrize("status", list(SemanticStatus))
@pytest.mark.parametrize("reason", ["", " padded", 1, {}])
def test_reason_rules_unchanged(status, reason):
    with pytest.raises(ValueError, match="reason_code"):
        SemanticValue(status, 1 if status is SemanticStatus.KNOWN else None, reason, ())


@pytest.mark.parametrize(
    "status", [SemanticStatus.UNKNOWN, SemanticStatus.NOT_APPLICABLE]
)
def test_absent_status_rules_unchanged(status):
    assert SemanticValue(status, None, "synthetic:reason", ()).value is None
    with pytest.raises(ValueError, match="value must be None"):
        SemanticValue(status, (), "synthetic:reason", ())


def test_invalid_status_type():
    with pytest.raises(TypeError, match="status"):
        SemanticValue("known", 1, None, ())
