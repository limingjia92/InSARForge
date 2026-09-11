"""Configuration command boundaries and explicit exclusive persistence."""

import hashlib
import json
import os
import sys
from pathlib import Path

from pydantic_core import PydanticCustomError

from ._values import absolute_path, path_string, scan_secrets
from .errors import ConfigurationError
from .resolution import resolve
from .yaml_io import dump

VALID = "VALID: configuration only; data/backend checks deferred."


def run_validate(path, overrides):
    try:
        resolve(path, overrides)
    except ConfigurationError as e:
        print(str(e), file=sys.stderr)
        return 1
    except Exception:
        print("CONFIG_INPUT: Unexpected configuration failure.", file=sys.stderr)
        return 1
    print(VALID)
    return 0


def serialize(requested, resolved, record):
    """All serialization, including completion JSON, precedes any mkdir."""
    requested_text = dump(requested)
    resolved_text = dump(resolved)
    saved_record = {
        **record,
        "outputs": {
            "requested_config.yaml": hashlib.sha256(
                requested_text.encode("utf-8")
            ).hexdigest(),
            "resolved_config.yaml": hashlib.sha256(
                resolved_text.encode("utf-8")
            ).hexdigest(),
        },
    }
    scan_secrets(saved_record)
    record_text = (
        json.dumps(
            saved_record, allow_nan=False, ensure_ascii=False, sort_keys=True, indent=2
        )
        + "\n"
    )
    return {
        "requested_config.yaml": requested_text,
        "resolved_config.yaml": resolved_text,
        "config_resolution.json": record_text,
    }


def persist(contents, target):
    """An interrupted new directory may remain; never clean or overwrite it."""
    try:
        target.mkdir(parents=False, exist_ok=False)
        for name, text in contents.items():
            fd = os.open(target / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
                stream.write(text)
    except OSError:
        raise ConfigurationError("CONFIG_WRITE") from None


def explain(record):
    lines = []
    for path, source in record["field_sources"].items():
        deps = ", ".join(source["dependencies"])
        lines.append(
            f"{path}: {source['origin']}" + (f"; dependencies: {deps}" if deps else "")
        )
    for item in record["normalizations"]:
        lines.append(f"{item['path']}: normalization {item['rule']}")
    return "\n".join(lines) + "\n"


def run_resolve(path, overrides, explain=False, write_dir=None):
    try:
        requested, resolved, record = resolve(path, overrides)
        if write_dir is not None:
            scan_secrets(write_dir)
            try:
                path_string(write_dir)
            except PydanticCustomError as e:
                raise ConfigurationError(e.type) from None
            target = Path(absolute_path(write_dir, record["base_directory"]))
        try:
            contents = serialize(requested, resolved, record)
        except ConfigurationError:
            raise
        except Exception:
            raise ConfigurationError("CONFIG_WRITE") from None
        if write_dir is not None:
            persist(contents, target)
        explanation = explain_record(record) if explain else ""
    except ConfigurationError as e:
        print(str(e), file=sys.stderr)
        return 1
    except Exception:
        print("CONFIG_INPUT: Unexpected configuration failure.", file=sys.stderr)
        return 1
    sys.stdout.write(contents["resolved_config.yaml"])
    if explanation:
        sys.stderr.write(explanation)
    if write_dir is not None:
        print("Configuration files saved.", file=sys.stderr)
    return 0


# Avoid shadowing the helper with the frozen CLI flag name.
explain_record = explain
