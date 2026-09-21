"""Independent P4.2 audit regressions against b82224f.

These assert frozen-contract behavior. Failure on the audited baseline is expected.
Run using an editable checkout: python -m pytest -q -s <this file>.
The repository's existing tiny dummy operations are fixture utilities only.
"""

import hashlib
import json
import sys
from dataclasses import replace
from pathlib import Path

import pytest
from test_fingerprint_cache import (
    ALLOCATION,
    PLUGIN,
    PROFILE,
    SCHEMA,
    Prepared,
    known,
    prepared,
)
from test_runtime_execution import (
    Codec,
    Dummy,
    Validator,
    fixture,
    records,
    run_ids,
    t,
)

import insarforge
from insarforge.contracts.context import ResourceAllocation
from insarforge.contracts.errors import WorkflowStateError
from insarforge.contracts.execution import OutputRef, RestartSafety, WorkflowPlan
from insarforge.contracts.identity import PluginDescriptor
from insarforge.contracts.operations import (
    ArtifactDraft,
    InputPortContract,
    OperationBinding,
    OutputPortContract,
    TaskOutcome,
)
from insarforge.contracts.record_serialization import record_from_bytes, record_to_bytes
from insarforge.contracts.values import ArtifactRef, freeze_json
from insarforge.core.exceptions import InSARForgeError
from insarforge.core.fingerprints import execution_identity
from insarforge.core.registry import PluginRegistry
from insarforge.core.runtime import Runtime
from insarforge.products.semantics import SemanticStatus, SemanticValue
from insarforge.products.validation import (
    ProductValidationReport,
    ValidationIssue,
    ValidationIssueKind,
)

REPO = Path(insarforge.__file__).resolve().parents[2]


def emit(label, **values):
    print(json.dumps({"probe": label, **values}, sort_keys=True))


def test_R01_external_stale_semantic_digest_cannot_reuse(tmp_path):
    rt, dummy = fixture(tmp_path)
    source = rt.run(WorkflowPlan(1, (t("source"),)))
    original_ref = source.outputs["source"]["out"][0]
    original_bytes = rt.store.read_bytes(original_ref.locator)

    def consumer(ref):
        return WorkflowPlan(1, (t("consumer", (ref,)),), (ref,))

    first = rt.run(
        consumer(original_ref),
        external_manifests={original_ref.record_id: original_bytes},
    )
    product = record_from_bytes(original_ref, original_bytes)
    changed = replace(
        product, semantic_metadata={"label": known("scientifically-changed")}
    )
    changed_bytes = record_to_bytes(changed)
    changed_ref = replace(
        original_ref, manifest_digest=hashlib.sha256(changed_bytes).hexdigest()
    )
    # Manifest and byte integrity agree, but the supplied semantic digest is stale.
    try:
        second = rt.run(
            consumer(changed_ref),
            external_manifests={changed_ref.record_id: changed_bytes},
        )
    except InSARForgeError:
        emit("R01", status="REJECTED_WITH_DOMAIN_ERROR")
        return
    emit(
        "R01",
        status=second.status,
        consumer_invokes=dummy.counts.get("consumer"),
        identical_output=first.outputs == second.outputs,
    )
    assert second.status != "SUCCEEDED" or dummy.counts["consumer"] == 2, (
        "Changed external semantic content was accepted under a stale semantic digest and old result reused"
    )


class SharingDummy(Dummy):
    def invoke(self, plugin, prep, inputs, parameters, context):
        outcome = super().invoke(plugin, prep, inputs, parameters, context)
        if inputs["in"]:
            # Legitimate, explicitly declared immutable upstream geometry/data asset.
            draft = outcome.outputs["out"][0].value
            draft = replace(draft, assets=inputs["in"][0].value.assets)
            return TaskOutcome({"out": (ArtifactDraft(SCHEMA, draft),)}, ())
        return outcome


