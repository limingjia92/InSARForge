import math

import pytest

from insarforge.products.serialization import canonical_json_bytes, strict_json_loads


def test_canonical_order_unicode():
    assert canonical_json_bytes({"b": 1, "a": "é"}) == '{"a":"é","b":1}'.encode()


def test_strict_json():
    assert strict_json_loads(b'{"a":[1]}')["a"] == (1,)
    with pytest.raises(ValueError):
        strict_json_loads('{"a":1,"a":2}')
    with pytest.raises(ValueError):
        strict_json_loads('{"a":NaN}')


def test_unsupported():
    with pytest.raises(TypeError):
        canonical_json_bytes({1: "x"})
    with pytest.raises(TypeError):
        canonical_json_bytes({"x": object()})
    with pytest.raises(TypeError):
        canonical_json_bytes({"x": math.nan})
