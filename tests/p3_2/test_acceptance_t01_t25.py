import hashlib
import io
import os
import subprocess
import sys
import sysconfig
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import pytest

from insarforge.cli import main
from insarforge.config import legacy
from insarforge.config.errors import ConfigurationError
from insarforge.config.resolution import resolve
from insarforge.config.yaml_io import dump

ROOT = Path(__file__).parents[2]
BASE = (
    "autoInSAR.py --lon 1 --lat 2 --reference_date 20250101 --secondary_date 20250113"
)


def command(tmp_path, text=BASE):
    path = tmp_path / "command.txt"
    path.write_bytes(text.encode())
    return path


def invoke(path, cwd="/srv/job", save=None):
    args = ["config", "translate-legacy", str(path), "--legacy-cwd", cwd]
    if save is not None:
        args += ["--write-dir", str(save)]
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        status = main(args)
    return status, out.getvalue(), err.getvalue()


def test_T01_all_options_have_concrete_targets(tmp_path):
    text = (
        "autoInSAR.py --mode stack --data_source copernicus --lon 1 --lat 2 "
        "--start_date 20230101 --end_date 20230201 --num_proc 0 --platform S1A "
        "--rel_orbit 10 --search_dlonlat 0.2 --roi_dlonlat 0.3 "
        "--zip_check_backend python --step post"
    )
    _, record = legacy.migrate_file(command(tmp_path, text), "/srv/job")
    assert len(record["field_mappings"]) == 13
    assert {item["option"] for item in record["field_mappings"]} >= {
        "mode",
        "step",
        "platform",
    }


def test_T02_both_snapshot_families_are_replayed():
    for name in ("manual_pair", "event_pair", "stack"):
        source = ROOT / "examples/legacy" / f"{name}.command.txt"
        translated, _ = legacy.migrate_file(source, "/__insarforge_fixture__/job")
        translated_path = ROOT / "tests/snapshots/legacy" / f"{name}.translated.yaml"
        resolved_path = ROOT / "tests/snapshots/legacy" / f"{name}.resolved.yaml"
        assert translated == translated_path.read_text()
        requested, resolved, _ = resolve(translated_path)
        assert dump(requested) == translated
        assert dump(resolved) == resolved_path.read_text()


