"""P4.3-02 E2E-01--08, with Runtime-only business calls and disk-only reopen."""

import gc
import hashlib
import os
import socket
import subprocess
import sys
import weakref
from pathlib import Path
from threading import Lock

import pytest

from insarforge.contracts.execution import TaskState
from insarforge.contracts.fingerprints import FingerprintResult
from insarforge.contracts.identity import PluginKind
from insarforge.contracts.plugins import (
    AcquireRequest,
    AnalysisRequest,
    CorrectionRequest,
    InspectionRequest,
    ProcessingRequest,
    QCRequest,
    SearchRequest,
)
from insarforge.contracts.records import (
    AcquisitionMetadata,
    CatalogSnapshot,
    QCReport,
    QCStatus,
)
from insarforge.contracts.values import ArtifactRef
from insarforge.core.fingerprints import execution_identity, input_identities
from insarforge.core.planning import validate_plan
from insarforge.core.result_identity import (
    artifact_semantic_digest,
    record_semantic_material,
)
from insarforge.products.models import Product, ProductDraft
from insarforge.products.semantics import SemanticStatus
from insarforge.products.serialization import canonical_json_bytes
from insarforge.provenance.runtime_evidence import ArtifactEvidence, PreparationEvidence
from insarforge.provenance.workspace import Workspace

from ._canonical_workflow import (
    BUDGET,
    ORDER,
    canonical_plan,
    canonical_runtime,
    reopen_workspace,
)
from ._fake_operations import ACQUISITION, CATALOG, PRODUCT, PROFILE, QC, build_harness

EXPECTED = {
    "search": (CatalogSnapshot, CATALOG, SearchRequest),
    "acquire": (Product, PRODUCT, AcquireRequest),
    "inspect": (AcquisitionMetadata, ACQUISITION, InspectionRequest),
    "process": (Product, PRODUCT, ProcessingRequest),
    "correct": (Product, PRODUCT, CorrectionRequest),
    "analyze": (Product, PRODUCT, AnalysisRequest),
    "assess": (QCReport, QC, QCRequest),
}


def assert_static(harness, plan, runtime):
    assert harness.registry.is_sealed and len(harness.registry) == 6
    assert {r.ref.kind for r in harness.registry.registrations()} == set(PluginKind)
    assert len(plan.tasks) == 7 and plan.topological_order() == ORDER
    assert plan.external_inputs == ()
    for task in plan.tasks:
        registration = harness.registry.resolve(task.plugin_ref)
        assert (
            harness.registry.resolve_binding(
                task.plugin_ref, task.operation_id, task.operation_api_version
            )
            in registration.bindings
        )
    report = validate_plan(plan, harness.registry)
    assert report.is_valid
    # Static runtime availability remains explicitly UNVERIFIED, not fabricated.
    assert {issue.code for issue in report.unverified} == {
        "PLAN_RUNTIME_ENVIRONMENT_UNVERIFIED"
    }
    dry = runtime.dry_run(plan)
    assert dry.plan_digest == plan.digest and dry.runtime_availability == "UNCHECKED"
    assert all(row["fingerprint"] is None for row in dry.tasks)
    assert all(call.stage == "validate" for call in harness.controls.journal.snapshot())


def test_e2e01_static_plan_and_dry_run_do_no_io_or_business(tmp_path, monkeypatch):
    harness = build_harness()
    plan = canonical_plan(harness)
    runtime = canonical_runtime(harness, tmp_path / "dry")

    def forbidden(*args, **kwargs):
        pytest.fail("static planning performed external I/O")

    with monkeypatch.context() as guard:
        guard.setattr(Path, "open", forbidden)
        guard.setattr(Path, "mkdir", forbidden)
        guard.setattr(os, "open", forbidden)
        guard.setattr(socket, "socket", forbidden)
        guard.setattr(subprocess, "Popen", forbidden)
        assert_static(harness, plan, runtime)
    assert not runtime.store.root.exists()
    assert {call.stage for call in harness.controls.journal.snapshot()} == {"validate"}


