"""Frozen P3.1 behavior: source validation, active profiles and safe output."""

import copy
import hashlib
import importlib.metadata
import json
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from insarforge.config.errors import ConfigurationError
from insarforge.config.resolution import resolve
from insarforge.config.yaml_io import dump

PROFILES = {
    "manual": {
        "schema_version": 1,
        "workflow": {
            "type": "pair",
            "pair": {
                "selection": "manual",
                "reference_date": "2025-01-01",
                "secondary_date": "2025-01-13",
            },
        },
        "data": {"search": {"longitude": 0, "latitude": 0}},
    },
    "event": {
        "schema_version": 1,
        "workflow": {
            "type": "pair",
            "pair": {"selection": "event", "event_date": "2025-01-07"},
        },
        "data": {"search": {"longitude": 0, "latitude": 0}},
    },
    "stack": {
        "schema_version": 1,
        "workflow": {
            "type": "stack",
            "stack": {"start_date": "2023-01-01", "end_date": "2023-03-01"},
        },
        "data": {"search": {"longitude": 0, "latitude": 0}},
    },
}

# The expected values are the specification, deliberately independent of models.
# path, active profile, explicit legal value, invalid value, expected resolved default
FIELDS = [
    ("schema_version", "manual", 1, True, 1),
    ("project.name", "manual", "test name", " ", None),
    ("project.work_dir", "manual", "work", "", None),
    ("workflow.type", "manual", "pair", "other", "pair"),
    ("workflow.stage", "manual", "prepare", "clean", "all"),
    ("workflow.pair.selection", "manual", "manual", "other", "manual"),
    ("workflow.pair.reference_date", "manual", "20241231", 20241231, "2025-01-01"),
    ("workflow.pair.secondary_date", "manual", "20250125", 20250125, "2025-01-13"),
    ("workflow.pair.event_date", "event", "20250108", 20250108, "2025-01-07"),
    ("workflow.pair.half_window_days", "event", 14, 0, 12),
    ("workflow.stack.start_date", "stack", "20221231", 20221231, "2023-01-01"),
    ("workflow.stack.end_date", "stack", "20230401", 20230401, "2023-03-01"),
    ("mission.name", "manual", "sentinel1", "alos", "sentinel1"),
    ("mission.platform", "manual", "S1C", "ALOS-2", "Sentinel-1"),
    ("mission.relative_orbit", "manual", 121, 0, None),
    ("data.provider", "manual", "cdse", "copernicus", "asf"),
    ("data.search.longitude", "manual", 20, 181, 0),
    ("data.search.latitude", "manual", 10, 91, 0),
    ("data.search.half_width_deg", "manual", 1, -1, 0.2),
    ("data.catalog.timeout_seconds", "manual", 70, 0, 60),
    ("data.catalog.request_size", "manual", 123, 0, 1000),
    ("data.download.zip_check_backend", "manual", "python", "bad", "auto"),
    ("data.paths.slc_dir", "manual", "inputs/slc", "C:slc", None),
    ("data.paths.orbit_dir", "manual", "inputs/orbit", "C:orbit", None),
    ("data.paths.dem_dir", "manual", "inputs/dem", "C:dem", None),
    ("data.paths.aux_dir", "manual", "inputs/aux", "C:aux", None),
    ("outputs.paths.process_dir", "manual", "out/process", "C:process", None),
    ("outputs.paths.results_dir", "manual", "out/results", "C:results", None),
    ("processing.backend", "manual", "isce2", "gamma", "isce2"),
    ("processing.roi.half_width_deg", "manual", 1, -1, 0.2),
    ("processing.isce2.pair.swaths", "manual", [3, 1], [1, 1], [1, 2, 3]),
    ("processing.isce2.pair.range_looks", "manual", 10, 0, 20),
    ("processing.isce2.pair.azimuth_looks", "manual", 2, 0, 5),
    ("processing.isce2.pair.filter_strength", "manual", 0.7, 1.1, 0.4),
    ("processing.isce2.pair.unwrap", "manual", True, "true", True),
    ("processing.isce2.pair.unwrapper", "manual", "snaphu_mcf", "other", "snaphu_mcf"),
    ("processing.isce2.pair.dense_offsets", "manual", True, "true", True),
    ("processing.isce2.pair.esd", "manual", False, "true", True),
    ("processing.isce2.pair.use_gpu", "manual", False, "true", True),
    ("processing.isce2.stack.use_gpu", "stack", False, "true", True),
    ("resources.num_proc", "stack", 16, -1, 0),
    ("qc.pair_export.min_coherence", "manual", 0.8, 1.1, 0.3),
    ("outputs.pair.phase_products", "manual", False, "true", True),
    ("outputs.pair.offset_products", "manual", False, "true", True),
    ("outputs.figures.enabled", "manual", False, "true", True),
    ("outputs.figures.dpi", "manual", 150, 0, 300),
    ("outputs.stack_advice.enabled", "stack", False, "true", True),
    ("outputs.stack_advice.temporal_neighbors", "stack", 3, 0, 2),
    ("outputs.stack_advice.quicklook_range_looks", "stack", 10, 0, 20),
    ("outputs.stack_advice.quicklook_azimuth_looks", "stack", 2, 0, 5),
    ("corrections", "manual", [], ["x"], []),
    ("analyzers", "manual", [], ["x"], []),
]
NULLABLE = {
    "project.name",
    "mission.relative_orbit",
    "processing.roi.half_width_deg",
    "data.paths.slc_dir",
    "data.paths.orbit_dir",
    "data.paths.dem_dir",
    "data.paths.aux_dir",
    "outputs.paths.process_dir",
    "outputs.paths.results_dir",
}
FORBIDDEN = {
    "schema_version",
    "workflow.type",
    "workflow.pair.selection",
    "mission.name",
    "processing.backend",
}
TASK_PATHS = [
    "data.paths.slc_dir",
    "data.paths.orbit_dir",
    "data.paths.dem_dir",
    "data.paths.aux_dir",
    "outputs.paths.process_dir",
    "outputs.paths.results_dir",
]
SUFFIXES = ["SLC", "orbits", "DEM", "AUX", "process", "results"]


