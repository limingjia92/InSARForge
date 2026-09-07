import json
import os
import subprocess
import sys


def test_imports_are_silent_and_lightweight():
    code = """
import contextlib
import io
import json
import logging
import sys

root = logging.getLogger()
before = {"level": root.level, "handlers": [id(handler) for handler in root.handlers]}
stdout = io.StringIO()
stderr = io.StringIO()
with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
    import insarforge
    import insarforge.core.exceptions
    import insarforge.core.logging

package_logger = logging.getLogger("insarforge")
names = ["numpy", "scipy", "osgeo", "h5py", "earthaccess", "isce", "isce3", "mintpy", "yaml", "pydantic", "click", "typer", "rich"]
print(json.dumps({
    "before": before,
    "after_level": root.level,
    "after_handlers": [id(handler) for handler in root.handlers],
    "owned_handlers": [handler.get_name() for handler in package_logger.handlers if handler.get_name() == "insarforge.console"],
    "stdout": stdout.getvalue(),
    "stderr": stderr.getvalue(),
    "heavy": [name for name in names if name in sys.modules],
}))
"""
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        env=environment,
        check=True,
    )
    report = json.loads(result.stdout)
    assert result.stderr == ""
    assert report["before"]["level"] == report["after_level"]
    assert report["before"]["handlers"] == report["after_handlers"]
    assert report["owned_handlers"] == []
    assert report["stdout"] == ""
    assert report["stderr"] == ""
    assert report["heavy"] == []
