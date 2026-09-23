import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from insarforge.contracts.values import validate_identifier


def _v(n, v, minv=None):
    if isinstance(v, bool) or not isinstance(v, int):
        raise TypeError(n)
    if minv is not None and v < minv:
        raise ValueError(n)


@dataclass(frozen=True)
class ResourceRequest:
    cpu_cores: int = 1
    memory_bytes: int | None = None
    gpu_count: int = 0

    def __post_init__(self):
        _v("cpu", self.cpu_cores, 1)
        _v("gpu", self.gpu_count, 0)
        if self.memory_bytes is not None:
            _v("memory", self.memory_bytes, 1)


@dataclass(frozen=True)
class ResourceAllocation:
    cpu_cores: int
    memory_bytes: int | None
    gpu_count: int

    def __post_init__(self):
        ResourceRequest(self.cpu_cores, self.memory_bytes, self.gpu_count)


@dataclass(frozen=True)
class ExecutionContext:
    run_id: str
    task_id: str
    attempt_id: str
    attempt_dir: Path
    artifact_dir: Path
    scratch_dir: Path
    allocated_resources: ResourceAllocation
    logger: logging.Logger
    cancellation_requested: Callable[[], bool]

    def __post_init__(self):
        for x in (self.run_id, self.task_id, self.attempt_id):
            validate_identifier(x)
        for x in (self.attempt_dir, self.artifact_dir, self.scratch_dir):
            if not isinstance(x, Path):
                raise TypeError("path")
        if not isinstance(self.allocated_resources, ResourceAllocation):
            raise TypeError("resources")
        if not isinstance(self.logger, logging.Logger):
            raise TypeError("logger")
        if not callable(self.cancellation_requested):
            raise TypeError("callback")