def test_R02_readonly_upstream_asset_reference_is_allowed(tmp_path):
    rt, dummy = fixture(tmp_path, SharingDummy())
    result = rt.run(WorkflowPlan(1, (t("a"), t("b", (OutputRef("a", "out"),)))))
    emit(
        "R02",
        status=result.status,
        states={k: v.value for k, v in result.states.items()},
    )
    assert result.status == "SUCCEEDED", (
        "Read-only declared upstream asset reuse is not an overwrite"
    )


def test_R03_resume_cache_only_run_checks_old_execution_identity(tmp_path):
    rt, dummy = fixture(tmp_path)
    plan = WorkflowPlan(1, (t(),))
    rt.run(plan)
    cached_run = rt.run(plan)
    assert not rt.store.inventory(f"runs/{cached_run.run_id}/attempts/*/*/started.json")
    dummy.identity = prepared(
        settings={"precision": "double", "threads": 1, "seed": 123}
    )
    refused = False
    try:
        resumed = rt.resume(cached_run.run_id)
        status = resumed.status
    except WorkflowStateError as exc:
        refused = "REPLAN" in str(exc)
        status = str(exc)
    emit("R03", refused=refused, status=status, invokes=dummy.counts["a"])
    assert refused, (
        "Cache-only source run lost its adopted recipe/execution identity during resume"
    )


def test_R04_unrelated_corrupt_receipt_does_not_block_new_task(tmp_path):
    rt, dummy = fixture(tmp_path)
    first = rt.run(WorkflowPlan(1, (t("a"),)))
    receipt_path = records(rt, "receipt")[0][0]
    rt.store.path(receipt_path).write_bytes(b'{"damaged":true}')
    # New independent computation, with default conservative UNSAFE restart policy.
    new = replace(t("independent"), restart_safety=RestartSafety.UNSAFE)
    result = rt.run(WorkflowPlan(1, (new,)))
    emit(
        "R04",
        old=first.status,
        status=result.status,
        invoked=dummy.counts.get("independent", 0),
    )
    assert result.status == "SUCCEEDED" and dummy.counts.get("independent") == 1, (
        "Corruption of an unrelated recipe poisoned independent first execution"
    )


def test_R05_handled_interruption_is_persisted_before_return(tmp_path):
    rt, dummy = fixture(tmp_path)
    dummy.failures = {"a": [KeyboardInterrupt()]}
    with pytest.raises(KeyboardInterrupt):
        rt.run(WorkflowPlan(1, (t(),)))
    rid = run_ids(rt)[0]
    status = rt.store.status(rid)
    finished = records(rt, "finished")
    emit(
        "R05",
        status=status,
        finished_count=len(finished),
        lock_released=not rt.store._locked,
    )
    assert status == "INTERRUPTED", (
        "Handled KeyboardInterrupt released the lock but left run RUNNING"
    )
    assert any(f["outcome"] == "interrupted" for _, f in finished)


def test_R06_persisted_preparation_reconstructs_execution_identity(tmp_path):
    rt, dummy = fixture(tmp_path)
    evidence = ArtifactRef(
        "evidence:calibration",
        "schema:evidence",
        1,
        "e" * 64,
        "f" * 64,
        "evidence:input",
    )
    identity = dummy.identity.semantic_execution_identity
    dummy.identity = Prepared(
        SemanticValue(
            identity.status, identity.value, identity.reason_code, (evidence,)
        ),
        freeze_json({"plan": "explicit-operation-preparation"}),
    )
    result = rt.run(WorkflowPlan(1, (t(),)))
    assert result.status == "SUCCEEDED"
    started = records(rt, "started")[0][1]
    saved = started["prepared"]
    # Baseline only persists these three fields. No execution evidence refs anywhere in the start record.
    restored = Prepared(
        SemanticValue(
            SemanticStatus(saved["status"]),
            freeze_json(saved["value"]),
            saved["reason_code"],
            (),
        )
    )
    actual = execution_identity(restored, ALLOCATION).value
    emit(
        "R06",
        persisted_fields=sorted(saved),
        identity_matches=actual == started["execution"],
        evidence_saved="evidence:calibration" in json.dumps(started),
    )
    persisted = b"\n".join(
        p.read_bytes() for p in rt.store.path("runs/" + result.run_id).rglob("*.json")
    )
    assert b"evidence:calibration" in persisted, (
        "Execution identity evidence refs were omitted from run provenance"
    )


