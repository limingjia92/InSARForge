"""Safe, stable configuration issues; no raw parser or model diagnostics."""

from ..core.exceptions import InSARForgeError

MESSAGES = {
    "CONFIG_INPUT": "Unable to read configuration or input limit exceeded.",
    "CONFIG_SYNTAX": "Unsupported or invalid YAML syntax.",
    "CONFIG_DUPLICATE_KEY": "Duplicate mapping key.",
    "CONFIG_UNKNOWN_KEY": "Unknown configuration field.",
    "CONFIG_TYPE": "Incorrect value or mapping type.",
    "CONFIG_RANGE": "Value outside the supported range or syntax.",
    "CONFIG_REQUIRED": "Required configuration information is missing.",
    "CONFIG_CONFLICT": "Conflicting configuration intentions.",
    "CONFIG_VERSION": "An explicit integer schema_version of 1 is required.",
    "CONFIG_UNSUPPORTED": "Unsupported configuration choice.",
    "CONFIG_OVERRIDE": "Invalid, duplicate or forbidden override.",
    "CONFIG_PATH": "Invalid POSIX path or configuration path collision.",
    "CONFIG_SECRET": "Recognizable credential material is forbidden.",
    "CONFIG_WRITE": "Unable to save; a new incomplete output directory may remain.",
    "LEGACY_TRANSLATION": "Legacy command cannot be migrated safely.",
}


class ConfigurationError(InSARForgeError):
    """Application exception containing only sanitized issue dictionaries."""

    def __init__(self, code="CONFIG_INPUT", message=None, path="", *, issues=None):
        self.issues = sorted(
            issues or [issue(code, path)],
            key=lambda x: (x["path"], x["code"], x.get("line", 0)),
        )
        first = self.issues[0]
        self.code, self.path, self.message = (
            first["code"],
            first["path"],
            first["message"],
        )
        super().__init__(
            "\n".join(
                f"{x['code']}{' [' + x['path'] + ']' if x['path'] else ''}: {x['message']}"
                for x in self.issues
            )
        )


def issue(code, path="", line=None, column=None):
    result = {"path": path, "code": code, "message": MESSAGES[code]}
    if line is not None:
        result["line"] = line
    if column is not None:
        result["column"] = column
    return result


def model_issues(error, path=""):
    """The caller supplies a schema-known path; never copy input, ctx or loc."""
    out = []
    for e in error.errors(
        include_input=False, include_context=False, include_url=False
    ):
        kind = e["type"]
        if kind in MESSAGES:
            code = kind
        elif kind == "missing":
            code = "CONFIG_REQUIRED"
        elif kind == "extra_forbidden":
            code = "CONFIG_UNKNOWN_KEY"
        elif kind == "literal_error":
            code = "CONFIG_UNSUPPORTED"
        elif kind in {
            "greater_than",
            "greater_than_equal",
            "less_than",
            "less_than_equal",
            "too_short",
            "too_long",
            "finite_number",
            "value_error",
            "string_pattern_mismatch",
        }:
            code = "CONFIG_RANGE"
        else:
            code = "CONFIG_TYPE"
        out.append(issue(code, path))
    return out
