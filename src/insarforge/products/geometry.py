from __future__ import annotations

from dataclasses import dataclass

from insarforge.contracts.values import FrozenJSON, freeze_json, validate_identifier
from insarforge.products.semantics import SemanticStatus, SemanticValue, UnitSpec


@dataclass(frozen=True)
class AxisDescriptor:
    axis_id: str
    role: str
    size: int
    unit: SemanticValue[UnitSpec]
    direction: SemanticValue[str]
    extensions: FrozenJSON

    def __post_init__(self):
        validate_identifier(self.axis_id)
        validate_identifier(self.role)
        if (
            isinstance(self.size, bool)
            or not isinstance(self.size, int)
            or self.size <= 0
        ):
            raise ValueError("size")
        if not isinstance(self.unit, SemanticValue) or not isinstance(
            self.direction, SemanticValue
        ):
            raise TypeError("semantic")
        if self.unit.status is SemanticStatus.KNOWN and not isinstance(
            self.unit.value, UnitSpec
        ):
            raise TypeError("unit")
        if self.direction.status is SemanticStatus.KNOWN:
            if not isinstance(self.direction.value, str):
                raise TypeError("direction")
            validate_identifier(self.direction.value)
        object.__setattr__(self, "extensions", freeze_json(self.extensions))


@dataclass(frozen=True)
class GeometryDescriptor:
    geometry_id: str
    domain_id: str
    shape: tuple[int, ...]
    axes: tuple[AxisDescriptor, ...]
    registration: SemanticValue[str]
    coordinate_reference: SemanticValue[str]
    extensions: FrozenJSON

    def __post_init__(self):
        validate_identifier(self.geometry_id)
        validate_identifier(self.domain_id)
        shape = tuple(self.shape)
        axes = tuple(self.axes)
        if not shape or any(
            isinstance(x, bool) or not isinstance(x, int) or x <= 0 for x in shape
        ):
            raise ValueError("shape")
        if any(not isinstance(x, AxisDescriptor) for x in axes) or len(axes) != len(
            shape
        ):
            raise ValueError("axes")
        if len({x.axis_id for x in axes}) != len(axes) or any(
            x.size != n for x, n in zip(axes, shape)
        ):
            raise ValueError("axes")
        for value, name, identifier in (
            (self.registration, "registration", True),
            (self.coordinate_reference, "coordinate_reference", False),
        ):
            if not isinstance(value, SemanticValue):
                raise TypeError(name)
            if value.status is SemanticStatus.KNOWN:
                if (
                    not isinstance(value.value, str)
                    or not value.value
                    or value.value != value.value.strip()
                ):
                    raise ValueError(name)
                if identifier:
                    validate_identifier(value.value)
        object.__setattr__(self, "shape", shape)
        object.__setattr__(self, "axes", axes)
        object.__setattr__(self, "extensions", freeze_json(self.extensions))
