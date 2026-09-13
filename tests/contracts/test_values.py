import pytest

from insarforge.contracts.values import ArtifactRef, freeze_json, validate_identifier


def test_values_and_artifact():
    src = {"a": [1, {"b": True}]}
    out = freeze_json(src)
    src["a"].append(2)
    assert out["a"] == (1, {"b": True})
    assert isinstance(out["a"], tuple)
    with pytest.raises(TypeError):
        out["a"][1]["b"] = False
    assert list(freeze_json({"x": 1, "y": 2})) == ["x", "y"]
    for x in (float("nan"), float("inf"), b"x", {1}, object()):
        with pytest.raises((TypeError, ValueError)):
            freeze_json(x)
    assert validate_identifier("AbC") == "AbC"
    for x in ("", " a", "a ", "a b", "a\n"):
        with pytest.raises(ValueError):
            validate_identifier(x)
    with pytest.raises(TypeError):
        validate_identifier(1)
    a = ArtifactRef("r", "s", 1, None, "m", "l")
    assert a.semantic_digest is None
    with pytest.raises(ValueError):
        ArtifactRef("r", "s", 0, None, "m", "l")
    with pytest.raises(TypeError):
        ArtifactRef("r", "s", True, None, "m", "l")
