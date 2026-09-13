import ast
import dataclasses
import pathlib

import pytest

from insarforge.contracts.identity import (
    CapabilityAvailability,
    CapabilityCheckResult,
    CapabilityId,
    PluginDescriptor,
    PluginKind,
    PluginRef,
)
from insarforge.contracts.values import ArtifactRef


def test_identity():
    assert [x.value for x in PluginKind] == [
        "mission",
        "provider",
        "processor",
        "correction",
        "analyzer",
        "qc",
    ]
    with pytest.raises(TypeError):
        PluginRef("mission", "x", 1)
    p = PluginRef(PluginKind.MISSION, "X", 1)
    assert p.plugin_id == "X"
    for x in ("", " a", "a ", "a b", "a\n"):
        with pytest.raises(ValueError):
            PluginRef(PluginKind.MISSION, x, 1)
    with pytest.raises(TypeError):
        PluginRef(PluginKind.MISSION, "x", True)
    assert [CapabilityId("b:x"), CapabilityId("a:x")][1] < CapabilityId("b:x")
    with pytest.raises(ValueError):
        CapabilityId("x")
    d = PluginDescriptor(
        PluginKind.PROCESSOR,
        "p",
        1,
        "v1",
        "Display Name",
        [CapabilityId("b:x"), CapabilityId("a:x")],
    )
    assert d.capabilities[0].value == "a:x"
    assert d.ref == PluginRef(PluginKind.PROCESSOR, "p", 1)
    with pytest.raises(ValueError):
        PluginDescriptor(PluginKind.PROCESSOR, "p", 1, " ", "D", ())
    e = [ArtifactRef("r", "s", 1, None, "m", "l")]
    c = CapabilityCheckResult(
        CapabilityId("a:x"), CapabilityAvailability.AVAILABLE, None, e
    )
    e.clear()
    assert len(c.evidence_refs) == 1
    with pytest.raises(ValueError):
        CapabilityCheckResult(
            CapabilityId("a:x"), CapabilityAvailability.UNKNOWN, None, ()
        )


def test_boundaries():
    tree = ast.parse(pathlib.Path("src/insarforge/contracts/identity.py").read_text())
    bad = (
        "config",
        "pydantic",
        "yaml",
        "numpy",
        "h5py",
        "osgeo",
        "earthaccess",
        "missions",
        "providers",
        "processors",
        "corrections",
        "analyzers",
        "qc",
    )
    assert not any(
        any(b in (n.module or "") for b in bad)
        for n in ast.walk(tree)
        if isinstance(n, ast.ImportFrom)
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        PluginRef(PluginKind.QC, "x", 1).plugin_id = "y"
