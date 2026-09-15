from dataclasses import MISSING, FrozenInstanceError, fields, replace
from typing import get_type_hints

import pytest

import insarforge.contracts.plugins as plugins
from insarforge.contracts.identity import PluginKind, PluginRef
from insarforge.contracts.plugins import Analyzer, Correction, Processor, Provider
from insarforge.contracts.values import ArtifactRef
from insarforge.products.assets import (
    AssetKind,
    AssetLocation,
    AssetLocationKind,
    NativeAsset,
)
from insarforge.products.geometry import AxisDescriptor, GeometryDescriptor
from insarforge.products.grid import GridDefinition
from insarforge.products.layers import DataLayer, LayerSelector
from insarforge.products.models import (
    LineageEntry,
    ProducerRef,
    Product,
    ProductDraft,
    ProductionRef,
)
from insarforge.products.nodata import NoDataKind, NoDataSpec
from insarforge.products.semantics import (
    SemanticStatus,
    SemanticValue,
    SignSpec,
    UnitSpec,
)


def sv(value):
    return SemanticValue(SemanticStatus.KNOWN, value, None, ())


def unknown():
    return SemanticValue(SemanticStatus.UNKNOWN, None, "unknown", ())


def asset():
    return NativeAsset(
        "asset:x",
        AssetKind.FILE,
        AssetLocation(AssetLocationKind.ABSOLUTE_LOCAL, "/tmp/x", None),
        None,
        None,
        None,
        None,
    )


def layer(geometry="geometry:x"):
    return DataLayer(
        "layer:x",
        "role:test",
        "asset:x",
        LayerSelector("selector:test", "synthetic:subobject"),
        sv("quantity:x"),
        sv(UnitSpec("unit:x", "quantity:x", None)),
        sv(SignSpec("sign:x", "observable:x", "direction:x", None, None, ())),
        sv(geometry) if geometry else unknown(),
        sv(NoDataSpec(NoDataKind.NONE, None, None)),
        ("axis:x",),
    )


def draft(**kw):
    base = dict(
        schema_version=1,
        product_kind="product:test",
        profile_id="profile:test",
        profile_version=1,
        lineage=(),
        assets=(asset(),),
        geometries=(),
        layers=(),
        extensions={},
    )
    base.update(kw)
    return ProductDraft(**base)


def test_draft_and_cross_references():
    assert draft(layers=()).assets[0].asset_id == "asset:x"
    with pytest.raises(ValueError):
        draft(layers=(layer("geometry:x"),))
    g = final_geometry()
    assert draft(geometries=(g,), layers=(layer(),))
    with pytest.raises(ValueError):
        draft(assets=(asset(), asset()))


def test_immutability_and_product():
    src = []
    d = draft(lineage=tuple(src), extensions={"test-owner:x": [1]})
    assert isinstance(d.lineage, tuple)
    p = Product(
        "product:x",
        1,
        "product:test",
        "profile:test",
        1,
        PluginRef(PluginKind.PROCESSOR, "plugin:x", 1),
        "1.0",
        None,
        (),
        (asset(),),
        (),
        (),
        {},
    )
    assert p.provenance_ref is None
    with pytest.raises(Exception):
        p.product_id = "x"
    names = {f.name for f in fields(Product)}
    assert not names & {
        "unit",
        "sign",
        "geometry",
        "semantic_digest",
        "manifest_digest",
        "cache_key",
        "task_id",
        "run_id",
        "attempt_id",
    }
    with pytest.raises(ValueError):
        Product(
            "bad id",
            1,
            "product:test",
            "profile:test",
            1,
            PluginRef(PluginKind.PROCESSOR, "plugin:x", 1),
            "1.0",
            None,
            (),
            (),
            (),
            (),
            (),
        )


def test_forward_references_resolve():
    for proto, method in (
        (Provider, "acquire"),
        (Processor, "process"),
        (Correction, "correct"),
        (Analyzer, "analyze"),
    ):
        namespace = vars(plugins) | {"ProductDraft": ProductDraft}
        hints = get_type_hints(getattr(proto, method), namespace)
        assert "ProductDraft" in str(hints.get("return"))


def final_geometry():
    return GeometryDescriptor(
        geometry_id="geometry:x",
        domain="domain:test",
        coordinate_reference=sv("synthetic coordinate text"),
        axes=(
            AxisDescriptor(
                "axis:x",
                "role:test",
                sv(UnitSpec("unit:x", "quantity:x", None)),
                sv("direction:test"),
            ),
        ),
        shape=(2,),
        grid_definition=sv(
            GridDefinition(
                "grid:test-v1", {"nested": {"values": [1, 2], "text": "测试"}}
            )
        ),
        registration=sv("registration:test"),
        reference=sv(
            ArtifactRef(
                "record:test",
                "schema:test",
                1,
                "semantic:test",
                "manifest:test",
                "synthetic://unresolved/record",
            )
        ),
    )


