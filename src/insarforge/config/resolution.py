"""Sparse validation, applicable defaults and configuration-only resolution."""

import copy

from pydantic import TypeAdapter, ValidationError

from .._version import __version__
from ._values import absolute_path, scan_secrets, source_path
from .errors import ConfigurationError, issue, model_issues
from .models import (
    DEFAULTS_REVISION,
    DEFERRED_CHECKS,
    FORBIDDEN_OVERRIDES,
    PROFILES,
    PROVIDER_TIMEOUTS,
    TASK_DIRECTORIES,
    Config,
    Model,
    Selection,
    Version,
    WorkflowCommon,
    WorkflowType,
)
from .overrides import parse_entries
from .yaml_io import load_file


def child_model(field):
    annotation = field.annotation
    return (
        annotation
        if isinstance(annotation, type) and issubclass(annotation, Model)
        else None
    )


def fields_of(schema, prefix="", include_mappings=False):
    result = {}
    for name, field in schema.model_fields.items():
        path = f"{prefix}.{name}" if prefix else name
        child = child_model(field)
        if include_mappings or child is None:
            result[path] = field
        if child:
            result.update(fields_of(child, path, include_mappings))
    return result


def leaf_value(field, value, path):
    annotation = field.rebuild_annotation()
    try:
        return TypeAdapter(annotation).validate_python(value, strict=True)
    except ValidationError as e:
        raise ConfigurationError(issues=model_issues(e, path)) from None


def _selector(annotation, value, path):
    try:
        return TypeAdapter(annotation).validate_python(value, strict=True)
    except ValidationError as e:
        raise ConfigurationError(issues=model_issues(e, path)) from None


def select_schema(raw):
    if "schema_version" not in raw:
        raise ConfigurationError("CONFIG_VERSION")
    _selector(Version, raw["schema_version"], "schema_version")
    workflow = raw.get("workflow", {})
    if not isinstance(workflow, dict):
        raise ConfigurationError("CONFIG_TYPE", path="workflow")
    typ = _selector(
        WorkflowType,
        workflow.get("type", WorkflowCommon.model_fields["type"].default),
        "workflow.type",
    )
    if typ == "stack":
        return PROFILES["stack"]
    pair = workflow.get("pair", {})
    if not isinstance(pair, dict):
        raise ConfigurationError("CONFIG_TYPE", path="workflow.pair")
    if "selection" not in pair:
        raise ConfigurationError("CONFIG_REQUIRED", path="workflow.pair.selection")
    selection = _selector(Selection, pair["selection"], "workflow.pair.selection")
    return PROFILES[selection]


def validate_sparse(schema, raw, prefix=""):
    """Recurse model fields; no defaults, required checks or model validators.

    This is the same field schema, not a parallel permissive schema. Cross-field
    validators run only after explicit overrides and deterministic derivations.
    """
    if not isinstance(raw, dict):
        raise ConfigurationError("CONFIG_TYPE", path=prefix)
    all_paths = {
        p
        for model in PROFILES.values()
        for p in fields_of(model, include_mappings=True)
    }
    issues = []
    canonical = {}
    for name in raw:
        if name not in schema.model_fields:
            path = f"{prefix}.{name}" if prefix else name
            # Only known schema paths may appear in an error.
            code = "CONFIG_CONFLICT" if path in all_paths else "CONFIG_UNKNOWN_KEY"
            issues.append(issue(code, path if path in all_paths else prefix))
    for name, field in schema.model_fields.items():
        if name not in raw:
            continue
        path = f"{prefix}.{name}" if prefix else name
        try:
            child = child_model(field)
            canonical[name] = (
                validate_sparse(child, raw[name], path)
                if child
                else leaf_value(field, raw[name], path)
            )
        except ConfigurationError as e:
            issues.extend(e.issues)
    if issues:
        raise ConfigurationError(issues=issues)
    return canonical


def at(tree, path):
    for part in path.split("."):
        tree = tree[part]
    return tree


def put(tree, path, value):
    parts = path.split(".")
    for part in parts[:-1]:
        tree = tree.setdefault(part, {})
    tree[parts[-1]] = value


def leaves(tree, prefix=""):
    result = {}
    for key, value in tree.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            result.update(leaves(value, path))
        else:
            result[path] = value
    return result


