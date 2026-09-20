"""Small dummy operations test runtime mechanics, not the six-family P4.3 gate."""

import hashlib
import json
import os
import threading
from dataclasses import replace
from pathlib import Path

import pytest
from test_fingerprint_cache import (
    ALLOCATION,
    PLUGIN,
    PROFILE,
    SCHEMA,
    known,
    prepared,
    task,
)

from insarforge.contracts.context import ResourceAllocation, ResourceRequest
from insarforge.contracts.errors import (
    ContractError,
    RetryableExecutionError,
    WorkflowStateError,
    WorkspaceError,
)
from insarforge.contracts.execution import (
    CachePolicy,
    OutputRef,
    RestartSafety,
    RetryPolicy,
    TaskState,
    WorkflowPlan,
)
from insarforge.contracts.identity import PluginDescriptor
from insarforge.contracts.operations import (
    ArtifactDraft,
    InputPortContract,
    OperationBinding,
    OutputPortContract,
    ResolvedInput,
    TaskOutcome,
)
from insarforge.contracts.record_serialization import record_from_bytes
from insarforge.core.registry import PluginRegistry
from insarforge.core.runtime import Runtime, RuntimeCrash
from insarforge.products.assets import (
    AssetIntegrity,
    AssetKind,
    AssetLocation,
    AssetLocationKind,
    NativeAsset,
)
from insarforge.products.models import ProductDraft
from insarforge.products.validation import (
    ProductValidationReport,
    validate_product_structure,
)
from insarforge.provenance.workspace import Workspace, key, parse_record, record_bytes


class Codec:
    def decode(self, artifact, payload, schema):
        return ResolvedInput(artifact, record_from_bytes(artifact, payload))

    def encode(self, value, schema):
        return ArtifactDraft(schema, value)


class Validator:
    def validate(self, value, schema, profile):
        return validate_product_structure(value)


class Dummy:
    def __init__(self):
        self.calls = []
        self.counts = {}
        self.failures = {}
        self.identity = prepared()
        self.preflight_error = False
        self.barrier = None
        self.hook = None
        self.bad_output = False
        self.weak_asset = False
        self.outside = None
        self.guard = threading.Lock()

    def factory(self):
        self.calls.append(("factory", None))
        return object()

    def validate_spec(self, *args):
        return ProductValidationReport(())

    def prepare(self, plugin, inputs, parameters, probe):
        self.calls.append(("prepare", parameters["label"]))
        assert isinstance(probe.allocated_resources, ResourceAllocation)
        if self.preflight_error:
            raise OSError("credential-private-text")
        return self.identity

    def invoke(self, plugin, prepared_value, inputs, parameters, context):
        name = context.task_id
        with self.guard:
            self.calls.append(("invoke", name))
            self.counts[name] = self.counts.get(name, 0) + 1
            count = self.counts[name]
        if self.barrier:
            self.barrier.wait(timeout=5)
        if self.hook:
            self.hook(context, inputs)
        if name in self.failures and count <= len(self.failures[name]):
            raise self.failures[name][count - 1]
        path = context.artifact_dir / "data.txt"
        raw = json.dumps(
            {
                "label": parameters["label"],
                "inputs": [
                    r.artifact.semantic_digest
                    for port in sorted(inputs)
                    for r in inputs[port]
                ],
            },
            sort_keys=True,
        ).encode()
        path.write_bytes(raw)
        if self.outside:
            path = self.outside
        asset = NativeAsset(
            "data",
            AssetKind.FILE,
            AssetLocation(AssetLocationKind.ABSOLUTE_LOCAL, str(path), None),
            "text/plain",
            len(raw),
            None
            if self.weak_asset
            else AssetIntegrity("sha256", hashlib.sha256(raw).hexdigest()),
            None,
        )
        value = ProductDraft(
            "product:test",
            "profile:test",
            1,
            (asset,),
            (),
            (),
            (),
            {"label": known(parameters["label"])},
            {},
        )
        return TaskOutcome(
            {"out": () if self.bad_output else (Codec().encode(value, SCHEMA),)}, ()
        )