def test_T03_bom_crlf_hashes_original_bytes(tmp_path):
    path = command(tmp_path)
    path.write_bytes(b"\xef\xbb\xbf" + BASE.encode() + b"\r\n")
    _, record = legacy.migrate_file(path, "/srv/job")
    assert record["source"]["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert legacy.translate_text("# harmless | comment\n\n" + BASE, "/srv/job")


def test_T04_lexer_accepts_continuation_and_rejects_interpreter_suffix(tmp_path):
    assert legacy.translate_text(
        "autoInSAR.py \\\n+ --lon 1 --lat 2 --reference_date 20250101 --secondary_date 20250113".replace(
            "+ ", ""
        ),
        "/srv/job",
    )
    with pytest.raises(ConfigurationError):
        legacy.translate_text("python3.wrong " + BASE, "/srv/job")
    with pytest.raises(ConfigurationError):
        legacy.translate_text(
            "~/autoInSAR.py --lon 1 --lat 2 --reference_date 20250101 --secondary_date 20250113",
            "/srv/job",
        )


def test_T05_unknown_missing_duplicate_are_rejected():
    for text in (
        "autoInSAR.py --wat x",
        "autoInSAR.py --lon",
        "autoInSAR.py --lon 1 --lon 2",
    ):
        with pytest.raises(ConfigurationError):
            legacy.translate_text(text, "/srv/job")


def test_T06_alias_conflicts_are_distinguished():
    with pytest.raises(ConfigurationError):
        legacy.translate_text(BASE + " --dlonlat 0.2 --search_dlonlat 0.2", "/srv/job")
    assert legacy.translate_text(BASE + " --dlonlat 0.2 --roi_dlonlat 0", "/srv/job")


def test_T07_geographic_and_width_bounds_fail():
    for suffix in (" --search_dlonlat 10000", " --roi_dlonlat 10000"):
        with pytest.raises(ConfigurationError):
            legacy.translate_text(BASE + suffix, "/srv/job")
    with pytest.raises(ConfigurationError):
        legacy.translate_text(BASE.replace("--lon 1", "--lon 181"), "/srv/job")


def test_T08_date_intent_is_strict():
    with pytest.raises(ConfigurationError):
        legacy.translate_text(
            "autoInSAR.py --lon 1 --lat 2 --event_date 20250101 --reference_date 20250102 --secondary_date 20250103",
            "/srv/job",
        )
    with pytest.raises(ConfigurationError):
        legacy.translate_text(BASE.replace("20250101", "20250132"), "/srv/job")


def test_T09_old_step_choices_are_exact():
    for step in ("search", "download", "orbit", "dem", "process", "all"):
        assert f"stage: {step}" in dump(
            legacy.translate_text(BASE + f" --step {step}", "/srv/job")[0]
        )
    for step in ("prepare", "unwrap", "geocode", "clean"):
        with pytest.raises(ConfigurationError):
            legacy.translate_text(BASE + f" --step {step}", "/srv/job")


def test_T10_platform_and_provider_choices():
    for platform in (
        "Sentinel-1",
        "Sentinel-1A",
        "Sentinel-1B",
        "Sentinel-1C",
        "Sentinel-1D",
        "S1",
        "S1A",
        "S1B",
        "S1C",
        "S1D",
    ):
        assert legacy.translate_text(BASE + f" --platform {platform}", "/srv/job")[0][
            "mission"
        ]["platform"]
    with pytest.raises(ConfigurationError):
        legacy.translate_text(BASE + " --data_source cdse", "/srv/job")


def test_T11_notices_are_structured_and_visible(tmp_path):
    path = command(
        tmp_path, "autoInSAR.py --lon 1 --lat 2 --event_date 20250107 --dlonlat 0.2"
    )
    status, _, stderr = invoke(path)
    assert status == 0
    assert "LEGACY_EVENT_BRACKETING" in stderr and "LEGACY_DEPRECATED_DLONLAT" in stderr
    record = legacy.migrate_file(path, "/srv/job")[1]
    assert all(isinstance(item, dict) for item in record["notices"])


def test_T12_paths_are_normalized_without_task_io(tmp_path):
    text, record = legacy.migrate_file(command(tmp_path), "/srv/a/../job")
    assert "work_dir: /srv/job" in text
    assert record["legacy_cwd"] == "/srv/job"


def test_T13_reader_is_bounded(tmp_path, monkeypatch):
    path = command(tmp_path)
    source_bytes = path.read_bytes()
    reads = []
    original = Path.open

    class Watch(io.BytesIO):
        def read(self, size=-1):
            reads.append(size)
            return super().read(size)

    def watched(self, *args, **kwargs):
        if self == path:
            return Watch(source_bytes)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", watched)
    legacy.migrate_file(path, "/srv/job")
    assert reads and max(reads) <= 1024 * 1024 + 1


def test_T14_shell_syntax_is_never_executed():
    for text in (
        BASE + "; touch /tmp/no",
        BASE + " && id",
        BASE + " $(id)",
        BASE + " > out",
    ):
        with pytest.raises(ConfigurationError):
            legacy.translate_text(text, "/srv/job")


def test_T15_secret_surfaces_are_rejected(tmp_path):
    with pytest.raises(ConfigurationError) as exc:
        legacy.translate_text(BASE, "https://example.invalid/?token=synthetic")
    assert exc.value.code == "CONFIG_SECRET"
    status, _, stderr = invoke(command(tmp_path), "/srv/job", tmp_path / "bad\tname")
    assert status == 1 and "CONFIG_PATH" in stderr


def test_T16_profile_drift_is_not_silently_accepted(tmp_path, monkeypatch):
    from insarforge.config import resolution

    monkeypatch.setitem(resolution.PROVIDER_TIMEOUTS, "asf", 61)
    with pytest.raises(ConfigurationError):
        legacy.migrate_file(command(tmp_path), "/srv/job")


def test_T17_record_has_complete_contract_types(tmp_path):
    record = legacy.migrate_file(command(tmp_path), "/srv/job")[1]
    required = {
        "record_version",
        "status",
        "scope",
        "schema_version",
        "mapping_revision",
        "defaults_revision",
        "insarforge_version",
        "mapping_basis",
        "source",
        "legacy_cwd",
        "explicit_options",
        "field_mappings",
        "synthesized_fields",
        "defaults_used",
        "normalizations",
        "notices",
        "deferred_checks",
        "provenance_limitations",
        "outputs",
    }
    assert required <= record.keys()
    assert record["outputs"]["insarforge.yaml"]


def test_T18_translated_yaml_is_canonically_valid(tmp_path):
    translated, _ = legacy.migrate_file(command(tmp_path), "/srv/job")
    p = tmp_path / "translated.yaml"
    p.write_text(translated)
    resolve(p)


def test_T19_no_save_has_no_files_and_has_output_hash(tmp_path):
    translated, record = legacy.migrate_file(command(tmp_path), "/srv/job")
    assert (
        translated
        and record["outputs"]["insarforge.yaml"]
        == hashlib.sha256(translated.encode()).hexdigest()
    )
    assert list(tmp_path.iterdir()) == [tmp_path / "command.txt"]


def test_T20_exclusive_save_rejects_existing_target(tmp_path):
    target = tmp_path / "out"
    target.mkdir()
    with pytest.raises(ConfigurationError):
        legacy.migrate_file(command(tmp_path), "/srv/job", target)


def test_T21_import_is_lightweight():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import insarforge, insarforge.config, insarforge.config.legacy; assert not any(m.startswith(('insarforge.sar','insarforge.processing')) for m in sys.modules)",
        ],
        capture_output=True,
        text=True,
        env={k: v for k, v in os.environ.items() if k != "PYTHONPATH"},
        timeout=10,
    )
    assert result.returncode == 0 and result.stderr == ""


def test_T22_translation_does_not_execute_legacy_or_network(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "subprocess.run",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("execution")),
    )
    assert legacy.migrate_file(command(tmp_path), "/srv/job")[0]


@pytest.mark.parametrize(
    "name",
    [
        "pair_manual_minimal",
        "pair_event_minimal",
        "stack_minimal",
        "pair_manual_full",
        "pair_event_full",
        "stack_full",
    ],
)
def test_T23_public_examples_validate_and_resolve(name):
    path = ROOT / "examples/config" / f"{name}.yaml"
    assert path.exists()
    resolve(path)


def test_T24_translation_is_deterministic_under_option_reordering():
    a = legacy.translate_text(BASE, "/srv/job")[0]
    b = legacy.translate_text(
        "autoInSAR.py --secondary_date 20250113 --lat 2 --lon 1 --reference_date 20250101",
        "/srv/job",
    )[0]
    assert dump(a) == dump(b)


def test_T25_installed_cli_help_and_version():
    cli = Path(sysconfig.get_path("scripts")) / (
        "insarforge.exe" if os.name == "nt" else "insarforge"
    )
    for args in (("--help",), ("--version",), ("doctor",)):
        result = subprocess.run(
            [str(cli), *args],
            capture_output=True,
            text=True,
            env={k: v for k, v in os.environ.items() if k != "PYTHONPATH"},
            timeout=10,
        )
        assert result.returncode == 0
