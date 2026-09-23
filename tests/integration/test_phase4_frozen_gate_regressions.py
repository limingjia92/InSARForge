"""Runtime proofs for frozen FZ-G27/G28/G29/G34; all values are synthetic."""

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from insarforge.contracts.execution import CachePolicy, OutputRef, WorkflowPlan
from insarforge.contracts.record_serialization import record_from_bytes
from insarforge.contracts.records import CatalogSnapshot
from insarforge.core._runtime_inputs import local_evidence
from insarforge.products.models import Product
from insarforge.products.semantics import SemanticStatus
from insarforge.provenance.workspace import Workspace, key

from ._canonical_workflow import canonical_plan, reopen_workspace
from ._phase4_gate_fixtures import composition, observe, runtime


def producer_plan(harness, label="synthetic:layout-one"):
    base = canonical_plan(harness)
    return WorkflowPlan(
        1,
        (
            base.task("search"),
            replace(base.task("acquire"), semantic_parameters={"label": label}),
        ),
    )


def consumer_plan(harness, ref, operation="analyze", label="synthetic:consume"):
    task = replace(
        canonical_plan(harness).task(operation),
        inputs={"source": (ref,)},
        semantic_parameters={"label": label},
    )
    return WorkflowPlan(1, (task,), (ref,))


def external(store, ref):
    proof = local_evidence(store, ref)
    assert proof is not None
    return {
        "external_manifests": {ref.record_id: store.read_bytes(ref.locator)},
        "external_evidence": {ref.record_id: proof},
    }


