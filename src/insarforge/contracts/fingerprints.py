"""Neutral immutable identity outcomes; no filesystem or runtime state."""

import re
from dataclasses import dataclass

from insarforge.contracts.errors import ContractError


def is_digest(value: object) -> bool:
    return type(value) is str and re.fullmatch("[0-9a-f]{64}", value) is not None


@dataclass(frozen=True)
class FingerprintResult:
    value: str | None
    reusable: bool
    reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if type(self.reusable) is not bool or type(self.reasons) not in (list, tuple):
            raise ContractError("IDENTITY_RESULT")
        reasons = tuple(self.reasons)
        if any(
            type(reason) is not str or re.fullmatch("[A-Z][A-Z0-9_]*", reason) is None
            for reason in reasons
        ):
            raise ContractError("IDENTITY_REASON")
        if self.reusable:
            if not is_digest(self.value) or reasons:
                raise ContractError("IDENTITY_RESULT")
        elif self.value is not None or not reasons:
            raise ContractError("IDENTITY_RESULT")
        object.__setattr__(self, "reasons", tuple(sorted(set(reasons))))


def unresolved(code: str) -> FingerprintResult:
    return FingerprintResult(None, False, (code,))