def populated_product():
    """Final geometry and layers with matching synthetic dimension identifiers."""
    geometry = final_geometry()
    source = layer(geometry.geometry_id)
    return Product(
        "product:synthetic",
        1,
        "product:test",
        "profile:test",
        1,
        PluginRef(PluginKind.PROCESSOR, "plugin:synthetic", 1),
        "synthetic-v1",
        None,
        (),
        (asset(),),
        (geometry,),
        (
            source,
            replace(source, layer_id="mask:a"),
            replace(source, layer_id="mask:b"),
        ),
        {},
    )


@pytest.mark.parametrize("builder", [draft, populated_product])
@pytest.mark.parametrize(
    "extensions",
    [
        {},
        {"vendor-x:flag": True},
        {"future-tool:data": {"values": [1, 2]}},
        {"insarforge:test-value": 1},
        {"Vendor:flag": 1, "vendor:flag": 2},
    ],
)
def test_extension_namespace_acceptance(builder, extensions):
    from insarforge.contracts.values import freeze_json

    stored = replace(builder(), extensions=extensions).extensions
    assert stored == freeze_json(extensions)
    assert list(stored) == list(extensions)


@pytest.mark.parametrize("builder", [draft, populated_product])
@pytest.mark.parametrize("key", ["flag", "metadata", ":flag", "vendor:", "a:b:c"])
def test_extension_namespace_rejection(builder, key):
    with pytest.raises(ValueError):
        replace(builder(), extensions={key: 1})


@pytest.mark.parametrize("builder", [draft, populated_product])
@pytest.mark.parametrize("extensions", [None, [], (), "text", 1])
def test_extensions_require_mapping(builder, extensions):
    with pytest.raises(TypeError):
        replace(builder(), extensions=extensions)


@pytest.mark.parametrize("builder", [draft, populated_product])
@pytest.mark.parametrize("readonly", [False, True])
def test_extension_snapshot_owns_all_layers(builder, readonly):
    from types import MappingProxyType

    source = {"vendor-x:data": {"values": [1, 2]}}
    supplied = MappingProxyType(source) if readonly else source
    stored = replace(builder(), extensions=supplied).extensions
    source["vendor-x:extra"] = True
    source["vendor-x:data"]["extra"] = 3
    source["vendor-x:data"]["values"].append(3)
    assert stored == {"vendor-x:data": {"values": (1, 2)}}
    with pytest.raises(TypeError):
        stored["vendor-x:extra"] = True
    with pytest.raises(TypeError):
        stored["vendor-x:data"]["extra"] = 3
    with pytest.raises(TypeError):
        stored["vendor-x:data"]["values"][0] = 3


def test_product_and_draft_field_lists_preserve_current_envelope():
    common = (
        "schema_version",
        "product_kind",
        "profile_id",
        "profile_version",
    )
    tail = ("lineage", "assets", "geometries", "layers", "extensions")
    assert tuple(f.name for f in fields(ProductDraft)) == common + tail
    assert tuple(f.name for f in fields(Product)) == (
        "product_id",
        *common,
        "producer",
        "producer_implementation_version",
        "provenance_ref",
        *tail,
    )


# S3a foundations are additive; the transitional envelope regression above stays.
def reference_artifact(semantic_digest="synthetic:digest"):
    return ArtifactRef(
        "synthetic:record",
        "synthetic:schema",
        1,
        semantic_digest,
        "synthetic:manifest",
        "synthetic://unresolved/record",
    )


def producer_ref(**changes):
    values = dict(
        plugin=PluginRef(PluginKind.PROCESSOR, "synthetic:plugin", 1),
        implementation_version="Synthetic build / alpha",
        implementation_identity_digest=sv("synthetic implementation / digest"),
        execution_identity_digest=sv("synthetic execution / digest"),
    )
    values.update(changes)
    return ProducerRef(**values)


def production_ref(**changes):
    values = dict(
        task_fingerprint=sv("synthetic fingerprint / value"),
        output_port="synthetic:output",
        attempt_id="synthetic:attempt",
    )
    values.update(changes)
    return ProductionRef(**values)


IDENTITY_OWNERS = [
    (producer_ref, "implementation_identity_digest"),
    (producer_ref, "execution_identity_digest"),
    (production_ref, "task_fingerprint"),
]


@pytest.mark.parametrize("implementation_known", [True, False])
@pytest.mark.parametrize("execution_known", [True, False])
def test_producer_identity_availability_combinations(
    implementation_known, execution_known
):
    implementation = (
        sv("synthetic:implementation") if implementation_known else unknown()
    )
    execution = sv("synthetic:execution") if execution_known else unknown()
    plugin = PluginRef(PluginKind.PROCESSOR, "synthetic:unregistered", 1)
    ref = producer_ref(
        plugin=plugin,
        implementation_identity_digest=implementation,
        execution_identity_digest=execution,
    )
    assert ref.plugin is plugin
    assert ref.implementation_version == "Synthetic build / alpha"
    assert ref.implementation_identity_digest is implementation
    assert ref.execution_identity_digest is execution


