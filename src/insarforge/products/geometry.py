"""Immutable geometry models defined by ADR 0008 and ADR 0009."""

from __future__ import annotations

from dataclasses import dataclass

from insarforge.contracts.values import ArtifactRef, validate_identifier
from insarforge.products.grid import GridDefinition
from insarforge.products.semantics import SemanticStatus, SemanticValue, UnitSpec


@dataclass(frozen=True)
class AxisDescriptor:
    axis_id: str
    role: str
    unit: SemanticValue[UnitSpec]
    direction: SemanticValue[str]

    def __post_init__(self) -> None:
        validate_identifier(self.axis_id)
        validate_identifier(self.role)
        if not isinstance(self.unit, SemanticValue):
            raise TypeError("unit must be a SemanticValue")
        if self.unit.status is SemanticStatus.KNOWN and not isinstance(
            self.unit.value, UnitSpec
        ):
            raise TypeError("unit must contain a UnitSpec when KNOWN")
        if not isinstance(self.direction, SemanticValue):
            raise TypeError("direction must be a SemanticValue")
        if self.direction.status is SemanticStatus.KNOWN:
            validate_identifier(self.direction.value)


@dataclass(frozen=True)
class GeometryDescriptor:
    geometry_id: str
    domain: str
    coordinate_reference: SemanticValue[str]
    axes: tuple[AxisDescriptor, ...]
    shape: tuple[int, ...]
    grid_definition: SemanticValue[GridDefinition]
    registration: SemanticValue[str]
    reference: SemanticValue[ArtifactRef]

    def __post_init__(self) -> None:
        validate_identifier(self.geometry_id)
        validate_identifier(self.domain)
        axes = tuple(self.axes)
        shape = tuple(self.shape)
        if not axes or not shape:
            raise ValueError("axes and shape must be non-empty")
        if any(not isinstance(axis, AxisDescriptor) for axis in axes):
            raise TypeError("axes must contain AxisDescriptor values")
        if len(axes) != len(shape):
            raise ValueError("axes and shape must have the same length")
        if len({axis.axis_id for axis in axes}) != len(axes):
            raise ValueError("axis_id values must be unique")
        for size in shape:
            if isinstance(size, bool) or not isinstance(size, int):
                raise TypeError("shape values must be integers excluding bool")
            if size <= 0:
                raise ValueError("shape values must be positive")
        for value, typ, name in (
            (self.coordinate_reference, str, "coordinate_reference"),
            (self.grid_definition, GridDefinition, "grid_definition"),
            (self.registration, str, "registration"),
            (self.reference, ArtifactRef, "reference"),
        ):
            if not isinstance(value, SemanticValue):
                raise TypeError(f"{name} must be a SemanticValue")
            if value.status is SemanticStatus.KNOWN and not isinstance(
                value.value, typ
            ):
                raise TypeError(f"{name} has the wrong KNOWN payload type")
        if self.coordinate_reference.status is SemanticStatus.KNOWN:
            text = self.coordinate_reference.value
            if not text or text != text.strip():
                raise ValueError("coordinate_reference must be non-empty and trimmed")
        if self.registration.status is SemanticStatus.KNOWN:
            validate_identifier(self.registration.value)
        object.__setattr__(self, "axes", axes)
        object.__setattr__(self, "shape", shape)