def hashes(store, ref, product):
    paths = [store.path(ref.locator)] + [Path(a.location.value) for a in product.assets]
    return {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def assert_lineage(disk, task, ref):
    product = disk.records[task]["out"][0]
    assert type(product) is Product
    assert tuple((entry.role, entry.artifact) for entry in product.lineage) == (
        ("source", ref),
    )
    assert product.produced_by.attempt_id == disk.receipts[task]["attempt_id"]
    return product


def failed_without_receipt(workspace, result, task):
    assert result.status == "FAILED"
    store = Workspace(workspace)
    resolution = store.read(
        "runs/" + result.run_id + "/resolutions/" + key(task) + ".json", "resolution"
    )
    assert resolution["state"] == "failed" and resolution["receipt"] is None
    assert task not in result.outputs
    assert not store.inventory("cache/**/*.json")
    assert not store.inventory("runs/" + result.run_id + "/attempts/*/*/result.json")
    return resolution


def test_fz_g27_native_layout_variants_are_consumed_through_product(tmp_path):
    observations, paths = [], []
    for label in ("synthetic:layout-one", "synthetic:layout-two"):
        harness, implementation = composition()
        plan = producer_plan(harness, label)
        analyzer = replace(
            canonical_plan(harness).task("analyze"),
            inputs={"source": (OutputRef("acquire", "out"),)},
        )
        plan = WorkflowPlan(1, plan.tasks + (analyzer,))
        workspace = tmp_path / label.replace(":", "-")
        result = runtime(harness, implementation, workspace).run(plan)
        assert result.status == "SUCCEEDED"
        disk = reopen_workspace(workspace)
        source = disk.records["acquire"]["out"][0]
        output = assert_lineage(disk, "analyze", disk.artifacts["acquire"]["out"][0])
        observations.append(output.semantic_metadata["synthetic:observations"].value)
        paths.append(source.assets[0].location.value)
        assert harness.controls.journal.count("business", "analyze", "analyze") == 1
        assert json.loads(Path(paths[-1]).read_text()) == {"a": "toy-A", "b": "toy-B"}
        assert (
            source.assets[0].integrity.digest
            == hashlib.sha256(Path(paths[-1]).read_bytes()).hexdigest()
        )
    assert paths[0] != paths[1]
    assert paths[0].endswith("/private/one/container.json")
    assert paths[1].endswith("/different/deep/two/container.json")
    assert observations[0] == observations[1]
    assert tuple(o["payload"] for o in observations[0]) == ("toy-A", "toy-B")


@pytest.mark.parametrize("unknown_sign", [False, True])
def test_fz_g28_layer_semantics_and_known_sign_consumer_gate(tmp_path, unknown_sign):
    harness, implementation = composition(require_sign=True)
    source_workspace = tmp_path / "producer"
    label = "synthetic:unknown-sign" if unknown_sign else "synthetic:layout-one"
    source_result = runtime(harness, implementation, source_workspace).run(
        producer_plan(harness, label)
    )
    assert source_result.status == "SUCCEEDED"
    disk = reopen_workspace(source_workspace)
    ref = disk.artifacts["acquire"]["out"][0]
    source = disk.records["acquire"]["out"][0]
    assert len(source.assets) == 1 and len(source.layers) == len(source.geometries) == 2
    assert {layer.asset_id for layer in source.layers} == {source.assets[0].asset_id}
    assert tuple(layer.selector.selector_string for layer in source.layers) == (
        "a",
        "b",
    )
    assert tuple(layer.unit.value.unit_id for layer in source.layers) == (
        "synthetic:unit-a",
        "synthetic:unit-b",
    )
    assert tuple(g.grid_definition.value.format_id for g in source.geometries) == (
        "synthetic:grid-a",
        "synthetic:grid-b",
    )
    assert all(
        layer.sign.status
        is (SemanticStatus.UNKNOWN if unknown_sign else SemanticStatus.KNOWN)
        for layer in source.layers
    )
    workspace = tmp_path / "consumer"
    result = runtime(harness, implementation, workspace).run(
        consumer_plan(harness, ref), **external(Workspace(source_workspace), ref)
    )
    if unknown_sign:
        resolution = failed_without_receipt(workspace, result, "analyze")
        assert resolution["error_code"]
        assert harness.controls.journal.count("invoke", "analyze", "analyze") == 0
        assert harness.controls.journal.count("business", "analyze", "analyze") == 0
    else:
        assert result.status == "SUCCEEDED"
        output = assert_lineage(reopen_workspace(workspace), "analyze", ref)
        assert output.semantic_metadata["synthetic:observations"].value == tuple(
            observe(source)
        )
        call = next(
            c
            for c in harness.controls.journal.snapshot()
            if c.stage == "business" and c.operation == "analyze"
        )
        assert call.request.product_inputs["source"][0].value == source
        assert harness.controls.journal.count("business", "analyze", "analyze") == 1


@pytest.mark.parametrize("alias", [False, True])
def test_fz_g29_correction_owns_new_asset_preserves_input_and_rejects_alias(
    tmp_path, alias
):
    harness, implementation = composition()
    producer_workspace = tmp_path / "producer"
    result = runtime(harness, implementation, producer_workspace).run(
        producer_plan(harness)
    )
    assert result.status == "SUCCEEDED"
    source_disk = reopen_workspace(producer_workspace)
    ref = source_disk.artifacts["acquire"]["out"][0]
    source = source_disk.records["acquire"]["out"][0]
    source_store = Workspace(producer_workspace)
    before = hashes(source_store, ref, source)
    workspace = tmp_path / "correction"
    plan = consumer_plan(
        harness, ref, "correct", "synthetic:alias" if alias else "synthetic:correct"
    )
    plan = replace(
        plan, tasks=(replace(plan.task("correct"), cache_policy=CachePolicy.AUTO),)
    )
    result = runtime(harness, implementation, workspace).run(
        plan, **external(source_store, ref)
    )
    assert hashes(source_store, ref, source) == before
    assert harness.controls.journal.count("business", "correct", "correct") == 1
    if alias:
        assert (
            failed_without_receipt(workspace, result, "correct")["error_code"]
            == "OUTPUT_INVALID"
        )
    else:
        assert result.status == "SUCCEEDED"
        output = assert_lineage(reopen_workspace(workspace), "correct", ref)
        assert output.product_id != source.product_id
        assert (
            output.assets[:-1] == source.assets and output.layers[:-1] == source.layers
        )
        assert output.geometries == source.geometries
        corrected = output.assets[-1]
        assert corrected.location != source.assets[0].location
        assert output.layers[-1].asset_id == corrected.asset_id
        assert output.layers[-1].layer_id not in {
            layer.layer_id for layer in source.layers
        }
        assert json.loads(Path(corrected.location.value).read_text()) == {
            "a": "corrected:toy-A"
        }
        assert (
            corrected.integrity.digest
            == hashlib.sha256(Path(corrected.location.value).read_bytes()).hexdigest()
        )


def test_fz_g34_catalog_drives_second_immutable_plan(tmp_path):
    harness, implementation = composition()
    base = canonical_plan(harness)
    plan_a = WorkflowPlan(1, (base.task("search"),))
    digest_a = plan_a.digest
    workspace_a = tmp_path / "discovery"
    result_a = runtime(harness, implementation, workspace_a).run(plan_a)
    assert result_a.status == "SUCCEEDED"
    disk_a = reopen_workspace(workspace_a)
    ref = disk_a.artifacts["search"]["out"][0]
    store_a = Workspace(workspace_a)
    original_plan = store_a.read_bytes("runs/" + result_a.run_id + "/plan.json")
    catalog = record_from_bytes(ref, store_a.read_bytes(ref.locator))
    assert type(catalog) is CatalogSnapshot and len(catalog.entries) == 1
    # Application composition happens only after strict reading of Plan A's result.
    plan_b = WorkflowPlan(
        1,
        (
            replace(
                base.task("acquire"),
                inputs={"catalog": (ref,)},
                semantic_parameters={"label": catalog.entries[0].entry_id},
            ),
            replace(
                base.task("analyze"), inputs={"source": (OutputRef("acquire", "out"),)}
            ),
        ),
        (ref,),
    )
    digest_b = plan_b.digest
    workspace_b = tmp_path / "execution"
    result_b = runtime(harness, implementation, workspace_b).run(
        plan_b, **external(store_a, ref)
    )
    assert result_b.status == "SUCCEEDED"
    disk_b = reopen_workspace(workspace_b)
    assert plan_a.digest == disk_a.plan.digest == digest_a
    assert plan_b.digest == disk_b.plan.digest == digest_b and digest_a != digest_b
    assert tuple(t.task_id for t in disk_a.plan.tasks) == ("search",)
    assert tuple(t.task_id for t in disk_b.plan.tasks) == ("acquire", "analyze")
    assert store_a.read_bytes("runs/" + result_a.run_id + "/plan.json") == original_plan
    assert harness.controls.journal.count("business", "search", "search") == 1
    call = next(
        c
        for c in harness.controls.journal.snapshot()
        if c.stage == "business" and c.operation == "acquire"
    )
    assert (
        call.request.catalog_ref == ref
        and call.request.entry_id == catalog.entries[0].entry_id
    )
    acquired = disk_b.records["acquire"]["out"][0]
    assert tuple((e.role, e.artifact) for e in acquired.lineage) == (("catalog", ref),)
    output = assert_lineage(disk_b, "analyze", disk_b.artifacts["acquire"]["out"][0])
    assert tuple(
        o["payload"] for o in output.semantic_metadata["synthetic:observations"].value
    ) == ("toy-A", "toy-B")
    assert all(disk_b.started[t]["fingerprint"] for t in ("acquire", "analyze"))
