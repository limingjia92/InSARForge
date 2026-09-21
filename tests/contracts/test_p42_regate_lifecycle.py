"""Independent R2 adjacent-boundary checks; production snapshot is unmodified."""

import json
from dataclasses import replace

import pytest
from test_fingerprint_cache import prepared
from test_runtime_execution import fixture, records, run_ids, t

from insarforge.contracts.errors import WorkflowStateError
from insarforge.contracts.execution import RestartSafety, WorkflowPlan


def emit(label, **kwargs):
    print(json.dumps({"probe": label, **kwargs}, sort_keys=True))


def test_replan_refusal_leaves_no_active_run_projection(tmp_path):
    rt, dummy = fixture(tmp_path)
    plan = WorkflowPlan(1, (t(),))
    assert rt.run(plan).status == "SUCCEEDED"
    cached = rt.run(plan)
    old = set(run_ids(rt))
    dummy.identity = prepared(
        settings={"precision": "double", "threads": 1, "seed": 98765}
    )
    with pytest.raises(WorkflowStateError, match="REPLAN"):
        rt.resume(cached.run_id)
    new = sorted(set(run_ids(rt)) - old)
    statuses = {rid: rt.store.status(rid) for rid in new}
    emit(
        "R2_REPLAN",
        new_run_statuses=statuses,
        invokes=dummy.counts,
        writer_locked=rt.store._locked,
    )
    assert not rt.store._locked
    assert all(s != "RUNNING" for s in statuses.values()), (
        "Handled REPLAN refusal left a durable run RUNNING after releasing its writer"
    )


@pytest.mark.parametrize("kind", ["started", "finished"])
def test_unrelated_corrupt_history_does_not_block_first_execution(tmp_path, kind):
    rt, dummy = fixture(tmp_path)
    assert rt.run(WorkflowPlan(1, (t("old"),))).status == "SUCCEEDED"
    location = records(rt, kind)[0][0]
    damaged = b'{"damaged":true}'
    rt.store.path(location).write_bytes(damaged)
    task = replace(t("new-independent"), restart_safety=RestartSafety.UNSAFE)
    error = None
    try:
        result = rt.run(WorkflowPlan(1, (task,)))
        status = result.status
    except Exception as exc:
        error = type(exc).__name__ + ":" + str(exc)
        status = None
    emit(
        "R2_CORRUPT_" + kind.upper(),
        error=error,
        status=status,
        invokes=dummy.counts,
        all_run_states={rid: rt.store.status(rid) for rid in run_ids(rt)},
    )
    assert rt.store.path(location).read_bytes() == damaged, (
        "Do not delete/rewrite bad history"
    )
    assert (
        error is None
        and status == "SUCCEEDED"
        and dummy.counts.get("new-independent") == 1
    ), "Unrelated damaged history poisoned a fresh independent execution scope"


@pytest.mark.parametrize("descending_ids", [False, True])
def test_interrupt_projection_uses_attempt_sequence_not_uuid_order(
    tmp_path, monkeypatch, descending_ids
):
    import itertools
    import uuid

    from insarforge.contracts.errors import RetryableExecutionError
    from insarforge.contracts.execution import OutputRef, RetryPolicy

    # Both UUID orders are legal. Only identity allocation is controlled, not
    # execution outcomes, filesystem reads, validation or receipt publication.
    counter = itertools.count(1)
    monkeypatch.setattr(
        uuid,
        "uuid4",
        lambda: uuid.UUID(
            int=((1 << 128) - next(counter)) if descending_ids else next(counter)
        ),
    )
    rt, dummy = fixture(tmp_path)
    dummy.failures = {
        "a": [RetryableExecutionError("transient")],
        "b": [KeyboardInterrupt()],
    }
    plan = WorkflowPlan(
        1,
        (
            replace(t("a"), retry_policy=RetryPolicy(2, 0)),
            t("b", (OutputRef("a", "out"),)),
        ),
    )
    with pytest.raises(KeyboardInterrupt):
        rt.run(plan)
    rid = run_ids(rt)[0]
    summary = rt.store.read("runs/" + rid + "/summary.json", "summary")
    resolutions = {r["task_id"]: r for _, r in records(rt, "resolution")}
    attempts = sorted(
        [s for _, s in records(rt, "started") if s["task_id"] == "a"],
        key=lambda s: s["sequence"],
    )
    outcomes = {f["attempt_id"]: f["outcome"] for _, f in records(rt, "finished")}
    emit(
        "R2_RETRY_INTERRUPT",
        descending_ids=descending_ids,
        summary=summary,
        a_resolution_state=resolutions["a"]["state"],
        a_attempts=[
            {
                "sequence": s["sequence"],
                "id": s["attempt_id"],
                "outcome": outcomes[s["attempt_id"]],
            }
            for s in attempts
        ],
    )
    assert dummy.counts == {"a": 2, "b": 1}
    assert resolutions["a"]["state"] == "succeeded"
    assert len([r for _, r in records(rt, "receipt") if r["task_id"] == "a"]) == 1
    assert summary["status"] == "INTERRUPTED"
    assert summary["states"]["a"] == "succeeded", (
        "Earlier failed attempt overwrote later committed success only because its random UUID sorts last"
    )


