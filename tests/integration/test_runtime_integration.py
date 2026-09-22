"""Integrated Runtime semantics with the accepted seven-operation fake harness.

Scenario JSON is observational test output in pytest temporary storage. Only
Runtime writes workspace/cache/receipt/state facts; no handler is called here.
"""

import gc
import hashlib
import json
import weakref
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest

from insarforge.contracts.context import ResourceAllocation, ResourceRequest
from insarforge.contracts.execution import (
    CachePolicy,
    OutputRef,
    RestartSafety,
    RetryPolicy,
    TaskState,
    WorkflowPlan,
)
from insarforge.contracts.record_serialization import record_from_bytes
from insarforge.contracts.records import QCReport
from insarforge.contracts.values import ArtifactRef
from insarforge.core.runtime import RuntimeCrash
from insarforge.products.models import Product
from insarforge.provenance.workspace import Workspace, key

from ._canonical_workflow import (
    ORDER,
    canonical_plan,
    canonical_runtime,
    reopen_workspace,
)
from ._fake_operations import build_harness
from ._fake_plugins import Controls, Failure, HoldPoint


def variant(harness, *, cache=CachePolicy.DISABLED, branch=False, changed=False):
    canonical = canonical_plan(harness)
    tasks = [replace(t, cache_policy=cache) for t in canonical.tasks]
    if branch:
        tasks = [t for t in tasks if t.task_id in ORDER[:5]]
        for suffix in ("a", "b"):
            tasks.extend(
                (
                    replace(
                        canonical.task("analyze"),
                        task_id="analyze_" + suffix,
                        cache_policy=cache,
                        semantic_parameters={
                            "label": "synthetic:"
                            + suffix
                            + (":changed" if changed and suffix == "b" else "")
                        },
                    ),
                    replace(
                        canonical.task("assess"),
                        task_id="assess_" + suffix,
                        cache_policy=cache,
                        inputs={"source": (OutputRef("analyze_" + suffix, "out"),)},
                    ),
                )
            )
    return WorkflowPlan(1, tuple(tasks))


def configure(plan, name, **changes):
    return replace(
        plan,
        tasks=tuple(
            replace(t, **changes) if t.task_id == name else t for t in plan.tasks
        ),
    )


def counts(harness, plan, stage="invoke"):
    return {
        t.task_id: harness.controls.journal.count(
            stage, t.operation_id.removeprefix("synthetic:"), t.task_id
        )
        for t in plan.tasks
    }


def attempts(store, run_id, name):
    facts = []
    for path in store.inventory(
        "runs/" + run_id + "/attempts/" + key(name) + "/*/started.json"
    ):
        parent = path.rsplit("/", 1)[0]
        start = store.read(path, "started")
        end = parent + "/finished.json"
        facts.append(
            {
                "path": parent,
                "started": start,
                "finished": store.read(end, "finished")
                if store.path(end).exists()
                else None,
            }
        )
    return sorted(facts, key=lambda f: f["started"]["sequence"])


