"""Repository regressions for the frozen P3.1 input, CLI, and save contract."""

import contextlib
import copy
import hashlib
import io
import json
import math
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from insarforge.config.cli import run_resolve, run_validate
from insarforge.config.errors import ConfigurationError
from insarforge.config.overrides import parse_entries
from insarforge.config.resolution import resolve
from insarforge.config.yaml_io import (
    MAX_BYTES,
    MAX_DEPTH,
    MAX_NODES,
    dump,
    load_file,
    parse_text,
)

BASE = {
    "schema_version": 1,
    "workflow": {
        "type": "pair",
        "pair": {
            "selection": "manual",
            "reference_date": "2025-01-01",
            "secondary_date": "2025-01-13",
        },
    },
    "data": {"search": {"longitude": 0, "latitude": 0}},
}
EVENT = {
    "schema_version": 1,
    "workflow": {
        "type": "pair",
        "pair": {"selection": "event", "event_date": "2025-01-07"},
    },
    "data": {"search": {"longitude": 0, "latitude": 0}},
}
STACK = {
    "schema_version": 1,
    "workflow": {
        "type": "stack",
        "stack": {"start_date": "2023-01-01", "end_date": "2023-03-01"},
    },
    "data": {"search": {"longitude": 0, "latitude": 0}},
}
SYNTHETIC_MARKER = "SYNTHETIC_REVIEW_TOKEN_703B"
QUERY_KEYS = [
    "access_token",
    "ACCESS-TOKEN",
    "access%5Ftoken",
    "api_key",
    "Api-Key",
    "api%2Dkey",
    "password",
    "PaSs-WoRd",
    "refresh_token",
    "client%5Fsecret",
    "private-key",
]


def set_path(data, path, value):
    current = data
    parts = path.split(".")
    for part in parts[:-1]:
        current = current.setdefault(part, {})
    current[parts[-1]] = value


def write_config(tmp_path, data=None, raw=None, name="config.yaml"):
    path = tmp_path / name
    if raw is None:
        path.write_text(
            json.dumps(data if data is not None else BASE), encoding="utf-8"
        )
    else:
        path.write_bytes(raw)
    return path


def call_cli(function, *args):
    stdout = io.StringIO()
    stderr = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        status = function(*args)
    return status, stdout.getvalue(), stderr.getvalue()


def run_module(tmp_path, *args):
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(
        [sys.executable, "-m", "insarforge", *args],
        capture_output=True,
        text=True,
        cwd=tmp_path,
        env=environment,
        check=False,
        timeout=15,
    )


def assert_error(path, code, overrides=()):
    with pytest.raises(ConfigurationError) as error:
        resolve(path, overrides)
    assert error.value.code == code
    return error.value


@pytest.mark.parametrize(
    "label",
    ["1e2", "+1e2", "1.2e3", "1e-3", ".5e2", "1e2e3"],
    ids=["1e2", "plus-1e2", "1.2e3", "1e-3", "dot-5e2", "repeated-exponent"],
)
def test_numeric_looking_strings_replay_without_type_change(tmp_path, label):
    data = copy.deepcopy(BASE)
    data["project"] = {"name": label}
    path = write_config(tmp_path, data)

    requested, resolved, _record = resolve(path)
    assert requested["project"]["name"] == label
    assert resolved["project"]["name"] == label

    requested_text = dump(requested)
    assert parse_text(requested_text) == requested
    resolved_path = tmp_path / "resolved.yaml"
    resolved_path.write_text(dump(resolved), encoding="utf-8")
    assert resolve(resolved_path)[1] == resolved


