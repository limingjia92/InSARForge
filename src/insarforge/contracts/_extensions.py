"""Private extension mapping validation and ownership under ADR0011."""

from collections.abc import Mapping

from insarforge.contracts.values import FrozenJSON, freeze_json, validate_identifier


def _validate_extension_key(key: str) -> str:
    """Validate namespace:local spelling without interpreting its owner."""
    if type(key) is not str:
        raise TypeError("extension key must be a string")
    if key.count(":") != 1:
        raise ValueError("extension key must contain exactly one colon")
    namespace, local_name = key.split(":")
    for component in (namespace, local_name):
        if ":" in component:
            raise ValueError("extension key components must not contain colons")
        validate_identifier(component)
    return key


def _freeze_extensions(extensions: Mapping[str, object]) -> Mapping[str, FrozenJSON]:
    """Validate every extension key before taking a canonical owned snapshot.

    This explicit mapping contract accepts nested JSON-like mutable input;
    freeze_json owns its conversion to the existing immutable representation.
    """
    if not isinstance(extensions, Mapping):
        raise TypeError("extensions must be a mapping")
    for key in extensions:
        _validate_extension_key(key)
    frozen = freeze_json(extensions)
    if not isinstance(frozen, Mapping):
        raise TypeError("frozen extensions must be a mapping")
    return frozen
