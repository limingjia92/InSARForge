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
        product_kind="product:test",
        profile_id="profile:test",
        profile_version=1,
        assets=(asset(),),
        geometries=(),
        layers=(),
        acquisition_refs=(),
        semantic_metadata={},
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
    d = draft(acquisition_refs=src, extensions={"test-owner:x": [1]})
    assert isinstance(d.acquisition_refs, tuple)
    p = Product(
        product_kind="product:test",
        profile_id="profile:test",
        profile_version=1,
        assets=(asset(),),
        layers=(),
        geometries=(),
        acquisition_refs=(),
        semantic_metadata={},
        extensions={},
        schema_id="insarforge:product",
        schema_version=2,
        product_id="product:x",
        producer=producer_ref(
            plugin=PluginRef(PluginKind.PROCESSOR, "plugin:x", 1),
            implementation_version="1.0",
        ),
        produced_by=production_ref(),
        lineage=(),
        provenance_ref="synthetic:provenance",
    )
    assert p.provenance_ref == "synthetic:provenance"
    with pytest.raises(FrozenInstanceError):
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
    with pytest.raises(ValueError, match="identifier"):
        replace(p, product_id="bad id")


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
    """Synthetic production with no acquisitions, metadata or processing inputs."""
    geometry = final_geometry()
    source = layer(geometry.geometry_id)
    return Product(
        product_kind="product:test",
        profile_id="profile:test",
        profile_version=1,
        assets=(asset(),),
        layers=(
            source,
            replace(source, layer_id="mask:a"),
            replace(source, layer_id="mask:b"),
        ),
        geometries=(geometry,),
        acquisition_refs=(),
        semantic_metadata={},
        extensions={},
        schema_id="insarforge:product",
        schema_version=2,
        product_id="product:synthetic",
        producer=producer_ref(
            plugin=PluginRef(PluginKind.PROCESSOR, "plugin:synthetic", 1),
            implementation_version="synthetic-v1",
        ),
        produced_by=production_ref(),
        lineage=(),
        provenance_ref="synthetic:provenance",
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


def test_product_final_field_order():
    assert tuple(f.name for f in fields(Product)) == (
        "product_kind",
        "profile_id",
        "profile_version",
        "assets",
        "layers",
        "geometries",
        "acquisition_refs",
        "semantic_metadata",
        "extensions",
        "schema_id",
        "schema_version",
        "product_id",
        "producer",
        "produced_by",
        "lineage",
        "provenance_ref",
    )


# S3a reference contracts remain unchanged when wired into Product.
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
    if isinstance(payload, SyntheticString):
        # PRO-P41-01 rejects subclasses at the generic boundary as well.
        with pytest.raises(TypeError, match="unsupported semantic payload"):
            sv(payload)
        value = sv("digest")
        # Retain the independent owner-defense check on a fresh test-only value.
        object.__setattr__(value, "value", payload)
    else:
        value = sv(payload)  # Valid generic payload, invalid at string owners.
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


DRAFT_FIELDS = (
    "product_kind",
    "profile_id",
    "profile_version",
    "assets",
    "layers",
    "geometries",
    "acquisition_refs",
    "semantic_metadata",
    "extensions",
)
CORE_FIELDS = (
    "schema_id",
    "schema_version",
    "product_id",
    "producer",
    "produced_by",
    "lineage",
    "provenance_ref",
)


def test_draft_final_required_fields_and_frozen_state():
    value = draft()
    assert tuple(f.name for f in fields(ProductDraft)) == DRAFT_FIELDS
    assert get_type_hints(ProductDraft)["acquisition_refs"] == tuple[ArtifactRef, ...]
    assert all(
        f.default is MISSING and f.default_factory is MISSING for f in fields(value)
    )
    assert not any(hasattr(value, name) for name in CORE_FIELDS)
    for name in DRAFT_FIELDS:
        with pytest.raises(FrozenInstanceError):
            setattr(value, name, None)
        supplied = {f.name: getattr(value, f.name) for f in fields(value)}
        del supplied[name]
        with pytest.raises(TypeError, match=name):
            ProductDraft(**supplied)


@pytest.mark.parametrize("name", CORE_FIELDS)
def test_draft_rejects_core_owned_constructor_keywords(name):
    with pytest.raises(TypeError, match=name):
        draft(**{name: None})


@pytest.mark.parametrize("container", [list, tuple, iter])
def test_draft_acquisition_order_and_weak_identity(container):
    first = reference_artifact(None)
    second = replace(reference_artifact(), record_id="synthetic:another")
    supplied = [second, first]
    value = draft(acquisition_refs=container(supplied))
    supplied.clear()
    assert value.acquisition_refs == (second, first)
    assert value.acquisition_refs[1] is first
    assert value.acquisition_refs[1].semantic_digest is None
    assert draft().acquisition_refs == ()
    assert draft(acquisition_refs=[second]).acquisition_refs == (second,)


@pytest.mark.parametrize(
    "item",
    [
        None,
        "synthetic:ref",
        1,
        {},
        LineageEntry("synthetic:role", reference_artifact()),
    ],
)
def test_draft_acquisition_rejects_non_artifact_members(item):
    with pytest.raises(TypeError, match="acquisition_refs"):
        draft(acquisition_refs=[item])


def test_draft_acquisition_requires_exact_artifact_type():
    class SyntheticArtifact(ArtifactRef):
        pass

    with pytest.raises(TypeError, match="acquisition_refs"):
        draft(acquisition_refs=[SyntheticArtifact(**vars(reference_artifact()))])


@pytest.mark.parametrize("different_details", [False, True])
def test_draft_acquisition_rejects_duplicate_record_ids(different_details):
    first = reference_artifact()
    second = (
        replace(first, schema_id="synthetic:other", semantic_digest=None)
        if different_details
        else first
    )
    with pytest.raises(ValueError, match="acquisition_refs"):
        draft(acquisition_refs=(first, second))


@pytest.mark.parametrize("value", [None, "text", 1, [], ()])
def test_draft_metadata_requires_mapping(value):
    with pytest.raises(TypeError, match="semantic_metadata"):
        draft(semantic_metadata=value)


@pytest.mark.parametrize("key", [None, 1, True, SyntheticString("quality")])
def test_draft_metadata_requires_exact_string_keys(key):
    with pytest.raises(TypeError, match="key"):
        draft(semantic_metadata={key: sv(1)})


@pytest.mark.parametrize("key", ["", "two words", " leading", "tail ", "x\x00y"])
def test_draft_metadata_rejects_invalid_identifier_keys(key):
    with pytest.raises(ValueError):
        draft(semantic_metadata={key: sv(1)})


@pytest.mark.parametrize(
    "value", [1, None, "raw", {}, [], {"status": "known", "value": 1}]
)
def test_draft_metadata_does_not_wrap_raw_values(value):
    with pytest.raises(TypeError, match="semantic_metadata value"):
        draft(semantic_metadata={"quality": value})


@pytest.mark.parametrize(
    "payload",
    [
        UnitSpec("unit:x", "quantity:x", None),
        reference_artifact(),
        SignSpec("convention:x", "observable:x", "direction:x", None, None, ()),
        (reference_artifact(),),
    ],
)
def test_draft_metadata_rejects_generic_non_json_semantic_payload(payload):
    value = sv(payload)  # Valid ADR0010 value; not FrozenJSON at this owner.
    with pytest.raises(TypeError):
        draft(semantic_metadata={"quality": value})


@pytest.mark.parametrize("payload", [object(), {"raw": 1}, [1]])
def test_draft_metadata_rejects_bypassed_opaque_or_mutable_payload(payload):
    value = sv(1)
    # Fresh test-only corruption follows the existing adversarial test convention.
    object.__setattr__(value, "value", payload)
    with pytest.raises(TypeError):
        draft(semantic_metadata={"quality": value})


@pytest.mark.parametrize("payload", ["text", True, 1, 1.0, (), (None, "text", 2)])
def test_draft_metadata_preserves_frozen_json_scalars_and_arrays(payload):
    entry = sv(payload)
    value = draft(semantic_metadata={"quality": entry})
    assert value.semantic_metadata["quality"] is entry
    assert value.semantic_metadata["quality"].value is entry.value


@pytest.mark.parametrize("readonly", [False, True])
def test_draft_metadata_owns_outer_mapping_preserving_semantic_values(readonly):
    from types import MappingProxyType

    nested = {"items": (None, 1, 1.0, True)}
    evidence = [reference_artifact(None)]
    known = SemanticValue(
        SemanticStatus.KNOWN, MappingProxyType(nested), "synthetic:reason", evidence
    )
    na = SemanticValue(
        SemanticStatus.NOT_APPLICABLE, None, "synthetic:not-applicable", ()
    )
    entries = {"quality": known, "Quality": unknown(), "z": na}
    supplied = MappingProxyType(entries) if readonly else entries
    value = draft(semantic_metadata=supplied)
    entries["quality"] = sv("replacement")
    entries["added"] = sv(2)
    del entries["Quality"]
    nested.clear()
    evidence.clear()
    assert list(value.semantic_metadata) == ["quality", "Quality", "z"]
    assert value.semantic_metadata["quality"] is known
    assert value.semantic_metadata["z"] is na
    assert value.semantic_metadata["Quality"].status is SemanticStatus.UNKNOWN
    assert known.value == {"items": (None, 1, 1.0, True)}
    assert known.reason_code == "synthetic:reason"
    assert len(known.evidence_refs) == 1
    assert known.evidence_refs[0].semantic_digest is None
    with pytest.raises(TypeError):
        value.semantic_metadata["quality"] = sv(2)
    with pytest.raises(TypeError):
        del value.semantic_metadata["z"]
    with pytest.raises(TypeError):
        known.value["items"] = ()


def test_draft_metadata_mapping_order_is_nonsemantic_without_sorting():
    entries = {"z": sv(1), "quality": unknown(), "Quality": sv("text")}
    forward = draft(semantic_metadata=entries)
    backward = draft(semantic_metadata=dict(reversed(entries.items())))
    assert forward == backward
    assert list(forward.semantic_metadata) == list(entries)
    assert list(backward.semantic_metadata) == list(reversed(entries))


def test_draft_metadata_and_extensions_keep_distinct_contracts():
    value = draft(
        semantic_metadata={"quality": sv(1)}, extensions={"vendor-x:quality": 2}
    )
    assert value.semantic_metadata["quality"].value == 1
    assert value.extensions == {"vendor-x:quality": 2}
    with pytest.raises(ValueError):
        draft(extensions={"quality": 1})
    with pytest.raises(TypeError):
        draft(semantic_metadata={"quality": 1})
    assert (
        draft(semantic_metadata={"a:b:c": sv(1)}).semantic_metadata["a:b:c"].value == 1
    )


def test_draft_content_collections_remain_owned_and_linked():
    assets = [asset()]
    geometries = [final_geometry()]
    layers = [layer()]
    value = draft(assets=assets, geometries=geometries, layers=layers)
    assets.clear()
    geometries.clear()
    layers.clear()
    assert value.assets == (asset(),)
    assert value.geometries == (final_geometry(),)
    assert value.layers == (layer(),)
    with pytest.raises(ValueError):
        draft(geometries=(final_geometry(), final_geometry()))
    with pytest.raises(ValueError):
        draft(geometries=(final_geometry(),), layers=(layer(), layer()))


def test_draft_acquisition_and_metadata_construction_never_resolves(monkeypatch):
    import builtins
    import io
    import socket

    from insarforge.core.registry import PluginRegistry

    reference = reference_artifact(None)
    entry = SemanticValue(
        SemanticStatus.UNKNOWN, None, "synthetic:unknown", (reference,)
    )

    def forbidden(*args, **kwargs):
        raise AssertionError("Draft construction attempted lookup or I/O")

    with monkeypatch.context() as patch:
        patch.setattr(builtins, "open", forbidden)
        patch.setattr(io, "open", forbidden)
        patch.setattr(socket, "socket", forbidden)
        patch.setattr(PluginRegistry, "resolve", forbidden)
        value = draft(
            acquisition_refs=(reference,), semantic_metadata={"quality": entry}
        )
    assert value.acquisition_refs == (reference,)
    assert value.semantic_metadata["quality"] is entry


PRODUCT_FIELDS = DRAFT_FIELDS + CORE_FIELDS


def test_product_final_types_and_frozen_required_fields():
    value = populated_product()
    hints = get_type_hints(Product)
    draft_hints = get_type_hints(ProductDraft)
    assert hints == {
        "product_kind": str,
        "profile_id": str,
        "profile_version": int,
        "assets": tuple[NativeAsset, ...],
        "layers": tuple[DataLayer, ...],
        "geometries": tuple[GeometryDescriptor, ...],
        "acquisition_refs": tuple[ArtifactRef, ...],
        "semantic_metadata": draft_hints["semantic_metadata"],
        "extensions": draft_hints["extensions"],
        "schema_id": str,
        "schema_version": int,
        "product_id": str,
        "producer": ProducerRef,
        "produced_by": ProductionRef,
        "lineage": tuple[LineageEntry, ...],
        "provenance_ref": str,
    }
    assert tuple(f.name for f in fields(ProductDraft)) == DRAFT_FIELDS
    assert Product.__dataclass_params__.frozen
    assert all(
        f.default is MISSING and f.default_factory is MISSING for f in fields(value)
    )
    for name in PRODUCT_FIELDS:
        with pytest.raises(FrozenInstanceError):
            setattr(value, name, None)


@pytest.mark.parametrize("name", PRODUCT_FIELDS)
def test_product_requires_every_final_field(name):
    value = populated_product()
    supplied = {f.name: getattr(value, f.name) for f in fields(value)}
    del supplied[name]
    with pytest.raises(TypeError, match=name):
        Product(**supplied)


def test_product_has_no_transitional_version_field_or_alias():
    value = populated_product()
    name = "producer_implementation_version"
    assert name not in {f.name for f in fields(value)}
    assert not hasattr(Product, name)
    assert not hasattr(value, name)
    supplied = {f.name: getattr(value, f.name) for f in fields(value)}
    with pytest.raises(TypeError, match=name):
        Product(**supplied, producer_implementation_version="synthetic:legacy")


@pytest.mark.parametrize(
    "value", [None, 2, True, SyntheticString("insarforge:product")]
)
def test_product_schema_id_requires_string(value):
    with pytest.raises(TypeError, match="schema_id"):
        replace(populated_product(), schema_id=value)


@pytest.mark.parametrize(
    "value",
    [
        "",
        "synthetic:other",
        "insarforge:product-manifest",
        " insarforge:product",
        "insarforge:product ",
        "InSARForge:product",
    ],
)
def test_product_schema_id_requires_exact_literal(value):
    with pytest.raises(ValueError, match="schema_id"):
        replace(populated_product(), schema_id=value)


@pytest.mark.parametrize("value", [True, False, 2.0, "2", None])
def test_product_schema_version_requires_integer_not_bool(value):
    with pytest.raises(TypeError, match="schema_version"):
        replace(populated_product(), schema_version=value)


@pytest.mark.parametrize("value", [1, 3, 0, -1])
def test_product_schema_version_requires_two(value):
    with pytest.raises(ValueError, match="schema_version"):
        replace(populated_product(), schema_version=value)


def test_product_preserves_supplied_envelope_without_cross_slot_rules():
    producer = producer_ref(implementation_identity_digest=unknown())
    production = production_ref(task_fingerprint=unknown())
    value = replace(
        populated_product(),
        product_id="Product:instance/测试",
        producer=producer,
        produced_by=production,
        provenance_ref="Provenance:separate/测试",
    )
    assert value.schema_id == "insarforge:product"
    assert type(value.schema_version) is int and value.schema_version == 2
    assert value.product_id == "Product:instance/测试"
    assert value.producer is producer
    assert value.produced_by is production
    assert value.provenance_ref == "Provenance:separate/测试"
    assert value.provenance_ref != production.attempt_id


@pytest.mark.parametrize("name", ["producer", "produced_by"])
@pytest.mark.parametrize("value", [None, "synthetic:reference", {}, 1])
def test_product_requires_typed_production_envelope(name, value):
    with pytest.raises(TypeError, match=name):
        replace(populated_product(), **{name: value})


def test_product_rejects_old_producer_and_swapped_envelope_types():
    value = populated_product()
    for producer in (value.producer.plugin, value.produced_by):
        with pytest.raises(TypeError, match="producer"):
            replace(value, producer=producer)
    with pytest.raises(TypeError, match="produced_by"):
        replace(value, produced_by=value.producer)


@pytest.mark.parametrize(
    "name,cls", [("producer", ProducerRef), ("produced_by", ProductionRef)]
)
def test_product_requires_exact_production_envelope_types(name, cls):
    class SyntheticReference(cls):
        pass

    value = populated_product()
    supplied = SyntheticReference(**vars(getattr(value, name)))
    with pytest.raises(TypeError, match=name):
        replace(value, **{name: supplied})


@pytest.mark.parametrize(
    "value", [None, 1, {}, SyntheticString("synthetic:provenance")]
)
def test_product_provenance_requires_exact_string(value):
    with pytest.raises(TypeError, match="provenance_ref"):
        replace(populated_product(), provenance_ref=value)


def test_product_provenance_rejects_nested_references():
    for value in (reference_artifact(), sv("synthetic:provenance")):
        with pytest.raises(TypeError, match="provenance_ref"):
            replace(populated_product(), provenance_ref=value)


@pytest.mark.parametrize("value", ["", "two words", " leading", "tail ", "x\x00y"])
def test_product_provenance_rejects_invalid_identifiers(value):
    with pytest.raises(ValueError, match="identifier"):
        replace(populated_product(), provenance_ref=value)


@pytest.mark.parametrize("name", ["product_id", "product_kind", "profile_id"])
def test_product_preserves_content_and_instance_identifier_validation(name):
    value = populated_product()
    with pytest.raises(TypeError, match="identifier"):
        replace(value, **{name: None})
    with pytest.raises(ValueError, match="identifier"):
        replace(value, **{name: "bad id"})


def test_product_profile_version_remains_independent_of_schema_revision():
    value = replace(populated_product(), profile_version=3)
    assert value.profile_version == 3 and value.schema_version == 2
    with pytest.raises(TypeError):
        replace(value, profile_version=True)
    with pytest.raises(ValueError):
        replace(value, profile_version=0)


@pytest.mark.parametrize("container", [list, tuple, iter])
def test_product_acquisition_reuses_order_ownership_and_weak_ref_contract(container):
    weak = reference_artifact(None)
    other = replace(
        weak, record_id="synthetic:other", schema_id="synthetic:open-schema"
    )
    supplied = [other, weak]
    value = replace(populated_product(), acquisition_refs=container(supplied))
    supplied.clear()
    assert type(value.acquisition_refs) is tuple
    assert value.acquisition_refs == (other, weak)
    assert value.acquisition_refs[1] is weak
    assert value.acquisition_refs[1].semantic_digest is None
    assert value.lineage == ()  # No generated lineage or subset rule.
    assert populated_product().acquisition_refs == ()


@pytest.mark.parametrize("different_details", [False, True])
def test_product_acquisition_rejects_duplicate_record_ids(different_details):
    first = reference_artifact()
    second = (
        replace(first, schema_id="synthetic:other", semantic_digest=None)
        if different_details
        else first
    )
    with pytest.raises(ValueError, match="acquisition_refs"):
        replace(populated_product(), acquisition_refs=[first, second])


def test_product_acquisition_requires_exact_artifact_members():
    class SyntheticArtifact(ArtifactRef):
        pass

    for item in (
        None,
        LineageEntry("synthetic:role", reference_artifact()),
        SyntheticArtifact(**vars(reference_artifact())),
    ):
        with pytest.raises(TypeError, match="acquisition_refs"):
            replace(populated_product(), acquisition_refs=[item])


@pytest.mark.parametrize("readonly", [False, True])
def test_product_metadata_reuses_owned_mapping_and_semantic_entries(readonly):
    from types import MappingProxyType

    nested = {"items": (1, None, True)}
    known = sv(MappingProxyType(nested))
    na = SemanticValue(SemanticStatus.NOT_APPLICABLE, None, "synthetic:unused", ())
    entries = {"quality": known, "Quality": unknown(), "other": na}
    supplied = MappingProxyType(entries) if readonly else entries
    value = replace(populated_product(), semantic_metadata=supplied)
    entries.clear()
    nested.clear()
    assert list(value.semantic_metadata) == ["quality", "Quality", "other"]
    assert value.semantic_metadata["quality"] is known
    assert known.value == {"items": (1, None, True)}
    assert value.semantic_metadata["Quality"].status is SemanticStatus.UNKNOWN
    assert value.semantic_metadata["other"] is na
    with pytest.raises(TypeError):
        value.semantic_metadata["added"] = sv(1)
    with pytest.raises(TypeError):
        del value.semantic_metadata["quality"]
    assert populated_product().semantic_metadata == {}


def test_product_metadata_reuses_mapping_key_and_payload_validation():
    value = populated_product()
    for bad in (None, []):
        with pytest.raises(TypeError, match="semantic_metadata"):
            replace(value, semantic_metadata=bad)
    for key in (1, SyntheticString("quality")):
        with pytest.raises(TypeError, match="key"):
            replace(value, semantic_metadata={key: sv(1)})
    for key in ("", "two words"):
        with pytest.raises(ValueError, match="identifier"):
            replace(value, semantic_metadata={key: sv(1)})
    with pytest.raises(TypeError, match="semantic_metadata value"):
        replace(value, semantic_metadata={"quality": 1})
    with pytest.raises(TypeError):
        replace(value, semantic_metadata={"quality": sv(reference_artifact())})


def test_product_metadata_is_distinct_from_namespaced_extensions():
    value = replace(
        populated_product(),
        semantic_metadata={"quality": sv(1), "a:b:c": unknown()},
        extensions={"vendor:quality": 2},
    )
    assert value.semantic_metadata["quality"].value == 1
    assert value.semantic_metadata["a:b:c"].status is SemanticStatus.UNKNOWN
    assert value.extensions == {"vendor:quality": 2}
    assert value == replace(
        value, semantic_metadata=dict(reversed(value.semantic_metadata.items()))
    )
    with pytest.raises(ValueError):
        replace(value, extensions={"quality": 2})


@pytest.mark.parametrize("container", [list, tuple, iter])
def test_product_lineage_order_ownership_roles_and_weak_identity(container):
    weak = reference_artifact(None)
    other = replace(weak, record_id="synthetic:other")
    first = LineageEntry("role:z", weak)
    different_role = LineageEntry("role:a", weak)
    different_artifact = LineageEntry("role:z", other)
    supplied = [first, different_role, different_artifact]
    value = replace(populated_product(), lineage=container(supplied))
    supplied.clear()
    assert type(value.lineage) is tuple
    assert value.lineage == (first, different_role, different_artifact)
    assert value.lineage[0] is first
    assert value.lineage[0].artifact.semantic_digest is None
    assert value.acquisition_refs == ()  # No generated acquisition inventory.
    assert populated_product().lineage == ()
    assert replace(value, lineage=[first]).lineage == (first,)
    assert replace(value, lineage=tuple(reversed(value.lineage))) != value


@pytest.mark.parametrize("changed_details", [False, True])
def test_product_lineage_repeated_occurrences_reject_only_conflicts(changed_details):
    first = LineageEntry("synthetic:role", reference_artifact())
    ref = (
        replace(
            first.artifact,
            schema_id="synthetic:other",
            semantic_digest=None,
            manifest_digest="manifest:other",
            locator="synthetic:elsewhere",
        )
        if changed_details
        else first.artifact
    )
    duplicate = LineageEntry(first.role, ref)
    if changed_details:
        with pytest.raises(ValueError, match="lineage"):
            replace(populated_product(), lineage=[first, duplicate])
    else:
        assert replace(populated_product(), lineage=[first, duplicate]).lineage == (
            first,
            duplicate,
        )


def test_product_lineage_requires_exact_lineage_entry_members():
    class SyntheticLineage(LineageEntry):
        pass

    ref = reference_artifact()
    for item in (
        ref,
        None,
        "synthetic:role",
        {"role": "synthetic:role", "artifact": ref},
        SyntheticLineage("synthetic:role", ref),
    ):
        with pytest.raises(TypeError, match="lineage"):
            replace(populated_product(), lineage=[item])


def test_product_acquisitions_and_lineage_are_independent_inventories():
    first = reference_artifact(None)
    second = replace(first, record_id="synthetic:second")
    value = replace(
        populated_product(),
        acquisition_refs=[first],
        lineage=[LineageEntry("synthetic:input", second)],
    )
    assert value.acquisition_refs == (first,)
    assert value.lineage[0].artifact is second
    overlap = replace(value, lineage=[LineageEntry("synthetic:input", first)])
    assert overlap.lineage[0].artifact is overlap.acquisition_refs[0]


def test_product_content_collections_remain_owned_and_linked():
    original = populated_product()
    assets, layers, geometries = (
        list(original.assets),
        list(original.layers),
        list(original.geometries),
    )
    value = replace(original, assets=assets, layers=layers, geometries=geometries)
    assets.clear()
    layers.clear()
    geometries.clear()
    assert value == original
    assert all(
        type(getattr(value, name)) is tuple
        for name in ("assets", "layers", "geometries")
    )
    for name in ("assets", "layers", "geometries"):
        with pytest.raises(ValueError):
            replace(value, **{name: getattr(value, name) * 2})
        with pytest.raises(TypeError):
            replace(value, **{name: [None]})
    with pytest.raises(ValueError, match="asset reference"):
        replace(value, assets=())
    with pytest.raises(ValueError, match="geometry reference"):
        replace(value, geometries=())


def test_product_constructor_does_not_resolve_or_compute(monkeypatch):
    import builtins
    import hashlib
    import io
    import os
    import socket

    from insarforge.core.registry import PluginRegistry

    original = populated_product()
    ref = reference_artifact(None)
    producer = producer_ref(execution_identity_digest=unknown())
    production = production_ref(task_fingerprint=unknown())
    lineage = [LineageEntry("synthetic:role", ref)]
    metadata = {
        "quality": SemanticValue(
            SemanticStatus.UNKNOWN, None, "synthetic:unknown", (ref,)
        )
    }

    def forbidden(*args, **kwargs):
        raise AssertionError(
            "Product construction attempted I/O, lookup or computation"
        )

    with monkeypatch.context() as patch:
        patch.setattr(builtins, "open", forbidden)
        patch.setattr(io, "open", forbidden)
        patch.setattr(os, "stat", forbidden)
        patch.setattr(socket, "socket", forbidden)
        patch.setattr(hashlib, "sha256", forbidden)
        patch.setattr(PluginRegistry, "resolve", forbidden)
        value = replace(
            original,
            producer=producer,
            produced_by=production,
            lineage=lineage,
            acquisition_refs=[ref],
            semantic_metadata=metadata,
        )
    assert value.producer is producer
    assert value.produced_by is production
    assert value.lineage == tuple(lineage)
    assert value.acquisition_refs == (ref,)
    assert value.semantic_metadata["quality"] is metadata["quality"]


@pytest.mark.parametrize(
    "changes",
    [
        {"schema_id": "synthetic:other"},
        {"schema_version": 3},
        {"semantic_digest": None},
        {"manifest_digest": "manifest:other"},
        {"locator": "synthetic:elsewhere"},
    ],
)
def test_lineage_same_key_rejects_each_reference_conflict(changes):
    first = LineageEntry("synthetic:role", reference_artifact())
    other = LineageEntry(first.role, replace(first.artifact, **changes))
    with pytest.raises(ValueError, match="lineage"):
        replace(populated_product(), lineage=(first, other))