def put(data, path, value):
    cur = data
    parts = path.split(".")
    for part in parts[:-1]:
        cur = cur.setdefault(part, {})
    cur[parts[-1]] = value


def at(data, path):
    for part in path.split("."):
        data = data[part]
    return data


def make(tmp_path, profile="manual", changes=None, raw=None):
    data = copy.deepcopy(PROFILES[profile])
    for key, value in (changes or {}).items():
        put(data, key, value)
    path = tmp_path / "config.yaml"
    path.write_bytes(
        raw if raw is not None else yaml.safe_dump(data, sort_keys=False).encode()
    )
    return path


def check_error(path, code=None, overrides=()):
    with pytest.raises(ConfigurationError) as exc:
        resolve(path, overrides)
    if code:
        assert exc.value.code == code
    return exc.value


@pytest.mark.parametrize(
    "field,profile,value,bad,default", FIELDS, ids=[r[0] for r in FIELDS]
)
def test_field_contract(tmp_path, field, profile, value, bad, default):
    p = make(tmp_path, profile)
    _, resolved, _ = resolve(p)
    if field == "project.work_dir":
        assert at(resolved, field) == str(tmp_path)
    elif field in TASK_PATHS:
        assert at(resolved, field) == str(tmp_path / SUFFIXES[TASK_PATHS.index(field)])
    else:
        assert at(resolved, field) == default
    p = make(tmp_path, profile, {field: value})
    requested, resolved, _ = resolve(p)
    expected = value
    if field.endswith("_date"):
        expected = value if "-" in value else f"{value[:4]}-{value[4:6]}-{value[6:]}"
    if field == "mission.platform":
        expected = "Sentinel-1C"
    assert at(requested, field) == expected
    if field in TASK_PATHS or field == "project.work_dir":
        expected = str(tmp_path / value)
    assert at(resolved, field) == expected
    check_error(make(tmp_path, profile, {field: bad}))
    if field in NULLABLE:
        requested, _, _ = resolve(make(tmp_path, profile, {field: None}))
        assert at(requested, field) is None
    else:
        check_error(make(tmp_path, profile, {field: None}))
    if field not in FORBIDDEN:
        p = make(tmp_path, profile)
        rhs = json.dumps(value) if isinstance(value, (list, str, bool)) else str(value)
        requested, resolved, record = resolve(p, [field + "=" + rhs])
        assert record["field_sources"][field]["origin"] == "cli_override"
        assert at(requested, field) == (
            "Sentinel-1C"
            if field == "mission.platform"
            else (
                f"{value[:4]}-{value[4:6]}-{value[6:]}"
                if field.endswith("_date")
                else value
            )
        )


