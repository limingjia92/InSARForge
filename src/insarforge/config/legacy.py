"""Offline migration of the supported autoInSAR command subset."""

import hashlib
import json
import math
import re
import shlex
from datetime import date
from pathlib import Path

from .errors import ConfigurationError
from .yaml_io import dump

OPTIONS = {
    "mode": 1,
    "data_source": 1,
    "lon": 1,
    "lat": 1,
    "event_date": 1,
    "reference_date": 1,
    "secondary_date": 1,
    "start_date": 1,
    "end_date": 1,
    "num_proc": 1,
    "platform": 1,
    "rel_orbit": 1,
    "search_dlonlat": 1,
    "roi_dlonlat": 1,
    "dlonlat": 1,
    "zip_check_backend": 1,
    "step": 1,
}
PLAT = {
    "Sentinel-1": "Sentinel-1",
    "Sentinel-1A": "Sentinel-1A",
    "Sentinel-1B": "Sentinel-1B",
    "Sentinel-1C": "Sentinel-1C",
    "Sentinel-1D": "Sentinel-1D",
    "S1": "Sentinel-1",
    "S1A": "Sentinel-1A",
    "S1B": "Sentinel-1B",
    "S1C": "Sentinel-1C",
    "S1D": "Sentinel-1D",
}
DATA_SOURCES = {"asf": "asf", "copernicus": "cdse"}
ZIP_BACKENDS = {"auto", "python", "zipinfo"}
STEPS = {
    "all",
    "config",
    "post",
    "download",
    "process",
    "search",
    "orbit",
    "dem",
    "clean",
}
LEGACY_DIR_SUFFIXES = {
    "data.paths.slc_dir": "SLC",
    "data.paths.orbit_dir": "orbits",
    "data.paths.dem_dir": "DEM",
    "data.paths.aux_dir": "AUX",
    "outputs.paths.process_dir": "process",
    "outputs.paths.results_dir": "results",
}


def _date(v):
    if len(v) != 8 or not v.isdigit():
        raise ConfigurationError("LEGACY_TRANSLATION")
    try:
        return date(int(v[:4]), int(v[4:6]), int(v[6:])).isoformat()
    except ValueError:
        raise ConfigurationError("LEGACY_TRANSLATION") from None


def tokenize(text):
    if text.startswith("\ufeff"):
        text = text[1:]
    if len(text.encode("utf-8")) > 1024 * 1024:
        raise ConfigurationError("LEGACY_TRANSLATION")
    text = _lex_command(text)
    try:
        toks = shlex.split(text, comments=True, posix=True)
    except ValueError:
        raise ConfigurationError("LEGACY_TRANSLATION") from None
    if not toks:
        raise ConfigurationError("LEGACY_TRANSLATION")
    toks = [t for t in toks if t != "\n"]
    first = toks.pop(0)
    _validate_program_path(first)
    if Path(first).name != "autoInSAR.py":
        # optional explicit python interpreter prefix
        interpreter = Path(first).name
        if interpreter not in {"python", "python3"} and not re.fullmatch(
            r"python3\.\d+", interpreter
        ):
            raise ConfigurationError("LEGACY_TRANSLATION")
        if not toks:
            raise ConfigurationError("LEGACY_TRANSLATION")
        script = toks.pop(0)
        _validate_program_path(script)
        if Path(script).name != "autoInSAR.py":
            raise ConfigurationError("LEGACY_TRANSLATION")
    out = []
    i = 0
    seen = set()
    while i < len(toks):
        t = toks[i]
        if not t.startswith("--") or t == "--":
            raise ConfigurationError("LEGACY_TRANSLATION")
        k, eq, val = t[2:].partition("=")
        if k not in OPTIONS:
            raise ConfigurationError("LEGACY_TRANSLATION")
        if k in seen:
            raise ConfigurationError("LEGACY_TRANSLATION")
        seen.add(k)
        if eq:
            value = val
        elif i + 1 >= len(toks) or toks[i + 1].startswith("--"):
            raise ConfigurationError("LEGACY_TRANSLATION")
        else:
            value = toks[i + 1]
            i += 1
        out.append((k, value))
        i += 1
    return out


def _validate_program_path(value):
    from ._values import scan_secrets

    if "://" in value or "@" in value or "-----BEGIN" in value:
        try:
            scan_secrets(value)
        except ConfigurationError:
            raise
        raise ConfigurationError("LEGACY_TRANSLATION")
    if (
        any(char in value for char in "~*?{}\\$")
        or value.startswith("//")
        or re.match(r"^[A-Za-z]:", value)
    ):
        raise ConfigurationError("LEGACY_TRANSLATION")