def t(name="a", sources=(), **changes):
    return task(
        inputs={"in": tuple(sources)},
        task_id=name,
        semantic_parameters={"label": name},
        restart_safety=RestartSafety.RESTARTABLE,
        **changes,
    )


def fixture(tmp_path, dummy=None, **options):
    dummy = dummy or Dummy()
    binding = OperationBinding(
        "synthetic:op",
        1,
        "synthetic:parameters",
        1,
        (InputPortContract("in", SCHEMA, PROFILE, 0, None, Codec(), Validator()),),
        (OutputPortContract("out", SCHEMA, PROFILE, 1, Codec(), Validator()),),
        (),
        1,
        dummy,
    )
    registry = PluginRegistry(1)
    registry.register(
        PluginDescriptor(PLUGIN.kind, PLUGIN.plugin_id, 1, "1", "dummy", ()),
        dummy.factory,
        (binding,),
    )
    registry.seal()
    runtime = Runtime(
        registry,
        tmp_path / "workspace",
        budget=options.pop("budget", ALLOCATION),
        implementation_files={PLUGIN: {"dummy.py": Path(__file__).resolve()}},
        **options,
    )
    return runtime, dummy


def records(runtime, kind):
    files = runtime.store.inventory("runs/**/*.json")
    found = []
    for p in files:
        try:
            value = parse_record(runtime.store.read_bytes(p), kind)
        except WorkspaceError:
            continue
        found.append((p, value))
    return found


def run_ids(runtime):
    return [p.split("/")[1] for p in runtime.store.inventory("runs/*/run.json")]


def test_serial_chain_and_commit_order(tmp_path):
    runtime, dummy = fixture(tmp_path)

    def check(point):
        if point == "before_receipt":
            assert not records(runtime, "receipt") or all(
                r["task_id"] == "a" for _, r in records(runtime, "receipt")
            )

    runtime.fault = check
    result = runtime.run(WorkflowPlan(1, (t(), t("b", (OutputRef("a", "out"),)))))
    assert result.status == "SUCCEEDED" and result.completion_order == ("a", "b")
    assert dummy.counts == {"a": 1, "b": 1}
    assert dummy.calls.index(("prepare", "a")) < dummy.calls.index(("invoke", "a"))
    assert len(records(runtime, "started")) == 2
    assert len(records(runtime, "receipt")) == 2
    output = result.outputs["b"]["out"][0]
    product = record_from_bytes(output, runtime.store.read_bytes(output.locator))
    assert product.lineage[0].artifact == result.outputs["a"]["out"][0]
    assert product.produced_by.attempt_id == records(runtime, "receipt")[1][1][
        "attempt_id"
    ] or product.produced_by.attempt_id in [
        r["attempt_id"] for _, r in records(runtime, "receipt")
    ]
    transitions = [r["state"] for _, r in records(runtime, "transition")]
    assert transitions == ["running", "succeeded", "running", "succeeded"]


def test_cache_receipt_reuse_no_attempt_and_original_lineage(tmp_path):
    runtime, dummy = fixture(tmp_path)
    plan = WorkflowPlan(1, (t(),))
    first = runtime.run(plan)
    original = runtime.store.read_bytes(first.outputs["a"]["out"][0].locator)
    second = runtime.run(plan)
    assert dummy.counts == {"a": 1}
    assert first.outputs == second.outputs
    assert runtime.store.read_bytes(second.outputs["a"]["out"][0].locator) == original
    assert not runtime.store.inventory(
        "runs/" + second.run_id + "/attempts/*/*/started.json"
    )
    assert (
        runtime.store.read(
            "runs/" + second.run_id + "/resolutions/" + key("a") + ".json", "resolution"
        )["disposition"]
        == "cache_reused"
    )


@pytest.mark.parametrize(
    "policy,weak", [(CachePolicy.DISABLED, False), (CachePolicy.AUTO, True)]
)
def test_no_cache_for_disabled_or_weak(tmp_path, policy, weak):
    runtime, dummy = fixture(tmp_path)
    dummy.weak_asset = weak
    plan = WorkflowPlan(1, (t(cache_policy=policy),))
    a = runtime.run(plan)
    b = runtime.run(plan)
    assert a.status == b.status == "SUCCEEDED"
    assert dummy.counts["a"] == 2
    assert (
        not runtime.store.inventory("cache/*/*.json")
        if policy is CachePolicy.DISABLED
        else True
    )
    if weak:
        assert a.outputs["a"]["out"][0].semantic_digest is None