def test_matching_corrupt_started_still_refuses_resume(tmp_path):
    from insarforge.core.exceptions import InSARForgeError
    from insarforge.core.runtime import RuntimeCrash

    rt, dummy = fixture(tmp_path)

    def crash(point):
        if point == "after_started":
            raise RuntimeCrash()

    rt.fault = crash
    with pytest.raises(RuntimeCrash):
        rt.run(WorkflowPlan(1, (t("same-scope"),)))
    rid = run_ids(rt)[0]
    location = records(rt, "started")[0][0]
    rt.store.path(location).write_bytes(b'{"damaged":true}')
    rt.fault = lambda point: None
    with pytest.raises(InSARForgeError):
        rt.resume(rid)
    assert dummy.counts.get("same-scope", 0) == 0
    emit("R2_MATCHING_HISTORY_CONTROL", invoked=0, resume_refused=True)


def run_snapshot(rt, rid):
    root = rt.store.path("runs/" + rid)
    return {p: p.read_bytes() for p in root.rglob("*.json")}


@pytest.mark.parametrize(
    "damage", ["started", "finished", "missing_started", "missing_attempt"]
)
@pytest.mark.parametrize("ended", ["interrupted", "exhausted"])
def test_same_scope_damage_cannot_replenish_budget(tmp_path, damage, ended):
    from insarforge.contracts.errors import RetryableExecutionError
    from insarforge.contracts.execution import CachePolicy, RetryPolicy
    from insarforge.core.exceptions import InSARForgeError
    from insarforge.core.runtime import RuntimeCrash

    rt, dummy = fixture(tmp_path)
    plan = WorkflowPlan(
        1,
        (
            replace(
                t(), retry_policy=RetryPolicy(2, 0), cache_policy=CachePolicy.DISABLED
            ),
        ),
    )
    if ended == "interrupted":

        def crash(point):
            if point == "after_started":
                raise RuntimeCrash()

        rt.fault = crash
        with pytest.raises(RuntimeCrash):
            rt.run(plan)
    else:
        dummy.failures["a"] = [RetryableExecutionError("transient")] * 2
        assert rt.run(plan).status == "FAILED"
    rid = run_ids(rt)[0]
    location, _ = max(records(rt, "started"), key=lambda item: item[1]["sequence"])
    parent = rt.store.path(location).parent
    if damage == "missing_attempt":
        parent.rename(tmp_path / "preserved-lost-attempt")
    elif damage == "missing_started":
        rt.store.path(location).rename(tmp_path / "preserved-lost-started.json")
    else:
        (parent / (damage + ".json")).write_bytes(b'{"damaged":true}')
    old = run_snapshot(rt, rid)
    counts = dict(dummy.counts)
    rt.fault = lambda point: None
    with pytest.raises(InSARForgeError):
        rt.resume(rid)
    assert run_ids(rt) == [rid]
    assert dummy.counts == counts and not rt.store._locked
    assert all(path.read_bytes() == raw for path, raw in old.items())
    independent = replace(t("independent"), restart_safety=RestartSafety.UNSAFE)
    assert rt.run(WorkflowPlan(1, (independent,))).status == "SUCCEEDED"
    assert dummy.counts.get("a", 0) == counts.get("a", 0)
    assert all(path.read_bytes() == raw for path, raw in old.items())


