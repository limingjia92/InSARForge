from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Protocol

from insarforge.contracts.context import ExecutionContext
from insarforge.contracts.identity import PluginDescriptor
from insarforge.contracts.records import (
    AcquisitionMetadata,
    CatalogSnapshot,
    CorrectionSpec,
    QCReport,
)
from insarforge.contracts.values import (
    ArtifactRef,
    FrozenJSON,
    freeze_json,
    validate_identifier,
)
from insarforge.products.models import Product, ProductDraft


@dataclass(frozen=True)
class ProductInput:
    """Already resolved Product and its reference; local type/schema checks only.

    The handler constructs this pair explicitly. No loading, asset validation,
    locator access or operation-side dependency belongs to this value.
    """

    artifact: ArtifactRef
    value: Product

    def __post_init__(self) -> None:
        if type(self.artifact) is not ArtifactRef:
            raise TypeError("artifact must be an exact ArtifactRef")
        if type(self.value) is not Product:
            raise TypeError("value must be an exact Product")
        if (
            self.artifact.schema_id != self.value.schema_id
            or self.artifact.schema_version != self.value.schema_version
        ):
            raise ValueError("artifact and Product schema must agree")


def _freeze_product_port_map(
    value: Mapping[str, Iterable[ProductInput]],
) -> Mapping[str, tuple[ProductInput, ...]]:
    if not isinstance(value, Mapping):
        raise TypeError("Product input port map must be a mapping")
    frozen = {}
    for key, members in value.items():
        if type(key) is not str:
            raise TypeError("Product input port name must be an exact str")
        validate_identifier(key)
        if isinstance(members, (str, bytes)):
            raise TypeError("Product inputs must be an iterable of ProductInput")
        inputs = tuple(members)
        if any(type(member) is not ProductInput for member in inputs):
            raise TypeError("Product inputs must contain exact ProductInput values")
        frozen[key] = inputs
    return MappingProxyType(frozen)


def _freeze_artifact_refs(value: Iterable[ArtifactRef]) -> tuple[ArtifactRef, ...]:
    if isinstance(value, (str, bytes)):
        raise TypeError("artifact refs must be an iterable of ArtifactRef")
    refs = tuple(value)
    if any(not isinstance(ref, ArtifactRef) for ref in refs):
        raise TypeError("artifact refs must contain ArtifactRef values")
    return refs


def _freeze_artifact_port_map(value: Mapping[str, Iterable[ArtifactRef]]):
    if not isinstance(value, Mapping):
        raise TypeError("artifact port map must be a mapping")
    frozen = {}
    for key, refs in value.items():
        validate_identifier(key)
        frozen[key] = _freeze_artifact_refs(refs)
    return MappingProxyType(frozen)


@dataclass(frozen=True)
class InspectionRequest:
    source: ProductInput
    parameters: FrozenJSON

    def __post_init__(self) -> None:
        if type(self.source) is not ProductInput:
            raise TypeError("source must be an exact ProductInput")
        object.__setattr__(self, "parameters", freeze_json(self.parameters))


@dataclass(frozen=True)
class SearchRequest:
    query_schema_id: str
    query_schema_version: int
    selectors: FrozenJSON

    def __post_init__(self) -> None:
        validate_identifier(self.query_schema_id)
        if isinstance(self.query_schema_version, bool) or not isinstance(
            self.query_schema_version, int
        ):
            raise TypeError("query_schema_version must be an int")
        if self.query_schema_version < 1:
            raise ValueError("query_schema_version must be >= 1")
        object.__setattr__(self, "selectors", freeze_json(self.selectors))


@dataclass(frozen=True)
class AcquireRequest:
    catalog_ref: ArtifactRef
    entry_id: str
    parameters: FrozenJSON

    def __post_init__(self) -> None:
        if not isinstance(self.catalog_ref, ArtifactRef):
            raise TypeError("catalog_ref must be an ArtifactRef")
        validate_identifier(self.entry_id)
        object.__setattr__(self, "parameters", freeze_json(self.parameters))


