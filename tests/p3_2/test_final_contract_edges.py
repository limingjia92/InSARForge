"""Independent checks of already-frozen P3.2 rules; no production modifications.
Uses only synthetic commands and tmp_path; never executes legacy shell content.
"""

import io
from contextlib import redirect_stderr, redirect_stdout

import pytest

from insarforge.cli import main
from insarforge.config import legacy, models, resolution
from insarforge.config.errors import ConfigurationError

BASE = (
    "autoInSAR.py --lon 1 --lat 2 --reference_date 20250101 --secondary_date 20250113"
)
EVENT = "autoInSAR.py --lon 1 --lat 2 --event_date 20250107"
CWD = "/__insarforge_fixture__/job"


def write_command(tmp_path, text=BASE):
    p = tmp_path / "command.txt"
    p.write_bytes(text.encode("utf-8"))
    return p


@pytest.mark.parametrize(
    "variant",
    [
        BASE.replace("20250101", "2025\\\n0101"),
        BASE.replace("20250101", '"2025\\\n0101"'),
    ],
)
def test_continuation_removes_newline_instead_of_inserting_space(variant):
    # Frozen §3.1: a POSIX backslash-newline is removed, not substituted by space.
    expected = legacy.translate_text(BASE, CWD)[0]
    actual = legacy.translate_text(variant, CWD)[0]
    assert actual == expected


def test_literal_newline_inside_quoted_numeric_argument_is_rejected():
    # Frozen §3.1: real control newlines in ordinary arguments are forbidden.
    text = BASE.replace("--lon 1", '--lon "1\n"')
    with pytest.raises(ConfigurationError):
        legacy.translate_text(text, CWD)


@pytest.mark.parametrize("text", [BASE, EVENT])
def test_selection_field_has_actual_recorded_origin(tmp_path, text):
    _, record = legacy.migrate_file(write_command(tmp_path, text), CWD)
    covered = {p for mapping in record["field_mappings"] for p in mapping["fields"]}
    covered.update(item["path"] for item in record["synthesized_fields"])
    assert "workflow.pair.selection" in covered, covered


@pytest.mark.parametrize(
    "group,key",
    [("synthesized_fields", "path"), ("normalizations", "path"), ("notices", "code")],
)
def test_record_list_sort_order_is_frozen(tmp_path, group, key):
    _, record = legacy.migrate_file(
        write_command(tmp_path, EVENT + " --dlonlat 0.3 --platform S1A"), CWD
    )
    sequence = [entry[key] for entry in record[group]]
    assert sequence == sorted(sequence), sequence


def test_legacy_figure_dpi_is_not_a_p31_origin_label(tmp_path):
    _, record = legacy.migrate_file(write_command(tmp_path), CWD)
    assert (
        record["defaults_used"]["outputs.figures.dpi"]["basis"]
        == "legacy_hardcoded_profile"
    )


def test_changed_legacy_layout_default_is_detected(tmp_path, monkeypatch):
    monkeypatch.setitem(resolution.TASK_DIRECTORIES, "data.paths.slc_dir", "OTHER_SLC")
    with pytest.raises(ConfigurationError) as err:
        legacy.migrate_file(write_command(tmp_path), CWD)
    assert err.value.code == "LEGACY_TRANSLATION"


def test_changed_roi_inheritance_default_is_detected(tmp_path, monkeypatch):
    monkeypatch.setattr(models.Roi.model_fields["half_width_deg"], "default", 0.5)
    with pytest.raises(ConfigurationError) as err:
        legacy.migrate_file(write_command(tmp_path), CWD)
    assert err.value.code == "LEGACY_TRANSLATION"


@pytest.mark.parametrize(
    "prefix",
    [
        '"https://user:SYNTHETIC_REVIEW_ONLY@host.invalid/autoInSAR.py"',
        '"https://host.invalid/autoInSAR.py?access_token=SYNTHETIC_REVIEW_ONLY"',
    ],
)
def test_credential_bearing_prefix_is_safely_rejected(tmp_path, prefix):
    src = write_command(tmp_path, prefix + BASE[len("autoInSAR.py") :])
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = main(["config", "translate-legacy", str(src), "--legacy-cwd", CWD])
    assert code == 1, (code, out.getvalue(), err.getvalue())
    assert out.getvalue() == ""
    assert "CONFIG_SECRET" in err.getvalue()
    assert "SYNTHETIC_REVIEW_ONLY" not in err.getvalue()


def test_plain_uri_is_not_a_posix_script_prefix(tmp_path):
    p = write_command(
        tmp_path, "https://host.invalid/autoInSAR.py" + BASE[len("autoInSAR.py") :]
    )
    with pytest.raises(ConfigurationError):
        legacy.migrate_file(p, CWD)


def test_normalization_entries_do_not_depend_on_option_order(tmp_path):
    a = BASE + " --step config --platform S1A --data_source copernicus"
    b = (
        "autoInSAR.py --data_source copernicus --platform S1A --step config"
        + BASE[len("autoInSAR.py") :]
    )
    p = write_command(tmp_path, a)
    _, ra = legacy.migrate_file(p, CWD)
    p.write_text(b)
    _, rb = legacy.migrate_file(p, CWD)
    # source hash and explicit_options may differ; normalized list has frozen ordering.
    assert ra["normalizations"] == rb["normalizations"]
