import importlib.metadata
import pathlib
import subprocess
import sys

import insarforge


def test_runtime_version_matches_metadata():
    assert insarforge.__version__ == importlib.metadata.version("insarforge")


def test_module_version_output_matches_metadata():
    expected = f"insarforge {importlib.metadata.version('insarforge')}\n"
    result = subprocess.run(
        [sys.executable, "-m", "insarforge", "--version"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert result.stdout == expected
    assert result.stderr == ""


def test_metadata_version_is_not_hard_coded_in_python_source():
    metadata_version = importlib.metadata.version("insarforge")
    source_root = pathlib.Path(__file__).parents[2] / "src" / "insarforge"
    assert all(
        metadata_version not in source.read_text()
        for source in source_root.rglob("*.py")
    )