def terminal(workspace, result):
    """Fresh strict readers cross-check terminal projections and actual receipts."""
    store = Workspace(workspace)
    prefix = "runs/" + result.run_id
    run = store.read(prefix + "/run.json", "run")
    plan = WorkflowPlan.from_json(store.read_bytes(prefix + "/plan.json"))
    summary = store.read(prefix + "/summary.json", "summary")
    assert run["plan_digest"] == plan.digest
    assert store.status(result.run_id) == summary["status"] == result.status
    assert summary["states"] == {n: s.value for n, s in result.states.items()}
    assert summary["completion_order"] == list(result.completion_order)
    assert all(
        s in (TaskState.SUCCEEDED, TaskState.FAILED, TaskState.BLOCKED)
        for s in result.states.values()
    )
    latest = {}
    for path in store.inventory(prefix + "/transitions/*.json"):
        fact = store.read(path, "transition")
        latest[fact["task_id"]] = fact["state"]
    assert latest == summary["states"]
    assert summary["run_id"] == result.run_id
    resolutions = {}
    history = {}
    for task in plan.tasks:
        name = task.task_id
        resolution = store.read(
            prefix + "/resolutions/" + key(name) + ".json", "resolution"
        )
        assert resolution["task_id"] == name
        assert resolution["state"] == summary["states"][name]
        local = attempts(store, result.run_id, name)
        history[name] = local
        for fact in local:
            start, end = fact["started"], fact["finished"]
            assert start["run_id"] == result.run_id and start["task_id"] == name
            assert start["scope_id"] == run["scope_id"]
            assert end is not None and end["attempt_id"] == start["attempt_id"]
            if end["outcome"] == "succeeded":
                assert end["receipt"] == fact["path"] + "/result.json"
            else:
                assert end["receipt"] is None
                assert not store.path(fact["path"] + "/result.json").exists()
        if resolution["state"] == "succeeded":
            receipt = store.read(resolution["receipt"], "receipt")
            parent = resolution["receipt"].rsplit("/", 1)[0]
            start = store.read(parent + "/started.json", "started")
            end = store.read(parent + "/finished.json", "finished")
            assert (
                end["outcome"] == "succeeded"
                and end["receipt"] == resolution["receipt"]
            )
            assert receipt["attempt_id"] == start["attempt_id"] == end["attempt_id"]
            assert (
                receipt["fingerprint"]
                == start["fingerprint"]
                == resolution["fingerprint"]
            )
            assert receipt["execution"] == start["execution"] == resolution["execution"]
            assert receipt["scope_id"] == start["scope_id"]
            assert receipt["inputs"] == start["inputs"]
            producer_inputs = {
                port: tuple(ArtifactRef(**row["artifact"]) for row in rows)
                for port, rows in start["resolved_inputs"].items()
            }
            outputs = {
                p: tuple(ArtifactRef(**ref) for ref in refs)
                for p, refs in receipt["outputs"].items()
            }
            assert outputs == result.outputs[name]
            for refs in outputs.values():
                for ref in refs:
                    raw = store.read_bytes(ref.locator)
                    assert hashlib.sha256(raw).hexdigest() == ref.manifest_digest
                    record = record_from_bytes(ref, raw)
                    if isinstance(record, Product):
                        assert record.produced_by.attempt_id == receipt["attempt_id"]
                        assert (
                            record.produced_by.task_fingerprint.value
                            == receipt["fingerprint"]
                        )
                        assert (
                            record.producer.execution_identity_digest.value
                            == receipt["execution"]
                        )
                        assert tuple(
                            (edge.role, edge.artifact) for edge in record.lineage
                        ) == tuple(
                            (port, item)
                            for port in sorted(producer_inputs)
                            for item in producer_inputs[port]
                        )
                    elif isinstance(record, QCReport):
                        assert record.input_refs == producer_inputs["source"]
            if resolution["disposition"] == "cache_reused":
                assert local == []
            else:
                assert resolution["disposition"] == "executed"
                assert start["run_id"] == result.run_id and receipt["task_id"] == name
        else:
            assert resolution["receipt"] is None and resolution["disposition"] is None
            assert name not in result.outputs
        resolutions[name] = resolution
    if result.status == "SUCCEEDED":
        disk = reopen_workspace(workspace, run_id=result.run_id)
        assert disk.artifacts == result.outputs and disk.summary == summary
    return {
        "run": run,
        "summary": summary,
        "resolutions": resolutions,
        "attempts": history,
    }