@pytest.fixture
def successful(tmp_path, monkeypatch):
    harness = build_harness()
    plan = canonical_plan(harness)
    runtime = canonical_runtime(harness, tmp_path / "workspace")
    assert_static(harness, plan, runtime)
    manifest_reads = []
    lock = Lock()
    read = Workspace.read_bytes

    def observed_read(store, relative):
        raw = read(store, relative)
        if "/manifests/" in relative:
            # Observe the commit point at the actual read, before returning bytes
            # to the production resolver. Never inject a resolved input object.
            receipt = relative.split("/manifests/", 1)[0] + "/result.json"
            assert store.path(receipt).is_file(), "input read before upstream commit"
            with lock:
                manifest_reads.append((relative, hashlib.sha256(raw).hexdigest()))
        return raw

    monkeypatch.setattr(Workspace, "read_bytes", observed_read)
    result = runtime.run(plan)
    assert result.status == "SUCCEEDED"
    during_runtime = tuple(manifest_reads)
    snapshot = reopen_workspace(tmp_path / "workspace")
    return harness, result, snapshot, during_runtime, tmp_path / "workspace"


def test_e2e02_e2e04_all_seven_business_calls_and_terminal_states(successful):
    harness, result, disk, _, _ = successful
    assert set(result.states) == set(ORDER)
    assert all(state is TaskState.SUCCEEDED for state in result.states.values())
    assert result.completion_order == ORDER
    assert result.outputs == disk.artifacts
    assert disk.summary["states"] == {name: "succeeded" for name in ORDER}
    assert disk.summary["completion_order"] == list(ORDER)
    calls = harness.controls.journal.snapshot()
    assert [call.operation for call in calls if call.stage == "business"] == list(ORDER)
    for name in ORDER:
        assert harness.controls.journal.count("invoke", name, name) == 1
        assert harness.controls.journal.count("business", name, name) == 1
    for kind in PluginKind:
        assert harness.controls.journal.count("factory", kind.value) == (
            2 if kind is PluginKind.PROVIDER else 1
        )


@pytest.mark.parametrize("name", ORDER)
def test_e2e03_committed_typed_edges_reach_correct_family_request(successful, name):
    harness, _, disk, reads, workspace = successful
    calls = {
        c.operation: c
        for c in harness.controls.journal.snapshot()
        if c.stage == "business"
    }
    call = calls[name]
    record_type, schema, request_type = EXPECTED[name]
    assert type(call.request) is request_type
    out = disk.artifacts[name]["out"][0]
    record = disk.records[name]["out"][0]
    assert type(record) is record_type
    assert (out.schema_id, out.schema_version) == (
        schema.schema_id,
        schema.schema_version,
    )
    if record_type is Product:
        assert (record.profile_id, record.profile_version) == (
            PROFILE.profile_id,
            PROFILE.profile_version,
        )
        business_result = call.result if type(call.result) is tuple else (call.result,)
        assert all(type(value) is ProductDraft for value in business_result)
    else:
        assert type(call.result) is record_type
    store = Workspace(workspace)
    task = disk.plan.task(name)
    for port in harness.binding(name).inputs:
        expected_refs = tuple(
            disk.artifacts[source.task_id][source.port][0]
            for source in task.inputs[port.port_id]
        )
        rows = disk.started[name]["resolved_inputs"][port.port_id]
        assert tuple(ArtifactRef(**row["artifact"]) for row in rows) == expected_refs
        for row, ref in zip(rows, expected_refs, strict=True):
            assert (ref.locator, ref.manifest_digest) in reads
            assert row["manifest_location"] == ref.locator
            assert row["effective_digest"] == ref.semantic_digest is not None
            resolved = port.codec.decode(
                ref, store.read_bytes(ref.locator), port.schema
            )
            assert port.validator.validate(
                resolved.value, port.schema, port.profile
            ).is_fully_verified
            proof = ArtifactEvidence.from_dict(row["evidence"])
            assert proof.artifact == ref
    if name == "search":
        assert call.request.selectors == task.semantic_parameters
    elif name == "acquire":
        assert call.request.catalog_ref == disk.artifacts["search"]["out"][0]
        assert (
            call.request.entry_id
            == disk.records["search"]["out"][0].entries[0].entry_id
        )
    elif name == "inspect":
        assert call.request.source.artifact == disk.artifacts["acquire"]["out"][0]
        assert call.request.source.value == disk.records["acquire"]["out"][0]
        assert record.source_ref == call.request.source.artifact
    elif name == "process":
        assert (
            call.request.product_inputs["source"][0].value
            == disk.records["acquire"]["out"][0]
        )
        assert (
            call.request.product_inputs["source"][0].artifact
            == disk.artifacts["acquire"]["out"][0]
        )
        assert call.request.acquisition_metadata_refs == (
            disk.artifacts["inspect"]["out"][0],
        )
    elif name in ("correct", "analyze"):
        upstream = "process" if name == "correct" else "correct"
        inputs = (
            call.request.source_inputs
            if name == "correct"
            else call.request.product_inputs
        )
        assert inputs["source"][0].artifact == disk.artifacts[upstream]["out"][0]
        assert inputs["source"][0].value == disk.records[upstream]["out"][0]
    else:
        assert call.request.target_refs == (disk.artifacts["analyze"]["out"][0],)
        assert record.input_refs == call.request.target_refs
        assert record.status is QCStatus.NOT_EVALUATED


