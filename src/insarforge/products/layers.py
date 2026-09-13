from __future__ import annotations

from dataclasses import dataclass

from insarforge.contracts.values import FrozenJSON, freeze_json, validate_identifier
from insarforge.products.semantics import (
    SemanticStatus,
    SemanticValue,
    SignSpec,
    UnitSpec,
)


@dataclass(frozen=True)
class LayerSelector:
    selector_kind: str
    parameters: FrozenJSON

    def __post_init__(self):
        validate_identifier(self.selector_kind)
        object.__setattr__(self, "parameters", freeze_json(self.parameters))


@dataclass(frozen=True)
class DataLayer:
    layer_id: str
    role: str
    asset_id: str
    selector: LayerSelector
    quantity_kind: SemanticValue[str]
    unit: SemanticValue[UnitSpec]
    sign: SemanticValue[SignSpec]
    geometry_ref: SemanticValue[str]
    extensions: FrozenJSON

    def __post_init__(self):
        for x in (self.layer_id, self.role, self.asset_id):
            validate_identifier(x)
        if not isinstance(self.selector, LayerSelector):
            raise TypeError("selector")
        for value, typ, name, identifier in (
            (self.quantity_kind, str, "quantity_kind", True),
            (self.unit, UnitSpec, "unit", False),
            (self.sign, SignSpec, "sign", False),
            (self.geometry_ref, str, "geometry_ref", True),
        ):
            if not isinstance(value, SemanticValue):
                raise TypeError(name)
            if value.status is SemanticStatus.KNOWN:
                if not isinstance(value.value, typ):
                    raise TypeError(name)
                if identifier:
                    validate_identifier(value.value)
        object.__setattr__(self, "extensions", freeze_json(self.extensions))
