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
