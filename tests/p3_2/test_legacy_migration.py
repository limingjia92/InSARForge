from pathlib import Path

import pytest

from insarforge.config.errors import ConfigurationError
from insarforge.config.legacy import translate_text
from insarforge.config.yaml_io import dump

ROOT = Path(__file__).parents[2]
FIX = ROOT / "examples/legacy"


def test_three_frozen_commands_and_snapshots():
    for name in ("manual_pair", "event_pair", "stack"):
        text = (FIX / f"{name}.command.txt").read_text()
        y, _ = translate_text(text, "/__insarforge_fixture__/job")
        assert y
        assert (
            dump(y)
            == (ROOT / f"tests/snapshots/legacy/{name}.translated.yaml").read_text()
        )


def test_all_options_and_aliases():
    text = "autoInSAR.py --mode stack --data_source copernicus --lon 0 --lat 0 --start_date 20230101 --end_date 20230201 --num_proc 2 --platform S1A --rel_orbit 10 --search_dlonlat 0.2 --roi_dlonlat 0.3 --zip_check_backend python --step post"
    y, _ = translate_text(text, "/tmp/job")
    assert y["data"]["provider"] == "cdse" and y["mission"]["platform"] == "Sentinel-1A"


def test_adversarial_inputs():
    bad = [
        "",
        "autoInSAR.py --wat x",
        "autoInSAR.py --lon",
        "autoInSAR.py --lon 0 --lon 1",
        "autoInSAR.py --lon 0; echo x",
        "autoInSAR.py --lon $(id)",
        "autoInSAR.py --lon 0 > x",
        "autoInSAR.py --mode pair --lon 0 --lat 0 --event_date 20230101 --reference_date 20230102 --secondary_date 20230103",
    ]
    for text in bad:
        with pytest.raises(ConfigurationError):
            translate_text(text, "/tmp/job")


def test_order_deterministic():
    a, _ = translate_text(
        "autoInSAR.py --lon 1 --lat 2 --reference_date 20230101 --secondary_date 20230102",
        "/tmp/j",
    )
    b, _ = translate_text(
        "autoInSAR.py --secondary_date 20230102 --lat 2 --lon 1 --reference_date 20230101",
        "/tmp/j",
    )
    assert a == b