@pytest.mark.parametrize(
    "exception,restart,budget,expected",
    [
        (RetryableExecutionError, RestartSafety.RESTARTABLE, 3, 2),
        (RetryableExecutionError, RestartSafety.UNSAFE, 3, 1),
        (OSError, RestartSafety.RESTARTABLE, 3, 1),
        (TimeoutError, RestartSafety.RESTARTABLE, 3, 1),
        (ValueError, RestartSafety.RESTARTABLE, 3, 1),
        (RetryableExecutionError, RestartSafety.RESTARTABLE, 1, 1),
    ],
)
def test_retry_classification_budget_and_safe_errors(
    tmp_path, exception, restart, budget, expected
):
    runtime, dummy = fixture(tmp_path)
    dummy.failures = {"a": [exception("secret-command-token")]}
    plan = WorkflowPlan(
        1, (replace(t(), restart_safety=restart, retry_policy=RetryPolicy(budget, 0)),)
    )
    result = runtime.run(plan)
    assert dummy.counts["a"] == expected
    assert result.status == ("SUCCEEDED" if expected == 2 else "FAILED")
    assert len(records(runtime, "started")) == expected
    outcomes = [r["outcome"] for _, r in records(runtime, "finished")]
    assert outcomes.count("failed") == 1 and outcomes.count("succeeded") == expected - 1
    assert not any(
        b"secret-command-token" in p.read_bytes()
        for p in runtime.store.area.rglob("*.json")
    )


def test_retry_exhaustion_and_clock(tmp_path):
    clock = [10.0]
    sleeps = []

    def sleep(seconds):
        sleeps.append(seconds)
        clock[0] += seconds

    runtime, dummy = fixture(tmp_path, _clock=lambda: clock[0], _sleep=sleep)
    dummy.failures = {"a": [RetryableExecutionError() for _ in range(4)]}
    result = runtime.run(WorkflowPlan(1, (t(retry_policy=RetryPolicy(3, 5)),)))
    assert result.status == "FAILED" and dummy.counts["a"] == 3 and sleeps == [5, 5]


def test_failure_blocks_dependents_but_independent_continues(tmp_path):
    runtime, dummy = fixture(tmp_path)
    dummy.failures = {"a": [ValueError()]}
    result = runtime.run(
        WorkflowPlan(1, (t(), t("b", (OutputRef("a", "out"),)), t("z")))
    )
    assert result.states == {
        "a": TaskState.FAILED,
        "b": TaskState.BLOCKED,
        "z": TaskState.SUCCEEDED,
    }
    assert dummy.counts == {"a": 1, "z": 1}


@pytest.mark.parametrize(
    "resource_request",
    [ResourceRequest(2), ResourceRequest(1, None, 1), ResourceRequest(1, 100, 0)],
)
def test_impossible_resources_preflight_no_attempt(tmp_path, resource_request):
    runtime, dummy = fixture(tmp_path)
    result = runtime.run(WorkflowPlan(1, (t(resources=resource_request),)))
    assert (
        result.status == "FAILED"
        and not dummy.counts
        and not records(runtime, "started")
    )


def test_prepare_and_output_failure(tmp_path):
    runtime, dummy = fixture(tmp_path)
    dummy.preflight_error = True
    assert runtime.run(WorkflowPlan(1, (t(),))).status == "FAILED"
    assert not records(runtime, "started")
    dummy.preflight_error = False
    dummy.bad_output = True
    assert runtime.run(WorkflowPlan(1, (t(),))).status == "FAILED"
    assert not records(runtime, "receipt")


