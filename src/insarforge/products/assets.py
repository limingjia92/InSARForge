from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from insarforge.contracts.values import FrozenJSON, freeze_json, validate_identifier


class AssetKind(Enum):
    FILE = "file"
    DIRECTORY = "directory"


class AssetLocationKind(Enum):
    MANIFEST_RELATIVE = "manifest_relative"
    ABSOLUTE_LOCAL = "absolute_local"
    REMOTE_REFERENCE = "remote_reference"


@dataclass(frozen=True)
class AssetLocation:
    kind: AssetLocationKind
    value: str
    anchor: Path | None

    def __post_init__(self):
        if not isinstance(self.kind, AssetLocationKind):
            raise TypeError("kind")
        if (
            not isinstance(self.value, str)
            or not self.value
            or self.value != self.value.strip()
        ):
            raise ValueError("value")
        if any(c in self.value for c in "\x00\r\n\t") or re.search(
            r"(^|/)(?:~|\$\{?[^/]+\}?)", self.value
        ):
            raise ValueError("value")
        if self.kind is AssetLocationKind.MANIFEST_RELATIVE:
            if (
                Path(self.value).is_absolute()
                or not isinstance(self.anchor, Path)
                or not self.anchor.is_absolute()
                or any(p == ".." for p in Path(self.value).parts)
            ):
                raise ValueError("anchor")
        elif self.kind is AssetLocationKind.ABSOLUTE_LOCAL:
            path = Path(self.value)
            if not path.is_absolute() or self.anchor is not None:
                raise ValueError("anchor")
        else:
            if self.anchor is not None:
                raise ValueError("anchor")
            p = urlparse(self.value)
            bad = {
                "token",
                "access_token",
                "auth",
                "authorization",
                "credential",
                "credentials",
                "signature",
                "sig",
                "x-amz-signature",
                "x-amz-credential",
                "x-amz-security-token",
                "x-goog-signature",
                "x-goog-credential",
                "x-amz-algorithm",
                "x-amz-date",
                "x-amz-expires",
            }
            if (
                not p.scheme
                or p.username
                or p.password
                or any(k.lower() in bad for k in parse_qs(p.query))
            ):
                raise ValueError("uri")


@dataclass(frozen=True)
class NativeAsset:
    asset_id: str
    role: str
    kind: AssetKind
    location: AssetLocation
    media_type: str | None
    size_bytes: int | None
    checksum_algorithm: str | None
    checksum: str | None
    extensions: FrozenJSON

    def __post_init__(self):
        validate_identifier(self.asset_id)
        validate_identifier(self.role)
        if not isinstance(self.kind, AssetKind):
            raise TypeError("kind")
        if not isinstance(self.location, AssetLocation):
            raise TypeError("location")
        if self.media_type is not None and (
            not isinstance(self.media_type, str)
            or not self.media_type
            or self.media_type != self.media_type.strip()
        ):
            raise ValueError("media_type")
        if self.size_bytes is not None and (
            isinstance(self.size_bytes, bool)
            or not isinstance(self.size_bytes, int)
            or self.size_bytes < 0
        ):
            raise ValueError("size_bytes")
        if (self.checksum_algorithm is None) != (self.checksum is None):
            raise ValueError("checksum pair")
        for name, value in (
            ("checksum_algorithm", self.checksum_algorithm),
            ("checksum", self.checksum),
        ):
            if value is not None and (not value or value != value.strip()):
                raise ValueError(name)
        object.__setattr__(self, "extensions", freeze_json(self.extensions))