def complete(schema, request, provider, sources, overridden, prefix=""):
    result = {}
    problems = []
    for name, field in schema.model_fields.items():
        path = f"{prefix}.{name}" if prefix else name
        child = child_model(field)
        if child:
            try:
                result[name] = complete(
                    child, request.get(name, {}), provider, sources, overridden, path
                )
            except ConfigurationError as e:
                problems.extend(e.issues)
            continue
        dependencies = []
        if name in request:
            value = copy.deepcopy(request[name])
            origin = "cli_override" if path in overridden else "yaml"
        elif path == "data.catalog.timeout_seconds":
            value = PROVIDER_TIMEOUTS[provider]
            origin = "profile_default"
            dependencies = ["data.provider"]
        elif not field.is_required():
            value = field.get_default(call_default_factory=True)
            origin = (field.json_schema_extra or {}).get("origin", "schema_default")
        else:
            problems.append(issue("CONFIG_REQUIRED", path))
            continue
        result[name] = value
        sources[path] = {"origin": origin, "dependencies": dependencies}
    if problems:
        raise ConfigurationError(issues=problems)
    return result


def resolve(path, overrides=()):
    original_path = source_path(path)
    base = original_path.rsplit("/", 1)[0] or "/"
    raw, sha = load_file(original_path)
    scan_secrets(raw)
    schema = select_schema(raw)
    canonical = validate_sparse(schema, raw)
    yaml_explicit = copy.deepcopy(raw)  # supplied values before canonicalization/CLI
    request = copy.deepcopy(canonical)
    active = fields_of(schema)
    accepted = []
    for field, value in parse_entries(overrides):
        if field in FORBIDDEN_OVERRIDES or field not in active:
            raise ConfigurationError(
                "CONFIG_OVERRIDE", path=field if field in active else ""
            )
        scan_secrets(value)
        validated = leaf_value(active[field], value, field)
        accepted.append({"path": field, "value": copy.deepcopy(validated)})
        put(request, field, validated)
    request = validate_sparse(
        schema, request
    )  # canonical model field order after CLI insertion
    scan_secrets(request)
    overridden = {x["path"] for x in accepted}
    sources = {}
    provider = request.get("data", {}).get(
        "provider",
        Config.model_fields["data"].annotation.model_fields["provider"].default,
    )
    resolved = complete(schema, request, provider, sources, overridden)
    normalizations = []
    original_leaves = leaves(raw)
    for field, value in leaves(canonical).items():
        if value != original_leaves[field]:
            normalizations.append(
                {
                    "path": field,
                    "rule": "platform_alias"
                    if field == "mission.platform"
                    else "date_iso",
                }
            )
    # Record override normalization as well, without retaining raw argv.
    for (field, value), entry in zip(parse_entries(overrides), accepted):
        if value != entry["value"]:
            normalizations.append(
                {
                    "path": field,
                    "rule": "platform_alias"
                    if field == "mission.platform"
                    else "date_iso",
                }
            )
    work = absolute_path(resolved["project"]["work_dir"], base)
    if work == "/":
        raise ConfigurationError("CONFIG_PATH", path="project.work_dir")
    if work != resolved["project"]["work_dir"]:
        normalizations.append(
            {"path": "project.work_dir", "rule": "path_absolute_lexical"}
        )
    resolved["project"]["work_dir"] = work
    for field, suffix in TASK_DIRECTORIES.items():
        value = at(resolved, field)
        if value is None:
            final = absolute_path(suffix, work)
            sources[field] = {"origin": "derived", "dependencies": ["project.work_dir"]}
        else:
            final = absolute_path(value, base)
        put(resolved, field, final)
        if value is not None and final != value:
            normalizations.append({"path": field, "rule": "path_absolute_lexical"})
    directories = [at(resolved, field) for field in TASK_DIRECTORIES]
    if work in directories or len(set(directories)) != len(directories):
        raise ConfigurationError("CONFIG_PATH", path="project.work_dir")
    if resolved["processing"]["roi"]["half_width_deg"] is None:
        resolved["processing"]["roi"]["half_width_deg"] = resolved["data"]["search"][
            "half_width_deg"
        ]
        sources["processing.roi.half_width_deg"] = {
            "origin": "derived",
            "dependencies": ["data.search.half_width_deg"],
        }
    try:
        resolved = schema.model_validate(resolved).model_dump()
    except ValidationError as e:
        raise ConfigurationError(issues=model_issues(e)) from None
    scan_secrets(resolved)
    deferred = list(DEFERRED_CHECKS)
    if schema is PROFILES["event"]:
        deferred.append("event_bracketing")
    record = {
        "record_version": 1,
        "status": "complete",
        "scope": "configuration_only",
        "schema_version": resolved["schema_version"],
        "defaults_revision": DEFAULTS_REVISION,
        "insarforge_version": __version__,
        "source": {"kind": "yaml", "path": original_path, "sha256": sha},
        "base_directory": base,
        "yaml_explicit": yaml_explicit,
        "overrides": accepted,
        "field_sources": sources,
        "normalizations": sorted(
            [
                dict(path=p, rule=r)
                for p, r in {(x["path"], x["rule"]) for x in normalizations}
            ],
            key=lambda x: (x["path"], x["rule"]),
        ),
        "deferred_checks": deferred,
    }
    return request, resolved, record