@pytest.mark.parametrize("point", ["before_receipt", "after_receipt"])
def test_crash_windows_resume_and_old_facts(tmp_path, point):
    runtime, dummy = fixture(tmp_path)
    plan = WorkflowPlan(1, (t(retry_policy=RetryPolicy(2)),))

    def crash(where):
        if where == point:
            raise RuntimeCrash()

    runtime.fault = crash
    with pytest.raises(RuntimeCrash):
        runtime.run(plan)
    old = run_ids(runtime)[0]
    prior = {
        p: p.read_bytes()
        for p in runtime.store.path("runs/" + old).rglob("*")
        if p.is_file()
    }
    runtime.fault = lambda _: None
    recovered = runtime.resume(old)
    assert recovered.status == "SUCCEEDED" and recovered.run_id != old
    assert dummy.counts["a"] == (2 if point == "before_receipt" else 1)
    assert all(p.read_bytes() == raw for p, raw in prior.items())
    assert runtime.store.status(old) == "INTERRUPTED"
    assert len(records(runtime, "started")) == (2 if point == "before_receipt" else 1)


@pytest.mark.parametrize(
    "restart,budget", [(RestartSafety.UNSAFE, 3), (RestartSafety.RESTARTABLE, 1)]
)
def test_interruption_cannot_reset_budget_or_unsafe_restart(tmp_path, restart, budget):
    runtime, dummy = fixture(tmp_path)

    def crash(point):
        if point == "before_receipt":
            raise RuntimeCrash()

    runtime.fault = crash
    with pytest.raises(RuntimeCrash):
        runtime.run(
            WorkflowPlan(
                1,
                (
                    replace(
                        t(), restart_safety=restart, retry_policy=RetryPolicy(budget)
                    ),
                ),
            )
        )
    old = run_ids(runtime)[0]
    runtime.fault = lambda _: None
    second = runtime.resume(old)
    third = runtime.resume(second.run_id)
    assert second.status == third.status == "FAILED" and dummy.counts["a"] == 1


def test_changed_prepared_identity_requires_replan(tmp_path):
    runtime, dummy = fixture(tmp_path)
    first = runtime.run(WorkflowPlan(1, (t(),)))
    dummy.identity = prepared(wrapper_digest="e" * 64)
    with pytest.raises(WorkflowStateError, match="REPLAN"):
        runtime.resume(first.run_id)
    assert dummy.counts["a"] == 1


def test_pure_dry_run(tmp_path, monkeypatch):
    runtime, dummy = fixture(tmp_path)

    def forbidden(*args, **kwargs):
        pytest.fail("dry run I/O")

    monkeypatch.setattr(Path, "open", forbidden)
    report = runtime.dry_run(WorkflowPlan(1, (t(), t("b", (OutputRef("a", "out"),)))))
    assert not dummy.calls
    assert report.runtime_availability == "UNCHECKED"
    assert all(row["fingerprint"] is None for row in report.tasks)
    assert not runtime.store.root.exists()


def test_second_writer_and_unsupported_filesystem(tmp_path, monkeypatch):
    from insarforge.provenance import workspace

    one = Workspace(tmp_path / "workspace")
    with one.writer():
        with pytest.raises(WorkspaceError, match="BUSY"):
            with Workspace(tmp_path / "workspace").writer():
                pass

    def unsupported(_):
        raise WorkspaceError("UNSUPPORTED")

    monkeypatch.setattr(workspace, "check_local", unsupported)
    with pytest.raises(WorkspaceError, match="UNSUPPORTED"):
        with one.writer():
            pass


def test_manifest_corruption_and_mtime_attack(tmp_path):
    runtime, dummy = fixture(tmp_path)
    plan = WorkflowPlan(1, (t(),))
    first = runtime.run(plan)
    ref = first.outputs["a"]["out"][0]
    product = record_from_bytes(ref, runtime.store.read_bytes(ref.locator))
    asset = Path(product.assets[0].location.value)
    before = asset.stat()
    raw = asset.read_bytes()
    asset.write_bytes(b"x" * len(raw))
    os.utime(asset, ns=(before.st_atime_ns, before.st_mtime_ns))
    assert runtime.run(plan).status == "SUCCEEDED"
    assert dummy.counts["a"] == 2
    runtime.store.path(ref.locator).write_bytes(b"corrupted")
    assert runtime.run(plan).status == "SUCCEEDED"