def _version(value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("version must be an int")
    if value < 1:
        raise ValueError("version must be >= 1")


@dataclass(frozen=True)
class ProcessingRequest:
    purpose: str
    profile_id: str
    profile_version: int
    product_inputs: Mapping[str, tuple[ProductInput, ...]]
    acquisition_metadata_refs: tuple[ArtifactRef, ...]
    auxiliary_inputs: Mapping[str, tuple[ArtifactRef, ...]]
    parameters: FrozenJSON

    def __post_init__(self) -> None:
        validate_identifier(self.purpose)
        validate_identifier(self.profile_id)
        _version(self.profile_version)
        object.__setattr__(
            self, "product_inputs", _freeze_product_port_map(self.product_inputs)
        )
        object.__setattr__(
            self,
            "acquisition_metadata_refs",
            _freeze_artifact_refs(self.acquisition_metadata_refs),
        )
        object.__setattr__(
            self, "auxiliary_inputs", _freeze_artifact_port_map(self.auxiliary_inputs)
        )
        object.__setattr__(self, "parameters", freeze_json(self.parameters))


@dataclass(frozen=True)
class CorrectionRequest:
    source_inputs: Mapping[str, tuple[ProductInput, ...]]
    external_inputs: Mapping[str, tuple[ArtifactRef, ...]]
    spec: CorrectionSpec
    parameters: FrozenJSON

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "source_inputs", _freeze_product_port_map(self.source_inputs)
        )
        object.__setattr__(
            self, "external_inputs", _freeze_artifact_port_map(self.external_inputs)
        )
        if not isinstance(self.spec, CorrectionSpec):
            raise TypeError("spec must be a CorrectionSpec")
        object.__setattr__(self, "parameters", freeze_json(self.parameters))


@dataclass(frozen=True)
class AnalysisRequest:
    product_inputs: Mapping[str, tuple[ProductInput, ...]]
    auxiliary_inputs: Mapping[str, tuple[ArtifactRef, ...]]
    profile_id: str
    profile_version: int
    parameters: FrozenJSON

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "product_inputs", _freeze_product_port_map(self.product_inputs)
        )
        object.__setattr__(
            self, "auxiliary_inputs", _freeze_artifact_port_map(self.auxiliary_inputs)
        )
        validate_identifier(self.profile_id)
        _version(self.profile_version)
        object.__setattr__(self, "parameters", freeze_json(self.parameters))


@dataclass(frozen=True)
class QCRequest:
    target_refs: tuple[ArtifactRef, ...]
    metric_profile_id: str
    metric_profile_version: int
    thresholds: FrozenJSON
    comparison_refs: tuple[ArtifactRef, ...]
    parameters: FrozenJSON

    def __post_init__(self) -> None:
        object.__setattr__(self, "target_refs", _freeze_artifact_refs(self.target_refs))
        validate_identifier(self.metric_profile_id)
        _version(self.metric_profile_version)
        object.__setattr__(self, "thresholds", freeze_json(self.thresholds))
        object.__setattr__(
            self, "comparison_refs", _freeze_artifact_refs(self.comparison_refs)
        )
        object.__setattr__(self, "parameters", freeze_json(self.parameters))


class Mission(Protocol):
    @property
    def descriptor(self) -> PluginDescriptor: ...

    def inspect(
        self, request: InspectionRequest, context: ExecutionContext
    ) -> AcquisitionMetadata: ...


class Provider(Protocol):
    @property
    def descriptor(self) -> PluginDescriptor: ...

    def search(
        self, request: SearchRequest, context: ExecutionContext
    ) -> CatalogSnapshot: ...

    def acquire(
        self, request: AcquireRequest, context: ExecutionContext
    ) -> ProductDraft: ...


class Processor(Protocol):
    @property
    def descriptor(self) -> PluginDescriptor: ...

    def process(
        self, request: ProcessingRequest, context: ExecutionContext
    ) -> tuple[ProductDraft, ...]: ...


class Correction(Protocol):
    @property
    def descriptor(self) -> PluginDescriptor: ...

    def correct(
        self, request: CorrectionRequest, context: ExecutionContext
    ) -> tuple[ProductDraft, ...]: ...


class Analyzer(Protocol):
    @property
    def descriptor(self) -> PluginDescriptor: ...

    def analyze(
        self, request: AnalysisRequest, context: ExecutionContext
    ) -> tuple[ProductDraft, ...]: ...


class QC(Protocol):
    @property
    def descriptor(self) -> PluginDescriptor: ...

    def assess(self, request: QCRequest, context: ExecutionContext) -> QCReport: ...
