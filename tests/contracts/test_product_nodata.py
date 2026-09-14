"""ADR 0007 NoData cases using synthetic values, without layer migration."""

import ast
import inspect
from dataclasses import FrozenInstanceError, fields
from enum import Enum

import pytest

from insarforge.products import nodata
from insarforge.products.nodata import NoDataKind, NoDataSpec


def test_enum_has_exact_members_and_stable_values():
    assert {name: member.value for name, member in NoDataKind.__members__.items()} == {
        "NONE": "none",
        "FINITE_VALUE": "finite_value",
        "NAN": "nan",
        "MASK": "mask",
    }
    assert len(NoDataKind) == 4
    assert not hasattr(NoDataKind, "UNKNOWN")
    assert not hasattr(NoDataKind, "NOT_APPLICABLE")


def test_public_fields_are_exact():
    assert [field.name for field in fields(NoDataSpec)] == [
        "kind",
        "value",
        "mask_layer_ref",
    ]
    assert not hasattr(NoDataSpec(NoDataKind.NONE, None, None), "extensions")


@pytest.mark.parametrize("kind", [None, "none", 0, True, Enum("Other", "NONE").NONE])
def test_kind_requires_nodata_enum(kind):
    with pytest.raises(TypeError, match="kind"):
        NoDataSpec(kind, None, None)


def test_none_explicitly_represents_known_no_nodata():
    spec = NoDataSpec(NoDataKind.NONE, None, None)
    assert spec.kind is NoDataKind.NONE
    assert spec.value is None
    assert spec.mask_layer_ref is None


@pytest.mark.parametrize("value", [0, 2.5, float("nan")])
def test_none_rejects_values(value):
    with pytest.raises(ValueError, match="value"):
        NoDataSpec(NoDataKind.NONE, value, None)


@pytest.mark.parametrize("value", [0, 7, -7, 0.0, 2.5, -2.5, 10**400])
def test_finite_values_preserve_numeric_type(value):
    spec = NoDataSpec(NoDataKind.FINITE_VALUE, value, None)
    assert spec.value == value
    assert type(spec.value) is type(value)
    assert spec.mask_layer_ref is None


@pytest.mark.parametrize("value", [None, True, False, "7", [], {}, 1j])
def test_finite_value_rejects_missing_bool_and_non_numeric_types(value):
    with pytest.raises(TypeError, match="int or float"):
        NoDataSpec(NoDataKind.FINITE_VALUE, value, None)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_finite_value_rejects_nonfinite_floats(value):
    with pytest.raises(ValueError, match="finite"):
        NoDataSpec(NoDataKind.FINITE_VALUE, value, None)


def test_nan_is_a_discriminator_without_a_nonfinite_payload():
    spec = NoDataSpec(NoDataKind.NAN, None, None)
    assert spec.kind is NoDataKind.NAN
    assert spec.value is None
    assert spec.mask_layer_ref is None
    assert not any(
        isinstance(getattr(spec, field.name), float) for field in fields(spec)
    )
    assert spec != NoDataSpec(NoDataKind.NONE, None, None)


@pytest.mark.parametrize("value", [float("nan"), 0, 2.5, float("inf"), "nan"])
def test_nan_rejects_actual_nan_and_other_payloads(value):
    with pytest.raises(ValueError, match="value"):
        NoDataSpec(NoDataKind.NAN, value, None)


@pytest.mark.parametrize(
    "kind,value",
    [(NoDataKind.NONE, None), (NoDataKind.NAN, None), (NoDataKind.FINITE_VALUE, 7)],
)
@pytest.mark.parametrize("mask_layer_ref", ["synthetic:mask", 7])
def test_non_mask_kinds_reject_mask_references(kind, value, mask_layer_ref):
    with pytest.raises(ValueError, match="mask_layer_ref"):
        NoDataSpec(kind, value, mask_layer_ref)


@pytest.mark.parametrize(
    "mask_layer_ref", ["synthetic:mask", "synthetic:é", "synthetic:e\u0301"]
)
def test_mask_preserves_valid_identifier_without_normalization(mask_layer_ref):
    # Self-reference and target resolution are deferred to structural validation.
    spec = NoDataSpec(NoDataKind.MASK, None, mask_layer_ref)
    assert spec.mask_layer_ref == mask_layer_ref
    assert spec.value is None


@pytest.mark.parametrize(
    "mask_layer_ref",
    [
        None,
        "",
        " ",
        " synthetic:mask",
        "synthetic:mask ",
        "synthetic mask",
        "synthetic\tmask",
        "synthetic\x00mask",
        "synthetic\u200bmask",
    ],
)
def test_mask_rejects_missing_or_invalid_identifiers(mask_layer_ref):
    with pytest.raises(ValueError):
        NoDataSpec(NoDataKind.MASK, None, mask_layer_ref)


@pytest.mark.parametrize("mask_layer_ref", [7, False, [], b"synthetic:mask"])
def test_mask_rejects_non_string_identifiers(mask_layer_ref):
    with pytest.raises(TypeError, match="identifier"):
        NoDataSpec(NoDataKind.MASK, None, mask_layer_ref)


@pytest.mark.parametrize("value", [0, 2.5, float("nan"), True])
def test_mask_rejects_non_none_values(value):
    with pytest.raises(ValueError, match="value"):
        NoDataSpec(NoDataKind.MASK, value, "synthetic:mask")


@pytest.mark.parametrize(
    "spec",
    [
        NoDataSpec(NoDataKind.NONE, None, None),
        NoDataSpec(NoDataKind.FINITE_VALUE, 7, None),
        NoDataSpec(NoDataKind.NAN, None, None),
        NoDataSpec(NoDataKind.MASK, None, "synthetic:mask"),
    ],
)
def test_specs_are_frozen_with_natural_equality_and_hashing(spec):
    same = NoDataSpec(spec.kind, spec.value, spec.mask_layer_ref)
    assert same == spec
    assert hash(same) == hash(spec)
    assert len({same, spec}) == 1
    for field in fields(spec):
        assert not isinstance(getattr(spec, field.name), (list, dict, set))
        with pytest.raises(FrozenInstanceError):
            setattr(spec, field.name, None)


def test_module_imports_only_standard_library_and_identifier_support():
    tree = ast.parse(inspect.getsource(nodata))
    allowed = {"math", "dataclasses", "enum", "insarforge.contracts.values"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert all(alias.name in allowed for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0
            assert node.module in allowed
            if node.module == "insarforge.contracts.values":
                assert [alias.name for alias in node.names] == ["validate_identifier"]
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id not in {"__import__", "open", "eval", "exec"}
