from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType

from insarforge.contracts.identity import PluginKind, PluginRef
from insarforge.contracts.values import (
    ArtifactRef,
    FrozenJSON,
    freeze_json,
    validate_identifier,
)
from insarforge.products.semantics import (
    PhysicalQuantity,
    SemanticStatus,
    SemanticValue,
    SignSpec,
    UnitSpec,
)


class ProviderAvailability(Enum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


class ProviderDelivery(Enum):
    DIRECT = "direct"
    ORDER_REQUIRED = "order_required"
    CATALOG_ONLY = "catalog_only"
    UNKNOWN = "unknown"


class QCStatus(Enum):
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"
    NOT_EVALUATED = "not_evaluated"


def _ver(v):
    if isinstance(v, bool) or not isinstance(v, int):
        raise TypeError("version")
    if v < 1:
        raise ValueError("version")


def _ev(xs):
    x = tuple(xs)
    if any(not isinstance(a, ArtifactRef) for a in x):
        raise TypeError("evidence")
    return x


def _reason(r, req=False):
    if req and (r is None or not isinstance(r, str) or not r or r != r.strip()):
        raise ValueError("reason")
    if r is not None and (not isinstance(r, str) or not r or r != r.strip()):
        raise ValueError("reason")


@dataclass(frozen=True)
class AccessStatus:
    availability: ProviderAvailability
    delivery: ProviderDelivery
    authentication_required: bool | None
    reason_code: str | None

    def __post_init__(self):
        if not isinstance(self.availability, ProviderAvailability) or not isinstance(
            self.delivery, ProviderDelivery
        ):
            raise TypeError("enum")
        if self.authentication_required is not None and not isinstance(
            self.authentication_required, bool
        ):
            raise TypeError("auth")
        _reason(
            self.reason_code, self.availability is not ProviderAvailability.AVAILABLE
        )


@dataclass(frozen=True)
class CatalogEntry:
    entry_id: str
    access: AccessStatus
    attributes: FrozenJSON
    evidence_refs: tuple[ArtifactRef, ...]

    def __post_init__(self):
        validate_identifier(self.entry_id)
        if not isinstance(self.access, AccessStatus):
            raise TypeError("access")
        object.__setattr__(self, "attributes", freeze_json(self.attributes))
        object.__setattr__(self, "evidence_refs", _ev(self.evidence_refs))


@dataclass(frozen=True)
class CatalogSnapshot:
    record_id: str
    schema_id: str
    schema_version: int
    provider: PluginRef
    query_schema_id: str
    query_schema_version: int
    selectors: FrozenJSON
    entries: tuple[CatalogEntry, ...]
    extensions: FrozenJSON

    def __post_init__(self):
        for x in (self.record_id, self.schema_id, self.query_schema_id):
            validate_identifier(x)
        _ver(self.schema_version)
        _ver(self.query_schema_version)
        if (
            not isinstance(self.provider, PluginRef)
            or self.provider.kind is not PluginKind.PROVIDER
        ):
            raise TypeError("provider")
        es = tuple(self.entries)
        if any(not isinstance(e, CatalogEntry) for e in es) or len(
            {e.entry_id for e in es}
        ) != len(es):
            raise ValueError("entries")
        object.__setattr__(self, "selectors", freeze_json(self.selectors))
        object.__setattr__(self, "entries", es)
        object.__setattr__(self, "extensions", freeze_json(self.extensions))


@dataclass(frozen=True)
class AcquisitionMetadata:
    record_id: str
    schema_id: str
    schema_version: int
    source_ref: ArtifactRef
    mission: PluginRef
    attributes: Mapping[str, SemanticValue[FrozenJSON]]
    evidence_refs: tuple[ArtifactRef, ...]
    extensions: FrozenJSON

    def __post_init__(self):
        validate_identifier(self.record_id)
        validate_identifier(self.schema_id)
        _ver(self.schema_version)
        if (
            not isinstance(self.source_ref, ArtifactRef)
            or not isinstance(self.mission, PluginRef)
            or self.mission.kind is not PluginKind.MISSION
        ):
            raise TypeError("refs")
        if not isinstance(self.attributes, Mapping):
            raise TypeError("attributes")
        a = {}
        for k, v in self.attributes.items():
            validate_identifier(k)
            if not isinstance(v, SemanticValue):
                raise TypeError("attribute")
            a[k] = SemanticValue(
                v.status,
                freeze_json(v.value) if v.status is SemanticStatus.KNOWN else None,
                v.reason_code,
                v.evidence_refs,
            )
        object.__setattr__(self, "attributes", MappingProxyType(a))
        object.__setattr__(self, "evidence_refs", _ev(self.evidence_refs))
        object.__setattr__(self, "extensions", freeze_json(self.extensions))


@dataclass(frozen=True)
class QCMetric:
    metric_id: str
    value: SemanticValue[FrozenJSON]
    unit: SemanticValue[UnitSpec]
    details: FrozenJSON

    def __post_init__(self):
        validate_identifier(self.metric_id)
        if not isinstance(self.value, SemanticValue) or not isinstance(
            self.unit, SemanticValue
        ):
            raise TypeError("semantic")
        val = (
            freeze_json(self.value.value)
            if self.value.status is SemanticStatus.KNOWN
            else None
        )
        if self.unit.status is SemanticStatus.KNOWN and not isinstance(
            self.unit.value, UnitSpec
        ):
            raise TypeError("unit")
        object.__setattr__(
            self,
            "value",
            SemanticValue(
                self.value.status, val, self.value.reason_code, self.value.evidence_refs
            ),
        )
        object.__setattr__(self, "details", freeze_json(self.details))


@dataclass(frozen=True)
class QCFinding:
    finding_code: str
    details: FrozenJSON

    def __post_init__(self):
        validate_identifier(self.finding_code)
        object.__setattr__(self, "details", freeze_json(self.details))


@dataclass(frozen=True)
class QCReport:
    record_id: str
    schema_id: str
    schema_version: int
    status: QCStatus
    method_id: str
    method_version: str
    input_refs: tuple[ArtifactRef, ...]
    metrics: tuple[QCMetric, ...]
    findings: tuple[QCFinding, ...]
    extensions: FrozenJSON

    def __post_init__(self):
        for x in (self.record_id, self.schema_id, self.method_id):
            validate_identifier(x)
        _ver(self.schema_version)
        if (
            not isinstance(self.status, QCStatus)
            or not isinstance(self.method_version, str)
            or not self.method_version
            or self.method_version != self.method_version.strip()
        ):
            raise TypeError("status/version")
        ins = tuple(self.input_refs)
        ms = tuple(self.metrics)
        fs = tuple(self.findings)
        if (
            any(not isinstance(x, ArtifactRef) for x in ins)
            or any(not isinstance(x, QCMetric) for x in ms)
            or len({x.metric_id for x in ms}) != len(ms)
            or any(not isinstance(x, QCFinding) for x in fs)
        ):
            raise TypeError("collections")
        object.__setattr__(self, "input_refs", ins)
        object.__setattr__(self, "metrics", ms)
        object.__setattr__(self, "findings", fs)
        object.__setattr__(self, "extensions", freeze_json(self.extensions))


@dataclass(frozen=True)
class CorrectionSpec:
    method_id: str
    input_domain_id: str
    output_domain_id: str
    application_stage_id: str
    operation_mode_id: str
    unit_requirement: SemanticValue[UnitSpec]
    sign_requirement: SemanticValue[SignSpec]
    frequency_requirement: SemanticValue[PhysicalQuantity]
    requirements: FrozenJSON

    def __post_init__(self):
        for x in (
            self.method_id,
            self.input_domain_id,
            self.output_domain_id,
            self.application_stage_id,
            self.operation_mode_id,
        ):
            validate_identifier(x)
        for v, t in (
            (self.unit_requirement, UnitSpec),
            (self.sign_requirement, SignSpec),
            (self.frequency_requirement, PhysicalQuantity),
        ):
            if not isinstance(v, SemanticValue):
                raise TypeError("requirement")
            if v.status is SemanticStatus.KNOWN and not isinstance(v.value, t):
                raise TypeError("payload")
        object.__setattr__(self, "requirements", freeze_json(self.requirements))
