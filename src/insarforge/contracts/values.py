from __future__ import annotations

import math
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import TypeAlias

FrozenJSON: TypeAlias = (
    None
    | bool
    | int
    | float
    | str
    | tuple["FrozenJSON", ...]
    | Mapping[str, "FrozenJSON"]
)


def validate_identifier(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError("identifier must be a string")
    if not value:
        raise ValueError("identifier must not be empty")
    if value != value.strip() or any(
        ch.isspace() or unicodedata.category(ch).startswith("C") for ch in value
    ):
        raise ValueError("identifier contains whitespace or control characters")
    return value


def freeze_json(value) -> FrozenJSON:
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("float must be finite")
        return value
    if isinstance(value, Mapping):
        frozen = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("mapping keys must be strings")
            frozen[key] = freeze_json(item)
        return MappingProxyType(frozen)
    if isinstance(value, (list, tuple)):
        return tuple(freeze_json(item) for item in value)
    raise TypeError(f"unsupported JSON value: {type(value).__name__}")


@dataclass(frozen=True)
class ArtifactRef:
    record_id: str
    schema_id: str
    schema_version: int
    semantic_digest: str | None
    manifest_digest: str
    locator: str

    def __post_init__(self) -> None:
        validate_identifier(self.record_id)
        validate_identifier(self.schema_id)
        if isinstance(self.schema_version, bool) or not isinstance(
            self.schema_version, int
        ):
            raise TypeError("schema_version must be an int")
        if self.schema_version < 1:
            raise ValueError("schema_version must be >= 1")
        for name, value in (
            ("semantic_digest", self.semantic_digest),
            ("manifest_digest", self.manifest_digest),
            ("locator", self.locator),
        ):
            if name == "semantic_digest" and value is None:
                continue
            if not isinstance(value, str):
                raise TypeError(f"{name} must be a string")
            if not value or value != value.strip():
                raise ValueError(f"{name} must be non-empty and trimmed")