def test_output_cannot_alias_upstream(tmp_path):
    runtime, dummy = fixture(tmp_path)
    outside = tmp_path / "upstream"
    outside.write_bytes(b"data")
    dummy.outside = outside
    assert runtime.run(WorkflowPlan(1, (t(),))).status == "FAILED"
    assert not records(runtime, "receipt")
    assert outside.read_bytes() == b"data"


def test_persistence_strict_and_secret_safe():
    for raw in (b"{}", b'{"schema_version":1,"schema_version":1}', b'{"x":NaN}'):
        with pytest.raises(WorkspaceError):
            parse_record(raw, "summary")
    with pytest.raises(WorkspaceError):
        record_bytes(
            "index",
            {"receipt": "https://user:secret@example.com", "receipt_digest": "d" * 64},
        )


def test_real_overlap_completion_order_and_coordinator_writes(tmp_path, monkeypatch):
    runtime, dummy = fixture(
        tmp_path, max_workers=2, budget=ResourceAllocation(2, 20, 2)
    )
    barrier = threading.Barrier(2)
    release = threading.Event()
    entered = set()

    def hook(context, inputs):
        if context.task_id in ("a", "b"):
            with dummy.guard:
                entered.add(context.task_id)
            barrier.wait(timeout=5)
            if context.task_id == "a":
                assert release.wait(5)

    dummy.hook = hook
    runtime.fault = lambda point: release.set() if point == "after_receipt" else None
    writer_threads = []
    original = runtime.store.write

    def write(*args, **kwargs):
        writer_threads.append(threading.get_ident())
        return original(*args, **kwargs)

    monkeypatch.setattr(runtime.store, "write", write)
    request = ResourceRequest(1, 10, 1)
    result = runtime.run(
        WorkflowPlan(
            1,
            (
                t(resources=request),
                t("b", resources=request),
                t(
                    "c",
                    (OutputRef("a", "out"), OutputRef("b", "out")),
                    resources=request,
                ),
            ),
        )
    )
    assert entered == {"a", "b"} and result.status == "SUCCEEDED"
    assert result.completion_order == ("b", "a", "c")
    assert set(writer_threads) == {threading.get_ident()}


def test_concurrent_resource_ceiling(tmp_path):
    import time

    runtime, dummy = fixture(
        tmp_path, max_workers=4, budget=ResourceAllocation(2, 20, 2)
    )
    current = [0, 0, 0]
    peak = [0, 0, 0]

    def hook(context, inputs):
        a = context.allocated_resources
        with dummy.guard:
            current[0] += a.cpu_cores
            current[1] += a.gpu_count
            current[2] += a.memory_bytes
            for i in range(3):
                peak[i] = max(peak[i], current[i])
        time.sleep(0.03)
        with dummy.guard:
            current[0] -= a.cpu_cores
            current[1] -= a.gpu_count
            current[2] -= a.memory_bytes

    dummy.hook = hook
    result = runtime.run(
        WorkflowPlan(
            1, tuple(t(str(i), resources=ResourceRequest(1, 10, 1)) for i in range(6))
        )
    )
    assert result.status == "SUCCEEDED" and peak == [2, 2, 20] and current == [0, 0, 0]


def test_cache_survives_missing_index(tmp_path):
    runtime, dummy = fixture(tmp_path)
    plan = WorkflowPlan(1, (t(),))
    runtime.run(plan)
    for path in runtime.store.area.glob("cache/*/*.json"):
        path.unlink()
    result = runtime.run(plan)
    assert result.status == "SUCCEEDED" and dummy.counts["a"] == 1


def test_unknown_execution_executes_but_resume_refuses(tmp_path):
    from test_fingerprint_cache import Prepared

    from insarforge.products.semantics import SemanticStatus, SemanticValue

    runtime, dummy = fixture(tmp_path)
    dummy.identity = Prepared(
        SemanticValue(SemanticStatus.UNKNOWN, None, "runtime:unknown", ())
    )
    result = runtime.run(WorkflowPlan(1, (t(),)))
    assert result.status == "SUCCEEDED"
    assert result.outputs["a"]["out"][0].semantic_digest is None
    assert not runtime.store.inventory("cache/*/*.json")
    with pytest.raises(WorkflowStateError, match="REPLAN"):
        runtime.resume(result.run_id)


