from __future__ import annotations

from dataclasses import dataclass

from insarforge.contracts.values import validate_identifier
from insarforge.products.nodata import NoDataKind, NoDataSpec
from insarforge.products.semantics import (
    SemanticStatus,
    SemanticValue,
    SignSpec,
    UnitSpec,
)


@dataclass(frozen=True)
class LayerSelector:
    format_id: str
    selector_string: str

    def __post_init__(self):
        validate_identifier(self.format_id)
        if not isinstance(self.selector_string, str):
            raise TypeError("selector_string")
        if (
            not self.selector_string
            or self.selector_string != self.selector_string.strip()
        ):
            raise ValueError(
                "selector_string must be non-empty without surrounding whitespace"
            )


@dataclass(frozen=True)
class DataLayer:
    layer_id: str
    role: str
    asset_id: str
    selector: LayerSelector | None
    quantity: SemanticValue[str]
    unit: SemanticValue[UnitSpec]
    sign: SemanticValue[SignSpec]
    geometry_ref: SemanticValue[str]
    nodata: SemanticValue[NoDataSpec]
    dimensions: tuple[str, ...]

    def __post_init__(self):
        for x in (self.layer_id, self.role, self.asset_id):
            validate_identifier(x)
        if self.selector is not None and not isinstance(self.selector, LayerSelector):
            raise TypeError("selector")
        for value, typ, name, identifier in (
            (self.quantity, str, "quantity", True),
            (self.unit, UnitSpec, "unit", False),
            (self.sign, SignSpec, "sign", False),
            (self.geometry_ref, str, "geometry_ref", True),
            (self.nodata, NoDataSpec, "nodata", False),
        ):
            if not isinstance(value, SemanticValue):
                raise TypeError(name)
            if value.status is SemanticStatus.KNOWN:
                if not isinstance(value.value, typ):
                    raise TypeError(name)
                if identifier:
                    validate_identifier(value.value)
        # Only self-reference is local; target existence and cycles are downstream.
        if (
            self.nodata.status is SemanticStatus.KNOWN
            and self.nodata.value.kind is NoDataKind.MASK
            and self.nodata.value.mask_layer_ref == self.layer_id
        ):
            raise ValueError("mask_layer_ref must not reference the owning layer")
        dimensions = tuple(self.dimensions)
        for dimension in dimensions:
            validate_identifier(dimension)
        if len(set(dimensions)) != len(dimensions):
            raise ValueError("dimensions must contain unique identifiers")
        object.__setattr__(self, "dimensions", dimensions)
