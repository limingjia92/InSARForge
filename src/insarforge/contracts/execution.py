"""Immutable planning values. No registry, operation adapters or runtime I/O."""

from __future__ import annotations

import hashlib
import heapq
import math
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import TypeAlias

from insarforge.contracts._execution_json import array, canonical, decode, fields, plain
from insarforge.contracts.context import ResourceRequest
from insarforge.contracts.errors import ContractError
from insarforge.contracts.identity import PluginKind, PluginRef
from insarforge.contracts.values import (
    ArtifactRef,
    FrozenJSON,
    freeze_json,
    validate_identifier,
)

TASK_SCHEMA_ID = "insarforge:task-spec"
PLAN_SCHEMA_ID = "insarforge:workflow-plan"
PLAN_DIGEST_DOMAIN = b"insarforge.workflow-plan.v1\0"


def _identifier(value: str) -> None:
    if type(value) is not str:
        raise ContractError("PLAN_IDENTIFIER")
    try:
        validate_identifier(value)
    except (TypeError, ValueError):
        raise ContractError("PLAN_IDENTIFIER") from None


def _integer(value: int, minimum: int = 1) -> None:
    if type(value) is not int or value < minimum:
        raise ContractError("PLAN_INTEGER")


def _version(value: int) -> None:
    _integer(value)
    if value != 1:
        raise ContractError("PLAN_SCHEMA_VERSION")


def _sequence(value: object) -> tuple:
    if type(value) not in (tuple, list):
        raise ContractError("PLAN_SEQUENCE")
    return tuple(value)


def _artifact(value: ArtifactRef) -> None:
    if type(value) is not ArtifactRef:
        raise ContractError("PLAN_ARTIFACT")
    _identifier(value.record_id)
    _identifier(value.schema_id)
    _integer(value.schema_version)
    for item in (value.manifest_digest, value.locator):
        if type(item) is not str or not item or item != item.strip():
            raise ContractError("PLAN_ARTIFACT")
    if value.semantic_digest is not None and (
        type(value.semantic_digest) is not str
        or not value.semantic_digest
        or value.semantic_digest != value.semantic_digest.strip()
    ):
        raise ContractError("PLAN_ARTIFACT")


