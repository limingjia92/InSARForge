import pytest
from test_product_models import populated_product

from insarforge.contracts.plugins import (
    AnalysisRequest,
    CorrectionRequest,
    ProcessingRequest,
    ProductInput,
    QCRequest,
)
from insarforge.contracts.values import ArtifactRef


def ref(i="r"):
    return ArtifactRef(i, "s", 1, None, "m", "l")


def test_processing_and_analysis_freeze():
    product = populated_product()
    paired = ProductInput(
        ArtifactRef("r", product.schema_id, product.schema_version, None, "m", "l"),
        product,
    )
    m = {"in": [paired]}
    auxiliary = {"in": [ref()]}
    p = {"x": [1]}
    r = ProcessingRequest("purpose", "profile", 1, m, [ref("a")], auxiliary, p)
    m["in"].clear()
    auxiliary["in"].clear()
    p["x"].append(2)
    assert r.product_inputs["in"] == (paired,)
    assert r.auxiliary_inputs["in"] == (ref(),)
    assert r.parameters["x"] == (1,)
    a = AnalysisRequest(r.product_inputs, r.auxiliary_inputs, "profile", 1, {})
    assert a.profile_id == "profile"


def test_processing_validation():
    with pytest.raises((TypeError, ValueError)):
        ProcessingRequest("", "p", 1, {}, [], {}, {})
    for v in (0, -1, True):
        with pytest.raises((TypeError, ValueError)):
            ProcessingRequest("x", "p", v, {}, [], {}, {})


def test_correction_validation():
    with pytest.raises(TypeError):
        CorrectionRequest({}, {}, object(), {})


def test_qc_freeze():
    t = [ref()]
    c = [ref("c")]
    th = {"x": [1]}
    p = {"y": [2]}
    r = QCRequest(t, "metrics", 1, th, c, p)
    t.clear()
    c.clear()
    th["x"].append(3)
    p["y"].append(4)
    assert len(r.target_refs) == len(r.comparison_refs) == 1
    assert r.thresholds["x"] == (1,)
    assert r.parameters["y"] == (2,)