def test_no_weak_asset_cache_index(tmp_path):
    runtime, dummy = fixture(tmp_path)
    dummy.weak_asset = True
    assert runtime.run(WorkflowPlan(1, (t(),))).status == "SUCCEEDED"
    assert not runtime.store.inventory("cache/*/*.json")


def test_corrupt_receipt_does_not_become_success(tmp_path):
    runtime, dummy = fixture(tmp_path)
    plan = WorkflowPlan(1, (t(),))
    first = runtime.run(plan)
    receipt = records(runtime, "receipt")[0][0]
    runtime.store.path(receipt).write_bytes(b'{"schema_version":999}')
    assert runtime.run(plan).status == "SUCCEEDED"
    assert dummy.counts["a"] == 2
    assert runtime.store.status(first.run_id) == "SUCCEEDED"


@pytest.mark.parametrize(
    "kind,payload",
    [
        ("transition", {"task_id": "a", "state": "cached"}),
        (
            "summary",
            {
                "run_id": "x" * 32,
                "status": "SUCCEEDED",
                "states": {},
                "completion_order": [],
            },
        ),
        ("index", {"receipt": "runs/x/result.json", "receipt_digest": "placeholder"}),
        (
            "finished",
            {
                "attempt_id": "a" * 32,
                "outcome": "failed",
                "error_code": "RAW_SECRET",
                "retryable": "yes",
                "ended_at": 1,
                "receipt": None,
                "evidence": [],
            },
        ),
    ],
)
def test_wrong_persisted_value_types_refused(kind, payload):
    with pytest.raises(WorkspaceError):
        record_bytes(kind, payload)


def test_runtime_import_boundaries():
    import ast
    import subprocess
    import sys

    root = Path(__file__).resolve().parents[2]
    files = [
        root / "src/insarforge" / name
        for name in (
            "core/runtime.py",
            "core/runtime_plan.py",
            "core/_runtime_artifacts.py",
            "provenance/workspace.py",
            "contracts/record_serialization.py",
        )
    ]
    forbidden = (
        "insarforge.config",
        "insarforge.missions",
        "insarforge.providers",
        "insarforge.processors",
        "insarforge.corrections",
        "insarforge.analyzers",
        "insarforge.qc",
        "numpy",
        "scipy",
        "pydantic",
        "rasterio",
        "osgeo",
    )
    for path in files:
        for node in ast.walk(ast.parse(path.read_text())):
            names = (
                [a.name for a in node.names]
                if isinstance(node, ast.Import)
                else ([node.module or ""] if isinstance(node, ast.ImportFrom) else [])
            )
            assert not any(
                n == f or n.startswith(f + ".") for n in names for f in forbidden
            )
            if "/provenance/" in path.as_posix():
                assert not any(n.startswith("insarforge.core.runtime") for n in names)
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                assert node.value.lower() not in {
                    "isce2",
                    "isce3",
                    "gamma",
                    "stamps",
                    "sentinel1",
                }
    p = subprocess.run(
        [
            sys.executable,
            "-B",
            "-I",
            "-c",
            "import sys; import insarforge.core.runtime; assert not any(k.split('.')[0] in {'numpy','pydantic','scipy','rasterio','osgeo'} for k in sys.modules)",
        ],
        cwd=root,
        capture_output=True,
        text=True,
    )
    assert p.returncode == 0, p.stderr