@pytest.mark.parametrize("profile", PROFILES)
def test_profile_roundtrip(tmp_path, profile):
    p = make(tmp_path, profile)
    original = p.read_bytes()
    req, res, rec = resolve(p)
    assert set(req) == set(PROFILES[profile])
    text = dump(res)
    assert text.endswith("\n") and not text.endswith("\n\n") and "\r" not in text
    p.write_text(text)
    assert resolve(p)[1] == res
    p.write_bytes(original)
    assert resolve(p) == (req, res, rec)
    if profile == "stack":
        assert res["qc"] == {} and set(res["processing"]["isce2"]["stack"]) == {
            "use_gpu"
        }
        assert "pair" not in res["workflow"] and "pair" not in res["outputs"]
    else:
        assert (
            "stack" not in res["workflow"] and "stack" not in res["processing"]["isce2"]
        )
        pair = res["workflow"]["pair"]
        assert set(pair) == (
            {"selection", "reference_date", "secondary_date"}
            if profile == "manual"
            else {"selection", "event_date", "half_window_days"}
        )


@pytest.mark.parametrize(
    "profile,field",
    [
        ("manual", "workflow.stack"),
        ("stack", "workflow.pair"),
        ("manual", "workflow.pair.event_date"),
        ("manual", "workflow.pair.half_window_days"),
        ("event", "workflow.pair.reference_date"),
        ("event", "workflow.pair.secondary_date"),
        ("manual", "processing.isce2.stack"),
        ("stack", "processing.isce2.pair"),
        ("manual", "outputs.stack_advice"),
        ("stack", "outputs.pair"),
        ("stack", "qc.pair_export"),
    ],
)
@pytest.mark.parametrize("value", [None, {}, 1])
def test_inactive_presence(tmp_path, profile, field, value):
    check_error(make(tmp_path, profile, {field: value}))


@pytest.mark.parametrize(
    "field",
    [
        "project",
        "workflow",
        "workflow.pair",
        "mission",
        "data",
        "data.search",
        "data.paths",
        "data.catalog",
        "data.download",
        "processing",
        "processing.roi",
        "processing.isce2",
        "processing.isce2.pair",
        "qc",
        "qc.pair_export",
        "resources",
        "outputs",
        "outputs.paths",
        "outputs.pair",
        "outputs.figures",
    ],
)
@pytest.mark.parametrize("value", [None, [], False, 1, "bad"])
def test_mapping_types_safe(tmp_path, field, value):
    check_error(make(tmp_path, changes={field: value}), "CONFIG_TYPE")


@pytest.mark.parametrize(
    "field,bad,fix",
    [
        ("data.search.latitude", 100, "0"),
        ("processing.isce2.pair.range_looks", "bad", "10"),
        ("workflow.pair.secondary_date", None, "2025-01-25"),
        ("project.work_dir", "", "work"),
        ("data.catalog.timeout_seconds", None, "90"),
        ("processing.roi.half_width_deg", -1, "0"),
    ],
)
def test_source_cannot_be_hidden(tmp_path, field, bad, fix):
    check_error(make(tmp_path, changes={field: bad}), overrides=[field + "=" + fix])