def _lex_command(text):
    """Recognize the finite one-command POSIX subset without evaluating it."""
    out = []
    quote = None
    comment = False
    terminated = False
    command_started = False
    i = 0
    while i < len(text):
        char = text[i]
        nxt = text[i + 1] if i + 1 < len(text) else ""
        if comment:
            if char in "\r\n":
                comment = False
                if command_started:
                    terminated = True
                if char == "\r" and nxt == "\n":
                    i += 1
            i += 1
            continue
        if quote == "'":
            if char == "'":
                quote = None
            elif char == "\n" or char == "\r":
                raise ConfigurationError("LEGACY_TRANSLATION")
            out.append(char)
            i += 1
            continue
        if quote == '"':
            command_started = True
            if char == '"':
                quote = None
            elif char in "\r\n":
                raise ConfigurationError("LEGACY_TRANSLATION")
            elif char == "\\" and nxt in "\r\n":
                if nxt == "\r" and i + 2 < len(text) and text[i + 2] == "\n":
                    i += 1
                i += 2
                continue
            elif char == "\\" and nxt:
                out.extend((char, nxt))
                i += 2
                continue
            elif char == "$" or char == "`":
                raise ConfigurationError("LEGACY_TRANSLATION")
            out.append(char)
            i += 1
            continue
        if terminated and char not in " \t\r\n#":
            raise ConfigurationError("LEGACY_TRANSLATION")
        if char == "#" and (i == 0 or text[i - 1].isspace()):
            comment = True
            i += 1
            continue
        if char in "'\"":
            quote = char
            command_started = True
            out.append(char)
            i += 1
            continue
        if char == "\\" and nxt in "\r\n":
            i += (
                2
                if not (nxt == "\r" and i + 2 < len(text) and text[i + 2] == "\n")
                else 3
            )
            continue
        if char in "\r\n":
            if command_started:
                terminated = True
            if char == "\r" and nxt == "\n":
                i += 1
            i += 1
            continue
        if char in ";&|<>`$*?{}":
            raise ConfigurationError("LEGACY_TRANSLATION")
        if not char.isspace():
            command_started = True
        out.append(char)
        i += 1
    if quote is not None:
        raise ConfigurationError("LEGACY_TRANSLATION")
    return "".join(out)


def _float(v, lo=None, hi=None):
    try:
        x = float(v)
    except (TypeError, ValueError, OverflowError):
        raise ConfigurationError("LEGACY_TRANSLATION") from None
    if (
        not math.isfinite(x)
        or (lo is not None and x < lo)
        or (hi is not None and x > hi)
    ):
        raise ConfigurationError("LEGACY_TRANSLATION")
    return x


