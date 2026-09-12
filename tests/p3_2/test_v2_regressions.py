"""Review-side regressions for existing P3.2 contract, not new public semantics.

Run against the installed candidate. These checks never execute legacy commands
or contact services; filesystem writes remain inside pytest tmp_path.
"""

import contextlib
import io
import json
from pathlib import Path

import pytest

from insarforge.cli import main
from insarforge.config import legacy

BASE = (
    "autoInSAR.py --lon 1 --lat 2 --reference_date 20250101 --secondary_date 20250113"
)
CWD = "/__insarforge_fixture__/job"


def invoke(path, cwd=CWD, save=None):
    args = ["config", "translate-legacy", str(path), "--legacy-cwd", cwd]
    if save is not None:
        args.extend(["--write-dir", str(save)])
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        result = main(args)
    return result, out.getvalue(), err.getvalue()


def command(tmp_path, suffix=""):
    path = tmp_path / "command.txt"
    path.write_text(BASE + suffix + "\n", encoding="utf-8")
    return path


@pytest.mark.parametrize("step", ["search", "orbit", "dem"])
def test_legitimate_old_steps_remain_accepted(tmp_path, step):
    result, out, err = invoke(command(tmp_path, " --step " + step))
    assert result == 0, err
    assert "stage: " + step in out


@pytest.mark.parametrize("step", ["prepare", "unwrap", "geocode"])
def test_nonlegacy_steps_are_not_accepted(tmp_path, step):
    result, out, _err = invoke(command(tmp_path, " --step " + step))
    assert result == 1
    assert out == ""


def test_input_read_is_bounded_before_allocation(tmp_path, monkeypatch):
    source = command(tmp_path)
    reads = []
    original_open = Path.open

    class WatchedInput(io.BytesIO):
        def read(self, size=-1):
            reads.append(size)
            return super().read(size)

    def watch_open(self, *args, **kwargs):
        if self == source:
            return WatchedInput((BASE + "\n").encode("utf-8"))
        return original_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", watch_open)
    result, _out, _err = invoke(source)
    assert result == 0
    assert reads
    assert all(0 < size <= 1024 * 1024 + 1 for size in reads), reads


def test_legacy_cwd_is_already_absolute_not_guessed(tmp_path):
    result, out, err = invoke(command(tmp_path), "relative/job")
    assert result == 1
    assert out == ""
    assert "CONFIG_PATH" in err


def test_record_cwd_is_same_normalized_value_as_yaml(tmp_path):
    path = command(tmp_path)
    text, record = legacy.migrate_file(path, "/srv/a/../job")
    assert "work_dir: /srv/job" in text
    assert record["legacy_cwd"] == "/srv/job"


def test_saving_does_not_change_complete_record(tmp_path):
    path = command(tmp_path)
    yaml1, record1 = legacy.migrate_file(path, CWD)
    yaml2, record2 = legacy.migrate_file(path, CWD, tmp_path / "output")
    assert yaml1 == yaml2
    assert record1 == record2


def test_save_directory_path_validation_is_not_skipped(tmp_path):
    target = tmp_path / "bad\tname"
    result, out, err = invoke(command(tmp_path), save=target)
    assert result == 1
    assert out == ""
    assert "CONFIG_PATH" in err
    assert not target.exists()


def test_default_record_contains_actual_derived_values(tmp_path):
    _text, record = legacy.migrate_file(command(tmp_path), CWD)
    defaults = record["defaults_used"]
    assert isinstance(defaults, dict)
    assert defaults["processing.roi.half_width_deg"]["value"] == 0.2
    assert defaults["processing.roi.half_width_deg"]["dependencies"] == [
        "data.search.half_width_deg"
    ]


def test_mapping_basis_identifies_mapping_not_execution(tmp_path):
    _text, record = legacy.migrate_file(command(tmp_path), CWD)
    assert isinstance(record["mapping_basis"], dict)
    assert record["mapping_basis"]["command_version_inferred"] is False


def test_record_outputs_include_hash_without_save(tmp_path):
    import hashlib

    text, record = legacy.migrate_file(command(tmp_path), CWD)
    assert (
        record["outputs"]["insarforge.yaml"]
        == hashlib.sha256(text.encode("utf-8")).hexdigest()
    )


def test_record_json_serializes_before_directory_creation(tmp_path, monkeypatch):
    source = command(tmp_path)
    target = tmp_path / "out"

    def fail_serialization(*args, **kwargs):
        raise TypeError("SYNTHETIC_SERIALIZATION_ONLY")

    monkeypatch.setattr(json, "dumps", fail_serialization)
    result, out, err = invoke(source, save=target)
    assert result == 1
    assert out == ""
    assert "SYNTHETIC_SERIALIZATION_ONLY" not in err
    assert not target.exists()