def test_scalar_subset_roundtrip_preserves_labels_dates_booleans_null_and_numbers():
    values = parse_text(
        "normal: label\n"
        "date: 2025-01-01\n"
        "boolean: false\n"
        "null_value: null\n"
        "integer: -0\n"
        "scientific: 1e2\n"
        "decimal: -0.0\n"
    )
    replayed = parse_text(dump(values))

    assert replayed == values
    assert isinstance(replayed["normal"], str)
    assert isinstance(replayed["date"], str)
    assert isinstance(replayed["boolean"], bool)
    assert replayed["null_value"] is None
    assert isinstance(replayed["integer"], int) and replayed["integer"] == 0
    assert isinstance(replayed["scientific"], float) and replayed["scientific"] == 100.0
    assert math.copysign(1.0, replayed["decimal"]) == -1.0


def test_float_lexer_accepts_one_exponent_and_leaves_malformed_plain_tokens_as_strings():
    values = parse_text(
        "scientific: 1e2\n"
        "signed_scientific: +1e2\n"
        "decimal_scientific: 1.2e3\n"
        "small_scientific: 1e-3\n"
        "leading_dot: .5e2\n"
        "malformed: 1e2e3\n"
    )

    assert values["scientific"] == 100.0
    assert values["signed_scientific"] == 100.0
    assert values["decimal_scientific"] == 1200.0
    assert values["small_scientific"] == 0.001
    assert values["leading_dot"] == 50.0
    assert values["malformed"] == "1e2e3"


@pytest.mark.parametrize(
    "key", QUERY_KEYS, ids=lambda value: value.replace("%", "encoded-")
)
@pytest.mark.parametrize("via_override", [False, True], ids=["yaml", "override"])
def test_query_credentials_are_rejected_before_validate_resolve_explain_or_save(
    tmp_path, key, via_override
):
    url = f"https://example.invalid/path?{key}={SYNTHETIC_MARKER}"
    data = copy.deepcopy(BASE)
    data["project"] = {"name": "baseline" if via_override else url}
    path = write_config(tmp_path, data)
    overrides = [f"project.name={json.dumps(url)}"] if via_override else []

    error = assert_error(path, "CONFIG_SECRET", overrides)
    assert SYNTHETIC_MARKER not in str(error)

    status, stdout, stderr = call_cli(run_validate, str(path), overrides)
    assert status == 1
    assert stdout == ""
    assert SYNTHETIC_MARKER not in stdout + stderr

    for explain, write_dir in [(False, None), (True, None), (False, "saved")]:
        status, stdout, stderr = call_cli(
            run_resolve, str(path), overrides, explain, write_dir
        )
        assert status == 1
        assert stdout == ""
        assert SYNTHETIC_MARKER not in stdout + stderr
        assert not (tmp_path / "saved").exists()


def test_userinfo_credential_url_remains_blocked_without_echoing_synthetic_value(
    tmp_path,
):
    url = "https://user:SYNTHETIC_PASSWORD@example.invalid/path"
    path = write_config(tmp_path, {**BASE, "project": {"name": url}})

    error = assert_error(path, "CONFIG_SECRET")
    assert "SYNTHETIC_PASSWORD" not in str(error)
    status, stdout, stderr = call_cli(run_validate, str(path), [])
    assert status == 1
    assert stdout == ""
    assert "SYNTHETIC_PASSWORD" not in stdout + stderr


def test_secret_keys_and_private_key_values_are_rejected_without_echo(tmp_path):
    secret_key_data = copy.deepcopy(BASE)
    secret_key_data["synthetic-access-token"] = SYNTHETIC_MARKER
    path = write_config(tmp_path, secret_key_data)
    status, stdout, stderr = call_cli(run_validate, str(path), [])
    assert status == 1
    assert stdout == ""
    assert SYNTHETIC_MARKER not in stdout + stderr

    pem_data = copy.deepcopy(BASE)
    pem_data["project"] = {
        "name": "-----BEGIN PRIVATE KEY----- SYNTHETIC_PRIVATE_VALUE"
    }
    pem_path = write_config(tmp_path, pem_data, name="pem.yaml")
    status, stdout, stderr = call_cli(run_resolve, str(pem_path), [], True, "pem-out")
    assert status == 1
    assert stdout == ""
    assert "SYNTHETIC_PRIVATE_VALUE" not in stdout + stderr
    assert not (tmp_path / "pem-out").exists()


