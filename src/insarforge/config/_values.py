"""Shared value security and lexical path rules for models, input and saving."""

import os
import posixpath
import re
import unicodedata
from urllib.parse import parse_qsl, urlsplit

from pydantic_core import PydanticCustomError

from .errors import ConfigurationError

SECRET_KEYS = (
    "password",
    "passwd",
    "token",
    "accesstoken",
    "refreshtoken",
    "apikey",
    "secret",
    "clientsecret",
    "privatekey",
    "authorization",
    "cookie",
    "credentials",
    "username",
    "authentication",
)
PEM = re.compile(r"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----")
URL_AUTH = re.compile(r"[a-zA-Z][a-zA-Z0-9+.-]*://[^\s/?#]*@")
URL_SCHEME = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*://")


def _normalize_secret_key(value):
    return re.sub(r"[^a-z0-9]", "", value.lower())


def _is_secret_key(value):
    normalized = _normalize_secret_key(value)
    return any(word in normalized for word in SECRET_KEYS)


def _query_has_secret_key(value):
    if not URL_SCHEME.match(value):
        return False
    try:
        query = urlsplit(value).query.replace(";", "&")
    except ValueError:
        return False
    return any(
        _is_secret_key(key) for key, _ in parse_qsl(query, keep_blank_values=True)
    )


def scan_secrets(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if isinstance(key, str) and _is_secret_key(key):
                raise ConfigurationError("CONFIG_SECRET")
            scan_secrets(key)
            scan_secrets(item)
    elif isinstance(value, list):
        for item in value:
            scan_secrets(item)
    elif isinstance(value, str) and (
        PEM.search(value) or URL_AUTH.search(value) or _query_has_secret_key(value)
    ):
        raise ConfigurationError("CONFIG_SECRET")


def path_string(value):
    if not isinstance(value, str):
        raise PydanticCustomError("CONFIG_TYPE", "string required")
    if (
        not value
        or any(unicodedata.category(c) == "Cc" for c in value)
        or "\\" in value
        or "~" in value
        or re.search(r"\$(?:[A-Za-z_]|\{)", value)
        or value.startswith("//")
        or re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", value)
    ):
        raise PydanticCustomError("CONFIG_PATH", "invalid path")
    return value


def work_path_string(value):
    value = path_string(value)
    if posixpath.normpath(value) == "/":
        raise PydanticCustomError("CONFIG_PATH", "root work directory")
    return value


def absolute_path(value, base):
    """No stat/realpath: even CONFIG's original symlink parent stays lexical."""
    return posixpath.normpath(
        value if posixpath.isabs(value) else posixpath.join(str(base), value)
    )


def source_path(value):
    value = os.fspath(value)
    scan_secrets(value)
    try:
        path_string(value)
    except PydanticCustomError as e:
        raise ConfigurationError(e.type) from None
    return os.path.abspath(value)
