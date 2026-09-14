import re
import unicodedata
from dataclasses import dataclass

from .assets import AssetIntegrity, AssetKind


@dataclass(frozen=True)
class DirectoryMember:
    path: str
    member_kind: AssetKind
    size_bytes: int | None
    integrity: AssetIntegrity | None

    def __post_init__(self):
        if (
            not isinstance(self.path, str)
            or not self.path
            or self.path != self.path.strip()
            or self.path.startswith("/")
            or "\\" in self.path
            or any(unicodedata.category(c) == "Cc" for c in self.path)
            or "~" in self.path
            or re.search(r"\$\{?[^/]+\}?", self.path)
        ):
            raise ValueError("path")
        parts = self.path.split("/")
        if any(p in ("", ".", "..") for p in parts):
            raise ValueError("path")
        if not isinstance(self.member_kind, AssetKind) or self.member_kind not in (
            AssetKind.FILE,
            AssetKind.DIRECTORY,
        ):
            raise TypeError("member_kind")
        if self.member_kind is AssetKind.DIRECTORY:
            if self.size_bytes is not None or self.integrity is not None:
                raise ValueError("directory metadata")
        else:
            if self.size_bytes is not None and (
                isinstance(self.size_bytes, bool)
                or not isinstance(self.size_bytes, int)
                or self.size_bytes < 0
            ):
                raise ValueError("size_bytes")
            if self.integrity is not None and not isinstance(
                self.integrity, AssetIntegrity
            ):
                raise TypeError("integrity")


@dataclass(frozen=True)
class DirectoryMemberManifest:
    schema_version: int
    members: tuple[DirectoryMember, ...]

    def __post_init__(self):
        if (
            isinstance(self.schema_version, bool)
            or not isinstance(self.schema_version, int)
            or self.schema_version != 1
        ):
            raise ValueError("schema_version")
        ms = tuple(self.members)
        if any(not isinstance(m, DirectoryMember) for m in ms):
            raise TypeError("members")
        if len({m.path for m in ms}) != len(ms):
            raise ValueError("duplicate path")
        object.__setattr__(self, "members", tuple(sorted(ms, key=lambda m: m.path)))