def test_unknown_cli_argument_does_not_echo_a_potential_secret(tmp_path):
    path = write_config(tmp_path)
    result = run_module(
        tmp_path,
        "config",
        "validate",
        str(path),
        f"--access-token={SYNTHETIC_MARKER}",
    )
    assert result.returncode == 2
    assert result.stdout == ""
    assert SYNTHETIC_MARKER not in result.stdout + result.stderr


def test_source_secret_cannot_be_masked_by_a_safe_override(tmp_path):
    data = copy.deepcopy(BASE)
    data["project"] = {
        "name": "https://example.invalid/path?access_token=SYNTHETIC_REVIEW_TOKEN_703B"
    }
    path = write_config(tmp_path, data)

    status, stdout, stderr = call_cli(
        run_resolve, str(path), ['project.name="safe-label"'], False, "masked"
    )
    assert status == 1
    assert stdout == ""
    assert SYNTHETIC_MARKER not in stdout + stderr
    assert not (tmp_path / "masked").exists()


def test_bom_and_crlf_input_are_accepted_and_hash_the_original_bytes(tmp_path):
    text = json.dumps(BASE, indent=2) + "\n"
    raw = b"\xef\xbb\xbf" + text.replace("\n", "\r\n").encode("utf-8")
    path = write_config(tmp_path, raw=raw)

    parsed, digest = load_file(path)
    assert parsed["schema_version"] == 1
    assert digest == hashlib.sha256(raw).hexdigest()
    assert resolve(path)[1]["workflow"]["pair"]["selection"] == "manual"


@pytest.mark.parametrize(
    "raw,code",
    [
        (b"", "CONFIG_SYNTAX"),
        (b"first: 1\n---\nsecond: 2\n", "CONFIG_SYNTAX"),
        (b"- item\n", "CONFIG_TYPE"),
        (b"plain scalar\n", "CONFIG_TYPE"),
        (b"1: value\n", "CONFIG_TYPE"),
    ],
    ids=[
        "empty",
        "multiple-documents",
        "sequence-root",
        "scalar-root",
        "non-string-key",
    ],
)
def test_document_shape_errors_are_stable(tmp_path, raw, code):
    path = write_config(tmp_path, raw=raw)
    assert_error(path, code)


def test_nested_unknown_key_is_rejected(tmp_path):
    data = copy.deepcopy(BASE)
    data["data"]["search"]["unknown_nested"] = 1
    assert_error(write_config(tmp_path, data), "CONFIG_UNKNOWN_KEY")


@pytest.mark.parametrize(
    "text",
    [
        "value: !!str 1\n",
        "value: &anchor 1\n",
        "value: *anchor\n",
        "value: {<<: {nested: 1}}\n",
        "&root [*root]\n",
    ],
    ids=["tag", "anchor", "alias", "merge", "recursive-alias"],
)
def test_forbidden_yaml_features_are_rejected_before_construction(text):
    with pytest.raises(ConfigurationError) as error:
        parse_text(text)
    assert error.value.code in {"CONFIG_SYNTAX", "CONFIG_INPUT"}


def test_yaml_depth_node_and_byte_limits_are_enforced(tmp_path):
    deep = "value: " + "[" * (MAX_DEPTH + 1) + "0" + "]" * (MAX_DEPTH + 1)
    with pytest.raises(ConfigurationError) as depth_error:
        parse_text(deep)
    assert depth_error.value.code == "CONFIG_INPUT"

    many_nodes = "value: [" + ",".join("0" for _ in range(MAX_NODES + 1)) + "]"
    with pytest.raises(ConfigurationError) as node_error:
        parse_text(many_nodes)
    assert node_error.value.code == "CONFIG_INPUT"

    oversized = b"value: " + b"x" * MAX_BYTES
    path = write_config(tmp_path, raw=oversized)
    assert_error(path, "CONFIG_INPUT")