class TaskState(Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    BLOCKED = "blocked"


class CompletionDisposition(Enum):
    EXECUTED = "executed"
    CACHE_REUSED = "cache_reused"


class AttemptOutcome(Enum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


class RestartSafety(Enum):
    RESTARTABLE = "restartable"
    UNSAFE = "unsafe"


class CachePolicy(Enum):
    AUTO = "auto"
    DISABLED = "disabled"


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 1
    backoff_seconds: float | int = 0

    def __post_init__(self) -> None:
        _integer(self.max_attempts)
        if type(self.backoff_seconds) not in (int, float):
            raise ContractError("PLAN_BACKOFF")
        try:
            finite = math.isfinite(self.backoff_seconds)
        except OverflowError:
            finite = False
        if not finite or self.backoff_seconds < 0:
            raise ContractError("PLAN_BACKOFF")


@dataclass(frozen=True)
class OutputRef:
    task_id: str
    port: str

    def __post_init__(self) -> None:
        _identifier(self.task_id)
        _identifier(self.port)


@dataclass(frozen=True)
class OutputDeclaration:
    """Data-only port declaration; does not replace operation schema/profile refs."""

    port: str
    schema_id: str
    schema_version: int
    count: int = 1
    profile_id: str | None = None
    profile_version: int | None = None

    def __post_init__(self) -> None:
        _identifier(self.port)
        _identifier(self.schema_id)
        _integer(self.schema_version)
        _integer(self.count)
        if self.profile_id is None:
            if self.profile_version is not None:
                raise ContractError("PLAN_PROFILE")
        else:
            _identifier(self.profile_id)
            _integer(self.profile_version)


InputSource: TypeAlias = ArtifactRef | OutputRef


@dataclass(frozen=True)
class TaskSpec:
    schema_version: int
    task_id: str
    plugin_ref: PluginRef
    operation_id: str
    operation_api_version: int
    inputs: Mapping[str, tuple[InputSource, ...]]
    outputs: tuple[OutputDeclaration, ...]
    semantic_parameters: FrozenJSON
    resources: ResourceRequest
    retry_policy: RetryPolicy = RetryPolicy()
    restart_safety: RestartSafety = RestartSafety.UNSAFE
    cache_policy: CachePolicy = CachePolicy.AUTO

    def __post_init__(self) -> None:
        _version(self.schema_version)
        _identifier(self.task_id)
        _identifier(self.operation_id)
        _integer(self.operation_api_version)
        if (
            type(self.plugin_ref) is not PluginRef
            or type(self.plugin_ref.kind) is not PluginKind
        ):
            raise ContractError("PLAN_PLUGIN")
        _identifier(self.plugin_ref.plugin_id)
        _integer(self.plugin_ref.api_version)
        if type(self.resources) is not ResourceRequest:
            raise ContractError("PLAN_RESOURCES")
        _integer(self.resources.cpu_cores)
        _integer(self.resources.gpu_count, 0)
        if self.resources.memory_bytes is not None:
            _integer(self.resources.memory_bytes)
        if type(self.retry_policy) is not RetryPolicy:
            raise ContractError("PLAN_RETRY_POLICY")
        if (
            type(self.restart_safety) is not RestartSafety
            or type(self.cache_policy) is not CachePolicy
        ):
            raise ContractError("PLAN_POLICY")
        if not isinstance(self.inputs, Mapping):
            raise ContractError("PLAN_INPUTS")
        inputs = {}
        for port, sources in self.inputs.items():
            _identifier(port)
            if port in inputs:
                raise ContractError("PLAN_DUPLICATE_PORT")
            sources = _sequence(sources)
            for source in sources:
                if type(source) is ArtifactRef:
                    _artifact(source)
                elif type(source) is not OutputRef:
                    raise ContractError("PLAN_SOURCE")
            inputs[port] = sources
        outputs = _sequence(self.outputs)
        if not outputs or any(
            type(output) is not OutputDeclaration for output in outputs
        ):
            raise ContractError("PLAN_OUTPUTS")
        ports = [output.port for output in outputs]
        if len(set(ports)) != len(ports) or set(ports) & inputs.keys():
            raise ContractError("PLAN_DUPLICATE_PORT")
        try:
            parameters = freeze_json(self.semantic_parameters)
        except (TypeError, ValueError, RecursionError):
            raise ContractError("PLAN_PARAMETERS") from None
        object.__setattr__(
            self, "inputs", MappingProxyType(dict(sorted(inputs.items())))
        )
        object.__setattr__(
            self, "outputs", tuple(sorted(outputs, key=lambda x: x.port))
        )
        object.__setattr__(self, "semantic_parameters", parameters)

    def to_dict(self) -> dict:
        """Return an independent, persistence-safe explicit JSON projection."""
        result = _task_dict(self)
        canonical(result)
        return result

    @classmethod
    def from_dict(cls, value: dict) -> TaskSpec:
        try:
            canonical(value)
            return _task_from_dict(value)
        except (TypeError, ValueError, OverflowError, RecursionError):
            raise ContractError("PLAN_TASK_JSON") from None


@dataclass(frozen=True)
class WorkflowPlan:
    schema_version: int
    tasks: tuple[TaskSpec, ...]
    external_inputs: tuple[ArtifactRef, ...] = ()

    def __post_init__(self) -> None:
        _version(self.schema_version)
        tasks = _sequence(self.tasks)
        if any(type(task) is not TaskSpec for task in tasks):
            raise ContractError("PLAN_TASKS")
        ids = [task.task_id for task in tasks]
        if len(set(ids)) != len(ids):
            raise ContractError("PLAN_DUPLICATE_TASK")
        external = _sequence(self.external_inputs)
        declared = {}
        for ref in external:
            _artifact(ref)
            if ref.record_id in declared:
                raise ContractError("PLAN_DUPLICATE_EXTERNAL")
            declared[ref.record_id] = ref
        consumed = {}
        by_id = {task.task_id: task for task in tasks}
        for task in tasks:
            for sources in task.inputs.values():
                for source in sources:
                    if type(source) is ArtifactRef:
                        if (
                            source.record_id in consumed
                            and consumed[source.record_id] != source
                        ):
                            raise ContractError("PLAN_CONFLICTING_EXTERNAL")
                        consumed[source.record_id] = source
                    else:
                        if source.task_id == task.task_id:
                            raise ContractError("PLAN_SELF_REFERENCE")
                        if source.task_id not in by_id:
                            raise ContractError("PLAN_UNKNOWN_TASK")
                        if source.port not in {
                            p.port for p in by_id[source.task_id].outputs
                        }:
                            raise ContractError("PLAN_UNKNOWN_PORT")
        if declared != consumed:
            raise ContractError("PLAN_EXTERNAL_SET")
        object.__setattr__(self, "tasks", tuple(sorted(tasks, key=lambda x: x.task_id)))
        object.__setattr__(
            self, "external_inputs", tuple(sorted(external, key=lambda x: x.record_id))
        )
        self.topological_order()

    def dependencies(self, task_id: str) -> tuple[str, ...]:
        task = self.task(task_id)
        return tuple(
            sorted(
                {
                    source.task_id
                    for sources in task.inputs.values()
                    for source in sources
                    if type(source) is OutputRef
                }
            )
        )

    def dependents(self, task_id: str) -> tuple[str, ...]:
        self.task(task_id)
        return tuple(
            task.task_id
            for task in self.tasks
            if task_id in self.dependencies(task.task_id)
        )

    def task(self, task_id: str) -> TaskSpec:
        _identifier(task_id)
        for task in self.tasks:
            if task.task_id == task_id:
                return task
        raise ContractError("PLAN_UNKNOWN_TASK")

    def topological_order(self) -> tuple[str, ...]:
        dependencies = {
            task.task_id: set(self.dependencies(task.task_id)) for task in self.tasks
        }
        children = {task.task_id: [] for task in self.tasks}
        for task_id, parents in dependencies.items():
            for parent in parents:
                children[parent].append(task_id)
        ready = [key for key, parents in dependencies.items() if not parents]
        heapq.heapify(ready)
        result = []
        while ready:
            key = heapq.heappop(ready)
            result.append(key)
            for child in children[key]:
                dependencies[child].remove(key)
                if not dependencies[child]:
                    heapq.heappush(ready, child)
        if len(result) != len(self.tasks):
            raise ContractError("PLAN_CYCLE")
        return tuple(result)

    def to_dict(self) -> dict:
        result = {
            "schema_id": PLAN_SCHEMA_ID,
            "schema_version": self.schema_version,
            "tasks": [_task_dict(task) for task in self.tasks],
            "external_inputs": [_artifact_dict(ref) for ref in self.external_inputs],
        }
        canonical(result)
        return result

    @property
    def digest(self) -> str:
        return hashlib.sha256(
            PLAN_DIGEST_DOMAIN + canonical(self.to_dict())
        ).hexdigest()

    def to_json(self) -> bytes:
        return canonical({"plan": self.to_dict(), "plan_digest": self.digest})

    @classmethod
    def from_json(cls, payload: str | bytes) -> WorkflowPlan:
        envelope = fields(decode(payload), "plan plan_digest")
        plan = cls.from_dict(envelope["plan"])
        if (
            type(envelope["plan_digest"]) is not str
            or envelope["plan_digest"] != plan.digest
        ):
            raise ContractError("PLAN_DIGEST_MISMATCH")
        return plan

    @classmethod
    def from_dict(cls, value: dict) -> WorkflowPlan:
        try:
            canonical(value)
            value = fields(value, "schema_id schema_version tasks external_inputs")
            if value["schema_id"] != PLAN_SCHEMA_ID:
                raise ContractError("PLAN_SCHEMA_ID")
            return cls(
                value["schema_version"],
                tuple(TaskSpec.from_dict(task) for task in array(value["tasks"])),
                tuple(
                    _artifact_from_dict(ref) for ref in array(value["external_inputs"])
                ),
            )
        except (TypeError, ValueError, OverflowError, RecursionError):
            raise ContractError("PLAN_JSON_VALUE") from None


def _artifact_dict(ref: ArtifactRef) -> dict:
    return {
        "record_id": ref.record_id,
        "schema_id": ref.schema_id,
        "schema_version": ref.schema_version,
        "semantic_digest": ref.semantic_digest,
        "manifest_digest": ref.manifest_digest,
        "locator": ref.locator,
    }


def _artifact_from_dict(value: dict) -> ArtifactRef:
    value = fields(
        value,
        "record_id schema_id schema_version semantic_digest manifest_digest locator",
    )
    result = ArtifactRef(**value)
    _artifact(result)
    return result


def _task_dict(task: TaskSpec) -> dict:
    def source(ref):
        if type(ref) is ArtifactRef:
            return {"kind": "artifact", "artifact": _artifact_dict(ref)}
        return {"kind": "output", "task_id": ref.task_id, "port": ref.port}

    return {
        "schema_id": TASK_SCHEMA_ID,
        "schema_version": task.schema_version,
        "task_id": task.task_id,
        "plugin_ref": {
            "kind": task.plugin_ref.kind.value,
            "plugin_id": task.plugin_ref.plugin_id,
            "api_version": task.plugin_ref.api_version,
        },
        "operation_id": task.operation_id,
        "operation_api_version": task.operation_api_version,
        "inputs": {
            port: [source(ref) for ref in refs] for port, refs in task.inputs.items()
        },
        "outputs": [
            {
                "port": out.port,
                "schema_id": out.schema_id,
                "schema_version": out.schema_version,
                "profile_id": out.profile_id,
                "profile_version": out.profile_version,
                "count": out.count,
            }
            for out in task.outputs
        ],
        "semantic_parameters": plain(task.semantic_parameters),
        "resources": {
            "cpu_cores": task.resources.cpu_cores,
            "memory_bytes": task.resources.memory_bytes,
            "gpu_count": task.resources.gpu_count,
        },
        "retry_policy": {
            "max_attempts": task.retry_policy.max_attempts,
            "backoff_seconds": task.retry_policy.backoff_seconds,
        },
        "restart_safety": task.restart_safety.value,
        "cache_policy": task.cache_policy.value,
    }


def _task_from_dict(value: dict) -> TaskSpec:
    value = fields(
        value,
        "schema_id schema_version task_id plugin_ref operation_id operation_api_version inputs outputs semantic_parameters resources retry_policy restart_safety cache_policy",
    )
    if value["schema_id"] != TASK_SCHEMA_ID:
        raise ContractError("PLAN_SCHEMA_ID")
    plugin = fields(value["plugin_ref"], "kind plugin_id api_version")
    if type(value["inputs"]) is not dict:
        raise ContractError("PLAN_INPUTS")
    inputs = {}
    for port, sources in value["inputs"].items():
        parsed = []
        for source in array(sources):
            if type(source) is not dict:
                raise ContractError("PLAN_SOURCE")
            if source.get("kind") == "artifact":
                fields(source, "kind artifact")
                parsed.append(_artifact_from_dict(source["artifact"]))
            elif source.get("kind") == "output":
                fields(source, "kind task_id port")
                parsed.append(OutputRef(source["task_id"], source["port"]))
            else:
                raise ContractError("PLAN_SOURCE")
        inputs[port] = tuple(parsed)
    outputs = tuple(
        OutputDeclaration(
            **fields(
                out, "port schema_id schema_version profile_id profile_version count"
            )
        )
        for out in array(value["outputs"])
    )
    resources = ResourceRequest(
        **fields(value["resources"], "cpu_cores memory_bytes gpu_count")
    )
    retry = RetryPolicy(**fields(value["retry_policy"], "max_attempts backoff_seconds"))
    return TaskSpec(
        value["schema_version"],
        value["task_id"],
        PluginRef(
            PluginKind(plugin["kind"]), plugin["plugin_id"], plugin["api_version"]
        ),
        value["operation_id"],
        value["operation_api_version"],
        inputs,
        outputs,
        value["semantic_parameters"],
        resources,
        retry,
        RestartSafety(value["restart_safety"]),
        CachePolicy(value["cache_policy"]),
    )
