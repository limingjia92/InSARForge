"""Schema v1. Shared leaf annotations also validate sparse source/overrides.

Separate concrete profiles make inactive fields absent, rather than nullable.
Model fields are the sole source of leaf rules, order and fixed defaults.
"""

import math
import re
from datetime import date
from typing import Annotated, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    model_validator,
)
from pydantic_core import PydanticCustomError

from ._values import path_string, work_path_string
from .errors import ConfigurationError, issue


def real(value):
    if type(value) not in (int, float):
        raise PydanticCustomError("CONFIG_TYPE", "number required")
    try:
        finite = math.isfinite(value)
    except OverflowError:
        finite = False
    if not finite:
        raise PydanticCustomError("CONFIG_RANGE", "finite number required")
    return value


def calendar(value):
    if re.fullmatch(r"[0-9]{8}", value):
        value = f"{value[:4]}-{value[4:6]}-{value[6:]}"
    elif not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        raise PydanticCustomError("CONFIG_RANGE", "date format")
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        raise PydanticCustomError("CONFIG_RANGE", "calendar date") from None


def label(value):
    if (
        not value.strip()
        or len(value) > 128
        or any(c in value for c in "\n\r\v\f\x85\u2028\u2029")
    ):
        raise PydanticCustomError("CONFIG_RANGE", "single line label")
    return value


def string(value):
    if type(value) is not str:
        raise PydanticCustomError("CONFIG_TYPE", "string required")
    return value


def version(value):
    if type(value) is not int or value != 1:
        raise PydanticCustomError("CONFIG_VERSION", "version 1 required")
    return value


PLATFORM_ALIASES = {
    "S1": "Sentinel-1",
    "S1A": "Sentinel-1A",
    "S1B": "Sentinel-1B",
    "S1C": "Sentinel-1C",
    "S1D": "Sentinel-1D",
}
PROVIDER_TIMEOUTS = {"asf": 60, "cdse": 90}
DEFAULTS_REVISION = "schema1-p3-v1"
DEFERRED_CHECKS = (
    "acquisition_selection",
    "single_orbit",
    "product_metadata",
    "backend_capability",
    "resource_allocation",
    "data_access",
)
TASK_DIRECTORIES = {
    "data.paths.slc_dir": "SLC",
    "data.paths.orbit_dir": "orbits",
    "data.paths.dem_dir": "DEM",
    "data.paths.aux_dir": "AUX",
    "outputs.paths.process_dir": "process",
    "outputs.paths.results_dir": "results",
}
FORBIDDEN_OVERRIDES = frozenset(
    {
        "schema_version",
        "workflow.type",
        "workflow.pair.selection",
        "mission.name",
        "processing.backend",
    }
)

Positive = Annotated[StrictInt, Field(gt=0)]
Nonnegative = Annotated[StrictInt, Field(ge=0)]
Real = Annotated[int | float, BeforeValidator(real)]
Width = Annotated[Real, Field(ge=0)]
Unit = Annotated[Real, Field(ge=0, le=1)]
Date = Annotated[StrictStr, AfterValidator(calendar)]
PathString = Annotated[StrictStr, BeforeValidator(path_string)]
WorkPath = Annotated[StrictStr, BeforeValidator(work_path_string)]
Label = Annotated[StrictStr, AfterValidator(label)]
Version = Annotated[StrictInt, BeforeValidator(version)]
Selection = Annotated[Literal["manual", "event"], BeforeValidator(string)]
WorkflowType = Annotated[Literal["pair", "stack"], BeforeValidator(string)]
Stage = Annotated[
    Literal[
        "all", "search", "download", "orbit", "dem", "prepare", "process", "postprocess"
    ],
    BeforeValidator(string),
]
Provider = Annotated[Literal["asf", "cdse"], BeforeValidator(string)]
Platform = Annotated[
    Literal["Sentinel-1", "Sentinel-1A", "Sentinel-1B", "Sentinel-1C", "Sentinel-1D"],
    BeforeValidator(lambda v: PLATFORM_ALIASES.get(string(v), v)),
]


def swaths(value):
    if (
        not value
        or len(set(value)) != len(value)
        or any(x not in (1, 2, 3) for x in value)
    ):
        raise PydanticCustomError("CONFIG_RANGE", "unique swaths 1/2/3 required")
    return value


def empty(value):
    if value:
        raise PydanticCustomError("CONFIG_UNSUPPORTED", "empty list only")
    return value


Swaths = Annotated[list[StrictInt], AfterValidator(swaths)]
Empty = Annotated[list, AfterValidator(empty)]


def default(value, origin="schema_default"):
    return Field(default=value, json_schema_extra={"origin": origin})


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)


class Project(Model):
    name: Label | None = default(None)
    work_dir: WorkPath = default(".")


class ManualPair(Model):
    selection: Annotated[Literal["manual"], BeforeValidator(string)]
    reference_date: Date
    secondary_date: Date


class EventPair(Model):
    selection: Annotated[Literal["event"], BeforeValidator(string)]
    event_date: Date
    half_window_days: Positive = default(12, "profile_default")


class StackDates(Model):
    start_date: Date
    end_date: Date


class WorkflowCommon(Model):
    type: WorkflowType = default("pair")
    stage: Stage = default("all")


class ManualWorkflow(WorkflowCommon):
    pair: ManualPair


class EventWorkflow(WorkflowCommon):
    pair: EventPair


class StackWorkflow(WorkflowCommon):
    type: WorkflowType = default("stack", "profile_default")
    stack: StackDates


