import importlib.metadata
import subprocess
import sys

import pytest

from insarforge.cli import main


def test_main_without_arguments_prints_root_help(capsys):
    assert main([]) == 0
    assert "usage: insarforge" in capsys.readouterr().out


@pytest.mark.parametrize("arguments", [["--help"], []])
def test_module_root_help(arguments):
    result = subprocess.run(
        [sys.executable, "-m", "insarforge", *arguments],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "usage: insarforge" in result.stdout
    assert result.stderr == ""


def test_module_version():
    result = subprocess.run(
        [sys.executable, "-m", "insarforge", "--version"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert result.stdout == f"insarforge {importlib.metadata.version('insarforge')}\n"
    assert result.stderr == ""


def test_doctor(capsys):
    assert main(["doctor"]) == 0
    output = capsys.readouterr().out
    for expected in (
        "InSARForge doctor",
        "Version:",
        "Python:",
        "Core environment: OK",
        "External backend checks: not implemented in Phase 2",
    ):
        assert expected in output


def test_config_without_nested_command_prints_help(capsys):
    assert main(["config"]) == 0
    assert "usage: insarforge config" in capsys.readouterr().out


def test_config_validate_is_phase_2_placeholder(tmp_path, capsys):
    assert main(["config", "validate", str(tmp_path / "example.yaml")]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "Configuration validation is not implemented in Phase 2.\n"


def test_config_validate_missing_path_is_argparse_error(capsys):
    with pytest.raises(SystemExit) as error:
        main(["config", "validate"])
    assert error.value.code == 2
    assert "required: path" in capsys.readouterr().err


def test_console_script_entry_point():
    entries = importlib.metadata.entry_points(
        group="console_scripts", name="insarforge"
    )
    assert len(entries) == 1
    assert next(iter(entries)).value == "insarforge.cli:main"