@pytest.mark.parametrize("value", [None, "synthetic:plugin", {}, 1])
def test_producer_requires_plugin_reference(value):
    with pytest.raises(TypeError, match="plugin"):
        producer_ref(plugin=value)


class SyntheticString(str):
    pass


@pytest.mark.parametrize("value", [None, 1, True, (), SyntheticString("build")])
def test_producer_version_requires_exact_string(value):
    with pytest.raises(TypeError, match="implementation_version"):
        producer_ref(implementation_version=value)


@pytest.mark.parametrize("value", ["", " ", "\t", " build", "build ", "build\n"])
def test_producer_version_requires_nonempty_trimmed_text(value):
    with pytest.raises(ValueError, match="implementation_version"):
        producer_ref(implementation_version=value)


@pytest.mark.parametrize("builder,field", IDENTITY_OWNERS)
@pytest.mark.parametrize("value", [None, "synthetic:digest", 1, {}])
def test_identity_requires_semantic_value(builder, field, value):
    with pytest.raises(TypeError, match=field):
        builder(**{field: value})


@pytest.mark.parametrize("builder,field", IDENTITY_OWNERS)
def test_identity_rejects_not_applicable_only_at_owner(builder, field):
    value = SemanticValue(SemanticStatus.NOT_APPLICABLE, None, "synthetic:reason", ())
    with pytest.raises(ValueError, match=field):
        builder(**{field: value})
    assert value.status is SemanticStatus.NOT_APPLICABLE


@pytest.mark.parametrize("builder,field", IDENTITY_OWNERS)
@pytest.mark.parametrize("payload", [1, True, 1.5, (), SyntheticString("digest")])
def test_identity_known_requires_exact_string(builder, field, payload):
    value = sv(payload)  # Valid generic payload, invalid at these string owners.
    with pytest.raises(TypeError, match=field):
        builder(**{field: value})


@pytest.mark.parametrize("builder,field", IDENTITY_OWNERS)
@pytest.mark.parametrize("payload", ["", " ", "\t", " digest", "digest ", "digest\n"])
def test_identity_known_requires_nonempty_trimmed_text(builder, field, payload):
    value = sv(payload)
    with pytest.raises(ValueError, match=field):
        builder(**{field: value})


@pytest.mark.parametrize("builder,field", IDENTITY_OWNERS)
@pytest.mark.parametrize("reason", [None, "", " ", " reason", "reason ", 1])
def test_identity_owner_rechecks_unknown_reason(builder, field, reason):
    value = unknown()
    # Existing adversarial-test convention: bypass only on a fresh local value.
    # Generic SemanticValue normally rejects these before reaching the owner.
    object.__setattr__(value, "reason_code", reason)
    with pytest.raises(ValueError, match=field):
        builder(**{field: value})


@pytest.mark.parametrize("builder,field", IDENTITY_OWNERS)
def test_identity_unknown_rejects_payload_without_inventing_identity(builder, field):
    value = unknown()
    object.__setattr__(value, "value", "synthetic:invalid-payload")
    with pytest.raises(ValueError, match=field):
        builder(**{field: value})


@pytest.mark.parametrize("builder,field", IDENTITY_OWNERS)
@pytest.mark.parametrize("known", [True, False])
def test_identity_preserves_text_reason_evidence_and_owned_values(
    builder, field, known
):
    first = reference_artifact(None)
    second = replace(first, record_id="synthetic:other")
    source = [second, first, second]
    value = SemanticValue(
        SemanticStatus.KNOWN if known else SemanticStatus.UNKNOWN,
        "Synthetic opaque / identity 测试" if known else None,
        "Synthetic reason / text",
        source,
    )
    ref = builder(**{field: value})
    stored = getattr(ref, field)
    source.clear()
    assert stored is value
    assert stored.evidence_refs == (second, first, second)
    assert stored.reason_code == "Synthetic reason / text"
    assert stored.value == ("Synthetic opaque / identity 测试" if known else None)
    assert stored.status is (SemanticStatus.KNOWN if known else SemanticStatus.UNKNOWN)
    with pytest.raises(FrozenInstanceError):
        stored.value = "replacement"