def test_override_count_combined_utf8_bytes_rhs_and_duplicates_are_limited():
    with pytest.raises(ConfigurationError) as count_error:
        parse_entries(["project.name=value"] * 129)
    assert count_error.value.code == "CONFIG_OVERRIDE"

    large_value = "\u6c49" * 200000
    with pytest.raises(ConfigurationError) as bytes_error:
        parse_entries(
            [f"project.name={large_value}", f"project.work_dir={large_value}"]
        )
    assert bytes_error.value.code == "CONFIG_OVERRIDE"

    for entry in (
        "project.name",
        "project.name=",
        "project.name={nested: 1}",
        "project.name=value\n---\nother: 1",
        "project.name=[1, {nested: 1}]",
        "project.name=value",
    ):
        entries = (
            [entry, "project.name=other"] if entry == "project.name=value" else [entry]
        )
        with pytest.raises(ConfigurationError) as rhs_error:
            parse_entries(entries)
        assert rhs_error.value.code in {"CONFIG_OVERRIDE", "CONFIG_SYNTAX"}


def test_illegal_source_value_cannot_be_hidden_by_override(tmp_path):
    data = copy.deepcopy(BASE)
    data["data"]["search"]["latitude"] = 100
    path = write_config(tmp_path, data)

    status, stdout, stderr = call_cli(
        run_validate, str(path), ["data.search.latitude=0"]
    )
    assert status == 1
    assert stdout == ""
    assert stderr.startswith("CONFIG_RANGE")


@pytest.mark.parametrize(
    "profile,data",
    [("manual", BASE), ("event", EVENT), ("stack", STACK)],
    ids=["manual", "event", "stack"],
)
def test_cli_resolve_explain_and_write_dir_cover_all_profiles(tmp_path, profile, data):
    path = write_config(tmp_path, copy.deepcopy(data))
    status, stdout, stderr = call_cli(run_resolve, str(path), [], True, None)
    assert status == 0
    assert stdout.endswith("\n")
    assert "\n" not in stderr or "profile_default" in stderr
    resolved = parse_text(stdout)
    assert resolved["workflow"]["type"] == ("stack" if profile == "stack" else "pair")
    assert "derived" in stderr
    if profile == "event":
        assert "event_date" in resolved["workflow"]["pair"]
    elif profile == "manual":
        assert "reference_date" in resolved["workflow"]["pair"]
    else:
        assert "stack" in resolved["workflow"] and "pair" not in resolved["workflow"]

    status, saved_stdout, saved_stderr = call_cli(
        run_resolve, str(path), [], False, f"{profile}-saved"
    )
    assert status == 0
    assert saved_stdout == stdout
    assert "Configuration files saved." in saved_stderr
    target = tmp_path / f"{profile}-saved"
    assert sorted(item.name for item in target.iterdir()) == [
        "config_resolution.json",
        "requested_config.yaml",
        "resolved_config.yaml",
    ]
    record = json.loads((target / "config_resolution.json").read_text(encoding="utf-8"))
    for name, digest in record["outputs"].items():
        assert hashlib.sha256((target / name).read_bytes()).hexdigest() == digest


def test_default_resolve_writes_no_files_or_task_directories(tmp_path):
    path = write_config(tmp_path)
    before = sorted(item.name for item in tmp_path.iterdir())

    status, stdout, stderr = call_cli(run_resolve, str(path), [], False, None)
    assert status == 0
    assert stdout
    assert stderr == ""
    assert sorted(item.name for item in tmp_path.iterdir()) == before
    assert not any(
        (tmp_path / name).exists() for name in ("SLC", "DEM", "process", "results")
    )


