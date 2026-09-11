"""Bounded private YAML subset and deterministic serialization."""

import hashlib
import re
from pathlib import Path

import yaml
from yaml.events import AliasEvent, MappingStartEvent, SequenceStartEvent

from ._values import scan_secrets
from .errors import ConfigurationError, issue

MAX_BYTES = 1024 * 1024
MAX_DEPTH = 32
MAX_NODES = 20000

_NULL = re.compile(r"^(?:null|~|)$")
_BOOL = re.compile(r"^(?:true|false)$")
_INT = re.compile(r"^[-+]?(?:0|[1-9][0-9]*)$")
_FLOAT = re.compile(
    r"^[-+]?(?:(?:(?:0|[1-9][0-9]*)\.[0-9]*|\.[0-9]+)"
    r"(?:[eE][-+]?[0-9]+)?|(?:0|[1-9][0-9]*)[eE][-+]?[0-9]+)$"
)
_DATE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")


class Loader(yaml.SafeLoader):
    """Reject forbidden events during composition, before object construction."""

    yaml_implicit_resolvers = {}

    def __init__(self, stream):
        super().__init__(stream)
        self._depth = 0
        self._nodes = 0

    def compose_node(self, parent, index):
        event = self.peek_event()
        if (
            isinstance(event, AliasEvent)
            or getattr(event, "anchor", None)
            or getattr(event, "tag", None)
        ):
            raise ConfigurationError("CONFIG_SYNTAX")
        self._nodes += 1
        container = isinstance(event, (MappingStartEvent, SequenceStartEvent))
        if container:
            self._depth += 1
        if self._nodes > MAX_NODES or self._depth > MAX_DEPTH:
            raise ConfigurationError("CONFIG_INPUT")
        try:
            return super().compose_node(parent, index)
        finally:
            if container:
                self._depth -= 1


def mapping(loader, node, deep=False):
    result = {}
    for kn, vn in node.value:
        if kn.tag != "tag:yaml.org,2002:str":
            raise ConfigurationError("CONFIG_TYPE")
        key = loader.construct_scalar(kn)
        if key == "<<":
            raise ConfigurationError("CONFIG_SYNTAX")
        if key in result:
            raise ConfigurationError(
                issues=[
                    issue(
                        "CONFIG_DUPLICATE_KEY",
                        line=kn.start_mark.line + 1,
                        column=kn.start_mark.column + 1,
                    )
                ]
            )
        scan_secrets({key: None})
        result[key] = loader.construct_object(vn, deep=deep)
    return result


Loader.add_constructor("tag:yaml.org,2002:map", mapping)
Loader.add_implicit_resolver("tag:yaml.org,2002:null", _NULL, ["n", "~", ""])
Loader.add_implicit_resolver("tag:yaml.org,2002:bool", _BOOL, list("tf"))
Loader.add_implicit_resolver(
    "tag:yaml.org,2002:int",
    _INT,
    list("-+0123456789"),
)
# No octal, underscores or ambiguous leading zeros in either number grammar.
Loader.add_implicit_resolver(
    "tag:yaml.org,2002:float",
    _FLOAT,
    list("-+0123456789."),
)


def _parse(text):
    try:
        if not isinstance(text, str) or len(text.encode("utf-8")) > MAX_BYTES:
            raise ConfigurationError("CONFIG_INPUT")
        if text.startswith("\ufeff"):
            text = text[1:]
        if text.startswith("\ufeff"):
            raise ConfigurationError("CONFIG_SYNTAX")
        loader = Loader(text)
        try:
            # get_single_node rejects a second document before construction.
            node = loader.get_single_node()
            if node is None:
                raise ConfigurationError("CONFIG_SYNTAX")
            value = loader.construct_document(node)
        finally:
            loader.dispose()
    except ConfigurationError:
        raise
    except (yaml.YAMLError, ValueError, UnicodeError, RecursionError, OverflowError):
        raise ConfigurationError("CONFIG_SYNTAX") from None
    scan_secrets(value)
    return value


def parse_text(text):
    value = _parse(text)
    if not isinstance(value, dict):
        raise ConfigurationError("CONFIG_TYPE")
    return value


def parse_value(text):
    """Consume the entire RHS; maps anywhere are not scalar/leaf-list syntax."""
    if not text.strip():
        raise ConfigurationError("CONFIG_OVERRIDE")
    value = _parse(text)

    def no_maps(item):
        if isinstance(item, dict):
            raise ConfigurationError("CONFIG_OVERRIDE")
        if isinstance(item, list):
            for child in item:
                no_maps(child)

    no_maps(value)
    return value


def load_file(path):
    try:
        with Path(path).open("rb") as stream:
            data = stream.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            raise ConfigurationError("CONFIG_INPUT")
        text = data.decode("utf-8-sig")
        # A second BOM must not be stripped by _parse.
        if text.startswith("\ufeff"):
            raise ConfigurationError("CONFIG_SYNTAX")
    except ConfigurationError:
        raise
    except (OSError, UnicodeError, TypeError, ValueError):
        raise ConfigurationError("CONFIG_INPUT") from None
    return parse_text(text), hashlib.sha256(data).hexdigest()


class Dumper(yaml.SafeDumper):
    def ignore_aliases(self, data):
        return True

    def increase_indent(self, flow=False, indentless=False):
        return super().increase_indent(flow, False)


def _string(dumper, value):
    style = (
        "'"
        if any(
            pattern.fullmatch(value) for pattern in (_NULL, _BOOL, _INT, _FLOAT, _DATE)
        )
        else None
    )
    return dumper.represent_scalar("tag:yaml.org,2002:str", value, style=style)


Dumper.add_representer(str, _string)
Dumper.add_representer(
    type(None),
    lambda dumper, value: dumper.represent_scalar("tag:yaml.org,2002:null", "null"),
)


def dump(data):
    scan_secrets(data)
    return (
        yaml.dump(
            data,
            Dumper=Dumper,
            allow_unicode=True,
            sort_keys=False,
            default_flow_style=False,
            indent=2,
            width=4096,
        ).rstrip("\n")
        + "\n"
    )