@pytest.mark.parametrize("known", [True, False])
@pytest.mark.parametrize(
    "output_port,attempt_id",
    [("synthetic:output", "synthetic:attempt"), ("Output.X/测试", "Attempt-Y:2")],
)
def test_production_preserves_fingerprint_and_identifiers(
    known, output_port, attempt_id
):
    fingerprint = sv("synthetic:fingerprint") if known else unknown()
    ref = production_ref(
        task_fingerprint=fingerprint, output_port=output_port, attempt_id=attempt_id
    )
    assert ref.task_fingerprint is fingerprint
    assert ref.output_port == output_port
    assert ref.attempt_id == attempt_id
    if not known:
        assert ref.task_fingerprint.status is SemanticStatus.UNKNOWN
        assert ref.task_fingerprint.value is None


@pytest.mark.parametrize("field", ["output_port", "attempt_id"])
@pytest.mark.parametrize("value", [None, 1, True, ()])
def test_production_identifiers_require_strings(field, value):
    with pytest.raises(TypeError):
        production_ref(**{field: value})


@pytest.mark.parametrize("field", ["output_port", "attempt_id"])
@pytest.mark.parametrize("value", ["", " ", "two words", " leading", "tail ", "x\x00y"])
def test_production_rejects_invalid_identifiers(field, value):
    with pytest.raises(ValueError):
        production_ref(**{field: value})


@pytest.mark.parametrize("digest", ["synthetic:digest", None])
def test_lineage_stores_unresolved_artifact_with_optional_semantic_identity(digest):
    artifact = reference_artifact(digest)
    entry = LineageEntry("Synthetic:role/测试", artifact)
    assert entry.role == "Synthetic:role/测试"
    assert entry.artifact is artifact
    assert entry.artifact.semantic_digest == digest


@pytest.mark.parametrize("value", [None, 1, True, (), SyntheticString("role")])
def test_lineage_role_requires_exact_string(value):
    with pytest.raises(TypeError):
        LineageEntry(value, reference_artifact())


@pytest.mark.parametrize("value", ["", " ", "two words", " leading", "tail ", "x\x00y"])
def test_lineage_rejects_invalid_role(value):
    with pytest.raises(ValueError):
        LineageEntry(value, reference_artifact())


@pytest.mark.parametrize("value", [None, "synthetic:artifact", {}, 1])
def test_lineage_requires_artifact_reference(value):
    with pytest.raises(TypeError, match="artifact"):
        LineageEntry("synthetic:role", value)


@pytest.mark.parametrize(
    "value,expected,forbidden",
    [
        (
            producer_ref(),
            (
                "plugin",
                "implementation_version",
                "implementation_identity_digest",
                "execution_identity_digest",
            ),
            ("extensions", "metadata", "availability"),
        ),
        (
            production_ref(),
            ("task_fingerprint", "output_port", "attempt_id"),
            ("cache_key", "task", "runtime", "extensions"),
        ),
        (
            LineageEntry("synthetic:role", reference_artifact()),
            ("role", "artifact"),
            ("semantic_digest", "position", "extensions"),
        ),
    ],
)
def test_static_reference_exact_required_fields_and_frozen_values(
    value, expected, forbidden
):
    assert tuple(f.name for f in fields(value)) == expected
    assert all(
        f.default is MISSING and f.default_factory is MISSING for f in fields(value)
    )
    assert not any(hasattr(value, name) for name in forbidden)
    assert value == replace(value)
    for name in expected:
        with pytest.raises(FrozenInstanceError):
            setattr(value, name, None)
    assert type(value).__dataclass_params__.frozen


def test_reference_identity_components_remain_distinct():
    original = producer_ref()
    assert original != replace(original, implementation_identity_digest=sv("changed"))
    assert original != replace(original, execution_identity_digest=sv("changed"))
    production = production_ref()
    assert production != replace(production, attempt_id="synthetic:other")
    lineage = LineageEntry("synthetic:role", reference_artifact())
    assert lineage != replace(lineage, role="synthetic:other")


def test_reference_construction_does_not_resolve_or_compute(monkeypatch):
    import builtins
    import hashlib
    import io
    import os
    import socket

    from insarforge.core.registry import PluginRegistry

    plugin = PluginRef(PluginKind.PROCESSOR, "synthetic:unregistered", 1)
    fingerprint = unknown()
    artifact = reference_artifact(None)

    def forbidden(*args, **kwargs):
        raise AssertionError("static reference attempted I/O, lookup or computation")

    with monkeypatch.context() as patch:
        patch.setattr(builtins, "open", forbidden)
        patch.setattr(io, "open", forbidden)
        patch.setattr(os, "stat", forbidden)
        patch.setattr(socket, "socket", forbidden)
        patch.setattr(hashlib, "sha256", forbidden)
        patch.setattr(PluginRegistry, "resolve", forbidden)
        producer = producer_ref(plugin=plugin)
        production = production_ref(task_fingerprint=fingerprint)
        entry = LineageEntry("synthetic:role", artifact)
    assert producer.plugin is plugin
    assert production.task_fingerprint is fingerprint
    assert entry.artifact is artifact
