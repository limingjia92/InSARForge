from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from insarforge.contracts._extensions import _freeze_extensions
from insarforge.contracts.identity import PluginRef
from insarforge.contracts.values import (
    ArtifactRef,
    FrozenJSON,
    validate_identifier,
)
from insarforge.products.assets import NativeAsset
from insarforge.products.geometry import GeometryDescriptor
from insarforge.products.layers import DataLayer
from insarforge.products.semantics import (
    SemanticStatus,
    SemanticValue,
    _validate_payload,
)


def _identity_value(value: SemanticValue[str], name: str) -> None:
    """Validate supplied ADR0012 identity availability without resolving it."""
    if not isinstance(value, SemanticValue):
        raise TypeError(name)
    if value.status is SemanticStatus.KNOWN:
        if type(value.value) is not str:
            raise TypeError(name)
        if not value.value or value.value != value.value.strip():
            raise ValueError(name)
    elif value.status is SemanticStatus.UNKNOWN:
        if (
            value.value is not None
            or not isinstance(value.reason_code, str)
            or not value.reason_code
            or value.reason_code != value.reason_code.strip()
        ):
            raise ValueError(name)
    else:
        raise ValueError(name)


@dataclass(frozen=True)
class ProducerRef:
    """Supplied software and execution identities; no registry or runtime lookup."""

    plugin: PluginRef
    implementation_version: str
    implementation_identity_digest: SemanticValue[str]
    execution_identity_digest: SemanticValue[str]

    def __post_init__(self):
        if not isinstance(self.plugin, PluginRef):
            raise TypeError("plugin")
        if type(self.implementation_version) is not str:
            raise TypeError("implementation_version")
        if (
            not self.implementation_version
            or self.implementation_version != self.implementation_version.strip()
        ):
            raise ValueError("implementation_version")
        _identity_value(
            self.implementation_identity_digest, "implementation_identity_digest"
        )
        _identity_value(self.execution_identity_digest, "execution_identity_digest")


@dataclass(frozen=True)
class ProductionRef:
    """Static traceability of an actual production, including weak identity."""

    task_fingerprint: SemanticValue[str]
    output_port: str
    attempt_id: str

    def __post_init__(self):
        _identity_value(self.task_fingerprint, "task_fingerprint")
        validate_identifier(self.output_port)
        validate_identifier(self.attempt_id)


@dataclass(frozen=True)
class LineageEntry:
    """An input role and its unresolved artifact; content identity may be absent."""

    role: str
    artifact: ArtifactRef

    def __post_init__(self):
        if type(self.role) is not str:
            raise TypeError("role")
        validate_identifier(self.role)
        if not isinstance(self.artifact, ArtifactRef):
            raise TypeError("artifact")


def _version(value):
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("version")
    if value < 1:
        raise ValueError("version")


def _tuple(value, typ, name):
    result = tuple(value)
    if any(not isinstance(item, typ) for item in result):
        raise TypeError(name)
    return result


def _unique(items, attr, name):
    if len({getattr(item, attr) for item in items}) != len(items):
        raise ValueError(name)


def _content_collections(assets, geometries, layers):
    assets = _tuple(assets, NativeAsset, "assets")
    geometries = _tuple(geometries, GeometryDescriptor, "geometries")
    layers = _tuple(layers, DataLayer, "layers")
    _unique(assets, "asset_id", "assets")
    _unique(geometries, "geometry_id", "geometries")
    _unique(layers, "layer_id", "layers")
    asset_ids = {item.asset_id for item in assets}
    geometry_ids = {item.geometry_id for item in geometries}
    for layer in layers:
        if layer.asset_id not in asset_ids:
            raise ValueError("asset reference")
        if (
            layer.geometry_ref.status is SemanticStatus.KNOWN
            and layer.geometry_ref.value not in geometry_ids
        ):
            raise ValueError("geometry reference")
    return assets, geometries, layers


def _content_common(product_kind, profile_id, profile_version):
    validate_identifier(product_kind)
    validate_identifier(profile_id)
    _version(profile_version)