def test_override_missing_leaf_and_crossfield(tmp_path):
    data = copy.deepcopy(PROFILES["manual"])
    del data["workflow"]["pair"]["secondary_date"]
    p = make(tmp_path, raw=yaml.safe_dump(data).encode())
    assert (
        resolve(p, ["workflow.pair.secondary_date=2025-01-25"])[1]["workflow"]["pair"][
            "secondary_date"
        ]
        == "2025-01-25"
    )
    check_error(p, "CONFIG_REQUIRED")
    p = make(tmp_path, changes={"workflow.pair.secondary_date": "2024-01-01"})
    assert (
        resolve(p, ["workflow.pair.secondary_date=2025-01-25"])[0]["workflow"]["pair"][
            "secondary_date"
        ]
        == "2025-01-25"
    )


@pytest.mark.parametrize(
    "overrides",
    [
        ["schema_version=1"],
        ["workflow.type=pair"],
        ["workflow.pair.selection=manual"],
        ["mission.name=sentinel1"],
        ["processing.backend=isce2"],
        ["project=null"],
        ["project=[]"],
        ["project={}"],
        ["unknown=1"],
        ["processing.isce2.pair.swaths[0]=1"],
        ["data.*=1"],
        ["project.name"],
        ["project.name="],
        ["project.name= "],
        ["project.name=a", "project.name=a"],
        ["project.name=ok\npassword: FAKE"],
        ["project.name=ok\n---\nother"],
        ["project.name=!!str ok"],
        ["project.name=&x ok"],
        ["project.name=*x"],
    ],
)
def test_override_rejections(tmp_path, overrides):
    check_error(make(tmp_path), overrides=overrides)


def test_override_lists_full_rhs(tmp_path):
    req, res, rec = resolve(
        make(tmp_path), ["processing.isce2.pair.swaths=[3,1]", 'project.name="a=b"']
    )
    assert req["processing"]["isce2"]["pair"]["swaths"] == [3, 1]
    assert res["project"]["name"] == "a=b"
    assert rec["overrides"] == [
        {"path": "processing.isce2.pair.swaths", "value": [3, 1]},
        {"path": "project.name", "value": "a=b"},
    ]


@pytest.mark.parametrize(
    "field",
    [
        "processing.isce2.pair.range_looks",
        "processing.isce2.pair.azimuth_looks",
        "data.catalog.timeout_seconds",
        "data.catalog.request_size",
        "outputs.figures.dpi",
        "resources.num_proc",
    ],
)
@pytest.mark.parametrize("bad", [True, False, 1.0, "1", -1])
def test_strict_integer_fields(tmp_path, field, bad):
    check_error(make(tmp_path, changes={field: bad}))


@pytest.mark.parametrize(
    "field",
    [
        "data.search.longitude",
        "data.search.latitude",
        "data.search.half_width_deg",
        "processing.roi.half_width_deg",
        "processing.isce2.pair.filter_strength",
        "qc.pair_export.min_coherence",
    ],
)
@pytest.mark.parametrize(
    "bad", [True, False, "0.3", float("nan"), float("inf"), float("-inf")]
)
def test_strict_real_fields(tmp_path, field, bad):
    check_error(make(tmp_path, changes={field: bad}))


@pytest.mark.parametrize(
    "value",
    [
        "2025011",
        "2025-W01-3",
        "2025-02-29",
        "2024-02-30",
        "0000-01-01",
        "2025-1-01",
        "2025-01-01T00:00:00",
        20250101,
        1.0,
        True,
        None,
    ],
)
def test_date_invalid(tmp_path, value):
    check_error(make(tmp_path, changes={"workflow.pair.reference_date": value}))


@pytest.mark.parametrize("value", ["20240229", "2024-02-29"])
def test_leap_date(tmp_path, value):
    assert (
        resolve(make(tmp_path, changes={"workflow.pair.reference_date": value}))[0][
            "workflow"
        ]["pair"]["reference_date"]
        == "2024-02-29"
    )


