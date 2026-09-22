"""Canonical test composition and fresh persisted reads, using production APIs.

The only business implementations/ports are the P4.3-01 harness. This module
adds no scheduler, cache, fake store, or direct operation invocation.
"""

from dataclasses import dataclass
from pathlib import Path

from insarforge.contracts.context import ResourceAllocation, ResourceRequest
from insarforge.contracts.execution import (
    CachePolicy,
    OutputDeclaration,
    OutputRef,
    RestartSafety,
    RetryPolicy,
    TaskSpec,
    WorkflowPlan,
)
from insarforge.contracts.record_serialization import record_from_bytes
from insarforge.contracts.values import ArtifactRef
from insarforge.core.runtime import Runtime
from insarforge.provenance.workspace import Workspace, key

ORDER = ("search", "acquire", "inspect", "process", "correct", "analyze", "assess")
BUDGET = ResourceAllocation(1, None, 0)


def canonical_plan(harness, *, search_label="synthetic:query"):
    """Acquired Product also feeds process; inspect contributes its metadata."""
    edges = {
        "search": {},
        "acquire": {"catalog": (OutputRef("search", "out"),)},
        "inspect": {"source": (OutputRef("acquire", "out"),)},
        "process": {
            "source": (OutputRef("acquire", "out"),),
            "metadata": (OutputRef("inspect", "out"),),
        },
        "correct": {"source": (OutputRef("process", "out"),)},
        "analyze": {"source": (OutputRef("correct", "out"),)},
        "assess": {"source": (OutputRef("analyze", "out"),)},
    }
    tasks = []
    for operation in ORDER:
        registration = harness.registration(operation)
        binding = harness.registry.resolve_binding(
            registration.ref, "synthetic:" + operation, 1
        )
        outputs = tuple(
            OutputDeclaration(
                p.port_id,
                p.schema.schema_id,
                p.schema.schema_version,
                p.count,
                None if p.profile is None else p.profile.profile_id,
                None if p.profile is None else p.profile.profile_version,
            )
            for p in binding.outputs
        )
        tasks.append(
            TaskSpec(
                schema_version=1,
                task_id=operation,
                plugin_ref=registration.ref,
                operation_id=binding.operation_id,
                operation_api_version=binding.operation_api_version,
                inputs=edges[operation],
                outputs=outputs,
                semantic_parameters={
                    "label": search_label
                    if operation == "search"
                    else "synthetic:" + operation
                },
                resources=ResourceRequest(),
                retry_policy=RetryPolicy(1),
                restart_safety=RestartSafety.RESTARTABLE,
                cache_policy=CachePolicy.DISABLED,
            )
        )
    return WorkflowPlan(1, tuple(tasks))


def canonical_runtime(harness, workspace):
    implementation = {
        name: Path(__file__).with_name(name)
        for name in ("__init__.py", "_fake_plugins.py", "_fake_operations.py")
    }
    return Runtime(
        harness.registry,
        workspace,
        budget=BUDGET,
        implementation_files={
            r.ref: dict(implementation) for r in harness.registry.registrations()
        },
    )


@dataclass(frozen=True)
class PersistedRun:
    plan: WorkflowPlan
    run: dict
    summary: dict
    resolutions: dict
    receipts: dict
    started: dict
    finished: dict
    artifacts: dict
    records: dict


def reopen_workspace(workspace):
    """Read one canonical run using only its workspace path, not a live result.

    All records use existing strict readers. This test reader deliberately does
    not resume or execute anything, and neither repairs nor synthesizes facts.
    """
    store = Workspace(workspace)
    runs = store.inventory("runs/*/run.json")
    assert len(runs) == 1
    location = runs[0]
    prefix = location.rsplit("/", 1)[0]
    run = store.read(location, "run")
    assert prefix == "runs/" + run["run_id"]
    plan = WorkflowPlan.from_json(store.read_bytes(prefix + "/plan.json"))
    summary = store.read(prefix + "/summary.json", "summary")
    assert store.status(run["run_id"]) == summary["status"]
    resolutions, receipts, started, finished, artifacts, records = (
        {},
        {},
        {},
        {},
        {},
        {},
    )
    for task in plan.tasks:
        name = task.task_id
        resolution = store.read(
            prefix + "/resolutions/" + key(name) + ".json", "resolution"
        )
        receipt = store.read(resolution["receipt"], "receipt")
        attempt = resolution["receipt"].rsplit("/", 1)[0]
        resolutions[name] = resolution
        receipts[name] = receipt
        started[name] = store.read(attempt + "/started.json", "started")
        finished[name] = store.read(attempt + "/finished.json", "finished")
        artifacts[name] = {
            port: tuple(ArtifactRef(**value) for value in values)
            for port, values in receipt["outputs"].items()
        }
        records[name] = {
            port: tuple(
                record_from_bytes(ref, store.read_bytes(ref.locator)) for ref in refs
            )
            for port, refs in artifacts[name].items()
        }
    return PersistedRun(
        plan, run, summary, resolutions, receipts, started, finished, artifacts, records
    )