def test_R07_unsafe_external_bytes_not_persisted_before_validation(tmp_path):
    rt, dummy = fixture(tmp_path)
    # Synthetic marker, never a real credential. Invalid record must be rejected before persistence.
    raw = b'{"password":"AUDIT_SYNTHETIC_NEVER_A_REAL_SECRET_7392"}'
    ref = ArtifactRef(
        "external:bad",
        "insarforge:product",
        2,
        None,
        hashlib.sha256(raw).hexdigest(),
        "external:caller",
    )
    try:
        result = rt.run(
            WorkflowPlan(1, (t("consumer", (ref,)),), (ref,)),
            external_manifests={ref.record_id: raw},
        )
        status = result.status
    except InSARForgeError:
        status = "REJECTED_WITH_DOMAIN_ERROR"
    leaked = [
        p.relative_to(rt.store.area).as_posix()
        for p in rt.store.area.rglob("*.json")
        if b"AUDIT_SYNTHETIC_NEVER_A_REAL_SECRET_7392" in p.read_bytes()
    ]
    emit("R07", status=status, leaked_files=leaked, invokes=dummy.counts)
    assert not leaked, (
        "Rejected external record was copied into durable provenance before safety validation"
    )


class UnverifiedValidator(Validator):
    def validate(self, value, schema, profile):
        return ProductValidationReport(
            (
                ValidationIssue(
                    ValidationIssueKind.UNVERIFIED,
                    "profile:sign-not-verified",
                    "profile",
                    {},
                ),
            )
        )