@pytest.mark.parametrize(
    "field,value",
    [
        ("run_id", "f" * 32),
        ("scope_id", "e" * 32),
        ("task_id", "not-in-plan"),
        ("sequence", 8),
    ],
)
def test_attributed_history_requires_path_payload_and_sequence_bindings(
    tmp_path, field, value
):
    from insarforge.core.exceptions import InSARForgeError

    rt, dummy = fixture(tmp_path)
    result = rt.run(WorkflowPlan(1, (t(),)))
    location = records(rt, "started")[0][0]
    wire = json.loads(rt.store.read_bytes(location))
    wire["payload"][field] = value
    rt.store.path(location).write_text(json.dumps(wire))
    damaged = rt.store.read_bytes(location)
    with pytest.raises(InSARForgeError):
        rt.resume(result.run_id)
    assert dummy.counts == {"a": 1}
    assert rt.store.read_bytes(location) == damaged
    assert run_ids(rt) == [result.run_id]


def test_older_source_resume_counts_sibling_attempts(tmp_path):
    from insarforge.contracts.execution import CachePolicy, RetryPolicy
    from insarforge.core.runtime import RuntimeCrash

    rt, dummy = fixture(tmp_path)
    plan = WorkflowPlan(
        1,
        (
            replace(
                t(), retry_policy=RetryPolicy(2, 0), cache_policy=CachePolicy.DISABLED
            ),
        ),
    )

    def crash(point):
        if point == "before_receipt":
            raise RuntimeCrash()

    rt.fault = crash
    with pytest.raises(RuntimeCrash):
        rt.run(plan)
    original = run_ids(rt)[0]
    with pytest.raises(RuntimeCrash):
        rt.resume(original)
    before = {p: p.read_bytes() for p in rt.store.path("runs").rglob("*.json")}
    rt.fault = lambda point: None
    assert rt.resume(original).status == "FAILED"
    assert rt.resume(original).status == "FAILED"
    assert dummy.counts == {"a": 2}
    assert sorted(s["sequence"] for _, s in records(rt, "started")) == [1, 2]
    assert all(p.read_bytes() == raw for p, raw in before.items())


def test_unusable_earlier_candidate_does_not_hide_valid_later_candidate(
    tmp_path, monkeypatch
):
    import itertools
    import uuid

    counter = itertools.count(1)
    monkeypatch.setattr(uuid, "uuid4", lambda: uuid.UUID(int=next(counter)))
    rt, dummy = fixture(tmp_path)
    plan = WorkflowPlan(1, (replace(t(), restart_safety=RestartSafety.UNSAFE),))
    first = rt.run(plan)
    location = records(rt, "started")[0][0]
    rt.store.path(location).write_bytes(b'{"damaged":true}')
    second = rt.run(plan)
    assert second.status == "SUCCEEDED" and dummy.counts == {"a": 2}
    receipts = rt.store.inventory("runs/*/attempts/*/*/result.json")
    assert receipts[0].startswith("runs/" + first.run_id + "/")
    assert receipts[1].startswith("runs/" + second.run_id + "/")
    third = rt.run(plan)
    assert third.status == "SUCCEEDED" and third.outputs == second.outputs
    assert dummy.counts == {"a": 2}
    assert rt.store.path(location).read_bytes() == b'{"damaged":true}'


