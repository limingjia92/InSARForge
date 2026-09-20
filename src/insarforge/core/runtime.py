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
from insarforge.contracts._execution_json import plain
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
    _artifact_from_dict,
)
from insarforge.contracts.record_serialization import record_from_bytes
from insarforge.core._runtime_artifacts import (
    candidate_from_receipt,
    finalize,
    output_data,
    resolve_inputs,
    sha,
)
from insarforge.core.cache import can_publish_cache, validate_cache_candidate
from insarforge.core.content_identity import code_content_identity, engine_code_identity
from insarforge.core.fingerprints import (
    execution_identity,
    input_identities,
    task_fingerprint,
)
from insarforge.core.runtime_plan import RunResult, allocation, dry_run, validate_task
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

    def run(self, plan, *, external_manifests=None, config_refs=()):
        with self.store.writer():
            return self._run(plan, dict(external_manifests or {}), None, config_refs)

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
            plan = WorkflowPlan.from_json(self.store.read_bytes(prefix + "/plan.json"))
            if plan.digest != original["plan_digest"]:
                raise WorkflowStateError("RESUME_PLAN_CHANGED")
            external = {
                ref.record_id: self.store.read_bytes(
                    prefix + "/external/" + key(ref.record_id) + ".json"
                )
                for ref in plan.external_inputs
            }
            return self._run(plan, external, original, ())

    def _history(self, scope):
        histories = {}
        for location in self.store.inventory("runs/*/attempts/*/*/started.json"):
            started = self.store.read(location, "started")
            if started["scope_id"] != scope:
                continue
            prefix = location.rsplit("/", 1)[0]
            finished = None
            if self.store.path(prefix + "/finished.json").exists():
                finished = self.store.read(prefix + "/finished.json", "finished")
                if (
                    finished["attempt_id"] != started["attempt_id"]
                    or finished["outcome"] not in ("succeeded", "failed", "interrupted")
                    or type(finished["retryable"]) is not bool
                ):
                    raise WorkflowStateError("ATTEMPT_HISTORY_INVALID")
            histories.setdefault(started["task_id"], []).append(
                (prefix, started, finished)
            )
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
                    receipt = self.store.read(parent + "/result.json", "receipt")
                    if any(
                        receipt[k] != started[k]
                        for k in (
                            "attempt_id",
                            "task_id",
                            "scope_id",
                            "fingerprint",
                            "execution",
                            "inputs",
                        )
                    ):
                        raise WorkflowStateError("RECOVERY_RECEIPT")
                    for refs in receipt["outputs"].values():
                        for data in refs:
                            ref = _artifact_from_dict(data)
                            if not ref.locator.startswith(parent + "/manifests/"):
                                raise WorkflowStateError("RECOVERY_LOCATION")
                            raw = self.store.read_bytes(ref.locator)
                            if sha(raw) != ref.manifest_digest:
                                raise WorkflowStateError("RECOVERY_MANIFEST")
                            record_from_bytes(ref, raw)
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

    def _run(self, plan, external, source, config_refs):
        if type(plan) is not WorkflowPlan or not self.registry.is_sealed:
            raise ContractError("RUNTIME_PLAN_OR_REGISTRY")
        # Whole-plan structural validation already belongs to WorkflowPlan.
        # Static per-task errors become FAILED without preventing independent work.
        if set(external) != {r.record_id for r in plan.external_inputs}:
            raise ContractError("EXTERNAL_INPUT_SET")
        for ref in plan.external_inputs:
            if sha(external[ref.record_id]) != ref.manifest_digest:
                raise ContractError("EXTERNAL_INPUT_HASH")
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
            self._recover(source)
        run_id = uuid.uuid4().hex
        scope = source["scope_id"] if source else uuid.uuid4().hex
        prefix = "runs/" + run_id
        self.store.write_bytes(prefix + "/plan.json", plan.to_json())
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
        history = self._history(scope)
        states = {t.task_id: TaskState.PENDING for t in plan.tasks}
        produced = {}
        completion = []
        active = {}
        ready_at = {}
        events = 0
        if source:
            for name, members in history.items():
                last = members[-1][2]
                if last and last["outcome"] == "failed" and last["retryable"]:
                    ready_at[name] = (
                        last["ended_at"] + plan.task(name).retry_policy.backoff_seconds
                    )
        cancelled = threading.Event()
        ended = queue.Queue()

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
                            inputs, refs = resolve_inputs(
                                self.store, task, bound, produced, external
                            )
                            registration = self.registry.resolve(task.plugin_ref)
                            plugin = registration.factory()
                            prepared = bound.handler.prepare(
                                plugin, inputs, task.semantic_parameters, _Probe(alloc)
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
                            old = history.get(name, [])
                            if source and (
                                not recipe.reusable
                                or not execution.reusable
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
                                try:
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
                                    damaged = True
                                except Exception:
                                    damaged = True
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
                                prepared=dict(
                                    status=prepared.semantic_execution_identity.status.value,
                                    value=plain(
                                        prepared.semantic_execution_identity.value
                                    ),
                                    reason_code=prepared.semantic_execution_identity.reason_code,
                                ),
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
                                    data["refs"],
                                    data["context"],
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