class Mission(Model):
    name: Annotated[Literal["sentinel1"], BeforeValidator(string)] = default(
        "sentinel1", "profile_default"
    )
    platform: Platform = default("Sentinel-1", "profile_default")
    relative_orbit: Positive | None = default(None)


class Search(Model):
    longitude: Annotated[Real, Field(ge=-180, le=180)]
    latitude: Annotated[Real, Field(ge=-90, le=90)]
    half_width_deg: Width = default(0.2, "profile_default")


class Catalog(Model):
    timeout_seconds: Positive
    request_size: Positive = default(1000, "profile_default")


class Download(Model):
    zip_check_backend: Annotated[
        Literal["auto", "python", "zipinfo"], BeforeValidator(string)
    ] = default("auto")


class DataPaths(Model):
    slc_dir: PathString | None = default(None)
    orbit_dir: PathString | None = default(None)
    dem_dir: PathString | None = default(None)
    aux_dir: PathString | None = default(None)


class Data(Model):
    provider: Provider = default("asf", "profile_default")
    search: Search
    catalog: Catalog
    download: Download
    paths: DataPaths


class Roi(Model):
    half_width_deg: Width | None = default(None)


class PairProcessing(Model):
    swaths: Swaths = default([1, 2, 3], "profile_default")
    range_looks: Positive = default(20, "profile_default")
    azimuth_looks: Positive = default(5, "profile_default")
    filter_strength: Unit = default(0.4, "profile_default")
    unwrap: StrictBool = default(True, "profile_default")
    unwrapper: Annotated[Literal["snaphu_mcf"], BeforeValidator(string)] = default(
        "snaphu_mcf", "profile_default"
    )
    dense_offsets: StrictBool = default(True, "profile_default")
    esd: StrictBool = default(True, "profile_default")
    use_gpu: StrictBool = default(True, "profile_default")


class StackProcessing(Model):
    use_gpu: StrictBool = default(True, "profile_default")


class PairIsce2(Model):
    pair: PairProcessing


class StackIsce2(Model):
    stack: StackProcessing


class ProcessingCommon(Model):
    backend: Annotated[Literal["isce2"], BeforeValidator(string)] = default(
        "isce2", "profile_default"
    )
    roi: Roi


class PairBackend(ProcessingCommon):
    isce2: PairIsce2


class StackBackend(ProcessingCommon):
    isce2: StackIsce2


class PairExport(Model):
    min_coherence: Unit = default(0.3, "profile_default")


class PairQC(Model):
    pair_export: PairExport


class StackQC(Model):
    pass


class Resources(Model):
    num_proc: Nonnegative = default(0)


class OutputPaths(Model):
    process_dir: PathString | None = default(None)
    results_dir: PathString | None = default(None)


class PairOutput(Model):
    phase_products: StrictBool = default(True, "profile_default")
    offset_products: StrictBool = default(True, "profile_default")


class Figures(Model):
    enabled: StrictBool = default(True)
    dpi: Positive = default(300, "profile_default")


class Advice(Model):
    enabled: StrictBool = default(True, "profile_default")
    temporal_neighbors: Positive = default(2, "profile_default")
    quicklook_range_looks: Positive = default(20, "profile_default")
    quicklook_azimuth_looks: Positive = default(5, "profile_default")


class PairOutputs(Model):
    paths: OutputPaths
    pair: PairOutput
    figures: Figures


class StackOutputs(Model):
    paths: OutputPaths
    figures: Figures
    stack_advice: Advice


class Config(Model):
    schema_version: Version
    project: Project
    workflow: ManualWorkflow
    mission: Mission
    data: Data
    processing: PairBackend
    corrections: Empty = default([])
    analyzers: Empty = default([])
    qc: PairQC
    resources: Resources
    outputs: PairOutputs

    @model_validator(mode="after")
    def relationships(self):
        issues = []
        if self.workflow.type == "pair":
            pair = self.workflow.pair
            if (
                isinstance(pair, ManualPair)
                and pair.reference_date >= pair.secondary_date
            ):
                issues.append(issue("CONFIG_CONFLICT", "workflow.pair.secondary_date"))
            if self.resources.num_proc != 0:
                issues.append(issue("CONFIG_CONFLICT", "resources.num_proc"))
            native = self.processing.isce2.pair
            if not native.unwrap and self.outputs.pair.phase_products:
                issues.append(issue("CONFIG_CONFLICT", "outputs.pair.phase_products"))
            if not native.dense_offsets and self.outputs.pair.offset_products:
                issues.append(issue("CONFIG_CONFLICT", "outputs.pair.offset_products"))
        elif self.workflow.stack.start_date >= self.workflow.stack.end_date:
            issues.append(issue("CONFIG_CONFLICT", "workflow.stack.end_date"))
        search = self.data.search
        for path, width in [
            ("data.search.half_width_deg", search.half_width_deg),
            ("processing.roi.half_width_deg", self.processing.roi.half_width_deg),
        ]:
            if width is not None and (
                abs(search.longitude) + width > 180 or abs(search.latitude) + width > 90
            ):
                issues.append(issue("CONFIG_RANGE", path))
        if issues:
            raise ConfigurationError(issues=issues)
        return self


class EventConfig(Config):
    workflow: EventWorkflow


class StackConfig(Config):
    workflow: StackWorkflow
    processing: StackBackend
    qc: StackQC
    outputs: StackOutputs


PROFILES = {"manual": Config, "event": EventConfig, "stack": StackConfig}