def test_write_dir_requires_new_target_existing_parent_and_no_file_collision(tmp_path):
    path = write_config(tmp_path)

    existing = tmp_path / "existing"
    existing.mkdir()
    status, stdout, stderr = call_cli(run_resolve, str(path), [], False, "existing")
    assert status == 1 and stdout == "" and stderr.startswith("CONFIG_WRITE")
    assert list(existing.iterdir()) == []

    status, stdout, stderr = call_cli(
        run_resolve, str(path), [], False, "missing-parent/target"
    )
    assert status == 1 and stdout == "" and stderr.startswith("CONFIG_WRITE")
    assert not (tmp_path / "missing-parent").exists()

    collision = tmp_path / "collision"
    collision.write_text("SYNTHETIC_KEEP", encoding="utf-8")
    status, stdout, stderr = call_cli(run_resolve, str(path), [], False, "collision")
    assert status == 1 and stdout == "" and stderr.startswith("CONFIG_WRITE")
    assert collision.read_text(encoding="utf-8") == "SYNTHETIC_KEEP"


def test_serialization_failure_happens_before_target_mkdir(tmp_path):
    path = write_config(tmp_path)
    target = tmp_path / "serialization-failure"

    with patch(
        "insarforge.config.cli.json.dumps", side_effect=TypeError("synthetic failure")
    ):
        status, stdout, stderr = call_cli(
            run_resolve, str(path), [], False, "serialization-failure"
        )

    assert status == 1
    assert stdout == ""
    assert stderr.startswith("CONFIG_WRITE")
    assert not target.exists()


def test_file_creation_is_exclusive_and_completion_record_is_last(tmp_path):
    path = write_config(tmp_path)
    target = tmp_path / "exclusive"
    real_mkdir = Path.mkdir

    def inject_collision(directory, *args, **kwargs):
        result = real_mkdir(directory, *args, **kwargs)
        if directory == target:
            (directory / "requested_config.yaml").write_text(
                "SYNTHETIC_KEEP", encoding="utf-8"
            )
        return result

    with patch.object(Path, "mkdir", inject_collision):
        status, stdout, stderr = call_cli(
            run_resolve, str(path), [], False, "exclusive"
        )
    assert status == 1
    assert stdout == ""
    assert stderr.startswith("CONFIG_WRITE")
    assert (target / "requested_config.yaml").read_text(
        encoding="utf-8"
    ) == "SYNTHETIC_KEEP"
    assert not (target / "config_resolution.json").exists()

    ordered_target = tmp_path / "ordered"
    calls = []
    real_open = os.open

    def record_open(filename, flags, mode=0o777):
        calls.append(Path(filename).name)
        return real_open(filename, flags, mode)

    with patch("insarforge.config.cli.os.open", side_effect=record_open):
        status, stdout, stderr = call_cli(run_resolve, str(path), [], False, "ordered")
    assert status == 0
    assert stderr == "Configuration files saved.\n"
    assert calls == [
        "requested_config.yaml",
        "resolved_config.yaml",
        "config_resolution.json",
    ]
    assert ordered_target.exists()


def test_partial_write_leaves_only_written_files_and_preserves_input(tmp_path):
    path = write_config(tmp_path)
    original = path.read_bytes()
    target = tmp_path / "partial"
    calls = []
    real_open = os.open

    def fail_on_second(filename, flags, mode=0o777):
        calls.append(Path(filename).name)
        if len(calls) == 2:
            raise OSError("synthetic write failure")
        return real_open(filename, flags, mode)

    with patch("insarforge.config.cli.os.open", side_effect=fail_on_second):
        status, stdout, stderr = call_cli(run_resolve, str(path), [], False, "partial")

    assert status == 1
    assert stdout == ""
    assert stderr.startswith("CONFIG_WRITE")
    assert path.read_bytes() == original
    assert sorted(item.name for item in target.iterdir()) == ["requested_config.yaml"]
    assert calls == ["requested_config.yaml", "resolved_config.yaml"]


