"""Opaque, immutable grid representation defined by ADR 0009."""

from collections.abc import Mapping
from dataclasses import dataclass

from insarforge.contracts.values import FrozenJSON, freeze_json, validate_identifier


@dataclass(frozen=True)
class GridDefinition:
    """A format identity and its complete, uninterpreted semantic parameters."""

    format_id: str
    parameters: FrozenJSON

    def __post_init__(self) -> None:
        validate_identifier(self.format_id)
        if not isinstance(self.parameters, Mapping):
            raise TypeError("parameters must be a Mapping")
        parameters = freeze_json(self.parameters)
        if not isinstance(parameters, Mapping):
            raise TypeError("frozen parameters must be a Mapping")
        object.__setattr__(self, "parameters", parameters)
