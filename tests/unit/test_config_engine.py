import pytest

from insarforge.config.errors import ConfigurationError
from insarforge.config.resolution import resolve
from insarforge.config.yaml_io import parse_text


def manual():
    return {
        "schema_version": 1,
        "workflow": {
            "type": "pair",
            "pair": {
                "selection": "manual",
                "reference_date": "20250101",
                "secondary_date": "20250113",
            },
        },
        "data": {"search": {"longitude": 0, "latitude": 0}},
        "processing": {"isce2": {}},
    }


def write(tmp_path, text):
    p = tmp_path / "config.yaml"
    p.write_text(text, encoding="utf-8")
    return p


def test_minimal_pair_resolution_and_sparse_request(tmp_path):
    p = write(
        tmp_path,
        "schema_version: 1\nworkflow:\n  type: pair\n  pair:\n    selection: manual\n    reference_date: '20250101'\n    secondary_date: '20250113'\ndata:\n  search: {longitude: 0, latitude: 0}\nprocessing:\n  isce2: {}\n",
    )
    requested, resolved, record = resolve(p)
    assert requested["data"]["search"]["longitude"] == 0
    assert "catalog" not in requested["data"]
    assert resolved["workflow"]["pair"]["reference_date"] == "2025-01-01"
    assert resolved["workflow"].get("stack") is None
    assert record["field_sources"]


def test_missing_version_rejected(tmp_path):
    p = write(
        tmp_path,
        "workflow: {type: pair, pair: {selection: manual, reference_date: '2025-01-01', secondary_date: '2025-01-13'}}\ndata: {search: {longitude: 0, latitude: 0}}\nprocessing: {isce2: {}}\n",
    )
    with pytest.raises(ConfigurationError) as e:
        resolve(p)
    assert e.value.code == "CONFIG_VERSION"


@pytest.mark.parametrize(
    "text",
    [
        "a: yes\n",
        "a: 0x14\n",
        "a: 020\n",
        "a: 2_0\n",
        "a: !!str 1\n",
        "a: &x 1\nb: *x\n",
    ],
)
def test_yaml_subset_rejects_or_preserves_ambiguous_scalars(text):
    if "!!str" in text or "&x" in text:
        with pytest.raises(ConfigurationError):
            parse_text(text)
    else:
        parsed = parse_text(text)
        assert isinstance(parsed["a"], str)


def test_duplicate_nested_key_rejected():
    with pytest.raises(ConfigurationError) as e:
        parse_text("a:\n  x: 1\n  x: 2\n")
    assert e.value.code == "CONFIG_DUPLICATE_KEY"


def test_override_can_fill_defaulted_leaf(tmp_path):
    p = write(
        tmp_path,
        "schema_version: 1\nworkflow: {type: pair, pair: {selection: manual, reference_date: '2025-01-01', secondary_date: '2025-01-13'}}\ndata: {search: {longitude: 0, latitude: 0}}\nprocessing: {isce2: {}}\n",
    )
    _, resolved, _ = resolve(p, ["processing.isce2.pair.range_looks=10"])
    assert resolved["processing"]["isce2"]["pair"]["range_looks"] == 10