@pytest.mark.parametrize(
    "arguments",
    [
        ["config", "--help"],
        ["config", "validate", "--help"],
        ["config", "resolve", "--help"],
    ],
    ids=["config-help", "validate-help", "resolve-help"],
)
def test_config_help_is_available_without_reading_a_file(tmp_path, arguments):
    result = run_module(tmp_path, *arguments)
    assert result.returncode == 0
    assert "usage: insarforge" in result.stdout
    assert result.stderr == ""


def test_cli_status_contract_for_success_input_error_and_syntax_error(tmp_path):
    path = write_config(tmp_path)
    valid = run_module(tmp_path, "config", "validate", str(path))
    assert valid.returncode == 0
    assert valid.stdout == "VALID: configuration only; data/backend checks deferred.\n"
    assert valid.stderr == ""

    resolved = run_module(tmp_path, "config", "resolve", str(path))
    assert resolved.returncode == 0
    assert resolved.stderr == ""
    assert parse_text(resolved.stdout)["schema_version"] == 1

    missing = run_module(tmp_path, "config", "validate", str(tmp_path / "missing.yaml"))
    assert missing.returncode == 1
    assert missing.stdout == ""
    assert missing.stderr.startswith("CONFIG_INPUT:")

    malformed_path = write_config(tmp_path, raw=b"key: [")
    malformed = run_module(tmp_path, "config", "validate", str(malformed_path))
    assert malformed.returncode == 1
    assert malformed.stdout == ""
    assert malformed.stderr.startswith("CONFIG_SYNTAX:")
    assert "key:" not in malformed.stderr

    missing_argument = run_module(tmp_path, "config", "validate")
    assert missing_argument.returncode == 2
    assert missing_argument.stdout == ""
    assert "required: path" in missing_argument.stderr


def test_config_execution_does_not_import_sar_or_call_external_boundaries(tmp_path):
    code = """
import contextlib
import io
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

from insarforge.config.cli import run_validate

path = Path(sys.argv[1])
stdout = io.StringIO()
stderr = io.StringIO()
real_open = Path.open

def guarded_open(current, *args, **kwargs):
    if current != path:
        raise AssertionError("unexpected file read")
    return real_open(current, *args, **kwargs)

real_getenv = os.getenv

def guarded_getenv(key, default=None):
    if key.lower() in {
        "asf_username",
        "asf_password",
        "cdse_username",
        "cdse_password",
        "earthdata_username",
        "earthdata_password",
        "netrc",
    }:
        raise AssertionError("credential env")
    return real_getenv(key, default)

with (
    contextlib.redirect_stdout(stdout),
    contextlib.redirect_stderr(stderr),
    patch("socket.create_connection", side_effect=AssertionError("network")),
    patch("socket.socket.connect", side_effect=AssertionError("network")),
    patch("subprocess.run", side_effect=AssertionError("external tool")),
    patch("subprocess.Popen", side_effect=AssertionError("external tool")),
    patch.object(os, "getenv", guarded_getenv),
    patch.object(Path, "open", guarded_open),
):
    status = run_validate(str(path), [])

heavy = {
    "numpy",
    "scipy",
    "osgeo",
    "h5py",
    "earthaccess",
    "isce",
    "isce3",
    "mintpy",
    "requests",
}
print(json.dumps({
    "status": status,
    "stdout": stdout.getvalue(),
    "stderr": stderr.getvalue(),
    "heavy": sorted(name for name in heavy if name in sys.modules),
}))
"""
    path = write_config(tmp_path)
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    result = subprocess.run(
        [sys.executable, "-c", code, str(path)],
        capture_output=True,
        text=True,
        cwd=tmp_path,
        env=environment,
        check=False,
        timeout=15,
    )
    assert result.returncode == 0
    report = json.loads(result.stdout)
    assert report == {
        "status": 0,
        "stdout": "VALID: configuration only; data/backend checks deferred.\n",
        "stderr": "",
        "heavy": [],
    }