def assert_persisted_chain(disk, workspace):
    """Assertions use only data loaded by fresh existing persisted readers."""
    store = Workspace(workspace)
    assert disk.run["plan_digest"] == disk.plan.digest
    assert disk.run["run_id"] == disk.summary["run_id"]
    assert disk.summary["status"] == "SUCCEEDED"
    assert disk.summary["states"] == {name: "succeeded" for name in ORDER}
    assert (
        set(disk.artifacts) == set(disk.receipts) == set(disk.resolutions) == set(ORDER)
    )
    for name in ORDER:
        task = disk.plan.task(name)
        resolution, receipt = disk.resolutions[name], disk.receipts[name]
        started, finished = disk.started[name], disk.finished[name]
        assert (
            resolution["state"] == "succeeded"
            and resolution["disposition"] == "executed"
        )
        assert resolution["error_code"] is None and resolution["blocked_by"] == []
        assert started["task_id"] == receipt["task_id"] == resolution["task_id"] == name
        assert started["run_id"] == disk.run["run_id"]
        assert started["scope_id"] == receipt["scope_id"] == disk.run["scope_id"]
        assert started["attempt_id"] == receipt["attempt_id"] == finished["attempt_id"]
        assert started["sequence"] == 1 and started["plan_digest"] == disk.plan.digest
        assert (
            finished["outcome"] == "succeeded"
            and finished["error_code"] is None
            and not finished["retryable"]
        )
        assert finished["receipt"] == resolution["receipt"]
        assert (
            started["fingerprint"]
            == receipt["fingerprint"]
            == resolution["fingerprint"]
            is not None
        )
        assert (
            started["execution"]
            == receipt["execution"]
            == resolution["execution"]
            is not None
        )
        preparation = PreparationEvidence.from_dict(started["prepared"])
        assert execution_identity(preparation, BUDGET).value == receipt["execution"]
        inputs = {
            port: tuple(disk.artifacts[s.task_id][s.port][0] for s in sources)
            for port, sources in task.inputs.items()
        }
        assert canonical_json_bytes(input_identities(inputs)) == canonical_json_bytes(
            started["inputs"]
        )
        assert started["inputs"] == receipt["inputs"]
        for port, sources in task.inputs.items():
            rows = started["resolved_inputs"][port]
            assert len(rows) == len(sources)
            for source, row in zip(sources, rows, strict=True):
                upstream = disk.artifacts[source.task_id][source.port][0]
                proof = ArtifactEvidence.from_dict(row["evidence"])
                assert ArtifactRef(**row["artifact"]) == proof.artifact == upstream
                assert proof.output_port == source.port
                assert (
                    proof.producer_fingerprint
                    == disk.receipts[source.task_id]["fingerprint"]
                )
                expected_inputs = {
                    role: tuple(disk.artifacts[s.task_id][s.port][0] for s in refs)
                    for role, refs in disk.plan.task(source.task_id).inputs.items()
                }
                assert proof.ordered_inputs == expected_inputs
        ref = disk.artifacts[name]["out"][0]
        record = disk.records[name]["out"][0]
        assert (
            hashlib.sha256(store.read_bytes(ref.locator)).hexdigest()
            == ref.manifest_digest
        )
        assert ref.locator.startswith(
            resolution["receipt"].rsplit("/", 1)[0] + "/manifests/"
        )
        semantic = artifact_semantic_digest(
            record,
            producer_fingerprint=FingerprintResult(receipt["fingerprint"], True),
            output_port="out",
            ordered_inputs=inputs,
            asset_content_identities={},
        )
        assert semantic.reusable and semantic.value == ref.semantic_digest
        if type(record) is Product:
            assert record.produced_by.attempt_id == receipt["attempt_id"]
            assert record.produced_by.output_port == "out"
            assert record.produced_by.task_fingerprint.status is SemanticStatus.KNOWN
            assert record.produced_by.task_fingerprint.value == receipt["fingerprint"]
            assert record.producer.plugin == task.plugin_ref
            assert (
                record.producer.implementation_identity_digest.value
                == disk.run["implementations"][name]["value"]
            )
            assert (
                record.producer.execution_identity_digest.value == receipt["execution"]
            )
            assert tuple((e.role, e.artifact) for e in record.lineage) == tuple(
                (port, ref) for port in sorted(inputs) for ref in inputs[port]
            )
            assert store.read(record.provenance_ref, "started") == started
    assert (
        disk.records["assess"]["out"][0].input_refs == disk.artifacts["analyze"]["out"]
    )
    assert len(store.inventory("runs/*/attempts/*/*/result.json")) == 7
    assert len(store.inventory("runs/*/attempts/*/*/started.json")) == 7
    assert len(store.inventory("runs/*/attempts/*/*/finished.json")) == 7
    assert len(store.inventory("runs/*/resolutions/*.json")) == 7
    transitions = {name: [] for name in ORDER}
    for location in store.inventory("runs/*/transitions/*.json"):
        transition = store.read(location, "transition")
        transitions[transition["task_id"]].append(transition["state"])
    assert transitions == {name: ["running", "succeeded"] for name in ORDER}


