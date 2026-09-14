from __future__ import annotations

from dataclasses import dataclass

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
from insarforge.products.semantics import SemanticStatus


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


def _collections(lineage, assets, geometries, layers):
    lineage = _tuple(lineage, ArtifactRef, "lineage")
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
    return lineage, assets, geometries, layers


def _common(schema_version, product_kind, profile_id, profile_version):
    _version(schema_version)
    validate_identifier(product_kind)
    validate_identifier(profile_id)
    _version(profile_version)


@dataclass(frozen=True)
class ProductDraft:
    schema_version: int
    product_kind: str
    profile_id: str
    profile_version: int
    lineage: tuple[ArtifactRef, ...]
    assets: tuple[NativeAsset, ...]
    geometries: tuple[GeometryDescriptor, ...]
    layers: tuple[DataLayer, ...]
    extensions: FrozenJSON

    def __post_init__(self):
        _common(
            self.schema_version,
            self.product_kind,
            self.profile_id,
            self.profile_version,
        )
        lineage, assets, geometries, layers = _collections(
            self.lineage, self.assets, self.geometries, self.layers
        )
        for name, value in (
            ("lineage", lineage),
            ("assets", assets),
            ("geometries", geometries),
            ("layers", layers),
        ):
            object.__setattr__(self, name, value)
        object.__setattr__(self, "extensions", _freeze_extensions(self.extensions))


@dataclass(frozen=True)
class Product:
    product_id: str
    schema_version: int
    product_kind: str
    profile_id: str
    profile_version: int
    producer: PluginRef
    producer_implementation_version: str
    provenance_ref: ArtifactRef | None
    lineage: tuple[ArtifactRef, ...]
    assets: tuple[NativeAsset, ...]
    geometries: tuple[GeometryDescriptor, ...]
    layers: tuple[DataLayer, ...]
    extensions: FrozenJSON

    def __post_init__(self):
        validate_identifier(self.product_id)
        _common(
            self.schema_version,
            self.product_kind,
            self.profile_id,
            self.profile_version,
        )
        if not isinstance(self.producer, PluginRef):
            raise TypeError("producer")
        if (
            not isinstance(self.producer_implementation_version, str)
            or not self.producer_implementation_version
            or self.producer_implementation_version
            != self.producer_implementation_version.strip()
        ):
            raise ValueError("producer_implementation_version")
        if self.provenance_ref is not None and not isinstance(
            self.provenance_ref, ArtifactRef
        ):
            raise TypeError("provenance_ref")
        lineage, assets, geometries, layers = _collections(
            self.lineage, self.assets, self.geometries, self.layers
        )
        for name, value in (
            ("lineage", lineage),
            ("assets", assets),
            ("geometries", geometries),
            ("layers", layers),
        ):
            object.__setattr__(self, name, value)
        object.__setattr__(self, "extensions", _freeze_extensions(self.extensions))
