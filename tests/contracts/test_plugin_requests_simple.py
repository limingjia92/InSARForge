import dataclasses
from types import MappingProxyType

import pytest
from test_product_models import populated_product

from insarforge.contracts.plugins import (
    AcquireRequest,
    InspectionRequest,
    ProductInput,
    SearchRequest,
    _freeze_artifact_port_map,
    _freeze_artifact_refs,
)
from insarforge.contracts.values import ArtifactRef


def ref(i="r1"):
    return ArtifactRef(i, "schema", 1, None, "manifest", "locator")


def test_inspection_request_freezes_and_validates():
    p = {"nested": {"items": [1]}}
    product = populated_product()
    source = ProductInput(
        ArtifactRef(
            "r1", product.schema_id, product.schema_version, None, "manifest", "locator"
        ),
        product,
    )
    r = InspectionRequest(source, p)
    assert r.source is source
    p["nested"]["items"].append(2)
    assert r.parameters["nested"]["items"] == (1,)
    with pytest.raises(TypeError):
        r.parameters["nested"]["x"] = 1
    with pytest.raises(dataclasses.FrozenInstanceError):
        r.source = source


def test_inspection_invalid_source():
    with pytest.raises(TypeError):
        InspectionRequest("bad", {})


def test_search_request():
    s = {"a": [1]}
    r = SearchRequest("query", 1, s)
    s["a"].append(2)
    assert r.selectors["a"] == (1,)
    for version in (0, -1):
        with pytest.raises(ValueError):
            SearchRequest("q", version, {})
    with pytest.raises(TypeError):
        SearchRequest("q", True, {})
    with pytest.raises(ValueError):
        SearchRequest("", 1, {})


def test_acquire_request():
    p = {"x": [1]}
    r = AcquireRequest(ref(), "entry", p)
    p["x"].append(2)
    assert r.parameters["x"] == (1,)
    with pytest.raises(TypeError):
        AcquireRequest("bad", "entry", {})
    with pytest.raises(ValueError):
        AcquireRequest(ref(), "", {})


def test_private_helpers():
    items = [ref("a"), ref("b")]
    frozen = _freeze_artifact_refs(items)
    items.clear()
    assert [x.record_id for x in frozen] == ["a", "b"]
    with pytest.raises(TypeError):
        _freeze_artifact_refs("x")
    with pytest.raises(TypeError):
        _freeze_artifact_refs(["x"])
    ports = {"z": [ref("a")], "a": [ref("b")]}
    result = _freeze_artifact_port_map(ports)
    ports["z"].clear()
    ports["new"] = []
    assert list(result) == ["z", "a"]
    assert isinstance(result, MappingProxyType)
    with pytest.raises(TypeError):
        result["x"] = ()
    with pytest.raises(ValueError):
        _freeze_artifact_port_map({"": []})