def test_e2e05_persisted_products_attempts_lineage_receipts_agree(successful):
    _, _, disk, _, workspace = successful
    assert_persisted_chain(disk, workspace)


def produce_and_forget(workspace, *, search_label="synthetic:query"):
    harness = build_harness()
    plan = canonical_plan(harness, search_label=search_label)
    runtime = canonical_runtime(harness, workspace)
    assert_static(harness, plan, runtime)
    result = runtime.run(plan)
    assert result.status == "SUCCEEDED"
    references = tuple(weakref.ref(value) for value in (harness, plan, runtime, result))
    del harness, plan, runtime, result
    gc.collect()
    assert all(ref() is None for ref in references)


def test_e2e06_reopen_in_fresh_interpreter_without_original_objects(tmp_path):
    workspace = tmp_path / "workspace"
    produce_and_forget(workspace)
    code = """
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from integration._canonical_workflow import reopen_workspace
from integration.test_canonical_fake_e2e import assert_persisted_chain
workspace = Path(sys.argv[2])
disk = reopen_workspace(workspace)
assert_persisted_chain(disk, workspace)
print(disk.summary['status'], len(disk.artifacts))
"""
    result = subprocess.run(
        [
            sys.executable,
            "-B",
            "-I",
            "-c",
            code,
            str(Path(__file__).resolve().parents[1]),
            str(workspace),
        ],
        env={},
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "SUCCEEDED 7"


def test_e2e07_fresh_workspaces_have_equal_semantics_and_distinct_attempts(tmp_path):
    first, second = tmp_path / "one", tmp_path / "two"
    produce_and_forget(first)
    produce_and_forget(second)
    a, b = reopen_workspace(first), reopen_workspace(second)
    assert a.plan.to_json() == b.plan.to_json() and a.plan.digest == b.plan.digest
    assert a.run["run_id"] != b.run["run_id"]
    for name in ORDER:
        assert a.started[name]["attempt_id"] != b.started[name]["attempt_id"]
        assert a.started[name]["prepared"] == b.started[name]["prepared"]
        assert a.receipts[name]["fingerprint"] == b.receipts[name]["fingerprint"]
        assert (
            a.artifacts[name]["out"][0].semantic_digest
            == b.artifacts[name]["out"][0].semantic_digest
            is not None
        )
        one = record_semantic_material(a.records[name]["out"][0], {})
        two = record_semantic_material(b.records[name]["out"][0], {})
        assert one is not None and canonical_json_bytes(one) == canonical_json_bytes(
            two
        )
        assert str(tmp_path).encode() not in canonical_json_bytes(one)
        assert a.run["run_id"].encode() not in canonical_json_bytes(one)
    assert_persisted_chain(a, first)
    assert_persisted_chain(b, second)


def test_declared_search_change_propagates_through_every_artifact_identity(tmp_path):
    first, second = tmp_path / "one", tmp_path / "two"
    produce_and_forget(first)
    produce_and_forget(second, search_label="synthetic:changed-query")
    a, b = reopen_workspace(first), reopen_workspace(second)
    assert a.plan.digest != b.plan.digest
    assert (
        a.records["search"]["out"][0].selectors
        != b.records["search"]["out"][0].selectors
    )
    for name in ORDER:
        assert a.receipts[name]["fingerprint"] != b.receipts[name]["fingerprint"]
        assert (
            a.artifacts[name]["out"][0].semantic_digest
            != b.artifacts[name]["out"][0].semantic_digest
        )


def test_e2e08_cold_runtime_without_credentials_backends_network_or_external_writes(
    tmp_path,
):
    code = """
import sys, os, socket, subprocess, importlib.abc
from pathlib import Path
root = Path(sys.argv[2]).resolve()
blocked = ('insarforge.missions', 'insarforge.providers', 'insarforge.processors', 'insarforge.corrections', 'insarforge.analyzers', 'insarforge.qc', 'isce', 'isce2', 'isce3', 'gamma', 'gmtsar', 'stamps', 'mintpy')
class RejectBackend(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if any(fullname == p or fullname.startswith(p + '.') for p in blocked):
            raise AssertionError('backend import forbidden: ' + fullname)
sys.meta_path.insert(0, RejectBackend())
def forbidden(*args, **kwargs):
    raise AssertionError('network/native process forbidden')
socket.socket = forbidden
socket.create_connection = forbidden
subprocess.Popen = forbidden
def contained(path):
    if isinstance(path, (str, bytes, os.PathLike)):
        assert Path(os.fsdecode(path)).resolve().is_relative_to(root), 'write outside pytest workspace'
def audit(event, args):
    if event == 'open':
        mode, flags = args[1], args[2]
        if (isinstance(mode, str) and any(c in mode for c in 'wax+')) or (isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)):
            contained(args[0])
    elif event in ('os.mkdir', 'os.remove', 'os.rmdir'):
        contained(args[0])
    elif event == 'os.rename':
        contained(args[0]); contained(args[1])
sys.addaudithook(audit)
sys.path.insert(0, sys.argv[1])
from integration.test_canonical_fake_e2e import produce_and_forget, assert_persisted_chain
from integration._canonical_workflow import reopen_workspace
workspace = root / 'isolated'
produce_and_forget(workspace)
assert_persisted_chain(reopen_workspace(workspace), workspace)
assert not any(k == p or k.startswith(p + '.') for k in sys.modules for p in blocked)
print('ISOLATED SUCCEEDED')
"""
    result = subprocess.run(
        [
            sys.executable,
            "-B",
            "-I",
            "-c",
            code,
            str(Path(__file__).resolve().parents[1]),
            str(tmp_path),
        ],
        env={},
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ISOLATED SUCCEEDED"
