from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from insarforge.contracts.values import ArtifactRef, validate_identifier


class PluginKind(Enum):
    MISSION = "mission"
    PROVIDER = "provider"
    PROCESSOR = "processor"
    CORRECTION = "correction"
    ANALYZER = "analyzer"
    QC = "qc"


class CapabilityAvailability(Enum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class PluginRef:
    kind: PluginKind
    plugin_id: str
    api_version: int

    def __post_init__(self):
        if not isinstance(self.kind, PluginKind):
            raise TypeError("kind")
        validate_identifier(self.plugin_id)
        if isinstance(self.api_version, bool) or not isinstance(self.api_version, int):
            raise TypeError("api_version")
        if self.api_version < 1:
            raise ValueError("api_version")


@dataclass(frozen=True, order=True)
class CapabilityId:
    value: str

    def __post_init__(self):
        if not isinstance(self.value, str):
            raise TypeError("value")
        if self.value.count(":") != 1:
            raise ValueError("capability")
        a, b = self.value.split(":")
        validate_identifier(a)
        validate_identifier(b)


@dataclass(frozen=True)
class PluginDescriptor:
    kind: PluginKind
    plugin_id: str
    api_version: int
    implementation_version: str
    display_name: str
    capabilities: tuple[CapabilityId, ...]

    def __post_init__(self):
        PluginRef(self.kind, self.plugin_id, self.api_version)
        for n, v in [
            ("implementation_version", self.implementation_version),
            ("display_name", self.display_name),
        ]:
            if not isinstance(v, str):
                raise TypeError(n)
            if not v or v != v.strip():
                raise ValueError(n)
        caps = tuple(self.capabilities)
        if any(not isinstance(c, CapabilityId) for c in caps):
            raise TypeError("capabilities")
        if len(set(caps)) != len(caps):
            raise ValueError("duplicate capabilities")
        object.__setattr__(self, "capabilities", tuple(sorted(caps)))

    @property
    def ref(self) -> PluginRef:
        return PluginRef(self.kind, self.plugin_id, self.api_version)


@dataclass(frozen=True)
class CapabilityCheckResult:
    capability: CapabilityId
    availability: CapabilityAvailability
    reason_code: str | None
    evidence_refs: tuple[ArtifactRef, ...]

    def __post_init__(self):
        if not isinstance(self.capability, CapabilityId) or not isinstance(
            self.availability, CapabilityAvailability
        ):
            raise TypeError("type")
        if self.reason_code is not None and (
            not isinstance(self.reason_code, str)
            or not self.reason_code
            or self.reason_code != self.reason_code.strip()
        ):
            raise ValueError("reason")
        if (
            self.availability is not CapabilityAvailability.AVAILABLE
            and self.reason_code is None
        ):
            raise ValueError("reason required")
        ev = tuple(self.evidence_refs)
        if any(not isinstance(x, ArtifactRef) for x in ev):
            raise TypeError("evidence")
        object.__setattr__(self, "evidence_refs", ev)
