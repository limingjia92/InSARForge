"""Single coordinator with one execution path for serial and bounded threads."""

import logging
import queue
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from pathlib import Path

import insarforge
from insarforge.contracts._execution_json import canonical, decode, plain
from insarforge.contracts.context import ExecutionContext
from insarforge.contracts.errors import (
    ContractError,
    OutputValidationError,
    RetryableExecutionError,
    WorkflowStateError,
)
from insarforge.contracts.execution import (
    CachePolicy,
    CompletionDisposition,
    RestartSafety,
    TaskState,
    WorkflowPlan,
    _artifact_dict,
)
from insarforge.contracts.record_serialization import record_from_bytes
from insarforge.core._runtime_artifacts import (
    candidate_from_receipt,
    finalize,
    output_data,
    resolve_inputs,
    sha,
)
from insarforge.core._runtime_inputs import local_evidence, shared_assets
from insarforge.core.cache import can_publish_cache, validate_cache_candidate
from insarforge.core.content_identity import code_content_identity, engine_code_identity
from insarforge.core.fingerprints import (
    execution_identity,
    input_identities,
    task_fingerprint,
)
from insarforge.core.runtime_plan import RunResult, allocation, dry_run, validate_task
from insarforge.provenance.runtime_evidence import ArtifactEvidence, PreparationEvidence
from insarforge.provenance.workspace import Workspace, key


class RuntimeCrash(BaseException):
    """Internal fault-injection boundary, equivalent to lost coordinator progress."""


@dataclass(frozen=True)
class _Probe:
    allocated_resources: object


def _identity(result):
    return {
        "value": result.value,
        "reusable": result.reusable,
        "reasons": list(result.reasons),
    }


def _allocation(value):
    return {
        "cpu_cores": value.cpu_cores,
        "gpu_count": value.gpu_count,
        "memory_bytes": value.memory_bytes,
    }


def _error(exc):
    if isinstance(exc, RetryableExecutionError):
        return "EXECUTION_RETRYABLE", True
    if isinstance(exc, OutputValidationError):
        return "OUTPUT_INVALID", False
    if isinstance(exc, ContractError):
        return "CONTRACT_INVALID", False
    return "EXECUTION_FAILED", False