@pytest.mark.parametrize("cached_source", [False, True])
@pytest.mark.parametrize("worker_fails", [False, True])
def test_replan_with_admitted_worker_closes_and_preserves_cache_success(
    tmp_path, cached_source, worker_fails
):
    import threading

    from test_runtime_execution import Dummy

    from insarforge.contracts.context import ResourceAllocation
    from insarforge.contracts.errors import ContractError, RetryableExecutionError
    from insarforge.provenance.workspace import key

    entered = threading.Event()
    stopped = threading.Event()

    class Selective(Dummy):
        initial = True

        def prepare(self, plugin, inputs, parameters, probe):
            name = parameters["label"]
            if self.initial and name == "b":
                raise ContractError("SYNTHETIC_PREFLIGHT")
            if not self.initial and name == "c":
                assert entered.wait(5)
                return prepared(settings={"seed": 98765})
            return super().prepare(plugin, inputs, parameters, probe)

    dummy = Selective()
    rt, _ = fixture(
        tmp_path, dummy, max_workers=2, budget=ResourceAllocation(2, None, 0)
    )
    if cached_source:
        assert rt.run(WorkflowPlan(1, (t("a"), t("c")))).status == "SUCCEEDED"
    plan = WorkflowPlan(1, (t("a"), t("b"), t("c")))
    original = rt.run(plan)
    assert original.status == "FAILED"
    old = run_snapshot(rt, original.run_id)
    known_runs = set(run_ids(rt))
    dummy.initial = False

    def hook(context, inputs):
        assert context.task_id == "b"
        entered.set()
        for _ in range(500):
            if context.cancellation_requested():
                stopped.set()
                if worker_fails:
                    raise RetryableExecutionError("synthetic transient")
                return
            threading.Event().wait(0.01)
        pytest.fail("cooperative cancellation was not requested")

    dummy.hook = hook
    with pytest.raises(WorkflowStateError, match="RESUME_REPLAN_REQUIRED"):
        rt.resume(original.run_id)
    assert stopped.is_set() and not rt.store._locked
    assert dummy.counts == {"a": 1, "b": 1, "c": 1}
    (new,) = set(run_ids(rt)) - known_runs
    summary = rt.store.read("runs/" + new + "/summary.json", "summary")
    assert summary["status"] == "FAILED"
    assert summary["states"] == {"a": "succeeded", "b": "failed", "c": "failed"}
    assert summary["completion_order"] == ["b"]
    starts = [(loc, s) for loc, s in records(rt, "started") if s["run_id"] == new]
    assert len(starts) == 1 and starts[0][1]["task_id"] == "b"
    end = rt.store.read(
        starts[0][0].replace("started.json", "finished.json"), "finished"
    )
    assert end["outcome"] == ("failed" if worker_fails else "interrupted")
    assert end["retryable"] is worker_fails
    refused = rt.store.read(
        "runs/" + new + "/resolutions/" + key("c") + ".json", "resolution"
    )
    assert refused["cache_reasons"] == ["RESUME_REPLAN_REQUIRED"]
    assert all(path.read_bytes() == raw for path, raw in old.items())
    with rt.store.writer():
        assert rt.store.status(new) == "FAILED"