@pytest.mark.parametrize(
    "profile,field,value",
    [
        ("manual", "workflow.pair.secondary_date", "2025-01-01"),
        ("manual", "workflow.pair.secondary_date", "2024-12-31"),
        ("stack", "workflow.stack.end_date", "2023-01-01"),
        ("stack", "workflow.stack.end_date", "2022-12-31"),
    ],
)
def test_date_order_conflict(tmp_path, profile, field, value):
    check_error(make(tmp_path, profile, {field: value}), "CONFIG_CONFLICT")


@pytest.mark.parametrize(
    "lon,lat,width",
    [(0, 0, 0), (180, 90, 0), (-180, -90, 0), (179, 89, 1), (-179, -89, 1)],
)
def test_spatial_boundaries(tmp_path, lon, lat, width):
    res = resolve(
        make(
            tmp_path,
            changes={
                "data.search.longitude": lon,
                "data.search.latitude": lat,
                "data.search.half_width_deg": width,
            },
        )
    )[1]
    assert res["processing"]["roi"]["half_width_deg"] == width


@pytest.mark.parametrize(
    "field,value",
    [
        ("data.search.half_width_deg", 91),
        ("processing.roi.half_width_deg", 91),
        ("processing.roi.half_width_deg", -1),
        ("processing.roi.half_width_deg", float("inf")),
    ],
)
def test_spatial_reject(tmp_path, field, value):
    check_error(make(tmp_path, changes={field: value}))


@pytest.mark.parametrize("roi", [None, 0, 0.1, 1])
def test_roi_inheritance_scope(tmp_path, roi):
    req, res, rec = resolve(
        make(tmp_path, changes={"processing.roi.half_width_deg": roi}),
        ["data.search.half_width_deg=0.5"],
    )
    assert req["processing"]["roi"]["half_width_deg"] == roi
    assert res["processing"]["roi"]["half_width_deg"] == (0.5 if roi is None else roi)
    assert rec["field_sources"]["processing.roi.half_width_deg"]["origin"] == (
        "derived" if roi is None else "yaml"
    )


@pytest.mark.parametrize(
    "setting,output",
    [("unwrap", "phase_products"), ("dense_offsets", "offset_products")],
)
def test_output_dependencies(tmp_path, setting, output):
    p = make(tmp_path, changes={"processing.isce2.pair." + setting: False})
    check_error(p, "CONFIG_CONFLICT")
    assert (
        resolve(p, ["outputs.pair." + output + "=false"])[1]["outputs"]["pair"][output]
        is False
    )


def test_pair_workers_and_disabled_settings(tmp_path):
    check_error(make(tmp_path, changes={"resources.num_proc": 1}), "CONFIG_CONFLICT")
    assert (
        resolve(
            make(
                tmp_path,
                changes={"outputs.figures.enabled": False, "outputs.figures.dpi": 100},
            )
        )[1]["outputs"]["figures"]["dpi"]
        == 100
    )
    assert (
        resolve(
            make(
                tmp_path,
                "stack",
                {
                    "outputs.stack_advice.enabled": False,
                    "outputs.stack_advice.temporal_neighbors": 3,
                },
            )
        )[1]["outputs"]["stack_advice"]["temporal_neighbors"]
        == 3
    )


@pytest.mark.parametrize("version", [None, True, "1", 1.0, 0, 2])
def test_version_exact(tmp_path, version):
    check_error(make(tmp_path, changes={"schema_version": version}), "CONFIG_VERSION")


def test_version_selection_required(tmp_path):
    data = copy.deepcopy(PROFILES["manual"])
    del data["schema_version"]
    check_error(make(tmp_path, raw=yaml.safe_dump(data).encode()), "CONFIG_VERSION")
    data = copy.deepcopy(PROFILES["manual"])
    del data["workflow"]["pair"]["selection"]
    check_error(make(tmp_path, raw=yaml.safe_dump(data).encode()), "CONFIG_REQUIRED")