def _semantic_metadata(value):
    """Own the outer map; reuse canonical payload validation and immutable entries."""
    if not isinstance(value, Mapping):
        raise TypeError("semantic_metadata")
    result = {}
    for key, entry in value.items():
        if type(key) is not str:
            raise TypeError("semantic_metadata key")
        validate_identifier(key)
        if not isinstance(entry, SemanticValue):
            raise TypeError("semantic_metadata value")
        if entry.status is SemanticStatus.KNOWN:
            _validate_payload(entry.value, json_only=True)
        result[key] = entry
    return MappingProxyType(result)


@dataclass(frozen=True)
class ProductDraft:
    product_kind: str
    profile_id: str
    profile_version: int
    assets: tuple[NativeAsset, ...]
    layers: tuple[DataLayer, ...]
    geometries: tuple[GeometryDescriptor, ...]
    acquisition_refs: tuple[ArtifactRef, ...]
    semantic_metadata: Mapping[str, SemanticValue[FrozenJSON]]
    extensions: FrozenJSON

    def __post_init__(self):
        _content_common(
            self.product_kind,
            self.profile_id,
            self.profile_version,
        )
        assets, geometries, layers = _content_collections(
            self.assets, self.geometries, self.layers
        )
        acquisition_refs = tuple(self.acquisition_refs)
        if any(type(ref) is not ArtifactRef for ref in acquisition_refs):
            raise TypeError("acquisition_refs")
        _unique(acquisition_refs, "record_id", "acquisition_refs")
        for name, value in (
            ("assets", assets),
            ("geometries", geometries),
            ("layers", layers),
            ("acquisition_refs", acquisition_refs),
        ):
            object.__setattr__(self, name, value)
        object.__setattr__(
            self, "semantic_metadata", _semantic_metadata(self.semantic_metadata)
        )
        object.__setattr__(self, "extensions", _freeze_extensions(self.extensions))


@dataclass(frozen=True)
class Product:
    product_kind: str
    profile_id: str
    profile_version: int
    assets: tuple[NativeAsset, ...]
    layers: tuple[DataLayer, ...]
    geometries: tuple[GeometryDescriptor, ...]
    acquisition_refs: tuple[ArtifactRef, ...]
    semantic_metadata: Mapping[str, SemanticValue[FrozenJSON]]
    extensions: FrozenJSON
    schema_id: str
    schema_version: int
    product_id: str
    producer: ProducerRef
    produced_by: ProductionRef
    lineage: tuple[LineageEntry, ...]
    provenance_ref: str

    def __post_init__(self):
        validate_identifier(self.product_id)
        _content_common(
            self.product_kind,
            self.profile_id,
            self.profile_version,
        )
        if type(self.schema_id) is not str:
            raise TypeError("schema_id")
        if self.schema_id != "insarforge:product":
            raise ValueError("schema_id")
        if isinstance(self.schema_version, bool) or not isinstance(
            self.schema_version, int
        ):
            raise TypeError("schema_version")
        if self.schema_version != 2:
            raise ValueError("schema_version")
        if type(self.producer) is not ProducerRef:
            raise TypeError("producer")
        if type(self.produced_by) is not ProductionRef:
            raise TypeError("produced_by")
        if type(self.provenance_ref) is not str:
            raise TypeError("provenance_ref")
        validate_identifier(self.provenance_ref)
        assets, geometries, layers = _content_collections(
            self.assets, self.geometries, self.layers
        )
        acquisition_refs = tuple(self.acquisition_refs)
        if any(type(ref) is not ArtifactRef for ref in acquisition_refs):
            raise TypeError("acquisition_refs")
        _unique(acquisition_refs, "record_id", "acquisition_refs")
        lineage = tuple(self.lineage)
        if any(type(entry) is not LineageEntry for entry in lineage):
            raise TypeError("lineage")
        if len({(entry.role, entry.artifact.record_id) for entry in lineage}) != len(
            lineage
        ):
            raise ValueError("lineage")
        for name, value in (
            ("lineage", lineage),
            ("assets", assets),
            ("geometries", geometries),
            ("layers", layers),
            ("acquisition_refs", acquisition_refs),
        ):
            object.__setattr__(self, name, value)
        object.__setattr__(
            self, "semantic_metadata", _semantic_metadata(self.semantic_metadata)
        )
        object.__setattr__(self, "extensions", _freeze_extensions(self.extensions))
