"""Strict, side-effect-free JSON primitives for planning values."""

from __future__ import annotations

import json
from collections.abc import Mapping

from insarforge.contracts._persistence import _validate_persistence_value
from insarforge.contracts.errors import ContractError
from insarforge.contracts.values import FrozenJSON


def plain(value: FrozenJSON) -> object:
    if isinstance(value, Mapping):
        return {key: plain(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [plain(item) for item in value]
    return value


def canonical(value: dict) -> bytes:
    try:
        _validate_persistence_value(value)
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError):
        raise ContractError("PLAN_JSON_VALUE") from None


def fields(value: object, names: str) -> dict:
    if type(value) is not dict or set(value) != set(names.split()):
        raise ContractError("PLAN_JSON_FIELDS")
    return value


def array(value: object) -> list:
    if type(value) is not list:
        raise ContractError("PLAN_JSON_ARRAY")
    return value


def decode(payload: str | bytes) -> dict:
    if type(payload) not in (str, bytes):
        raise ContractError("PLAN_JSON_TYPE")

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ContractError("PLAN_JSON_DUPLICATE_KEY")
            result[key] = value
        return result

    def constant(_):
        raise ContractError("PLAN_JSON_NONFINITE")

    try:
        if type(payload) is bytes:
            payload = payload.decode("utf-8")
        result = json.loads(payload, object_pairs_hook=pairs, parse_constant=constant)
    except (ValueError, UnicodeError, RecursionError):
        raise ContractError("PLAN_JSON_INVALID") from None
    # Also catches overflow such as 1e999, after construction freezes the values.
    if type(result) is not dict:
        raise ContractError("PLAN_JSON_OBJECT")
    try:
        _validate_persistence_value(result)
    except RecursionError:
        raise ContractError("PLAN_JSON_INVALID") from None
    return result