def test_ordered_repeated_inputs_and_adr0014(tmp_path):
    from insarforge.contracts.plugins import ProductInput

    runtime, dummy = fixture(tmp_path)
    seen = []

    def hook(context, inputs):
        if context.task_id == "z":
            paired = [ProductInput(r.artifact, r.value) for r in inputs["in"]]
            seen.extend(p.artifact for p in paired)

    dummy.hook = hook
    plan = WorkflowPlan(
        1,
        (
            t(),
            t("b"),
            t(
                "z",
                (
                    OutputRef("b", "out"),
                    OutputRef("a", "out"),
                    OutputRef("b", "out"),
                ),
            ),
        ),
    )
    result = runtime.run(plan)
    assert result.status == "SUCCEEDED"
    assert seen == [
        result.outputs["b"]["out"][0],
        result.outputs["a"]["out"][0],
        result.outputs["b"]["out"][0],
    ]

    ref = result.outputs["z"]["out"][0]
    raw = runtime.store.read_bytes(ref.locator)
    product = record_from_bytes(ref, raw)
    assert tuple(e.artifact for e in product.lineage) == tuple(seen)
    before = dict(dummy.counts)
    reused = runtime.run(plan)
    assert reused.status == "SUCCEEDED"
    assert reused.outputs == result.outputs
    assert dummy.counts == before
    assert runtime.store.read_bytes(ref.locator) == raw


@pytest.mark.parametrize("kind", ["catalog", "acquisition", "qc"])
def test_record_codec_roundtrip_and_runtime(kind, tmp_path):
    from test_fingerprint_cache import ref

    from insarforge.contracts.execution import OutputDeclaration
    from insarforge.contracts.identity import PluginKind, PluginRef
    from insarforge.contracts.operations import RecordSchemaRef
    from insarforge.contracts.record_serialization import record_to_bytes
    from insarforge.contracts.records import (
        AccessStatus,
        AcquisitionMetadata,
        CatalogEntry,
        CatalogSnapshot,
        ProviderAvailability,
        ProviderDelivery,
        QCReport,
        QCStatus,
    )
    from insarforge.contracts.values import ArtifactRef

    if kind == "catalog":
        record = CatalogSnapshot(
            "record:a",
            "schema:catalog",
            1,
            PluginRef(PluginKind.PROVIDER, "dummy:provider", 1),
            "query:v1",
            1,
            {},
            (
                CatalogEntry(
                    "entry:a",
                    AccessStatus(
                        ProviderAvailability.AVAILABLE,
                        ProviderDelivery.DIRECT,
                        True,
                        None,
                    ),
                    {},
                    (),
                ),
            ),
            {},
        )
    elif kind == "acquisition":
        record = AcquisitionMetadata(
            "record:a",
            "schema:acquisition",
            1,
            ref(),
            PluginRef(PluginKind.MISSION, "dummy:mission", 1),
            {"orbit": known(1)},
            (),
            {},
        )
    else:
        record = QCReport(
            "record:a",
            "schema:qc",
            1,
            QCStatus.FAIL,
            "method:test",
            "1",
            (),
            (),
            (),
            {},
        )
    raw = record_to_bytes(record)
    ar = ArtifactRef(
        record.record_id,
        record.schema_id,
        record.schema_version,
        None,
        hashlib.sha256(raw).hexdigest(),
        "synthetic:record",
    )
    assert record_from_bytes(ar, raw) == record
    with pytest.raises(ContractError):
        record_from_bytes(ar, raw + b" ")

    class Typed(Dummy):
        def invoke(self, plugin, prep, inputs, parameters, context):
            self.counts["a"] = self.counts.get("a", 0) + 1
            return TaskOutcome(
                {"out": (ArtifactDraft(RecordSchemaRef(record.schema_id, 1), record),)},
                (),
            )

    class TypedValidator:
        def validate(self, *args):
            return ProductValidationReport(())

    d = Typed()
    schema = RecordSchemaRef(record.schema_id, 1)
    b = OperationBinding(
        "synthetic:op",
        1,
        "parameters:v1",
        1,
        (),
        (OutputPortContract("out", schema, None, 1, Codec(), TypedValidator()),),
        (),
        1,
        d,
    )
    registry = PluginRegistry(1)
    registry.register(
        PluginDescriptor(PLUGIN.kind, PLUGIN.plugin_id, 1, "1", "dummy", ()),
        d.factory,
        (b,),
    )
    registry.seal()
    runtime = Runtime(
        registry,
        tmp_path / "typed",
        budget=ALLOCATION,
        implementation_files={PLUGIN: {"dummy.py": Path(__file__).resolve()}},
    )
    spec = task(
        inputs={},
        task_id="a",
        semantic_parameters={"label": "a"},
        outputs=(OutputDeclaration("out", record.schema_id, 1),),
    )
    first = runtime.run(WorkflowPlan(1, (spec,)))
    second = runtime.run(WorkflowPlan(1, (spec,)))
    assert first.status == second.status == "SUCCEEDED" and d.counts["a"] == 1


