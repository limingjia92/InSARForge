"""Recognizable-secret checks for explicit record serialization projections."""

import re
from collections.abc import Mapping
from urllib.parse import parse_qsl, urlsplit

from insarforge.contracts.errors import ContractError
from insarforge.contracts.values import FrozenJSON

# Keep the Phase-3 recognizable patterns without importing its Pydantic boundary.
_SECRET_KEYS = (
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
_PEM = re.compile(r"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----")
_URL_AUTH = re.compile(r"[a-zA-Z][a-zA-Z0-9+.-]*://[^\s/?#]*@")
_URL_SCHEME = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*://")
# Additional credential/signed-query forms already rejected by AssetLocation.
_CREDENTIAL_QUERY_KEYS = frozenset(
    {
        "auth",
        "credential",
        "signature",
        "sig",
        "x-amz-signature",
        "x-amz-credential",
        "x-amz-security-token",
        "x-goog-signature",
        "x-goog-credential",
        "x-amz-algorithm",
        "x-amz-date",
        "x-amz-expires",
    }
)


def _is_secret_key(value: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]", "", value.lower())
    return any(word in normalized for word in _SECRET_KEYS)


def _query_has_secret_key(value: str) -> bool:
    if not _URL_SCHEME.match(value):
        return False
    try:
        query = urlsplit(value).query.replace(";", "&")
    except ValueError:
        return False
    return any(
        _is_secret_key(key) or key.lower() in _CREDENTIAL_QUERY_KEYS
        for key, _ in parse_qsl(query, keep_blank_values=True)
    )


def _validate_persistence_value(value: FrozenJSON) -> None:
    """Reject known secret forms without changing or disclosing record values.

    Call only on an existing codec's explicit JSON projection. This does not
    discover secrets, validate schemas, or inspect arbitrary domain objects.
    """
    if isinstance(value, Mapping):
        for key, item in value.items():
            if isinstance(key, str) and _is_secret_key(key):
                raise ContractError("PERSISTENCE_SECRET")
            _validate_persistence_value(key)
            _validate_persistence_value(item)
    elif isinstance(value, (tuple, list)):
        for item in value:
            _validate_persistence_value(item)
    elif isinstance(value, str) and (
        _PEM.search(value) or _URL_AUTH.search(value) or _query_has_secret_key(value)
    ):
        raise ContractError("PERSISTENCE_SECRET")