def runtime_with_validator(tmp_path, validator, dummy=None):
    dummy = dummy or Dummy()
    binding = OperationBinding(
        "synthetic:op",
        1,
        "synthetic:parameters",
        1,
        (InputPortContract("in", SCHEMA, PROFILE, 0, None, Codec(), validator),),
        (OutputPortContract("out", SCHEMA, PROFILE, 1, Codec(), validator),),
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
    return Runtime(
        registry,
        tmp_path / "workspace",
        budget=ALLOCATION,
        implementation_files={PLUGIN: {"dummy.py": Path(__file__).resolve()}},
    ), dummy


def test_R08_unverified_required_output_profile_cannot_commit_success(tmp_path):
    rt, dummy = runtime_with_validator(tmp_path, UnverifiedValidator())
    try:
        result = rt.run(WorkflowPlan(1, (t(),)))
        status = result.status
    except InSARForgeError:
        status = "REJECTED_WITH_DOMAIN_ERROR"
    emit(
        "R08",
        status=status,
        receipts=len(records(rt, "receipt")),
        cache_indices=len(rt.store.inventory("cache/*/*.json")),
    )
    assert status != "SUCCEEDED", (
        "Required scientific/profile validation UNVERIFIED was treated as complete output validation"
    )
    assert not records(rt, "receipt")


def test_control_unchanged_recipe_reuses_valid_committed_output(tmp_path):
    rt, dummy = fixture(tmp_path)
    plan = WorkflowPlan(1, (t(),))
    first, second = rt.run(plan), rt.run(plan)
    assert first.status == second.status == "SUCCEEDED"
    assert first.outputs == second.outputs and dummy.counts["a"] == 1


def test_control_repeated_inputs_keep_lineage_multiplicity(tmp_path):
    rt, dummy = fixture(tmp_path)
    result = rt.run(
        WorkflowPlan(
            1, (t("a"), t("b", (OutputRef("a", "out"), OutputRef("a", "out"))))
        )
    )
    assert result.status == "SUCCEEDED"
    ref = result.outputs["b"]["out"][0]
    product = record_from_bytes(ref, rt.store.read_bytes(ref.locator))
    assert len(product.lineage) == 2 and product.lineage[0] == product.lineage[1]


def test_control_weak_producer_outputs_are_not_reused(tmp_path):
    rt, dummy = fixture(tmp_path)
    dummy.weak_asset = True
    plan = WorkflowPlan(1, (t(),))
    first, second = rt.run(plan), rt.run(plan)
    assert first.status == second.status == "SUCCEEDED"
    assert first.outputs["a"]["out"][0].semantic_digest is None
    assert dummy.counts["a"] == 2


def exported(rt, ref):
    from insarforge.core._runtime_inputs import local_evidence

    return ref, rt.store.read_bytes(ref.locator), local_evidence(rt.store, ref)


def consume(rt, ref, raw, proof=None, name="consumer"):
    plan = WorkflowPlan(1, (t(name, (ref,)),), (ref,))
    return rt.run(
        plan,
        external_manifests={ref.record_id: raw},
        external_evidence={} if proof is None else {ref.record_id: proof},
    )


def test_verified_external_cross_workspace_and_unknown_path(tmp_path):
    producer, _ = fixture(tmp_path / "producer")
    made = producer.run(WorkflowPlan(1, (t("source"),)))
    ref, raw, proof = exported(producer, made.outputs["source"]["out"][0])
    consumer, dummy = fixture(tmp_path / "consumer")
    first = consume(consumer, ref, raw, proof)
    second = consume(consumer, ref, raw, proof)
    assert first.status == second.status == "SUCCEEDED"
    assert dummy.counts["consumer"] == 1 and first.outputs == second.outputs
    # No producer registration lookup: a separately supplied exact evidence record
    # contains sufficient recipe/ordered inputs for recomputation.
    unknown, other = fixture(tmp_path / "unknown")
    a = consume(unknown, ref, raw)
    b = consume(unknown, ref, raw)
    assert a.status == b.status == "SUCCEEDED" and other.counts["consumer"] == 2
    assert a.outputs["consumer"]["out"][0].semantic_digest is None
    product = record_from_bytes(
        a.outputs["consumer"]["out"][0],
        unknown.store.read_bytes(a.outputs["consumer"]["out"][0].locator),
    )
    assert product.lineage[0].artifact == ref  # never replace original identity


def test_explicit_evidence_recomputes_metadata_and_asset_identity(tmp_path):
    from insarforge.provenance.runtime_evidence import ArtifactEvidence

    producer, _ = fixture(tmp_path / "producer")
    made = producer.run(WorkflowPlan(1, (t("source"),)))
    ref, raw, proof = exported(producer, made.outputs["source"]["out"][0])
    product = record_from_bytes(ref, raw)
    changed = replace(product, semantic_metadata={"label": known("changed")})
    changed_raw = record_to_bytes(changed)
    changed_ref = replace(ref, manifest_digest=hashlib.sha256(changed_raw).hexdigest())
    contradictory = ArtifactEvidence(
        changed_ref, proof.producer_fingerprint, proof.output_port, proof.ordered_inputs
    )
    rt, dummy = fixture(tmp_path / "consumer")
    result = consume(rt, changed_ref, changed_raw, contradictory)
    assert result.status == "FAILED" and dummy.counts == {}
    # Current bytes, not stat/path, are re-observed.
    Path(product.assets[0].location.value).write_bytes(b"asset changed")
    assert consume(rt, ref, raw, proof).status == "FAILED" and dummy.counts == {}


def test_equivalent_distinct_external_refs_preserve_original_cached_lineage(tmp_path):
    from insarforge.provenance.runtime_evidence import ArtifactEvidence

    producer, _ = fixture(tmp_path / "producer")
    made = producer.run(WorkflowPlan(1, (t("source"),)))
    ref, raw, proof = exported(producer, made.outputs["source"]["out"][0])
    product = record_from_bytes(ref, raw)
    other_raw = record_to_bytes(replace(product, product_id="record:separate"))
    other_ref = replace(
        ref,
        record_id="record:separate",
        manifest_digest=hashlib.sha256(other_raw).hexdigest(),
        locator="external:separate",
    )
    other_proof = ArtifactEvidence(
        other_ref, proof.producer_fingerprint, proof.output_port, proof.ordered_inputs
    )
    rt, dummy = fixture(tmp_path / "consumer")
    first = consume(rt, ref, raw, proof)
    second = consume(rt, other_ref, other_raw, other_proof)
    assert first.outputs == second.outputs and dummy.counts["consumer"] == 1
    output = second.outputs["consumer"]["out"][0]
    assert (
        record_from_bytes(output, rt.store.read_bytes(output.locator))
        .lineage[0]
        .artifact
        == ref
    )


def test_shared_assets_cache_resume_and_mutation(tmp_path):
    rt, dummy = fixture(tmp_path, SharingDummy())
    plan = WorkflowPlan(1, (t("a"), t("b", (OutputRef("a", "out"),))))
    first = rt.run(plan)
    second = rt.run(plan)
    third = rt.resume(second.run_id)
    assert first.status == second.status == third.status == "SUCCEEDED"
    assert dummy.counts == {"a": 1, "b": 1}
    a = first.outputs["a"]["out"][0]
    b = first.outputs["b"]["out"][0]
    pa = record_from_bytes(a, rt.store.read_bytes(a.locator))
    pb = record_from_bytes(b, rt.store.read_bytes(b.locator))
    assert pa.assets == pb.assets
    original = Path(pa.assets[0].location.value).read_bytes()
    Path(pa.assets[0].location.value).write_bytes(b"damaged")
    try:
        result = rt.resume(third.run_id)
        assert result.status in ("FAILED", "SUCCEEDED")
        if result.status == "SUCCEEDED":
            assert result.outputs != third.outputs
            assert dummy.counts["a"] == 2 and dummy.counts["b"] == 2
    except WorkflowStateError:
        pass
    assert Path(pa.assets[0].location.value).read_bytes() != original


@pytest.mark.parametrize("restart", [RestartSafety.UNSAFE, RestartSafety.RESTARTABLE])
def test_matching_corrupt_receipt_respects_restart_policy(tmp_path, restart):
    rt, dummy = fixture(tmp_path)
    task = replace(t(), restart_safety=restart)
    plan = WorkflowPlan(1, (task,))
    rt.run(plan)
    old = records(rt, "receipt")[0][0]
    rt.store.path(old).write_bytes(b"broken")
    result = rt.run(plan)
    assert rt.store.path(old).read_bytes() == b"broken"
    if restart is RestartSafety.UNSAFE:
        assert result.status == "FAILED" and dummy.counts["a"] == 1
    else:
        assert result.status == "SUCCEEDED" and dummy.counts["a"] == 2
        again = rt.run(plan)
        assert again.status == "SUCCEEDED" and dummy.counts["a"] == 2


def test_cache_only_and_mixed_resume_chain_identity(tmp_path):
    rt, dummy = fixture(tmp_path)
    rt.run(WorkflowPlan(1, (t("a"),)))
    plan = WorkflowPlan(1, (t("a"), t("b")))
    mixed = rt.run(plan)
    cached = rt.resume(mixed.run_id)
    resumed = rt.resume(cached.run_id)
    assert mixed.status == cached.status == resumed.status == "SUCCEEDED"
    assert dummy.counts == {"a": 1, "b": 1}
    dummy.identity = prepared(settings={"seed": 999})
    with pytest.raises(WorkflowStateError, match="REPLAN"):
        rt.resume(resumed.run_id)


def test_tampered_resolution_receipt_binding_refused(tmp_path):
    rt, _ = fixture(tmp_path)
    rt.run(WorkflowPlan(1, (t("other"),)))
    cached = rt.run(WorkflowPlan(1, (t(),)))
    location = rt.store.inventory(f"runs/{cached.run_id}/resolutions/*.json")[0]
    wire = json.loads(rt.store.read_bytes(location))
    other = [p for p, r in records(rt, "receipt") if r["task_id"] == "other"][0]
    wire["payload"]["receipt"] = other
    rt.store.path(location).write_text(json.dumps(wire))
    with pytest.raises(WorkflowStateError, match="IDENTITY|BINDING"):
        rt.resume(cached.run_id)


def test_persisted_preparation_really_reconstructs_and_v1_refused(tmp_path):
    from insarforge.contracts.errors import WorkspaceError
    from insarforge.provenance.runtime_evidence import PreparationEvidence
    from insarforge.provenance.workspace import parse_record

    rt, dummy = fixture(tmp_path)
    ref = ArtifactRef(
        "evidence:test", "schema:evidence", 1, "a" * 64, "b" * 64, "synthetic:evidence"
    )
    value = dummy.identity.semantic_execution_identity
    dummy.identity = Prepared(
        SemanticValue(value.status, value.value, None, (ref,)),
        freeze_json({"configuration": "explicit"}),
    )
    assert rt.run(WorkflowPlan(1, (t(),))).status == "SUCCEEDED"
    location, start = records(rt, "started")[0]
    restored = PreparationEvidence.from_dict(start["prepared"])
    assert restored.semantic_execution_identity.evidence_refs == (ref,)
    assert execution_identity(restored, ALLOCATION).value == start["execution"]
    wire = json.loads(rt.store.read_bytes(location))
    wire["schema_version"] = 1
    with pytest.raises(WorkspaceError, match="VERSION"):
        parse_record(json.dumps(wire).encode(), "started")
    # A changed execution evidence digest cannot silently validate a receipt.
    wire["schema_version"] = 2
    wire["payload"]["prepared"]["evidence_refs"][0]["semantic_digest"] = "c" * 64
    rt.store.path(location).write_text(json.dumps(wire))
    from insarforge.core._runtime_artifacts import candidate_from_receipt

    with pytest.raises(InSARForgeError, match="EXECUTION_EVIDENCE"):
        candidate_from_receipt(rt.store, records(rt, "receipt")[0][0])


def test_unverified_input_rejected_before_invoke(tmp_path):
    producer, _ = fixture(tmp_path / "producer")
    made = producer.run(WorkflowPlan(1, (t(),)))
    ref, raw, proof = exported(producer, made.outputs["a"]["out"][0])
    rt, dummy = runtime_with_validator(tmp_path / "consumer", UnverifiedValidator())
    assert consume(rt, ref, raw, proof).status == "FAILED"
    assert dummy.counts == {} and not records(rt, "receipt")


def test_handled_multiworker_interrupt_waits_and_closes(tmp_path):
    import threading

    from insarforge.contracts.execution import RetryPolicy

    rt, dummy = fixture(tmp_path, max_workers=2, budget=ResourceAllocation(2, None, 0))
    entered = threading.Barrier(2)
    stopped = threading.Event()

    def hook(context, inputs):
        entered.wait(timeout=5)
        if context.task_id == "a":
            raise KeyboardInterrupt()
        for _ in range(500):
            if context.cancellation_requested():
                stopped.set()
                return
            threading.Event().wait(0.01)
        pytest.fail("cooperative cancellation not requested")

    dummy.hook = hook
    plan = WorkflowPlan(
        1,
        (
            replace(t("a"), retry_policy=RetryPolicy(2, 0)),
            replace(t("b"), retry_policy=RetryPolicy(2, 0)),
        ),
    )
    with pytest.raises(KeyboardInterrupt):
        rt.run(plan)
    assert stopped.is_set() and not rt.store._locked
    rid = run_ids(rt)[0]
    assert rt.store.status(rid) == "INTERRUPTED"
    assert len(records(rt, "finished")) == 2
    assert all(f["outcome"] == "interrupted" for _, f in records(rt, "finished"))
    dummy.hook = None
    resumed = rt.resume(rid)
    assert resumed.status == "SUCCEEDED"
    assert dummy.counts == {"a": 2, "b": 2}


@pytest.mark.parametrize("point", ["before_receipt", "after_receipt"])
def test_handled_commit_window_preserves_facts(tmp_path, point):
    rt, dummy = fixture(tmp_path)

    def fault(p):
        if p == point:
            raise KeyboardInterrupt()

    rt.fault = fault
    with pytest.raises(KeyboardInterrupt):
        rt.run(WorkflowPlan(1, (t(),)))
    rid = run_ids(rt)[0]
    assert rt.store.status(rid) == "INTERRUPTED"
    outcome = records(rt, "finished")[0][1]["outcome"]
    assert outcome == ("succeeded" if point == "after_receipt" else "interrupted")
    before = {p: p.read_bytes() for p in rt.store.path("runs/" + rid).rglob("*.json")}
    rt.fault = lambda p: None
    result = rt.resume(rid)
    assert all(p.read_bytes() == raw for p, raw in before.items())
    assert result.status == ("SUCCEEDED" if point == "after_receipt" else "FAILED")


@pytest.mark.parametrize("point", ["before_receipt", "after_receipt"])
def test_real_process_loss_recovers_in_bounded_subprocess(tmp_path, point):
    import subprocess
    import textwrap

    script = textwrap.dedent("""
        import os, sys
        from pathlib import Path
        from dataclasses import replace
        import insarforge
        sys.path.insert(0, str(Path(insarforge.__file__).resolve().parents[2] / "tests/contracts"))
        from test_runtime_execution import fixture, t, WorkflowPlan
        from insarforge.contracts.execution import RetryPolicy
        runtime, dummy = fixture(Path(sys.argv[1]))
        runtime.fault = lambda event: os._exit(73) if event == sys.argv[2] else None
        runtime.run(WorkflowPlan(1, (replace(t(), retry_policy=RetryPolicy(2, 0)),)))
    """)
    process = subprocess.run(
        [sys.executable, "-B", "-I", "-c", script, str(tmp_path), point],
        capture_output=True,
        timeout=20,
        cwd=REPO,
    )
    assert process.returncode == 73, process.stderr
    rt, dummy = fixture(tmp_path)
    rid = run_ids(rt)[0]
    assert rt.store.status(rid) == "RUNNING"  # true death cannot synchronously finalize
    old = {p: p.read_bytes() for p in rt.store.path("runs/" + rid).rglob("*.json")}
    result = rt.resume(rid)
    assert result.status == "SUCCEEDED" and rt.store.status(rid) == "INTERRUPTED"
    assert all(p.read_bytes() == raw for p, raw in old.items())
    assert dummy.counts.get("a", 0) == (0 if point == "after_receipt" else 1)
    assert rt.resume(result.run_id).status == "SUCCEEDED"


@pytest.mark.parametrize(
    "kind", [ValidationIssueKind.ERROR, ValidationIssueKind.UNVERIFIED]
)
def test_required_output_obligations_require_affirmative_verification(tmp_path, kind):
    class Required(Validator):
        def validate(self, value, schema, profile):
            return ProductValidationReport(
                (ValidationIssue(kind, "profile:required", "profile", {}),)
            )

    rt, dummy = runtime_with_validator(tmp_path, Required())
    assert rt.run(WorkflowPlan(1, (t(),))).status == "FAILED"
    assert dummy.counts["a"] == 1 and not records(rt, "receipt")


def test_weak_external_assets_execute_without_promoting_identity(tmp_path):
    producer, d = fixture(tmp_path / "producer")
    d.weak_asset = True
    source = producer.run(WorkflowPlan(1, (t(),)))
    ref, raw, proof = exported(producer, source.outputs["a"]["out"][0])
    rt, dummy = fixture(tmp_path / "consumer")
    first = consume(rt, ref, raw, proof)
    second = consume(rt, ref, raw, proof)
    assert first.status == second.status == "SUCCEEDED"
    assert dummy.counts["consumer"] == 2
    assert first.outputs["consumer"]["out"][0].semantic_digest is None


def test_preparation_requires_object_and_preserves_unknown_identity(tmp_path):
    rt, dummy = fixture(tmp_path)
    dummy.identity = Prepared(dummy.identity.semantic_execution_identity, None)
    assert rt.run(WorkflowPlan(1, (t(),))).status == "FAILED"
    assert dummy.counts == {} and not records(rt, "started")


def test_artifact_evidence_is_immutable_and_bound_to_manifest(tmp_path):
    from insarforge.provenance.runtime_evidence import ArtifactEvidence

    producer, _ = fixture(tmp_path / "producer")
    result = producer.run(WorkflowPlan(1, (t(),)))
    ref, raw, proof = exported(producer, result.outputs["a"]["out"][0])
    source = dict(proof.ordered_inputs)
    owned = ArtifactEvidence(ref, proof.producer_fingerprint, proof.output_port, source)
    source["extra"] = (ref,)
    assert "extra" not in owned.ordered_inputs
    with pytest.raises(TypeError):
        owned.ordered_inputs["extra"] = (ref,)
    rt, _ = fixture(tmp_path / "consumer")
    wrong = replace(owned, artifact=replace(ref, manifest_digest="c" * 64))
    with pytest.raises(InSARForgeError, match="BINDING"):
        consume(rt, ref, raw, wrong)
    assert not rt.store.inventory("runs/*/external/*.json")


def test_shared_and_cached_assets_are_observed_without_fsync(tmp_path, monkeypatch):
    import os

    rt, dummy = fixture(tmp_path, SharingDummy())
    first = rt.run(WorkflowPlan(1, (t("a"),)))
    ref = first.outputs["a"]["out"][0]
    product = record_from_bytes(ref, rt.store.read_bytes(ref.locator))
    asset = Path(product.assets[0].location.value)
    original = os.fsync

    def checked(fd):
        assert Path(os.readlink(f"/proc/self/fd/{fd}")) != asset
        return original(fd)

    monkeypatch.setattr(os, "fsync", checked)
    plan = WorkflowPlan(1, (t("a"), t("b", (OutputRef("a", "out"),))))
    assert rt.run(plan).status == "SUCCEEDED"
    assert rt.run(plan).status == "SUCCEEDED"
    assert dummy.counts == {"a": 1, "b": 1}


def test_handled_interrupt_after_finished_preserves_success_projection(
    tmp_path, monkeypatch
):
    rt, _ = fixture(tmp_path)
    write = rt.store.write

    def interrupted(relative, kind, payload):
        result = write(relative, kind, payload)
        if kind == "finished":
            raise KeyboardInterrupt()
        return result

    monkeypatch.setattr(rt.store, "write", interrupted)
    with pytest.raises(KeyboardInterrupt):
        rt.run(WorkflowPlan(1, (t(),)))
    rid = run_ids(rt)[0]
    summary = rt.store.read("runs/" + rid + "/summary.json", "summary")
    assert summary["status"] == "INTERRUPTED"
    assert summary["states"] == {"a": "succeeded"}
    assert summary["completion_order"] == ["a"]
    assert records(rt, "finished")[0][1]["outcome"] == "succeeded"