def test_secret_parameters_and_outcome_never_commit(tmp_path):
    runtime, dummy = fixture(tmp_path)
    with pytest.raises(ContractError):
        WorkflowPlan(
            1, (replace(t(), semantic_parameters={"password": "secret-material"}),)
        ).to_json()
    # Logger supplied to the worker does not persist uncontrolled message text.
    dummy.hook = lambda context, inputs: context.logger.error(
        "private-native-exception"
    )
    assert runtime.run(WorkflowPlan(1, (t(),))).status == "SUCCEEDED"
    assert not any(
        b"private-native-exception" in p.read_bytes()
        for p in runtime.store.area.rglob("*")
        if p.is_file()
    )


def test_filesystem_symlink_refused(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    workspace = tmp_path / "alias"
    workspace.symlink_to(outside, target_is_directory=True)
    with pytest.raises(WorkspaceError, match="SYMLINK"):
        with Workspace(workspace).writer():
            pass
    assert not (outside / ".insarforge").exists()


@pytest.mark.parametrize(
    "contents",
    [
        '{"password":"synthetic-value"}',
        "api_key = synthetic-value",
        "message https://example.invalid/data?X-Amz-Signature=synthetic",
        "-----BEGIN PRIVATE KEY-----",
        '{"setting":1}',
    ],
)
def test_native_text_evidence_is_checked_before_receipt(tmp_path, contents):
    runtime, dummy = fixture(tmp_path)
    original = dummy.invoke

    def invoke(*args):
        outcome = original(*args)
        context = args[-1]
        path = context.attempt_dir / "native.txt"
        path.write_text(contents)
        evidence = NativeAsset(
            "native:evidence",
            AssetKind.FILE,
            AssetLocation(AssetLocationKind.ABSOLUTE_LOCAL, str(path), None),
            "text/plain",
            len(contents.encode()),
            AssetIntegrity("sha256", hashlib.sha256(contents.encode()).hexdigest()),
            None,
        )
        return TaskOutcome(outcome.outputs, (evidence,))

    dummy.invoke = invoke
    result = runtime.run(WorkflowPlan(1, (t(),)))
    assert dummy.counts == {"a": 1}
    if contents == '{"setting":1}':
        assert result.status == "SUCCEEDED"
        assert runtime.store.inventory("runs/*/attempts/*/*/result.json")
        return
    assert result.status == "FAILED"
    assert not runtime.store.inventory("runs/*/attempts/*/*/result.json")
    assert not runtime.store.inventory("cache/*/*.json")
    for location in runtime.store.inventory("runs/*/attempts/*/*/finished.json"):
        assert contents not in runtime.store.read_bytes(location).decode()


def test_provenance_projection_nested_shapes_and_source_revision(tmp_path):
    runtime, _ = fixture(tmp_path)
    runtime.source_revision = "a" * 40
    result = runtime.run(WorkflowPlan(1, (t(),)))
    payload = runtime.store.read("runs/" + result.run_id + "/run.json", "run")
    assert payload["code_provenance"]["source_revision"] == "a" * 40
    assert payload["code_provenance"]["package_version"]
    payload["engine_identity"]["extra"] = "not-declared"
    with pytest.raises(WorkspaceError):
        record_bytes("run", payload)
    receipt_path = runtime.store.inventory("runs/*/attempts/*/*/result.json")[0]
    receipt = runtime.store.read(receipt_path, "receipt")
    receipt["inputs"] = [{"port": "in", "semantic_digests": ["placeholder"]}]
    with pytest.raises(WorkspaceError):
        record_bytes("receipt", receipt)