@pytest.mark.parametrize(
    "path,value,code",
    [
        ("data.search.unknown", 1, "CONFIG_UNKNOWN_KEY"),
        ("processing.isce2.pair.range_looks", 0, "CONFIG_RANGE"),
        ("data.search.longitude", "1", "CONFIG_TYPE"),
        ("processing.backend", "gamma", "CONFIG_UNSUPPORTED"),
        ("mission.name", "s1", "CONFIG_UNSUPPORTED"),
        ("corrections", ["x"], "CONFIG_UNSUPPORTED"),
    ],
)
def test_error_classification(tmp_path, path, value, code):
    check_error(make(tmp_path, changes={path: value}), code)


BAD_PATHS = [
    "",
    None,
    False,
    0,
    [],
    "C:work",
    "C:/work",
    "C:\\work",
    "\\\\host\\share",
    "//host/share",
    "file:/work",
    "https://host/path",
    "work\tname",
    "work\x7f",
    "work\nname",
    "work\rname",
    "work\x00name",
    "~/work",
    "work/$VAR",
    "work/${VAR}",
    "work/~user",
]


@pytest.mark.parametrize("value", BAD_PATHS)
def test_path_grammar(tmp_path, value):
    check_error(
        make(tmp_path, changes={"project.work_dir": value}),
        "CONFIG_PATH" if isinstance(value, str) else "CONFIG_TYPE",
    )


@pytest.mark.parametrize("field", TASK_PATHS)
def test_path_collisions(tmp_path, field):
    check_error(make(tmp_path, changes={field: "."}), "CONFIG_PATH")


def test_paths_derivation_and_no_io(tmp_path, monkeypatch):
    p = make(
        tmp_path,
        changes={
            "project.work_dir": "a/../work",
            "data.paths.slc_dir": "data/slc",
            "data.paths.orbit_dir": "/mnt/c/nonexistent/orbits",
        },
    )
    original = p.read_bytes()
    with (
        patch.object(Path, "stat", side_effect=AssertionError("no task probes")),
        patch.object(Path, "resolve", side_effect=AssertionError("no realpath")),
    ):
        req, res, rec = resolve(p)
    assert req["project"]["work_dir"] == "a/../work"
    assert res["project"]["work_dir"] == str(tmp_path / "work")
    assert res["data"]["paths"]["slc_dir"] == str(tmp_path / "data/slc")
    assert res["data"]["paths"]["orbit_dir"] == "/mnt/c/nonexistent/orbits"
    assert res["data"]["paths"]["dem_dir"] == str(tmp_path / "work/DEM")
    assert set(tmp_path.iterdir()) == {p} and p.read_bytes() == original
    other = tmp_path / "other"
    other.mkdir()
    monkeypatch.chdir(other)
    assert resolve(p)[1] == res
    assert rec["field_sources"]["data.paths.dem_dir"] == {
        "origin": "derived",
        "dependencies": ["project.work_dir"],
    }


def test_lexical_symlink_base(tmp_path):
    actual = tmp_path / "actual"
    actual.mkdir()
    p = make(actual)
    alias = tmp_path / "alias"
    alias.mkdir()
    q = alias / "input.yaml"
    q.symlink_to(p)
    assert resolve(q)[1]["project"]["work_dir"] == str(alias)
    assert resolve(q)[2]["source"]["path"] == str(q)


def test_pairwise_path_collision(tmp_path):
    check_error(
        make(
            tmp_path,
            changes={"data.paths.slc_dir": "same", "outputs.paths.results_dir": "same"},
        ),
        "CONFIG_PATH",
    )
    check_error(make(tmp_path, changes={"project.work_dir": "/"}), "CONFIG_PATH")