def evidence(tmp_path, scenario, harness, plan, runs, **details):
    report = {
        "scenario": scenario,
        "task_ids": [t.task_id for t in plan.tasks],
        "invoke_counts": counts(harness, plan),
        "successful_business_counts": counts(harness, plan, "business"),
        "cache_policies": {t.task_id: t.cache_policy.value for t in plan.tasks},
        "retry_policies": {
            t.task_id: {
                "max_attempts": t.retry_policy.max_attempts,
                "backoff_seconds": t.retry_policy.backoff_seconds,
                "restart_safety": t.restart_safety.value,
            }
            for t in plan.tasks
        },
        "runs": runs,
        **details,
    }
    (tmp_path / "scenario.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )


@pytest.mark.parametrize("failure_count", [1, 2])
def test_rti01_retry_and_finite_budget(tmp_path, failure_count):
    failures = tuple(
        Failure("process", "process", n, True) for n in range(1, failure_count + 1)
    )
    harness = build_harness(controls=Controls(failures=failures))
    plan = configure(variant(harness), "process", retry_policy=RetryPolicy(2, 0))
    sleeps = []
    runtime = canonical_runtime(harness, tmp_path / "workspace", _sleep=sleeps.append)
    result = runtime.run(plan)
    disk = terminal(tmp_path / "workspace", result)
    assert counts(harness, plan)["process"] == 2
    history = disk["attempts"]["process"]
    assert [f["started"]["sequence"] for f in history] == [1, 2]
    assert history[0]["finished"]["error_code"] == "EXECUTION_RETRYABLE"
    assert history[0]["finished"]["retryable"] is True
    assert sleeps == []  # Fixed zero backoff never silently sleeps or resets budget.
    assert b"SYNTHETIC_INJECTED_FAILURE" not in b"".join(
        p.read_bytes() for p in runtime.store.area.rglob("*.json")
    )
    if failure_count == 1:
        assert result.status == "SUCCEEDED"
        assert history[1]["finished"]["outcome"] == "succeeded"
        assert counts(harness, plan, "business")["process"] == 1
        correction = next(
            c
            for c in harness.controls.journal.snapshot()
            if c.stage == "business" and c.operation == "correct"
        )
        assert (
            correction.request.source_inputs["source"][0].artifact
            == result.outputs["process"]["out"][0]
        )
        assert result.completion_order.count("process") == 2
    else:
        assert (
            result.status == "FAILED" and result.states["process"] is TaskState.FAILED
        )
        assert history[1]["finished"]["retryable"] is True
        for name in ("correct", "analyze", "assess"):
            assert (
                result.states[name] is TaskState.BLOCKED
                and counts(harness, plan)[name] == 0
            )
    evidence(
        tmp_path,
        "RTI-01/07/08",
        harness,
        plan,
        [disk],
        failures=[
            {
                "task_id": f.task_id,
                "ordinal": f.ordinal,
                "type": "RetryableExecutionError",
            }
            for f in failures
        ],
        sleep_calls=sleeps,
    )


def test_rti02_permanent_failure_preserves_independent_branch(tmp_path):
    harness = build_harness(
        controls=Controls(failures=(Failure("analyze", "analyze_a", 1, False),))
    )
    plan = configure(
        variant(harness, branch=True), "analyze_a", retry_policy=RetryPolicy(3, 0)
    )
    result = canonical_runtime(harness, tmp_path / "workspace").run(plan)
    disk = terminal(tmp_path / "workspace", result)
    assert result.status == "FAILED"
    assert (
        result.states["analyze_a"] is TaskState.FAILED
        and result.states["assess_a"] is TaskState.BLOCKED
    )
    assert (
        counts(harness, plan)["analyze_a"] == 1
        and counts(harness, plan)["assess_a"] == 0
    )
    assert disk["resolutions"]["assess_a"]["blocked_by"] == ["analyze_a"]
    for name in ("analyze_b", "assess_b"):
        assert (
            result.states[name] is TaskState.SUCCEEDED
            and counts(harness, plan)[name] == 1
        )
    failed = disk["attempts"]["analyze_a"]
    assert len(failed) == 1 and failed[0]["finished"]["retryable"] is False
    assert failed[0]["finished"]["error_code"] == "EXECUTION_FAILED"
    assert disk["attempts"]["assess_a"] == []
    evidence(
        tmp_path,
        "RTI-02/07/08",
        harness,
        plan,
        [disk],
        failures=[{"task_id": "analyze_a", "ordinal": 1, "type": "ExecutionError"}],
    )


@pytest.mark.parametrize(
    "budget,restart",
    [
        (2, RestartSafety.RESTARTABLE),
        (1, RestartSafety.RESTARTABLE),
        (2, RestartSafety.UNSAFE),
    ],
)
def test_rti03_fresh_resume_preserves_history_and_budget(tmp_path, budget, restart):
    harness = build_harness()
    plan = configure(
        variant(harness),
        "process",
        retry_policy=RetryPolicy(budget, 0),
        restart_safety=restart,
    )
    seen = []

    def crash(point):
        if point == "before_receipt":
            seen.append(point)
            if len(seen) == 4:
                raise RuntimeCrash()

    workspace = tmp_path / "workspace"
    runtime = canonical_runtime(harness, workspace, _fault=crash)
    with pytest.raises(RuntimeCrash):
        runtime.run(plan)
    store = Workspace(workspace)
    old = store.read(store.inventory("runs/*/run.json")[0], "run")["run_id"]
    prefix = "runs/" + old
    before = {
        p: hashlib.sha256(store.read_bytes(p)).hexdigest()
        for p in store.inventory(prefix + "/**/*")
        if store.path(p).is_file()
    }
    old_counts = counts(harness, plan)
    assert old_counts == {n: int(n in ORDER[:4]) for n in ORDER}
    assert len(attempts(store, old, "process")) == 1
    assert attempts(store, old, "process")[0]["finished"] is None
    refs = [weakref.ref(obj) for obj in (runtime, harness, plan)]
    del runtime, harness, plan, store
    gc.collect()
    assert all(ref() is None for ref in refs)
    fresh = build_harness()
    runtime = canonical_runtime(fresh, workspace)
    result = runtime.resume(old)
    disk = terminal(workspace, result)
    assert result.run_id != old and disk["run"]["resume_of"] == old
    store = Workspace(workspace)
    old_run = store.read(prefix + "/run.json", "run")
    assert disk["run"]["scope_id"] == old_run["scope_id"]
    after = {
        p: hashlib.sha256(store.read_bytes(p)).hexdigest()
        for p in store.inventory(prefix + "/**/*")
        if store.path(p).is_file()
    }
    assert all(after[p] == digest for p, digest in before.items())
    assert set(after) - set(before) == {prefix + "/recovery.json"}
    recovery = store.read(prefix + "/recovery.json", "recovery")
    assert store.status(old) == recovery["status"] == "INTERRUPTED"
    assert recovery["attempts"][0]["outcome"] == "interrupted"
    plan = WorkflowPlan.from_json(store.read_bytes(prefix + "/plan.json"))
    for name in ORDER[:3]:
        assert counts(fresh, plan)[name] == 0
        assert disk["resolutions"][name]["disposition"] == "cache_reused"
    allowed = budget == 2 and restart is RestartSafety.RESTARTABLE
    assert result.status == ("SUCCEEDED" if allowed else "FAILED")
    if allowed:
        assert counts(fresh, plan) == {n: int(n in ORDER[3:]) for n in ORDER}
        assert [f["started"]["sequence"] for f in disk["attempts"]["process"]] == [2]
    else:
        assert counts(fresh, plan) == dict.fromkeys(ORDER, 0)
        assert disk["resolutions"]["process"]["error_code"] == "RESTART_FORBIDDEN"
    # Returning to the older source cannot replenish the same scope's budget.
    repeated = canonical_runtime(fresh, workspace).resume(old)
    again = terminal(workspace, repeated)
    assert repeated.status == result.status
    assert all(not facts for facts in again["attempts"].values())
    assert all(
        store.status(p.split("/")[1]) != "RUNNING"
        for p in store.inventory("runs/*/run.json")
    )
    evidence(
        tmp_path,
        "RTI-03/07/08",
        fresh,
        plan,
        [disk, again],
        pre_resume_run_id=old,
        post_resume_run_id=result.run_id,
        old_invoke_counts=old_counts,
        fault={"point": "before_receipt", "ordinal": 4, "task_id": "process"},
        old_file_hashes_before=before,
        old_file_hashes_after=after,
        recovery=recovery,
    )


def test_rti04_auto_cold_warm_reuses_every_operation(tmp_path):
    harness = build_harness()
    plan = variant(harness, cache=CachePolicy.AUTO)
    workspace = tmp_path / "workspace"
    cold = canonical_runtime(harness, workspace).run(plan)
    cold_disk = terminal(workspace, cold)
    before = counts(harness, plan)
    assert before == dict.fromkeys(ORDER, 1)
    warm = canonical_runtime(harness, workspace).run(plan)
    warm_disk = terminal(workspace, warm)
    assert counts(harness, plan) == before and warm.outputs == cold.outputs
    assert cold_disk["run"]["scope_id"] != warm_disk["run"]["scope_id"]
    assert all(
        r["disposition"] == "cache_reused" for r in warm_disk["resolutions"].values()
    )
    assert all(not a for a in warm_disk["attempts"].values())
    assert all(
        t.cache_policy is CachePolicy.DISABLED for t in canonical_plan(harness).tasks
    )
    evidence(
        tmp_path,
        "RTI-04/07",
        harness,
        plan,
        [cold_disk, warm_disk],
        semantic_parameter_delta={},
        cold_invoke_counts=before,
    )


def test_rti05_branch_parameter_invalidates_only_descendants(tmp_path):
    harness = build_harness()
    plan = variant(harness, cache=CachePolicy.AUTO, branch=True)
    workspace = tmp_path / "workspace"
    cold = canonical_runtime(harness, workspace).run(plan)
    first = terminal(workspace, cold)
    assert counts(harness, plan) == dict.fromkeys([t.task_id for t in plan.tasks], 1)
    changed = variant(harness, cache=CachePolicy.AUTO, branch=True, changed=True)
    assert [t.task_id for t in plan.tasks if t != changed.task(t.task_id)] == [
        "analyze_b"
    ]
    second = canonical_runtime(harness, workspace).run(changed)
    disk = terminal(workspace, second)
    matrix = {}
    for name, count in counts(harness, changed).items():
        invalidated = name in ("analyze_b", "assess_b")
        assert count == (2 if invalidated else 1)
        assert disk["resolutions"][name]["disposition"] == (
            "executed" if invalidated else "cache_reused"
        )
        assert len(disk["attempts"][name]) == int(invalidated)
        old, new = cold.outputs[name]["out"][0], second.outputs[name]["out"][0]
        if invalidated:
            assert old.semantic_digest != new.semantic_digest
        else:
            assert old == new
        matrix[name] = {
            "invoke_count": count,
            "disposition": disk["resolutions"][name]["disposition"],
            "new_attempts": len(disk["attempts"][name]),
        }
    evidence(
        tmp_path,
        "RTI-05/07",
        harness,
        changed,
        [first, disk],
        semantic_parameter_delta={
            "analyze_b": {
                "label": {"before": "synthetic:b", "after": "synthetic:b:changed"}
            }
        },
        branch_matrix=matrix,
    )


@pytest.mark.parametrize("repetition", range(3))
def test_rti06_real_parallel_overlap_and_coherent_commit(tmp_path, repetition):
    participants = (("analyze", "analyze_a"), ("analyze", "analyze_b"))
    hold = HoldPoint(participants, timeout=20)
    harness = build_harness(controls=Controls(hold=hold))
    plan = variant(harness, branch=True)
    plan = replace(
        plan,
        tasks=tuple(
            replace(t, resources=ResourceRequest(1, 1024, 0)) for t in plan.tasks
        ),
    )
    workspace = tmp_path / "workspace"
    runtime = canonical_runtime(
        harness, workspace, max_workers=2, budget=ResourceAllocation(2, 2048, 0)
    )
    trace = []
    with ThreadPoolExecutor(max_workers=1) as coordinator:
        future = coordinator.submit(runtime.run, plan)
        try:
            assert hold.all_entered.wait(15), (
                "both branches did not enter before bounded deadline"
            )
            trace.append(
                {"event": "both_entered", "participants": [p[1] for p in participants]}
            )
            assert not future.done() and not hold.release.is_set()
            calls = harness.controls.journal.snapshot()
            for _, name in participants:
                assert counts(harness, plan)[name] == 1
                assert counts(harness, plan, "business")[name] == 0
            store = Workspace(workspace)
            run_id = store.read(store.inventory("runs/*/run.json")[0], "run")["run_id"]
            for _, name in participants:
                facts = attempts(store, run_id, name)
                assert len(facts) == 1 and facts[0]["finished"] is None
                assert facts[0]["started"]["allocation"] == {
                    "cpu_cores": 1,
                    "memory_bytes": 1024,
                    "gpu_count": 0,
                }
            assert store.path(
                "runs/" + run_id + "/resolutions/" + key("correct") + ".json"
            ).exists()
            trace.append(
                {
                    "event": "both_started_no_completion",
                    "invoke_sequences": [
                        c.sequence
                        for c in calls
                        if c.stage == "invoke"
                        and c.task_id in {"analyze_a", "analyze_b"}
                    ],
                }
            )
        finally:
            trace.append({"event": "release"})
            hold.release.set()
        result = future.result(timeout=20)
    disk = terminal(workspace, result)
    assert result.status == "SUCCEEDED"
    assert counts(harness, plan) == dict.fromkeys([t.task_id for t in plan.tasks], 1)
    assert set(result.completion_order) == {t.task_id for t in plan.tasks} and len(
        result.completion_order
    ) == len(plan.tasks)
    calls = harness.controls.journal.snapshot()
    enter = [
        c.sequence
        for c in calls
        if c.stage == "invoke" and c.task_id in {"analyze_a", "analyze_b"}
    ]
    completed = [
        c.sequence
        for c in calls
        if c.stage == "business" and c.task_id in {"analyze_a", "analyze_b"}
    ]
    assert max(enter) < min(completed)
    trace.append({"event": "completed", "business_sequences": completed})
    evidence(
        tmp_path,
        "RTI-06/07/08",
        harness,
        plan,
        [disk],
        repetition=repetition,
        max_workers=2,
        resource_budget={"cpu_cores": 2, "memory_bytes": 2048, "gpu_count": 0},
        hold_participants=[list(p) for p in participants],
        event_trace=trace,
    )