@pytest.mark.parametrize("descending", [False, True])
@pytest.mark.parametrize(
    "window", ["other_interrupt", "before_receipt", "after_receipt", "after_finished"]
)
def test_multiple_failures_then_terminal_window_preserves_sequence_and_completion(
    tmp_path, monkeypatch, descending, window
):
    import itertools
    import uuid

    from insarforge.contracts.errors import RetryableExecutionError
    from insarforge.contracts.execution import OutputRef, RetryPolicy

    counter = itertools.count(1)
    monkeypatch.setattr(
        uuid,
        "uuid4",
        lambda: uuid.UUID(
            int=(1 << 128) - next(counter) if descending else next(counter)
        ),
    )
    rt, dummy = fixture(tmp_path)
    dummy.failures = {
        "a": [RetryableExecutionError("transient")] * 2,
        "b": [KeyboardInterrupt()],
    }
    plan = WorkflowPlan(
        1,
        (
            replace(t("a"), retry_policy=RetryPolicy(3, 0)),
            t("b", (OutputRef("a", "out"),)),
        ),
    )
    if window in ("before_receipt", "after_receipt"):

        def fault(point):
            if point == window:
                raise KeyboardInterrupt()

        rt.fault = fault
    if window == "after_finished":
        write = rt.store.write

        def interrupted(relative, kind, payload):
            result = write(relative, kind, payload)
            if kind == "finished" and payload["outcome"] == "succeeded":
                raise KeyboardInterrupt()
            return result

        monkeypatch.setattr(rt.store, "write", interrupted)
    with pytest.raises(KeyboardInterrupt):
        rt.run(plan)
    rid = run_ids(rt)[0]
    summary = rt.store.read("runs/" + rid + "/summary.json", "summary")
    expected = "failed" if window == "before_receipt" else "succeeded"
    assert summary["status"] == "INTERRUPTED" and summary["states"]["a"] == expected
    assert summary["completion_order"] == ["a", "a", "a"] + (
        ["b"] if window == "other_interrupt" else []
    )
    attempts = sorted(
        [s for _, s in records(rt, "started") if s["task_id"] == "a"],
        key=lambda s: s["sequence"],
    )
    ends = {f["attempt_id"]: f for _, f in records(rt, "finished")}
    assert [s["sequence"] for s in attempts] == [1, 2, 3]
    assert [ends[s["attempt_id"]]["outcome"] for s in attempts] == [
        "failed",
        "failed",
        "interrupted" if window == "before_receipt" else "succeeded",
    ]
    assert all(ends[s["attempt_id"]]["retryable"] for s in attempts[:2])
    assert dummy.counts["a"] == 3
    assert len([f for _, f in records(rt, "receipt") if f["task_id"] == "a"]) == (
        0 if window == "before_receipt" else 1
    )


def test_cache_only_success_survives_other_task_interrupt(tmp_path):
    from insarforge.contracts.execution import OutputRef

    rt, dummy = fixture(tmp_path)
    producer = rt.run(WorkflowPlan(1, (t("a"),)))
    old = run_snapshot(rt, producer.run_id)
    dummy.failures["b"] = [KeyboardInterrupt()]
    before = set(run_ids(rt))
    with pytest.raises(KeyboardInterrupt):
        rt.run(WorkflowPlan(1, (t("a"), t("b", (OutputRef("a", "out"),)))))
    (rid,) = set(run_ids(rt)) - before
    summary = rt.store.read("runs/" + rid + "/summary.json", "summary")
    assert summary["states"] == {"a": "succeeded", "b": "failed"}
    assert summary["completion_order"] == ["b"]
    assert [s["task_id"] for _, s in records(rt, "started") if s["run_id"] == rid] == [
        "b"
    ]
    assert dummy.counts == {"a": 1, "b": 1}
    assert all(path.read_bytes() == raw for path, raw in old.items())


def test_replan_preserves_success_already_committed_in_new_run(tmp_path):
    from test_runtime_execution import Dummy

    from insarforge.contracts.errors import ContractError

    class Selective(Dummy):
        initial = True

        def prepare(self, plugin, inputs, parameters, probe):
            name = parameters["label"]
            if self.initial and name == "a":
                raise ContractError("SYNTHETIC_PREFLIGHT")
            if not self.initial and name == "b":
                return prepared(settings={"seed": 999})
            return super().prepare(plugin, inputs, parameters, probe)

    dummy = Selective()
    rt, _ = fixture(tmp_path, dummy)
    source = rt.run(WorkflowPlan(1, (t("a"), t("b"))))
    assert source.status == "FAILED"
    old = run_snapshot(rt, source.run_id)
    dummy.initial = False
    with pytest.raises(WorkflowStateError, match="REPLAN"):
        rt.resume(source.run_id)
    (rid,) = set(run_ids(rt)) - {source.run_id}
    summary = rt.store.read("runs/" + rid + "/summary.json", "summary")
    assert summary["status"] == "FAILED"
    assert summary["states"] == {"a": "succeeded", "b": "failed"}
    assert summary["completion_order"] == ["a"]
    assert dummy.counts == {"a": 1, "b": 1}
    assert len([f for _, f in records(rt, "receipt") if f["task_id"] == "a"]) == 1
    assert all(path.read_bytes() == raw for path, raw in old.items())
    with rt.store.writer():
        assert rt.store.status(rid) == "FAILED"
