import pytest

from insarforge.products.layers import DataLayer, LayerSelector
from insarforge.products.semantics import (
    SemanticStatus,
    SemanticValue,
    SignSpec,
    UnitSpec,
)


def sv(v):
    return SemanticValue(SemanticStatus.KNOWN, v, None, ())


def test_layers():
    s = LayerSelector("selector:test", {"a": [1]})
    d = DataLayer(
        "layer:x",
        "role:test",
        "asset:x",
        s,
        sv("quantity:x"),
        sv(UnitSpec("unit:x", "quantity:x", None)),
        sv(SignSpec("sign:x", "observable:x", "direction:x", None, None, ())),
        sv("geometry:x"),
        {},
    )
    assert d.selector is s
    with pytest.raises(Exception):
        LayerSelector("bad id", {})
    with pytest.raises(TypeError):
        DataLayer(
            "layer:x",
            "role:test",
            "asset:x",
            s,
            sv(1),
            sv(UnitSpec("unit:x", "quantity:x", None)),
            sv(SignSpec("sign:x", "observable:x", "direction:x", None, None, ())),
            sv("geometry:x"),
            {},
        )
