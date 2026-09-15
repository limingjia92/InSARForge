from dataclasses import MISSING, FrozenInstanceError, fields, replace
from types import MappingProxyType

import pytest

from insarforge.contracts.identity import PluginKind, PluginRef
from insarforge.contracts.records import (
    AccessStatus,
    AcquisitionMetadata,
    CatalogEntry,
    CatalogSnapshot,
    CorrectionSpec,
    ProviderAvailability,
    ProviderDelivery,
    QCReport,
    QCStatus,
)
from insarforge.contracts.values import ArtifactRef, freeze_json
from insarforge.products.semantics import (
    SemanticStatus,
    SemanticValue,
    UnitSpec,
)


def test_records():
    r = ArtifactRef("r", "s", 1, None, "m", "l")
    a = AccessStatus(
        ProviderAvailability.AVAILABLE, ProviderDelivery.DIRECT, None, None
    )
    e = CatalogEntry("e", a, {"x": [1]}, [r])
    assert e.attributes["x"] == (1,)
    c = CatalogSnapshot(
        "r", "s", 1, PluginRef(PluginKind.PROVIDER, "p", 1), "q", 1, {}, [e], {}
    )
    assert c.entries == (e,)
    m = AcquisitionMetadata(
        "r",
        "s",
        1,
        r,
        PluginRef(PluginKind.MISSION, "m", 1),
        {"x": SemanticValue(SemanticStatus.KNOWN, freeze_json({"a": [1]}), None, [])},
        [],
        {},
    )
    assert m.attributes["x"].value["a"] == (1,)
    u = UnitSpec("test:unit", "length", None)

    assert (
        QCReport("r", "s", 1, QCStatus.FAIL, "m", "1", [], [], [], {}).status
        is QCStatus.FAIL
    )
    assert (
        CorrectionSpec(
            "m",
            "i",
            "o",
            "a",
            "x",
            SemanticValue(SemanticStatus.KNOWN, u, None, []),
            SemanticValue(SemanticStatus.UNKNOWN, None, "x", []),
            SemanticValue(SemanticStatus.UNKNOWN, None, "x", []),
            {},
        ).method_id
        == "m"
    )


@pytest.fixture(params=[CatalogSnapshot, AcquisitionMetadata, QCReport])
def extension_record(request):
    ref = ArtifactRef("r", "s", 1, None, "m", "l")
    if request.param is CatalogSnapshot:
        entry = CatalogEntry(
            "entry",
            AccessStatus(
                ProviderAvailability.UNKNOWN, ProviderDelivery.UNKNOWN, None, "unknown"
            ),
            {},
            [ref],
        )
        return CatalogSnapshot(
            "r",
            "s",
            1,
            PluginRef(PluginKind.PROVIDER, "p", 1),
            "q",
            1,
            {"selection": [1]},
            [entry],
            {},
        )
    if request.param is AcquisitionMetadata:
        return AcquisitionMetadata(
            "r",
            "s",
            1,
            ref,
            PluginRef(PluginKind.MISSION, "m", 1),
            {"sample": SemanticValue(SemanticStatus.UNKNOWN, None, "unknown", [])},
            [ref],
            {},
        )
    return QCReport("r", "s", 1, QCStatus.FAIL, "method", "1", [ref], [], [], {})


@pytest.mark.parametrize(
    "extensions",
    [
        {},
        {"vendor-x:flag": True},
        {"future-tool:data": {"values": [1, 2]}},
        {"insarforge:test-value": 1},
        {"Vendor-X:Flag": 1, "vendor-x:flag": 2},
    ],
)
def test_record_extension_namespaces_preserved(extension_record, extensions):
    record = replace(extension_record, extensions=extensions)
    assert record.extensions == freeze_json(extensions)
    assert set(record.extensions) == set(extensions)


@pytest.mark.parametrize("key", ["flag", ":flag", "vendor:", "a:b:c"])
def test_record_extension_legacy_and_malformed_keys_rejected(extension_record, key):
    with pytest.raises(ValueError):
        replace(extension_record, extensions={key: 1})


@pytest.mark.parametrize("extensions", [None, [], (), "text", 1])
def test_record_extension_requires_mapping(extension_record, extensions):
    with pytest.raises(TypeError):
        replace(extension_record, extensions=extensions)


@pytest.mark.parametrize("view", [False, True])
def test_record_extension_owns_nested_snapshot(extension_record, view):
    values = [1, 2]
    nested = {"values": values}
    source = {"vendor-x:data": nested}
    record = replace(
        extension_record, extensions=MappingProxyType(source) if view else source
    )
    source["vendor-x:other"] = True
    nested["extra"] = 3
    values.append(4)
    assert record.extensions == {"vendor-x:data": {"values": (1, 2)}}
    with pytest.raises(TypeError):
        record.extensions["vendor-x:other"] = True
    with pytest.raises(TypeError):
        record.extensions["vendor-x:data"]["extra"] = 3
    with pytest.raises(TypeError):
        record.extensions["vendor-x:data"]["values"][0] = 9
    with pytest.raises(FrozenInstanceError):
        record.extensions = {}


def test_record_extensions_are_opaque_semantic_state(extension_record):
    first = replace(
        extension_record, extensions={"test-owner:data": {"values": [1, 2]}}
    )
    same = replace(extension_record, extensions={"test-owner:data": {"values": (1, 2)}})
    changed = replace(
        extension_record, extensions={"test-owner:data": {"values": [2, 1]}}
    )
    assert first == same
    assert first != changed
    assert "test-owner:data" in repr(first)
    for field in fields(extension_record):
        if field.name != "extensions":
            assert getattr(first, field.name) == getattr(changed, field.name)
            assert getattr(first, field.name) == getattr(extension_record, field.name)
    # In particular, opaque metadata cannot change catalog access, UNKNOWN
    # acquisition semantics, or the supplied QC FAIL outcome.
    assert replace(first, extensions={}) == extension_record


@pytest.mark.parametrize(
    "record_type, expected",
    [
        (
            CatalogSnapshot,
            (
                "record_id",
                "schema_id",
                "schema_version",
                "provider",
                "query_schema_id",
                "query_schema_version",
                "selectors",
                "entries",
                "extensions",
            ),
        ),
        (
            AcquisitionMetadata,
            (
                "record_id",
                "schema_id",
                "schema_version",
                "source_ref",
                "mission",
                "attributes",
                "evidence_refs",
                "extensions",
            ),
        ),
        (
            QCReport,
            (
                "record_id",
                "schema_id",
                "schema_version",
                "status",
                "method_id",
                "method_version",
                "input_refs",
                "metrics",
                "findings",
                "extensions",
            ),
        ),
    ],
)
def test_record_public_field_shape(record_type, expected):
    assert tuple(field.name for field in fields(record_type)) == expected
    extension = fields(record_type)[-1]
    assert extension.default is MISSING
    assert extension.default_factory is MISSING
    assert record_type.__dataclass_params__.frozen
