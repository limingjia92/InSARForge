import pytest

from insarforge.contracts.values import ArtifactRef
from insarforge.products.semantics import (
    PhysicalQuantity,
    SemanticStatus,
    SemanticValue,
    SignSpec,
    UnitSpec,
)


def test_semantics():
    r = ArtifactRef("r", "s", 1, None, "m", "l")
    assert [x.value for x in SemanticStatus] == ["known", "unknown", "not_applicable"]
    assert SemanticValue(SemanticStatus.KNOWN, 1, None, [r]).evidence_refs == (r,)
    for s, v, reason in [
        (SemanticStatus.KNOWN, None, None),
        (SemanticStatus.UNKNOWN, 1, "x"),
        (SemanticStatus.UNKNOWN, None, None),
        (SemanticStatus.NOT_APPLICABLE, None, None),
    ]:
        with pytest.raises(ValueError):
            SemanticValue(s, v, reason, [])
    u = UnitSpec("test:unit", "length", None)
    assert PhysicalQuantity(2, u, None, []).value == 2.0
    assert (
        SignSpec(
            "convention:test", "observable:test", "direction:a", "m1", "s1", [r]
        ).minuend_ref
        == "m1"
    )
    for x in (True, float("nan"), float("inf")):
        with pytest.raises((TypeError, ValueError)):
            PhysicalQuantity(x, u, None, [])
