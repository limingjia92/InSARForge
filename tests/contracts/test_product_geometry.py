from pathlib import Path

import pytest

from insarforge.products.geometry import AxisDescriptor, GeometryDescriptor
from insarforge.products.semantics import SemanticStatus, SemanticValue, UnitSpec


def sv(status, value=None, reason="r"):
    return SemanticValue(
        status, value, None if status is SemanticStatus.KNOWN else reason, ()
    )


def unit():
    return UnitSpec("unit:x", "quantity:x", None)


def axis(i="axis:x", size=2):
    return AxisDescriptor(
        i,
        "role:test",
        size,
        sv(SemanticStatus.KNOWN, unit()),
        sv(SemanticStatus.KNOWN, "direction:positive-a"),
        {},
    )


def test_geometry_contracts():
    a = axis()
    g = GeometryDescriptor(
        "geometry:x",
        "domain:test",
        [2, 3],
        [a, axis("axis:y", 3)],
        sv(SemanticStatus.KNOWN, "registration:test"),
        sv(SemanticStatus.KNOWN, "EPSG:4326"),
        {},
    )
    assert g.shape == (2, 3) and g.axes[0] is a
    with pytest.raises(Exception):
        axis(size=0)
    with pytest.raises(Exception):
        axis(size=True)
    with pytest.raises(Exception):
        AxisDescriptor(
            "bad id",
            "role:test",
            2,
            sv(SemanticStatus.KNOWN, "wrong"),
            sv(SemanticStatus.UNKNOWN),
            {},
        )
    with pytest.raises(Exception):
        GeometryDescriptor(
            "geometry:x",
            "domain:test",
            [],
            [],
            sv(SemanticStatus.UNKNOWN),
            sv(SemanticStatus.UNKNOWN),
            {},
        )
    with pytest.raises(Exception):
        GeometryDescriptor(
            "geometry:x",
            "domain:test",
            [2],
            [axis(), axis("axis:y")],
            sv(SemanticStatus.UNKNOWN),
            sv(SemanticStatus.UNKNOWN),
            {},
        )
    with pytest.raises(Exception):
        g.shape += (1,)


def test_geometry_immutability_and_imports():
    source = {"x": [1]}
    a = axis()
    g = GeometryDescriptor(
        "geometry:x",
        "domain:test",
        [2],
        [a],
        sv(SemanticStatus.UNKNOWN),
        sv(SemanticStatus.NOT_APPLICABLE),
        source,
    )
    source["x"].append(2)
    assert len(g.extensions["x"]) == 1
    tree = __import__("ast").parse(
        Path("src/insarforge/products/geometry.py").read_text()
    )
    assert not any(
        getattr(n, "module", "").startswith(
            (
                "insarforge.config",
                "insarforge.contracts.plugins",
                "insarforge.products.assets",
            )
        )
        for n in __import__("ast").walk(tree)
        if isinstance(n, __import__("ast").ImportFrom)
    )
