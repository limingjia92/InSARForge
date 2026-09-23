from __future__ import annotations

import math
from collections.abc import MutableMapping, MutableSequence, MutableSet
from dataclasses import dataclass, is_dataclass
from enum import Enum
from types import MappingProxyType
from typing import Generic, TypeVar

from insarforge.contracts.values import ArtifactRef, freeze_json, validate_identifier


class SemanticStatus(Enum):
    KNOWN = "known"
    UNKNOWN = "unknown"
    NOT_APPLICABLE = "not_applicable"


T = TypeVar("T")


def _reason(x):
    if x is not None and (not isinstance(x, str) or not x or x != x.strip()):
        raise ValueError("reason_code")


def _validate_payload(value, *, json_only=False):
    """Validate ownership domain completely, without converting any input.

    Only the existing immutable value-contract modules qualify compositionally;
    frozen external dataclasses and arbitrary Mapping facades do not qualify.
    Within a JSON object, members must also belong to the FrozenJSON language.
    """
    # Enum membership cannot establish deep ownership, even for scalar mixins.
    if isinstance(value, Enum):
        raise TypeError("unsupported semantic payload: Enum")
    if isinstance(value, (MutableMapping, MutableSequence, MutableSet, bytearray)):
        raise TypeError("mutable semantic payload")
    if value is None or type(value) in (str, bool, int):
        return
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError("semantic payload float must be finite")
        return
    if isinstance(value, tuple):
        for item in value:
            _validate_payload(item, json_only=json_only)
        return
    if isinstance(value, MappingProxyType):
        for key, item in value.items():
            if isinstance(key, Enum):
                raise TypeError("unsupported semantic payload: Enum")
            if type(key) is not str:
                raise TypeError("mapping keys must be strings")
            _validate_payload(item, json_only=True)
        return
    if not json_only:
        cls = type(value)
        if (
            cls.__module__
            in {
                "insarforge.contracts.values",
                "insarforge.contracts.identity",
                "insarforge.products.semantics",
                "insarforge.products.nodata",
                "insarforge.products.grid",
            }
            and is_dataclass(value)
            and cls.__dataclass_params__.frozen
        ):
            # These contracts own their nested state; do not reconstruct them.
            return
    raise TypeError(f"unsupported semantic payload: {type(value).__name__}")


def _snapshot_payload(value):
    """Own validated JSON views, preserving tuple and typed member semantics."""
    if isinstance(value, MappingProxyType):
        return freeze_json(value)
    if isinstance(value, tuple):
        return tuple(_snapshot_payload(item) for item in value)
    return value


@dataclass(frozen=True)
class SemanticValue(Generic[T]):
    status: SemanticStatus
    value: T | None
    reason_code: str | None
    evidence_refs: tuple[ArtifactRef, ...]

    def __post_init__(self):
        if not isinstance(self.status, SemanticStatus):
            raise TypeError("status")
        if self.status is SemanticStatus.KNOWN:
            if self.value is None:
                raise ValueError("known value required")
            _reason(self.reason_code)
        else:
            if self.value is not None:
                raise ValueError("value must be None")
            if self.reason_code is None:
                raise ValueError("reason required")
            _reason(self.reason_code)
        ev = tuple(self.evidence_refs)
        if any(not isinstance(x, ArtifactRef) for x in ev):
            raise TypeError("evidence_refs")
        if self.status is SemanticStatus.KNOWN:
            # R1: validate the ENTIRE candidate before creating any snapshot.
            _validate_payload(self.value)
            object.__setattr__(self, "value", _snapshot_payload(self.value))
        object.__setattr__(self, "evidence_refs", ev)


@dataclass(frozen=True)
class UnitSpec:
    unit_id: str
    quantity_kind: str
    definition_ref: str | None

    def __post_init__(self):
        validate_identifier(self.unit_id)
        validate_identifier(self.quantity_kind)
        if self.definition_ref is not None and (
            not isinstance(self.definition_ref, str)
            or not self.definition_ref
            or self.definition_ref != self.definition_ref.strip()
        ):
            raise ValueError("definition_ref")


@dataclass(frozen=True)
class SignSpec:
    convention_id: str
    observable: str
    positive_direction: str
    minuend_ref: str | None
    subtrahend_ref: str | None
    evidence_refs: tuple[ArtifactRef, ...]

    def __post_init__(self):
        for x in (self.convention_id, self.observable, self.positive_direction):
            validate_identifier(x)
        for x in (self.minuend_ref, self.subtrahend_ref):
            if x is not None:
                validate_identifier(x)
        ev = tuple(self.evidence_refs)
        if any(not isinstance(x, ArtifactRef) for x in ev):
            raise TypeError("evidence_refs")
        object.__setattr__(self, "evidence_refs", ev)


@dataclass(frozen=True)
class PhysicalQuantity:
    value: float
    unit: UnitSpec
    source_ref: ArtifactRef | None
    evidence_refs: tuple[ArtifactRef, ...]

    def __post_init__(self):
        if isinstance(self.value, bool) or not isinstance(self.value, (int, float)):
            raise TypeError("value")
        if not math.isfinite(self.value):
            raise ValueError("value must be finite")
        object.__setattr__(self, "value", float(self.value))
        if not isinstance(self.unit, UnitSpec):
            raise TypeError("unit")
        if self.source_ref is not None and not isinstance(self.source_ref, ArtifactRef):
            raise TypeError("source_ref")
        ev = tuple(self.evidence_refs)
        if any(not isinstance(x, ArtifactRef) for x in ev):
            raise TypeError("evidence_refs")
        object.__setattr__(self, "evidence_refs", ev)
