"""NoData representation contracts from ADR 0007, without backend conventions."""

import math
from dataclasses import dataclass
from enum import Enum

from insarforge.contracts.values import validate_identifier


class NoDataKind(Enum):
    NONE = "none"
    FINITE_VALUE = "finite_value"
    NAN = "nan"
    MASK = "mask"


@dataclass(frozen=True)
class NoDataSpec:
    """A known NoData representation; mask resolution belongs to validation."""

    kind: NoDataKind
    value: int | float | None
    mask_layer_ref: str | None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, NoDataKind):
            raise TypeError("kind must be NoDataKind")

        if self.kind is NoDataKind.FINITE_VALUE:
            if isinstance(self.value, bool) or not isinstance(self.value, (int, float)):
                raise TypeError("FINITE_VALUE requires an int or float, excluding bool")
            # Integers are finite without a potentially overflowing float conversion.
            if isinstance(self.value, float) and not math.isfinite(self.value):
                raise ValueError("value must be finite")
        elif self.value is not None:
            raise ValueError("value must be None for this kind")

        if self.kind is NoDataKind.MASK:
            if self.mask_layer_ref is None:
                raise ValueError("MASK requires mask_layer_ref")
            validate_identifier(self.mask_layer_ref)
        elif self.mask_layer_ref is not None:
            raise ValueError("mask_layer_ref must be None for this kind")