def translate_text(text, legacy_cwd):
    from ._values import absolute_path, path_string, scan_secrets

    if not isinstance(legacy_cwd, str):
        raise ConfigurationError("CONFIG_PATH")
    scan_secrets(legacy_cwd)
    if not legacy_cwd.startswith("/") or any(c in legacy_cwd for c in "\t\r\n\\$"):
        raise ConfigurationError("CONFIG_PATH")
    try:
        path_string(legacy_cwd)
        legacy_cwd = absolute_path(legacy_cwd, "/")
    except ConfigurationError:
        raise
    except Exception:
        raise ConfigurationError("CONFIG_PATH") from None
    if legacy_cwd == "/":
        raise ConfigurationError("CONFIG_PATH")
    pairs = tokenize(text)
    d = dict(pairs)
    explicit = [k for k, _ in pairs]
    mode = d.get("mode", "pair")
    if mode not in ("pair", "stack"):
        raise ConfigurationError("LEGACY_TRANSLATION")
    if "dlonlat" in d and "search_dlonlat" in d:
        raise ConfigurationError("LEGACY_TRANSLATION")
    if "num_proc" in d:
        try:
            parsed_num_proc = int(d["num_proc"], 10)
        except (TypeError, ValueError):
            raise ConfigurationError("LEGACY_TRANSLATION") from None
        if parsed_num_proc < 0 or (mode == "pair" and parsed_num_proc > 0):
            raise ConfigurationError("LEGACY_TRANSLATION")
    if mode == "stack" and (
        "event_date" in d or "reference_date" in d or "secondary_date" in d
    ):
        raise ConfigurationError("LEGACY_TRANSLATION")
    if mode == "pair" and ("start_date" in d or "end_date" in d):
        raise ConfigurationError("LEGACY_TRANSLATION")
    y = {
        "schema_version": 1,
        "project": {"work_dir": legacy_cwd},
        "workflow": {"type": mode},
        "mission": {"name": "sentinel1"},
        "data": {"search": {}},
        "processing": {"backend": "isce2"},
    }
    if mode == "pair":
        p = {}
        if "event_date" in d:
            if "reference_date" in d or "secondary_date" in d:
                raise ConfigurationError("LEGACY_TRANSLATION")
            p.update(selection="event", event_date=_date(d["event_date"]))
        else:
            if ("reference_date" in d) != ("secondary_date" in d):
                raise ConfigurationError("LEGACY_TRANSLATION")
            if "reference_date" not in d:
                raise ConfigurationError("LEGACY_TRANSLATION")
            r, s = _date(d["reference_date"]), _date(d["secondary_date"])
            if r >= s:
                raise ConfigurationError("LEGACY_TRANSLATION")
            p.update(selection="manual", reference_date=r, secondary_date=s)
        y["workflow"]["pair"] = p
    else:
        if ("start_date" in d) != ("end_date" in d):
            raise ConfigurationError("LEGACY_TRANSLATION")
        if "start_date" not in d:
            raise ConfigurationError("LEGACY_TRANSLATION")
        a, b = _date(d["start_date"]), _date(d["end_date"])
        if a >= b:
            raise ConfigurationError("LEGACY_TRANSLATION")
        y["workflow"]["stack"] = {"start_date": a, "end_date": b}
    if "lon" not in d or "lat" not in d:
        raise ConfigurationError("LEGACY_TRANSLATION")
    y["data"]["search"].update(
        longitude=_float(d["lon"], -180, 180), latitude=_float(d["lat"], -90, 90)
    )
    if "platform" in d:
        if d["platform"] not in PLAT:
            raise ConfigurationError("LEGACY_TRANSLATION")
        y["mission"]["platform"] = PLAT[d["platform"]]
    if "rel_orbit" in d:
        try:
            n = int(d["rel_orbit"], 10)
        except (TypeError, ValueError):
            raise ConfigurationError("LEGACY_TRANSLATION") from None
        if n <= 0:
            raise ConfigurationError("LEGACY_TRANSLATION")
        y["mission"]["relative_orbit"] = n
    if "data_source" in d:
        if d["data_source"] not in DATA_SOURCES:
            raise ConfigurationError("LEGACY_TRANSLATION")
        # canonical schema order places provider before search
        y["data"] = {
            "provider": DATA_SOURCES[d["data_source"]],
            "search": y["data"]["search"],
        }
    if "num_proc" in d:
        y["resources"] = {"num_proc": parsed_num_proc}
    for k, target in (
        ("search_dlonlat", "data.search.half_width_deg"),
        ("dlonlat", "data.search.half_width_deg"),
        ("roi_dlonlat", "processing.roi.half_width_deg"),
    ):
        if k in d:
            cur = y
            for part in target.split(".")[:-1]:
                cur = cur.setdefault(part, {})
            cur[target.split(".")[-1]] = _float(d[k], 0)
    if "zip_check_backend" in d:
        if d["zip_check_backend"] not in ZIP_BACKENDS:
            raise ConfigurationError("LEGACY_TRANSLATION")
        y.setdefault("data", {}).setdefault("download", {})["zip_check_backend"] = d[
            "zip_check_backend"
        ]
    if "step" in d:
        if d["step"] not in STEPS:
            raise ConfigurationError("LEGACY_TRANSLATION")
        if d["step"] == "clean":
            raise ConfigurationError("LEGACY_TRANSLATION")
        y["workflow"]["stage"] = (
            "prepare"
            if d["step"] == "config"
            else ("postprocess" if d["step"] == "post" else d["step"])
        )
    from .resolution import _resolve_mapping

    y, _, _ = _resolve_mapping(y, legacy_cwd + "/insarforge.yaml", "")
    return y, explicit