class Runtime:
    """Composition supplies sealed registry and explicit implementation content scopes.

    This cooperative in-process runtime does not sandbox plugin Python code.
    Only the coordinator receives the store; workers receive isolated contexts.
    """

    def __init__(
        self,
        registry,
        workspace,
        *,
        budget,
        implementation_files,
        max_workers=1,
        source_revision=None,
        core_semantics_revision="runtime:v1",
        _clock=time.time,
        _sleep=time.sleep,
        _fault=None,
    ):
        if type(max_workers) is not int or max_workers < 1:
            raise ContractError("WORKER_LIMIT")
        if source_revision is not None and (
            type(source_revision) is not str
            or len(source_revision) != 40
            or any(c not in "0123456789abcdef" for c in source_revision)
        ):
            raise ContractError("SOURCE_REVISION")
        self.source_revision = source_revision
        self.registry = registry
        self.store = Workspace(workspace)
        self.budget = budget
        self.implementation_files = {
            ref: dict(files) for ref, files in implementation_files.items()
        }
        self.max_workers = max_workers
        self.revision = core_semantics_revision
        self.clock = _clock
        self.sleep = _sleep
        self.fault = _fault or (lambda point: None)

    def dry_run(self, plan):
        return dry_run(plan, self.registry, budget=self.budget)

    def run(
        self, plan, *, external_manifests=None, external_evidence=None, config_refs=()
    ):
        with self.store.writer():
            self._current_run = None
            try:
                return self._run(
                    plan,
                    dict(external_manifests or {}),
                    None,
                    config_refs,
                    dict(external_evidence or {}),
                )
            except KeyboardInterrupt:
                self._close_terminal("INTERRUPTED")
                raise
            except Exception as exc:
                reason = (
                    "RESUME_REPLAN_REQUIRED"
                    if isinstance(exc, WorkflowStateError)
                    and str(exc) == "RESUME_REPLAN_REQUIRED"
                    else "RUN_CONTROL_EXIT"
                )
                self._close_terminal("FAILED", reason)
                raise

    def resume(self, source_run):
        if (
            type(source_run) is not str
            or len(source_run) != 32
            or any(c not in "0123456789abcdef" for c in source_run)
        ):
            raise WorkflowStateError("RESUME_RUN_ID")
        with self.store.writer():
            prefix = "runs/" + source_run
            original = self.store.read(prefix + "/run.json", "run")
            if original["run_id"] != source_run:
                raise WorkflowStateError("RESUME_RUN_BINDING")
            plan = WorkflowPlan.from_json(self.store.read_bytes(prefix + "/plan.json"))
            if plan.digest != original["plan_digest"]:
                raise WorkflowStateError("RESUME_PLAN_CHANGED")
            external = {
                ref.record_id: self.store.read_bytes(
                    prefix + "/external/" + key(ref.record_id) + ".json"
                )
                for ref in plan.external_inputs
            }
            proofs = decode(self.store.read_bytes(prefix + "/external-evidence.json"))
            proofs = {k: ArtifactEvidence.from_dict(v) for k, v in proofs.items()}
            self._current_run = None
            try:
                return self._run(plan, external, original, (), proofs)
            except KeyboardInterrupt:
                self._close_terminal("INTERRUPTED")
                raise
            except Exception as exc:
                reason = (
                    "RESUME_REPLAN_REQUIRED"
                    if isinstance(exc, WorkflowStateError)
                    and str(exc) == "RESUME_REPLAN_REQUIRED"
                    else "RUN_CONTROL_EXIT"
                )
                self._close_terminal("FAILED", reason)
                raise

    def _run_history(self, run, plan):
        """Read attributable attempts, including directories missing started facts."""
        prefix = "runs/" + run["run_id"]
        histories = {}
        for path in self.store.path(prefix + "/attempts").glob("*/*"):
            parent = path.relative_to(self.store.area).as_posix()
            self.store.path(parent)  # Reject directory links before reading facts.
            started = self.store.read(parent + "/started.json", "started")
            if (
                started["run_id"] != run["run_id"]
                or started["scope_id"] != run["scope_id"]
                or started["plan_digest"] != plan.digest
                or started["task_id"] not in {t.task_id for t in plan.tasks}
                or parent
                != prefix
                + "/attempts/"
                + key(started["task_id"])
                + "/"
                + started["attempt_id"]
            ):
                raise WorkflowStateError("ATTEMPT_HISTORY_BINDING")
            finished = None
            if self.store.path(parent + "/finished.json").exists():
                finished = self.store.read(parent + "/finished.json", "finished")
                if finished["attempt_id"] != started["attempt_id"] or (
                    finished["outcome"] == "succeeded"
                    and finished["receipt"] != parent + "/result.json"
                ):
                    raise WorkflowStateError("ATTEMPT_HISTORY_INVALID")
            histories.setdefault(started["task_id"], []).append(
                (parent, started, finished)
            )
        # RUNNING transitions witness admitted attempts even if their whole
        # directory was lost; missing history must not replenish a retry budget.
        admissions = {}
        for location in self.store.inventory(prefix + "/transitions/*.json"):
            fact = self.store.read(location, "transition")
            if fact["task_id"] not in {t.task_id for t in plan.tasks}:
                raise WorkflowStateError("ATTEMPT_HISTORY_BINDING")
            if fact["state"] == "running":
                admissions[fact["task_id"]] = admissions.get(fact["task_id"], 0) + 1
        if any(
            count > len(histories.get(name, [])) for name, count in admissions.items()
        ):
            raise WorkflowStateError("ATTEMPT_HISTORY_MISSING")
        return histories

    def _history(self, source, plan):
        # Fresh scopes have no retry history. For resume, run-level associations
        # select the scope BEFORE any attempt payload is parsed. Include sibling
        # resumes too: returning to an older source cannot replenish the budget.
        histories = {}
        if source is None:
            return histories
        for location in self.store.inventory("runs/*/run.json"):
            run = self.store.read(location, "run")
            if run["scope_id"] != source["scope_id"]:
                continue
            if (
                location != "runs/" + run["run_id"] + "/run.json"
                or run["plan_digest"] != plan.digest
            ):
                raise WorkflowStateError("SCOPE_HISTORY_BINDING")
            for name, members in self._run_history(run, plan).items():
                histories.setdefault(name, []).extend(members)
        for members in histories.values():
            members.sort(key=lambda x: x[1]["sequence"])
            if [m[1]["sequence"] for m in members] != list(range(1, len(members) + 1)):
                raise WorkflowStateError("ATTEMPT_SEQUENCE_INVALID")
        return histories

    def _recover(self, source):
        prefix = "runs/" + source["run_id"]
        if (
            self.store.path(prefix + "/summary.json").exists()
            or self.store.path(prefix + "/recovery.json").exists()
        ):
            return
        attempts = []
        for location in self.store.inventory(prefix + "/attempts/*/*/started.json"):
            parent = location.rsplit("/", 1)[0]
            started = self.store.read(location, "started")
            if self.store.path(parent + "/finished.json").exists():
                continue
            valid = False
            if self.store.path(parent + "/result.json").exists():
                try:
                    candidate_from_receipt(
                        self.store, parent + "/result.json", commit_only=True
                    )
                    valid = True
                except Exception:
                    pass
            attempts.append(
                dict(
                    attempt_id=started["attempt_id"],
                    outcome="succeeded" if valid else "interrupted",
                    receipt=parent + "/result.json" if valid else None,
                )
            )
        self.store.write(
            prefix + "/recovery.json",
            "recovery",
            dict(source_run=source["run_id"], status="INTERRUPTED", attempts=attempts),
        )

    def _close_terminal(self, status, reason="INTERRUPTED"):
        # The pool has already cancelled admission and awaited owned workers.
        # Keep the writer through receipt reconciliation and terminal publication.
        if self._current_run is None:
            return
        run_id, plan = self._current_run
        prefix = "runs/" + run_id
        run = self.store.read(prefix + "/run.json", "run")
        states = {t.task_id: "failed" for t in plan.tasks}
        pending_errors = {}
        committed = {}
        if self._pending_completions is not None:
            while True:
                try:
                    name, _, error = self._pending_completions.get_nowait()
                except queue.Empty:
                    break
                self._completion_order.append(name)
                pending_errors[name] = error
        histories = self._run_history(run, plan)
        for name, members in histories.items():
            members.sort(key=lambda item: item[1]["sequence"])
            if len({s["sequence"] for _, s, _ in members}) != len(members):
                raise WorkflowStateError("ATTEMPT_SEQUENCE_INVALID")
            for parent, start, finished in members:
                receipt = None
                if self.store.path(parent + "/result.json").exists():
                    try:
                        candidate_from_receipt(
                            self.store, parent + "/result.json", commit_only=True
                        )
                        receipt = parent + "/result.json"
                    except Exception:
                        # Invalid output is not committed success; retain bytes.
                        pass
                if finished is None:
                    error = pending_errors.get(name)
                    code, retryable = (
                        _error(error)
                        if isinstance(error, Exception)
                        else ("INTERRUPTED", False)
                    )
                    finished = dict(
                        attempt_id=start["attempt_id"],
                        outcome="succeeded"
                        if receipt
                        else (
                            "failed" if isinstance(error, Exception) else "interrupted"
                        ),
                        error_code=None if receipt else code,
                        retryable=False if receipt else retryable,
                        ended_at=self.clock(),
                        receipt=receipt,
                        evidence=[],
                    )
                    self.store.write(parent + "/finished.json", "finished", finished)
                if finished["outcome"] == "succeeded" and receipt is None:
                    raise WorkflowStateError("TERMINAL_RECEIPT_INVALID")
                states[name] = (
                    "succeeded" if finished["outcome"] == "succeeded" else "failed"
                )
                committed[name] = receipt if states[name] == "succeeded" else None
        # Resolutions also own cache-only successes, with no fabricated attempt.
        for location in self.store.inventory(prefix + "/resolutions/*.json"):
            fact = self.store.read(location, "resolution")
            name = fact["task_id"]
            if (
                name not in states
                or location != prefix + "/resolutions/" + key(name) + ".json"
            ):
                raise WorkflowStateError("TERMINAL_RESOLUTION_BINDING")
            if fact["state"] == "succeeded":
                receipt = candidate_from_receipt(
                    self.store, fact["receipt"], commit_only=True
                )
                if (
                    (receipt["fingerprint"], receipt["execution"])
                    != (fact["fingerprint"], fact["execution"])
                    or fact["disposition"] not in ("executed", "cache_reused")
                    or (
                        fact["disposition"] == "executed"
                        and (
                            not fact["receipt"].startswith(
                                prefix + "/attempts/" + key(name) + "/"
                            )
                            or receipt["task_id"] != name
                        )
                    )
                ):
                    raise WorkflowStateError("TERMINAL_RESOLUTION_BINDING")
            states[name] = fact["state"]
        for name, state in states.items():
            location = prefix + "/resolutions/" + key(name) + ".json"
            if self.store.path(location).exists():
                continue
            receipt = committed.get(name)
            fact = self.store.read(receipt, "receipt") if receipt else None
            self.store.write(
                location,
                "resolution",
                dict(
                    task_id=name,
                    state=state,
                    disposition="executed" if receipt else None,
                    receipt=receipt,
                    error_code=None
                    if receipt
                    else (
                        "INTERRUPTED" if status == "INTERRUPTED" else "PREFLIGHT_FAILED"
                    ),
                    blocked_by=[],
                    fingerprint=fact["fingerprint"] if fact else None,
                    execution=fact["execution"] if fact else None,
                    cache_reasons=[] if receipt else [reason],
                ),
            )
        if not self.store.path(prefix + "/summary.json").exists():
            self.store.write(
                prefix + "/summary.json",
                "summary",
                dict(
                    run_id=run_id,
                    status=status,
                    states=states,
                    completion_order=list(self._completion_order),
                ),
            )

    def _adopted(self, source, plan):
        adopted = {}
        seen = set()
        while source:
            if source["run_id"] in seen or source["plan_digest"] != plan.digest:
                raise WorkflowStateError("RESUME_SOURCE_INVALID")
            seen.add(source["run_id"])
            for task in plan.tasks:
                location = (
                    "runs/"
                    + source["run_id"]
                    + "/resolutions/"
                    + key(task.task_id)
                    + ".json"
                )
                if not self.store.path(location).exists():
                    continue
                resolution = self.store.read(location, "resolution")
                if resolution["task_id"] != task.task_id:
                    raise WorkflowStateError("RESUME_RESOLUTION_BINDING")
                if resolution["state"] != "succeeded" or task.task_id in adopted:
                    continue
                receipt = self.store.read(resolution["receipt"], "receipt")
                started = self.store.read(
                    resolution["receipt"].rsplit("/", 1)[0] + "/started.json", "started"
                )
                parts = resolution["receipt"].split("/")
                if (
                    len(parts) != 6
                    or parts[0] != "runs"
                    or parts[2] != "attempts"
                    or parts[5] != "result.json"
                    or started["run_id"] != parts[1]
                    or key(started["task_id"]) != parts[3]
                    or started["attempt_id"] != parts[4]
                    or resolution["disposition"] not in ("executed", "cache_reused")
                    or (
                        resolution["disposition"] == "executed"
                        and (
                            started["run_id"] != source["run_id"]
                            or started["scope_id"] != source["scope_id"]
                            or started["task_id"] != task.task_id
                        )
                    )
                ):
                    raise WorkflowStateError("RESUME_RESOLUTION_BINDING")
                if any(
                    receipt[k] != started[k]
                    for k in (
                        "fingerprint",
                        "execution",
                        "scope_id",
                        "task_id",
                        "attempt_id",
                        "inputs",
                    )
                ):
                    raise WorkflowStateError("RESUME_RECEIPT_BINDING")
                if (receipt["fingerprint"], receipt["execution"]) != (
                    resolution["fingerprint"],
                    resolution["execution"],
                ):
                    raise WorkflowStateError("RESUME_ADOPTED_IDENTITY")
                adopted[task.task_id] = (receipt["fingerprint"], receipt["execution"])
            parent = source["resume_of"]
            if parent is None:
                break
            previous = self.store.read("runs/" + parent + "/run.json", "run")
            if (
                previous["run_id"] != parent
                or previous["scope_id"] != source["scope_id"]
            ):
                raise WorkflowStateError("RESUME_SOURCE_INVALID")
            source = previous
        return adopted

    def _run(self, plan, external, source, config_refs, external_evidence):
        if type(plan) is not WorkflowPlan or not self.registry.is_sealed:
            raise ContractError("RUNTIME_PLAN_OR_REGISTRY")
        # Whole-plan structural validation already belongs to WorkflowPlan.
        # Static per-task errors become FAILED without preventing independent work.
        if set(external) != {r.record_id for r in plan.external_inputs}:
            raise ContractError("EXTERNAL_INPUT_SET")
        if not set(external_evidence).issubset(external):
            raise ContractError("EXTERNAL_EVIDENCE_SET")
        for ref in plan.external_inputs:
            if sha(external[ref.record_id]) != ref.manifest_digest:
                raise ContractError("EXTERNAL_INPUT_HASH")
            # Strict safety boundary precedes ALL durable copies.
            record_from_bytes(ref, external[ref.record_id])
            if ref.record_id in external_evidence:
                proof = external_evidence[ref.record_id]
                if type(proof) is not ArtifactEvidence or proof.artifact != ref:
                    raise ContractError("EXTERNAL_EVIDENCE_BINDING")
            else:
                proof = local_evidence(self.store, ref)
                if proof is not None:
                    external_evidence[ref.record_id] = proof
        engine = engine_code_identity(Path(insarforge.__file__).parent)
        implementations = {
            t.task_id: code_content_identity(
                self.implementation_files.get(t.plugin_ref, {})
            )
            for t in plan.tasks
        }
        identities = {name: _identity(value) for name, value in implementations.items()}
        if source:
            if (
                source["engine_identity"] != _identity(engine)
                or source["implementations"] != identities
                or not engine.reusable
                or any(not i.reusable for i in implementations.values())
            ):
                raise WorkflowStateError("RESUME_REPLAN_REQUIRED")
        history = self._history(source, plan)
        if source:
            self._recover(source)
        adopted = self._adopted(source, plan) if source else {}
        run_id = uuid.uuid4().hex
        scope = source["scope_id"] if source else uuid.uuid4().hex
        prefix = "runs/" + run_id
        self.store.write_bytes(prefix + "/plan.json", plan.to_json())
        self.store.write_bytes(
            prefix + "/external-evidence.json",
            canonical({k: v.to_dict() for k, v in external_evidence.items()}),
        )
        for ref in plan.external_inputs:
            self.store.write_bytes(
                prefix + "/external/" + key(ref.record_id) + ".json",
                external[ref.record_id],
            )
        self.store.write(
            prefix + "/run.json",
            "run",
            dict(
                run_id=run_id,
                scope_id=scope,
                resume_of=None if source is None else source["run_id"],
                plan_digest=plan.digest,
                engine_identity=_identity(engine),
                implementations=identities,
                source_kind="programmatic",
                code_provenance=dict(
                    package_version=insarforge.__version__,
                    source_revision=self.source_revision,
                ),
                config_refs=(
                    [_artifact_dict(r) for r in config_refs]
                    if source is None
                    else source["config_refs"]
                ),
            ),
        )
        self._current_run = (run_id, plan)
        self._completion_order = []
        self._pending_completions = None
        states = {t.task_id: TaskState.PENDING for t in plan.tasks}
        produced = {}
        completion = self._completion_order
        active = {}
        ready_at = {}
        events = 0
        decisions = {}
        current_identities = {}
        if source:
            for name, members in history.items():
                last = members[-1][2]
                if last and last["outcome"] == "failed" and last["retryable"]:
                    ready_at[name] = (
                        last["ended_at"] + plan.task(name).retry_policy.backoff_seconds
                    )
        cancelled = threading.Event()
        ended = queue.Queue()
        self._pending_completions = ended

        def transition(name, state):
            nonlocal events
            states[name] = state
            self.store.write(
                prefix + f"/transitions/{events:08}.json",
                "transition",
                dict(task_id=name, state=state.value),
            )
            events += 1

        def resolution(
            name, state, disposition=None, receipt=None, error=None, blocked=()
        ):
            transition(name, state)
            self.store.write(
                prefix + "/resolutions/" + key(name) + ".json",
                "resolution",
                dict(
                    task_id=name,
                    state=state.value,
                    disposition=None if disposition is None else disposition.value,
                    receipt=receipt,
                    error_code=error,
                    blocked_by=list(blocked),
                    fingerprint=current_identities.get(name, (None, None))[0],
                    execution=current_identities.get(name, (None, None))[1],
                    cache_reasons=decisions.get(name, []),
                ),
            )

        def work(name, handler, plugin, prepared, inputs, parameters, context):
            try:
                outcome = handler.invoke(plugin, prepared, inputs, parameters, context)
                ended.put((name, outcome, None))
            except BaseException as exc:
                ended.put((name, None, exc))

        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            try:
                while any(
                    s in (TaskState.PENDING, TaskState.RUNNING) for s in states.values()
                ):
                    made_progress = False
                    for name in sorted(states):
                        if states[name] is not TaskState.PENDING:
                            continue
                        task = plan.task(name)
                        deps = plan.dependencies(name)
                        blocked = [
                            d
                            for d in deps
                            if states[d] in (TaskState.FAILED, TaskState.BLOCKED)
                        ]
                        if blocked:
                            resolution(
                                name,
                                TaskState.BLOCKED,
                                error="UPSTREAM_FAILED",
                                blocked=blocked,
                            )
                            made_progress = True
                            continue
                        if any(states[d] is not TaskState.SUCCEEDED for d in deps):
                            continue
                        if (
                            ready_at.get(name, 0) > self.clock()
                            or len(active) >= self.max_workers
                        ):
                            continue
                        try:
                            bound = validate_task(task, self.registry, self.budget)
                            alloc = allocation(task.resources, self.budget)
                            used = [v["allocation"] for v in active.values()]
                            if (
                                sum(a.cpu_cores for a in used) + alloc.cpu_cores
                                > self.budget.cpu_cores
                                or sum(a.gpu_count for a in used) + alloc.gpu_count
                                > self.budget.gpu_count
                                or (
                                    self.budget.memory_bytes is not None
                                    and sum(a.memory_bytes or 0 for a in used)
                                    + (alloc.memory_bytes or 0)
                                    > self.budget.memory_bytes
                                )
                            ):
                                continue
                            inputs, refs, resolved_entries = resolve_inputs(
                                self.store,
                                task,
                                bound,
                                produced,
                                external,
                                prefix,
                                external_evidence,
                            )
                            original_refs = {
                                p: tuple(v.artifact for v in values)
                                for p, values in inputs.items()
                            }
                            allowed_shared = shared_assets(self.store, resolved_entries)
                            registration = self.registry.resolve(task.plugin_ref)
                            plugin = registration.factory()
                            prepared = bound.handler.prepare(
                                plugin, inputs, task.semantic_parameters, _Probe(alloc)
                            )
                            prepared = PreparationEvidence(
                                prepared.semantic_execution_identity,
                                prepared.preparation,
                            )
                            execution = execution_identity(prepared, alloc)
                            recipe = task_fingerprint(
                                task,
                                bound,
                                core_semantics_revision=self.revision,
                                engine_identity=engine,
                                implementation_identity=implementations[name],
                                prepared=prepared,
                                allocation=alloc,
                                resolved_inputs=refs,
                            )
                            current_identities[name] = (recipe.value, execution.value)
                            decisions[name] = list(recipe.reasons)
                            if task.cache_policy is CachePolicy.DISABLED:
                                decisions[name].append("CACHE_DISABLED")
                            old = history.get(name, [])
                            if source and (
                                not recipe.reusable
                                or not execution.reusable
                                or (
                                    name in adopted
                                    and adopted[name] != (recipe.value, execution.value)
                                )
                                or any(
                                    (r[1]["fingerprint"], r[1]["execution"])
                                    != (recipe.value, execution.value)
                                    for r in old
                                )
                            ):
                                raise WorkflowStateError("RESUME_REPLAN_REQUIRED")
                            candidates = []
                            if source:
                                candidates.extend(
                                    p + "/result.json"
                                    for p, _, _ in reversed(old)
                                    if self.store.path(p + "/result.json").exists()
                                )
                            if can_publish_cache(task.cache_policy, recipe):
                                candidates.extend(
                                    self.store.inventory(
                                        "runs/*/attempts/*/*/result.json"
                                    )
                                )
                            accepted = None
                            damaged = False
                            for location in dict.fromkeys(candidates):
                                associated = False
                                try:
                                    start_fact = self.store.read(
                                        location.rsplit("/", 1)[0] + "/started.json",
                                        "started",
                                    )
                                    associated = (
                                        start_fact["fingerprint"] == recipe.value
                                    )
                                    receipt = self.store.read(location, "receipt")
                                    if receipt["fingerprint"] != recipe.value:
                                        continue
                                    # DISABLED results are never reusable across fresh scopes.
                                    recovering = (
                                        source is not None
                                        and receipt["scope_id"] == scope
                                        and receipt["task_id"] == name
                                    )
                                    if (
                                        receipt["cache_policy"] != "auto"
                                        and not recovering
                                    ):
                                        continue
                                    candidate = candidate_from_receipt(
                                        self.store, location
                                    )
                                    decision = validate_cache_candidate(
                                        replace(task, cache_policy=CachePolicy.AUTO)
                                        if recovering
                                        else task,
                                        bound,
                                        recipe,
                                        execution,
                                        refs,
                                        candidate,
                                        decode_record=record_from_bytes,
                                    )
                                    if decision.accepted:
                                        accepted = (location, candidate)
                                        break
                                    damaged = damaged or associated
                                    decisions[name].extend(decision.reasons)
                                except Exception:
                                    damaged = damaged or associated
                                    decisions[name].append("CACHE_CANDIDATE_UNUSABLE")
                            if accepted:
                                location, candidate = accepted
                                produced[name] = {
                                    p: tuple(o.artifact for o in outputs)
                                    for p, outputs in candidate.outputs.items()
                                }
                                resolution(
                                    name,
                                    TaskState.SUCCEEDED,
                                    CompletionDisposition.CACHE_REUSED,
                                    location,
                                )
                                made_progress = True
                                continue
                            decisions[name].append("CACHE_MISS")
                            if old:
                                last = old[-1][2]
                                if (
                                    task.restart_safety is not RestartSafety.RESTARTABLE
                                    or len(old) >= task.retry_policy.max_attempts
                                    or (
                                        last is not None
                                        and last["outcome"] == "failed"
                                        and not last["retryable"]
                                    )
                                ):
                                    raise WorkflowStateError("RESUME_RESTART_FORBIDDEN")
                            elif (
                                damaged
                                and task.restart_safety is not RestartSafety.RESTARTABLE
                            ):
                                raise WorkflowStateError("DAMAGED_CACHE_UNSAFE")
                            attempt_id = uuid.uuid4().hex
                            attempt = (
                                prefix + "/attempts/" + key(name) + "/" + attempt_id
                            )
                            artifact_dir = self.store.path(attempt + "/artifacts")
                            scratch_dir = self.store.path(attempt + "/scratch")
                            artifact_dir.mkdir(parents=True)
                            scratch_dir.mkdir()
                            logger = logging.Logger("insarforge.attempt." + attempt_id)
                            logger.addHandler(logging.NullHandler())
                            logger.propagate = False
                            context = ExecutionContext(
                                run_id,
                                name,
                                attempt_id,
                                self.store.path(attempt),
                                artifact_dir,
                                scratch_dir,
                                alloc,
                                logger,
                                cancelled.is_set,
                            )
                            started = dict(
                                run_id=run_id,
                                scope_id=scope,
                                task_id=name,
                                attempt_id=attempt_id,
                                sequence=len(old) + 1,
                                plan_digest=plan.digest,
                                fingerprint=recipe.value,
                                execution=execution.value,
                                inputs=plain(input_identities(refs))
                                if input_identities(refs) is not None
                                else None,
                                allocation=_allocation(alloc),
                                prepared=prepared.to_dict(),
                                resolved_inputs=resolved_entries,
                                started_at=self.clock(),
                            )
                            self.store.write(
                                attempt + "/started.json", "started", started
                            )
                            history.setdefault(name, []).append(
                                (attempt, started, None)
                            )
                            transition(name, TaskState.RUNNING)
                            active[name] = dict(
                                allocation=alloc,
                                attempt=attempt,
                                context=context,
                                recipe=recipe,
                                execution=execution,
                                inputs=inputs,
                                refs=refs,
                                original_refs=original_refs,
                                shared=allowed_shared,
                                binding=bound,
                                registration=registration,
                            )
                            self.fault("after_started")
                            pool.submit(
                                work,
                                name,
                                bound.handler,
                                plugin,
                                prepared,
                                inputs,
                                task.semantic_parameters,
                                context,
                            )
                            made_progress = True
                        except WorkflowStateError as exc:
                            # Replan is an explicit whole-resume refusal, not a hidden new scope.
                            if str(exc) == "RESUME_REPLAN_REQUIRED":
                                raise
                            resolution(
                                name, TaskState.FAILED, error="RESTART_FORBIDDEN"
                            )
                            made_progress = True
                        except Exception:
                            decisions.setdefault(name, []).append(
                                "PREFLIGHT_VALIDATION_FAILED"
                            )
                            resolution(name, TaskState.FAILED, error="PREFLIGHT_FAILED")
                            made_progress = True
                    if active:
                        name, outcome, error = ended.get()
                        data = active.pop(name)
                        task = plan.task(name)
                        attempt = data["attempt"]
                        completion.append(name)
                        if isinstance(error, BaseException) and not isinstance(
                            error, Exception
                        ):
                            raise error
                        outputs = None
                        native = []
                        receipt_location = None
                        if error is None:
                            try:
                                # Re-observe inputs after invoke to detect cooperative ownership violations.
                                resolve_inputs(
                                    self.store,
                                    task,
                                    data["binding"],
                                    produced,
                                    external,
                                    prefix,
                                    external_evidence,
                                )
                                outputs, native = finalize(
                                    self.store,
                                    attempt,
                                    task,
                                    data["binding"],
                                    data["registration"],
                                    outcome,
                                    data["recipe"],
                                    data["execution"],
                                    implementations[name],
                                    data["original_refs"],
                                    data["context"],
                                    data["shared"],
                                )
                                self.fault("before_receipt")
                                receipt_location = attempt + "/result.json"
                                self.store.write(
                                    receipt_location,
                                    "receipt",
                                    dict(
                                        attempt_id=data["context"].attempt_id,
                                        task_id=name,
                                        scope_id=scope,
                                        fingerprint=data["recipe"].value,
                                        execution=data["execution"].value,
                                        inputs=plain(input_identities(data["refs"]))
                                        if input_identities(data["refs"]) is not None
                                        else None,
                                        outputs=output_data(outputs),
                                        cache_policy=task.cache_policy.value,
                                    ),
                                )
                                self.fault("after_receipt")
                            except Exception as exc:
                                error = exc
                        if (
                            receipt_location is not None
                            and self.store.path(receipt_location).exists()
                        ):
                            # Receipt publication wins over a later non-crash bookkeeping error.
                            error = None
                        code, retryable = (
                            (None, False) if error is None else _error(error)
                        )
                        finished = dict(
                            attempt_id=data["context"].attempt_id,
                            outcome="succeeded" if error is None else "failed",
                            error_code=code,
                            retryable=retryable,
                            ended_at=self.clock(),
                            receipt=receipt_location if error is None else None,
                            evidence=native,
                        )
                        self.store.write(
                            attempt + "/finished.json", "finished", finished
                        )
                        history[name][-1] = (attempt, history[name][-1][1], finished)
                        if error is None:
                            produced[name] = outputs
                            resolution(
                                name,
                                TaskState.SUCCEEDED,
                                CompletionDisposition.EXECUTED,
                                receipt_location,
                            )
                            if can_publish_cache(
                                task.cache_policy, data["recipe"]
                            ) and all(
                                ref.semantic_digest is not None
                                for refs in outputs.values()
                                for ref in refs
                            ):
                                self.store.write(
                                    "cache/"
                                    + data["recipe"].value
                                    + "/"
                                    + data["context"].attempt_id
                                    + ".json",
                                    "index",
                                    dict(
                                        receipt=receipt_location,
                                        receipt_digest=sha(
                                            self.store.read_bytes(receipt_location)
                                        ),
                                    ),
                                )
                        elif (
                            retryable
                            and task.restart_safety is RestartSafety.RESTARTABLE
                            and len(history[name]) < task.retry_policy.max_attempts
                        ):
                            transition(name, TaskState.PENDING)
                            ready_at[name] = (
                                self.clock() + task.retry_policy.backoff_seconds
                            )
                        else:
                            resolution(name, TaskState.FAILED, error=code)
                    elif not made_progress:
                        future = [
                            v
                            for k, v in ready_at.items()
                            if states[k] is TaskState.PENDING and v > self.clock()
                        ]
                        if not future:
                            raise WorkflowStateError("SCHEDULER_STALLED")
                        self.sleep(max(0, min(future) - self.clock()))
            except BaseException:
                cancelled.set()
                raise
        status = (
            "SUCCEEDED"
            if all(s is TaskState.SUCCEEDED for s in states.values())
            else "FAILED"
        )
        self.store.write(
            prefix + "/summary.json",
            "summary",
            dict(
                run_id=run_id,
                status=status,
                states={k: v.value for k, v in states.items()},
                completion_order=completion,
            ),
        )
        return RunResult(run_id, status, states, produced, tuple(completion))