def test_request_record_default_sources(tmp_path):
    p = make(
        tmp_path,
        changes={
            "mission.platform": "S1A",
            "workflow.pair.reference_date": "20250101",
            "data.catalog.timeout_seconds": 60,
            "processing.roi.half_width_deg": None,
        },
    )
    req, res, record = resolve(p, ["data.search.latitude=1", "data.provider=cdse"])
    assert req["data"]["search"]["latitude"] == res["data"]["search"]["latitude"] == 1
    assert record["yaml_explicit"]["data"]["search"]["latitude"] == 0
    assert (
        req["mission"]["platform"] == "Sentinel-1A"
        and req["workflow"]["pair"]["reference_date"] == "2025-01-01"
    )
    assert res["data"]["catalog"]["timeout_seconds"] == 60
    assert record["field_sources"]["data.catalog.timeout_seconds"]["origin"] == "yaml"
    assert record["field_sources"]["data.search.latitude"] == {
        "origin": "cli_override",
        "dependencies": [],
    }
    assert record["field_sources"]["project.name"]["origin"] == "schema_default"
    assert (
        record["field_sources"]["processing.isce2.pair.range_looks"]["origin"]
        == "profile_default"
    )
    assert record["field_sources"]["processing.roi.half_width_deg"] == {
        "origin": "derived",
        "dependencies": ["data.search.half_width_deg"],
    }
    assert record["source"] == {
        "kind": "yaml",
        "path": str(p),
        "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
    }
    assert record["insarforge_version"] == importlib.metadata.version("insarforge")
    assert (
        record["record_version"] == 1
        and record["status"] == "complete"
        and record["scope"] == "configuration_only"
        and record["defaults_revision"] == "schema1-p3-v1"
    )
    assert {"path": "workflow.pair.reference_date", "rule": "date_iso"} in record[
        "normalizations"
    ]
    assert {"path": "mission.platform", "rule": "platform_alias"} in record[
        "normalizations"
    ]
    assert set(record["deferred_checks"]) == {
        "acquisition_selection",
        "single_orbit",
        "product_metadata",
        "backend_capability",
        "resource_allocation",
        "data_access",
    }
    assert set(record) == {
        "record_version",
        "status",
        "scope",
        "schema_version",
        "defaults_revision",
        "insarforge_version",
        "source",
        "base_directory",
        "yaml_explicit",
        "overrides",
        "field_sources",
        "normalizations",
        "deferred_checks",
    }
    assert "event_bracketing" in resolve(make(tmp_path, "event"))[2]["deferred_checks"]
    assert (
        resolve(make(tmp_path), ["data.provider=cdse"])[1]["data"]["catalog"][
            "timeout_seconds"
        ]
        == 90
    )
    rec = resolve(make(tmp_path), ["data.provider=cdse"])[2]
    assert rec["field_sources"]["data.catalog.timeout_seconds"] == {
        "origin": "profile_default",
        "dependencies": ["data.provider"],
    }


def test_isolation_order_and_numeric_preservation(tmp_path):
    p = make(tmp_path)
    a = resolve(p)
    original = copy.deepcopy(a)
    a[1]["processing"]["isce2"]["pair"]["swaths"].append(99)
    resolve(p, ["data.provider=cdse", "processing.isce2.pair.range_looks=10"])
    assert resolve(p) == original
    one = resolve(p, ["project.name=x", "processing.isce2.pair.swaths=[3,1]"])
    two = resolve(p, ["processing.isce2.pair.swaths=[3,1]", "project.name=x"])
    assert dump(one[0]) == dump(two[0]) and dump(one[1]) == dump(two[1])
    req, res, _ = resolve(
        make(tmp_path, changes={"data.search.latitude": 0.123456789012345})
    )
    assert (
        at(req, "data.search.latitude")
        == at(res, "data.search.latitude")
        == 0.123456789012345
    )
    data = copy.deepcopy(PROFILES["manual"])
    data = {"data": data["data"], "workflow": data["workflow"], "schema_version": 1}
    req, _, _ = resolve(
        make(tmp_path, raw=yaml.safe_dump(data, sort_keys=False).encode())
    )
    assert list(req) == ["schema_version", "workflow", "data"]
