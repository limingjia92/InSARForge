"""Override syntax only; eligibility and field rules come from active models."""

from ._values import scan_secrets
from .errors import ConfigurationError
from .yaml_io import MAX_BYTES, parse_value


def parse_entries(entries):
    try:
        size = sum(len(value.encode("utf-8")) for value in entries)
    except (AttributeError, UnicodeError):
        raise ConfigurationError("CONFIG_OVERRIDE") from None
    if len(entries) > 128 or size > MAX_BYTES:
        raise ConfigurationError("CONFIG_OVERRIDE")
    result = []
    seen = set()
    for raw in entries:
        scan_secrets(raw)
        if "=" not in raw:
            raise ConfigurationError("CONFIG_OVERRIDE")
        path, rhs = raw.split("=", 1)
        if not path or path in seen or any(c in path for c in "[]*"):
            raise ConfigurationError("CONFIG_OVERRIDE")
        seen.add(path)
        value = parse_value(rhs)
        # Never retain the unvalidated raw argv in records.
        result.append((path, value))
    return result