def migrate_file(path, legacy_cwd, write_dir=None):
    from ._values import absolute_path, path_string, scan_secrets, source_path

    try:
        p = Path(source_path(path))
        with p.open("rb") as stream:
            raw = stream.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024:
            raise ConfigurationError("CONFIG_INPUT")
        text = raw.decode("utf-8-sig")
    except ConfigurationError:
        raise
    except Exception:
        raise ConfigurationError("CONFIG_INPUT") from None
    y, explicit = translate_text(text, legacy_cwd)
    translated = dump(y)
    target_fields = {
        "mode": ("workflow.type", "identity"),
        "data_source": ("data.provider", "provider_alias"),
        "lon": ("data.search.longitude", "float"),
        "lat": ("data.search.latitude", "float"),
        "event_date": ("workflow.pair.event_date", "date_iso"),
        "reference_date": ("workflow.pair.reference_date", "date_iso"),
        "secondary_date": ("workflow.pair.secondary_date", "date_iso"),
        "start_date": ("workflow.stack.start_date", "date_iso"),
        "end_date": ("workflow.stack.end_date", "date_iso"),
        "num_proc": ("resources.num_proc", "int"),
        "platform": ("mission.platform", "platform_alias"),
        "rel_orbit": ("mission.relative_orbit", "int"),
        "search_dlonlat": ("data.search.half_width_deg", "search_alias"),
        "roi_dlonlat": ("processing.roi.half_width_deg", "roi_width"),
        "dlonlat": ("data.search.half_width_deg", "search_alias"),
        "zip_check_backend": ("data.download.zip_check_backend", "identity"),
        "step": ("workflow.stage", "stage_alias"),
    }
    rec = {
        "record_version": 1,
        "status": "complete",
        "scope": "configuration_only",
        "schema_version": 1,
        "mapping_revision": "autoinsar-revb-schema1-v1",
        "defaults_revision": "schema1-p3-v1",
        "mapping_basis": {
            "revision": "autoinsar-revb-schema1-v1",
            "source_commit": "e03547eda0c2ceb842aba94522ca95cf5bdbdbe7",
            "command_version_inferred": False,
        },
        "source": {
            "kind": "legacy_command_file",
            "path": str(p),
            "sha256": hashlib.sha256(raw).hexdigest(),
        },
        "legacy_cwd": y["project"]["work_dir"],
        "explicit_options": explicit,
        "field_mappings": [
            {
                "option": option,
                "fields": [target_fields[option][0]],
                "rule": target_fields[option][1],
            }
            for option in OPTIONS
            if option in explicit
        ],
        "synthesized_fields": [
            {"path": "schema_version", "value": 1, "reason": "schema_identity"},
            {
                "path": "project.work_dir",
                "value": y["project"]["work_dir"],
                "reason": "legacy_cwd",
            },
            {
                "path": "mission.name",
                "value": "sentinel1",
                "reason": "fixed_mission_identity",
            },
            {
                "path": "processing.backend",
                "value": "isce2",
                "reason": "fixed_backend_identity",
            },
        ],
        "defaults_used": {
            "schema_version": {
                "value": 1,
                "basis": "synthesized_identity",
                "dependencies": [],
            },
            "mission.name": {
                "value": "sentinel1",
                "basis": "synthesized_identity",
                "dependencies": [],
            },
            "processing.backend": {
                "value": "isce2",
                "basis": "synthesized_identity",
                "dependencies": [],
            },
        },
        "normalizations": [],
        "notices": [],
        "deferred_checks": [],
        "provenance_limitations": [
            "user_legacy_version_not_inferred",
            "historical_revision_a_bytes_unavailable",
        ],
        "outputs": {},
    }
    rec["outputs"]["insarforge.yaml"] = hashlib.sha256(translated.encode()).hexdigest()
    rec["normalizations"] = [
        {"path": "project.work_dir", "rule": "path_absolute_lexical"}
    ]
    for option in explicit:
        path, rule = target_fields[option]
        if rule in {
            "date_iso",
            "platform_alias",
            "provider_alias",
            "stage_alias",
            "search_alias",
        }:
            rec["normalizations"].append({"path": path, "rule": rule})
    rec["normalizations"].sort(key=lambda item: item["path"])
    if "event_date" in explicit:
        rec["field_mappings"].append(
            {
                "option": "event_date",
                "fields": ["workflow.pair.selection"],
                "rule": "event_selection",
            }
        )
    if "reference_date" in explicit and "secondary_date" in explicit:
        rec["field_mappings"].append(
            {
                "option": "reference_date+secondary_date",
                "fields": ["workflow.pair.selection"],
                "rule": "manual_selection",
            }
        )
    rec["defaults_used"]["processing.roi.half_width_deg"] = {
        "value": 0.2,
        "basis": "derived",
        "dependencies": ["data.search.half_width_deg"],
    }
    if "mode" not in explicit:
        rec["synthesized_fields"].append(
            {
                "path": "workflow.type",
                "value": "pair",
                "reason": "legacy_parser_default",
            }
        )

    def notice(code, level, fields=()):
        rec["notices"].append({"code": code, "level": level, "fields": list(fields)})

    if "event_date" in explicit:
        notice("LEGACY_EVENT_BRACKETING", "warning", ["workflow.pair.event_date"])
    if "dlonlat" in explicit:
        notice("LEGACY_DEPRECATED_DLONLAT", "warning", ["data.search.half_width_deg"])
    if "rel_orbit" not in explicit:
        notice("LEGACY_UNIQUE_ORBIT_DEFERRED", "info", ["mission.relative_orbit"])
    if (
        "num_proc" in explicit
        and "type: pair" in translated
        and "num_proc: 0" in translated
    ):
        notice("LEGACY_PAIR_NUM_PROC_NEUTRAL", "info", ["resources.num_proc"])
    notice("LEGACY_DEFAULTS_APPLIED", "info")
    rec["field_mappings"].sort(key=lambda item: (item["fields"][0], item["option"]))
    rec["synthesized_fields"].sort(key=lambda item: item["path"])
    rec["notices"].sort(key=lambda item: item["code"])
    from .._version import __version__
    from . import resolution as _resolution
    from .resolution import _resolve_mapping, at

    _, effective, resolution_record = _resolve_mapping(
        y, str(p), rec["source"]["sha256"]
    )
    rec["insarforge_version"] = __version__
    rec["defaults_used"] = {
        field: {
            "value": at(effective, field),
            "basis": source["origin"],
            "dependencies": source["dependencies"],
        }
        for field, source in resolution_record["field_sources"].items()
        if source["origin"] != "yaml"
    }
    basis_overrides = {
        "data.provider": "legacy_parser_default",
        "mission.platform": "legacy_parser_default",
        "workflow.stage": "legacy_parser_default",
        "resources.num_proc": "legacy_parser_default",
        "data.download.zip_check_backend": "legacy_parser_default",
        "data.search.half_width_deg": "legacy_fallback",
        "processing.roi.half_width_deg": "legacy_inheritance",
        "mission.relative_orbit": "legacy_selection_policy",
        "data.paths.slc_dir": "legacy_layout_derivation",
        "data.paths.orbit_dir": "legacy_layout_derivation",
        "data.paths.dem_dir": "legacy_layout_derivation",
        "data.paths.aux_dir": "legacy_layout_derivation",
        "outputs.paths.process_dir": "legacy_layout_derivation",
        "outputs.paths.results_dir": "legacy_layout_derivation",
        "workflow.pair.half_window_days": "legacy_hardcoded_profile",
        "processing.isce2.pair.swaths": "legacy_hardcoded_profile",
        "processing.isce2.pair.range_looks": "legacy_hardcoded_profile",
        "processing.isce2.pair.azimuth_looks": "legacy_hardcoded_profile",
        "processing.isce2.pair.filter_strength": "legacy_hardcoded_profile",
        "processing.isce2.pair.unwrap": "legacy_hardcoded_profile",
        "processing.isce2.pair.unwrapper": "legacy_hardcoded_profile",
        "processing.isce2.pair.dense_offsets": "legacy_hardcoded_profile",
        "processing.isce2.pair.esd": "legacy_hardcoded_profile",
        "processing.isce2.pair.use_gpu": "legacy_hardcoded_profile",
        "processing.isce2.stack.use_gpu": "legacy_hardcoded_profile",
        "data.catalog.timeout_seconds": "legacy_hardcoded_profile",
        "data.catalog.request_size": "legacy_hardcoded_profile",
        "qc.pair_export.min_coherence": "legacy_hardcoded_profile",
        "outputs.stack_advice.enabled": "legacy_hardcoded_profile",
        "outputs.stack_advice.temporal_neighbors": "legacy_hardcoded_profile",
        "outputs.stack_advice.quicklook_range_looks": "legacy_hardcoded_profile",
        "outputs.stack_advice.quicklook_azimuth_looks": "legacy_hardcoded_profile",
        "outputs.pair.phase_products": "schema_default",
        "outputs.pair.offset_products": "schema_default",
    }
    for field, basis in basis_overrides.items():
        if field in rec["defaults_used"]:
            rec["defaults_used"][field]["basis"] = basis
    if "outputs.figures.dpi" in rec["defaults_used"]:
        rec["defaults_used"]["outputs.figures.dpi"]["basis"] = (
            "legacy_hardcoded_profile"
        )
    if "mode" not in explicit:
        rec["defaults_used"]["workflow.type"] = {
            "value": "pair",
            "basis": "legacy_parser_default",
            "dependencies": [],
        }
    expected = {
        "project.name": None,
        "workflow.stage": "all",
        "mission.platform": "Sentinel-1",
        "mission.relative_orbit": None,
        "data.catalog.request_size": 1000,
        "data.download.zip_check_backend": "auto",
        "data.search.half_width_deg": 0.2,
        "processing.isce2.pair.swaths": [1, 2, 3],
        "processing.isce2.pair.range_looks": 20,
        "processing.isce2.pair.azimuth_looks": 5,
        "processing.isce2.pair.filter_strength": 0.4,
        "processing.isce2.pair.unwrap": True,
        "processing.isce2.pair.unwrapper": "snaphu_mcf",
        "processing.isce2.pair.dense_offsets": True,
        "processing.isce2.pair.esd": True,
        "processing.isce2.pair.use_gpu": True,
        "qc.pair_export.min_coherence": 0.3,
        "resources.num_proc": 0,
        "corrections": [],
        "analyzers": [],
        "outputs.figures.enabled": True,
        "outputs.figures.dpi": 300,
        "outputs.pair.phase_products": True,
        "outputs.pair.offset_products": True,
    }
    provider = effective["data"]["provider"]
    expected["data.provider"] = "asf"
    expected["data.catalog.timeout_seconds"] = 90 if provider == "cdse" else 60
    if (
        effective["workflow"]["type"] == "pair"
        and effective["workflow"]["pair"]["selection"] == "event"
    ):
        expected["workflow.pair.half_window_days"] = 12
    if effective["workflow"]["type"] == "stack":
        expected.update(
            {
                "processing.isce2.stack.use_gpu": True,
                "outputs.stack_advice.enabled": True,
                "outputs.stack_advice.temporal_neighbors": 2,
                "outputs.stack_advice.quicklook_range_looks": 20,
                "outputs.stack_advice.quicklook_azimuth_looks": 5,
            }
        )
    for field, value in expected.items():
        if (
            field in rec["defaults_used"]
            and rec["defaults_used"][field]["value"] != value
        ):
            raise ConfigurationError("LEGACY_TRANSLATION")
    # Compatibility relationships are lexical and independent of the host filesystem.
    work = effective["project"]["work_dir"]
    if _resolution.TASK_DIRECTORIES != LEGACY_DIR_SUFFIXES:
        raise ConfigurationError("LEGACY_TRANSLATION")
    for field, suffix in LEGACY_DIR_SUFFIXES.items():
        expected_path = str(Path(work) / suffix)
        if at(effective, field) != expected_path:
            raise ConfigurationError("LEGACY_TRANSLATION")
    if (
        "processing.roi.half_width_deg" in rec["defaults_used"]
        and "roi_dlonlat" not in explicit
    ):
        if at(effective, "processing.roi.half_width_deg") != at(
            effective, "data.search.half_width_deg"
        ):
            raise ConfigurationError("LEGACY_TRANSLATION")
    rec["deferred_checks"] = resolution_record["deferred_checks"]
    rec["mapping_basis"] = {
        "source": "autoInSAR.py",
        "revision": "B",
        "source_sha256": "4df7b05682f1df689e460072d694d2b99169a422aba69b372de0b57c2601c262",
        "recorded_commit": "e03547eda0c2ceb842aba94522ca95cf5bdbdbe7",
        "command_version_inferred": False,
    }
    rec["provenance_limitations"] = [
        "user_legacy_version_not_inferred",
        "historical_revision_a_bytes_unavailable",
    ]
    if write_dir is None:
        return translated, rec
    record_text = json.dumps(rec, sort_keys=False, indent=2, ensure_ascii=False) + "\n"
    out = Path(write_dir)
    try:
        scan_secrets(str(write_dir))
        path_string(str(write_dir))
    except ConfigurationError:
        raise
    except Exception:
        raise ConfigurationError("CONFIG_PATH")
    if not out.is_absolute():
        out = Path(absolute_path(str(out), str(p.parent)))
    from .cli import persist

    persist(
        {"insarforge.yaml": translated, "legacy_translation.json": record_text}, out
    )
    return translated, rec
