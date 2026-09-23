"""Synthetic static planning conformance; no scheduler or scientific backend."""

import builtins
import itertools
import json
import os
import socket
import subprocess
import sys
from collections import Counter
from dataclasses import FrozenInstanceError, fields, replace
from pathlib import Path

import pytest

from insarforge.contracts.context import ResourceRequest
from insarforge.contracts.errors import (
    ContractError,
    OperationBindingError,
    OperationCapabilityUnsatisfiedError,
    PluginAPIVersionMismatchError,
    UnknownPluginError,
    WorkspaceError,
)
from insarforge.contracts.execution import (
    AttemptOutcome,
    CachePolicy,
    CompletionDisposition,
    OutputDeclaration,
    OutputRef,
    RestartSafety,
    RetryPolicy,
    TaskSpec,
    TaskState,
    WorkflowPlan,
)
from insarforge.contracts.identity import (
    CapabilityId,
    PluginDescriptor,
    PluginKind,
    PluginRef,
)
from insarforge.contracts.operations import (
    InputPortContract,
    OperationBinding,
    OutputPortContract,
    ProductProfileRef,
    RecordSchemaRef,
)
from insarforge.contracts.values import ArtifactRef
from insarforge.core.planning import load_plan, save_plan, validate_plan
from insarforge.core.registry import PluginRegistry
from insarforge.products.validation import (
    ProductValidationReport,
    ValidationIssue,
    ValidationIssueKind,
)

REF = PluginRef(PluginKind.PROCESSOR, "unanticipated:opaque-plugin", 1)
SCHEMA = RecordSchemaRef("test:record", 1)
PROFILE = ProductProfileRef("test:profile", 1)
CAP = CapabilityId("test:operation")


def artifact(**kwargs):
    return ArtifactRef(
        **dict(
            record_id="external",
            schema_id=SCHEMA.schema_id,
            schema_version=1,
            semantic_digest=None,
            manifest_digest="manifest",
            locator="relative/record.json",
            **kwargs,
        )
    )


def task(name="a", sources=(), count=1, **changes):
    values = dict(
        schema_version=1,
        task_id=name,
        plugin_ref=REF,
        operation_id="test:operation",
        operation_api_version=1,
        inputs={"in": sources},
        outputs=(OutputDeclaration("out", SCHEMA.schema_id, 1, count),),
        semantic_parameters={"nested": [1, {"unicode": "é"}]},
        resources=ResourceRequest(),
    )
    values.update(changes)
    return TaskSpec(**values)


class Adapters:
    def __init__(self, report=None):
        self.calls = Counter()
        self.report = ProductValidationReport(()) if report is None else report
        self.validation_args = []

    def validate_spec(self, parameters, inputs, outputs):
        self.calls["validate_spec"] += 1
        self.validation_args.append((parameters, inputs, outputs))
        return self.report

    def prepare(self, *args):
        self.calls["prepare"] += 1
        pytest.fail("prepare during planning")

    def invoke(self, *args):
        self.calls["invoke"] += 1
        pytest.fail("invoke during planning")

    def decode(self, *args):
        self.calls["decode"] += 1
        pytest.fail("decode during planning")

    def encode(self, *args):
        self.calls["encode"] += 1
        pytest.fail("encode during planning")

    def validate(self, *args):
        self.calls["record_validate"] += 1
        pytest.fail("record validation during planning")

    def factory(self):
        self.calls["factory"] += 1
        pytest.fail("factory during planning")


def registry(
    *,
    count=1,
    minimum=0,
    maximum=None,
    profile=None,
    report=None,
    sealed=True,
    capabilities=(CAP,),
    required=(CAP,),
):
    adapters = Adapters(report)
    binding = OperationBinding(
        "test:operation",
        1,
        "test:parameters",
        1,
        (
            InputPortContract(
                "in", SCHEMA, profile, minimum, maximum, adapters, adapters
            ),
        ),
        (OutputPortContract("out", SCHEMA, profile, count, adapters, adapters),),
        required,
        1,
        adapters,
    )
    reg = PluginRegistry(1)
    reg.register(
        PluginDescriptor(REF.kind, REF.plugin_id, 1, "test", "Test", capabilities),
        adapters.factory,
        (binding,),
    )
    if sealed:
        reg.seal()
    return reg, adapters, binding


def test_complete_fields_and_deep_ownership():
    sources = [artifact(), artifact()]
    params = {"nested": [{"x": [1]}]}
    inputs = {"in": sources}
    outputs = [OutputDeclaration("out", SCHEMA.schema_id, 1)]
    value = task(inputs=inputs, outputs=outputs, semantic_parameters=params)
    sources.clear()
    inputs.clear()
    outputs.clear()
    params["nested"][0]["x"].append(2)
    assert len(value.inputs["in"]) == 2
    assert value.semantic_parameters["nested"][0]["x"] == (1,)
    assert len(value.outputs) == 1
    with pytest.raises(FrozenInstanceError):
        value.task_id = "changed"
    with pytest.raises(TypeError):
        value.inputs["in"] = ()
    with pytest.raises(TypeError):
        value.semantic_parameters["nested"][0]["x"] = ()
    assert {f.name for f in fields(value)} == {
        "schema_version",
        "task_id",
        "plugin_ref",
        "operation_id",
        "operation_api_version",
        "inputs",
        "outputs",
        "semantic_parameters",
        "resources",
        "retry_policy",
        "restart_safety",
        "cache_policy",
    }
    assert value.retry_policy == RetryPolicy(1, 0)
    assert value.restart_safety is RestartSafety.UNSAFE


@pytest.mark.parametrize(
    "changes",
    [
        {"schema_version": True},
        {"schema_version": 2},
        {"task_id": ""},
        {"task_id": " white space"},
        {"task_id": 4},
        {"plugin_ref": None},
        {"operation_id": "bad\n"},
        {"operation_api_version": True},
        {"operation_api_version": 0},
        {"inputs": []},
        {"inputs": {"": ()}},
        {"inputs": {"in": "string"}},
        {"inputs": {"in": [object()]}},
        {"outputs": ()},
        {"outputs": [None]},
        {"resources": {}},
        {"retry_policy": {}},
        {"restart_safety": "unsafe"},
        {"cache_policy": "auto"},
        {"semantic_parameters": float("nan")},
        {"semantic_parameters": {1: "x"}},
        {"semantic_parameters": object()},
    ],
)
def test_task_rejects_invalid_construction(changes):
    with pytest.raises(ContractError):
        task(**changes)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_attempts": True},
        {"max_attempts": 0},
        {"max_attempts": 1.0},
        {"backoff_seconds": True},
        {"backoff_seconds": -1},
        {"backoff_seconds": float("inf")},
        {"backoff_seconds": float("nan")},
        {"backoff_seconds": "1"},
        {"backoff_seconds": 10**400},
    ],
)
def test_invalid_retry(kwargs):
    with pytest.raises(ContractError):
        RetryPolicy(**kwargs)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"port": ""},
        {"schema_id": ""},
        {"schema_version": True},
        {"schema_version": 0},
        {"count": False},
        {"count": 0},
        {"count": 1.1},
        {"profile_id": "p"},
        {"profile_version": 1},
        {"profile_id": "p", "profile_version": False},
    ],
)
def test_output_declaration_validation(kwargs):
    values = dict(port="out", schema_id="test:record", schema_version=1)
    values.update(kwargs)
    with pytest.raises(ContractError):
        OutputDeclaration(**values)


def test_duplicate_ports_and_output_refs():
    out = OutputDeclaration("out", SCHEMA.schema_id, 1)
    for outputs, inputs in [((out, out), {}), ((out,), {"out": ()})]:
        with pytest.raises(ContractError, match="DUPLICATE_PORT"):
            task(outputs=outputs, inputs=inputs)
    for args in [("", "out"), ("a", ""), (True, "out")]:
        with pytest.raises(ContractError):
            OutputRef(*args)


def test_plan_snapshots_queries_and_empty_plan():
    tasks = [task()]
    plan = WorkflowPlan(1, tasks)
    tasks.clear()
    assert plan.topological_order() == ("a",)
    assert plan.dependencies("a") == plan.dependents("a") == ()
    assert plan.task("a").task_id == "a"
    with pytest.raises(ContractError):
        plan.task("missing")
    with pytest.raises(FrozenInstanceError):
        plan.tasks = ()
    assert WorkflowPlan(1, ()).topological_order() == ()
    assert WorkflowPlan.from_json(WorkflowPlan(1, ()).to_json()) == WorkflowPlan(1, ())


@pytest.mark.parametrize(
    "edges",
    [
        {"a": ()},
        {"a": (), "b": ("a",), "c": ("b",)},
        {"a": (), "b": ("a",), "c": ("a",)},
        {"a": (), "b": ("a",), "c": ("a",), "d": ("b", "c")},
        {"a": (), "b": ("a",), "c": (), "d": ("c",)},
        {"z": (), "a": ("z",), "m": ()},
    ],
)
def test_dags_all_input_permutations(edges):
    tasks = [
        task(name, [OutputRef(parent, "out") for parent in parents])
        for name, parents in edges.items()
    ]
    expected = WorkflowPlan(1, tasks)
    for ordering in itertools.permutations(tasks):
        plan = WorkflowPlan(1, ordering)
        assert plan.topological_order() == expected.topological_order()
        assert plan.to_json() == expected.to_json()
        order = plan.topological_order()
        for child, parents in edges.items():
            assert all(order.index(parent) < order.index(child) for parent in parents)
    if "z" in edges:
        assert expected.topological_order() == ("m", "z", "a")


@pytest.mark.parametrize(
    "tasks,code",
    [
        ([task(), task()], "DUPLICATE_TASK"),
        ([task("a", [OutputRef("a", "out")])], "SELF_REFERENCE"),
        ([task("a", [OutputRef("missing", "out")])], "UNKNOWN_TASK"),
        ([task(), task("b", [OutputRef("a", "bad")])], "UNKNOWN_PORT"),
        (
            [task("a", [OutputRef("b", "out")]), task("b", [OutputRef("a", "out")])],
            "CYCLE",
        ),
        (
            [
                task("a", [OutputRef("c", "out")]),
                task("b", [OutputRef("a", "out")]),
                task("c", [OutputRef("b", "out")]),
                task("entry"),
            ],
            "CYCLE",
        ),
    ],
)
def test_invalid_graphs(tasks, code):
    with pytest.raises(ContractError, match=code):
        WorkflowPlan(1, tasks)


def test_ordered_repeated_sources_and_multi_record_count():
    upstream = task("a", count=2)
    downstream = task("b", [OutputRef("a", "out"), OutputRef("a", "out")], count=2)
    plan = WorkflowPlan(1, [downstream, upstream])
    assert plan.dependencies("b") == ("a",)
    assert plan.dependents("a") == ("b",)
    assert len(plan.task("b").inputs["in"]) == 2
    reg, _, _ = registry(count=2, maximum=4)
    assert validate_plan(plan, reg).is_valid
    reg, _, _ = registry(count=2, maximum=3)
    assert "PLAN_INPUT_COUNT" in {i.code for i in validate_plan(plan, reg).errors}
    reg, _, _ = registry(count=2, minimum=5)
    assert "PLAN_INPUT_COUNT" in {i.code for i in validate_plan(plan, reg).errors}


def test_precise_external_set_conflicts_and_missing_semantic_digest():
    ref = artifact()
    plan = WorkflowPlan(1, [task("a", [ref, ref]), task("b", [ref])], [ref])
    reg, _, _ = registry()
    report = validate_plan(plan, reg)
    assert report.is_valid and not report.is_fully_verified
    assert "PLAN_EXTERNAL_RECORD_UNVERIFIED" in {i.code for i in report.unverified}
    assert plan.external_inputs[0].semantic_digest is None
    assert WorkflowPlan.from_json(plan.to_json()).external_inputs == (ref,)
    for refs in [
        (),
        (ref, ref),
        (ref, replace(ref, record_id="unused")),
        (replace(ref, locator="other"),),
    ]:
        with pytest.raises(ContractError):
            WorkflowPlan(1, plan.tasks, refs)
    for name in ("locator", "manifest_digest", "semantic_digest", "schema_id"):
        conflicting = replace(ref, **{name: "different"})
        with pytest.raises(ContractError, match="CONFLICTING_EXTERNAL"):
            WorkflowPlan(1, [task(sources=[ref, conflicting])], [ref])


def test_exact_registry_resolution_and_pure_handler_report():
    plan = WorkflowPlan(1, [task()])
    reg, adapters, binding = registry()
    report = validate_plan(plan, reg)
    assert report.is_valid
    assert adapters.calls == {"validate_spec": 1}
    assert adapters.validation_args == [
        (plan.tasks[0].semantic_parameters, binding.inputs, binding.outputs)
    ]
    unsealed, _, _ = registry(sealed=False)
    with pytest.raises(ContractError, match="UNSEALED"):
        validate_plan(plan, unsealed)
    for changes, error in [
        (
            {"plugin_ref": PluginRef(PluginKind.QC, REF.plugin_id, 1)},
            UnknownPluginError,
        ),
        ({"plugin_ref": replace(REF, plugin_id="missing")}, UnknownPluginError),
        ({"plugin_ref": replace(REF, api_version=2)}, PluginAPIVersionMismatchError),
        ({"operation_id": "other"}, OperationBindingError),
        ({"operation_api_version": 2}, OperationBindingError),
    ]:
        with pytest.raises(error):
            validate_plan(WorkflowPlan(1, [task(**changes)]), reg)
    with pytest.raises(OperationCapabilityUnsatisfiedError):
        registry(capabilities=())


@pytest.mark.parametrize(
    "kind", [ValidationIssueKind.ERROR, ValidationIssueKind.UNVERIFIED]
)
def test_handler_report_is_not_truthiness(kind):
    issue = ValidationIssue(kind, "test:reason", "parameters", {})
    reg, _, _ = registry(report=ProductValidationReport((issue,)))
    result = validate_plan(WorkflowPlan(1, [task()]), reg)
    assert issue in result.issues
    assert result.is_valid is (kind is ValidationIssueKind.UNVERIFIED)


def test_wrong_handler_return_and_safe_handler_value_error():
    reg, adapters, _ = registry(report=True)
    with pytest.raises(ContractError, match="PLAN_HANDLER_REPORT"):
        validate_plan(WorkflowPlan(1, [task()]), reg)

    def bad(*args):
        raise ValueError("private-sensitive-text")

    adapters.validate_spec = bad
    with pytest.raises(ContractError) as caught:
        validate_plan(WorkflowPlan(1, [task()]), reg)
    assert "private-sensitive-text" not in str(caught.value)
    assert caught.value.__suppress_context__


@pytest.mark.parametrize(
    "changes,code",
    [
        ({"inputs": {}}, "PLAN_PORT_SET"),
        (
            {"outputs": (OutputDeclaration("other", SCHEMA.schema_id, 1),)},
            "PLAN_PORT_SET",
        ),
        ({"outputs": (OutputDeclaration("out", "other", 1),)}, "PLAN_OUTPUT_CONTRACT"),
        (
            {"outputs": (OutputDeclaration("out", SCHEMA.schema_id, 2),)},
            "PLAN_OUTPUT_CONTRACT",
        ),
        (
            {"outputs": (OutputDeclaration("out", SCHEMA.schema_id, 1, 2),)},
            "PLAN_OUTPUT_CONTRACT",
        ),
    ],
)
def test_binding_mismatches(changes, code):
    reg, _, _ = registry()
    result = validate_plan(WorkflowPlan(1, [task(**changes)]), reg)
    assert code in {i.code for i in result.errors}


def test_schema_and_profile_compatibility_and_external_unknown_profile():
    ref = artifact()
    out = OutputDeclaration("out", SCHEMA.schema_id, 1, 1, PROFILE.profile_id, 1)
    reg, _, _ = registry(profile=PROFILE)
    external = WorkflowPlan(1, [task(sources=[ref], outputs=(out,))], [ref])
    report = validate_plan(external, reg)
    assert report.is_valid
    assert "PLAN_EXTERNAL_PROFILE_UNVERIFIED" in {i.code for i in report.unverified}
    bad = replace(ref, schema_version=2)
    assert not validate_plan(
        WorkflowPlan(1, [task(sources=[bad], outputs=(out,))], [bad]), reg
    ).is_valid
    plan = WorkflowPlan(
        1, [task("a"), task("b", [OutputRef("a", "out")], outputs=(out,))]
    )
    assert "PLAN_INPUT_PROFILE" in {i.code for i in validate_plan(plan, reg).errors}
    good = WorkflowPlan(
        1,
        [task("a", outputs=(out,)), task("b", [OutputRef("a", "out")], outputs=(out,))],
    )
    assert validate_plan(good, reg).is_valid


def rich_plan():
    a = artifact()
    b = replace(a, record_id="second", locator="/absolute/stable.json")
    return WorkflowPlan(
        1,
        [
            task("z", [b, a, b], semantic_parameters={"x": [1, 1.0, "é"]}),
            task("a", [OutputRef("z", "out"), a]),
        ],
        [b, a],
    )


def test_full_json_roundtrip_digest_and_explicit_io(tmp_path):
    plan = rich_plan()
    payload = plan.to_json()
    assert "é".encode() in payload
    assert WorkflowPlan.from_json(payload) == plan
    assert WorkflowPlan.from_dict(plan.to_dict()) == plan
    assert TaskSpec.from_dict(plan.tasks[0].to_dict()) == plan.tasks[0]
    assert plan.digest.encode() in payload
    reg, _, _ = registry()
    path = tmp_path / "plan.json"
    save_plan(plan, path)
    assert load_plan(path, reg) == plan
    assert path.read_bytes() == payload
    assert list(tmp_path.iterdir()) == [path]
    projection = plan.to_dict()
    projection["tasks"][0]["inputs"]["in"].clear()
    assert plan.to_json() == payload
    changed = WorkflowPlan(
        1,
        [replace(t, semantic_parameters={"x": 2}) for t in plan.tasks],
        plan.external_inputs,
    )
    assert changed.digest != plan.digest


def test_order_is_data_but_map_and_task_order_are_not():
    plan = rich_plan()
    z = plan.task("z")
    # Reorder a repeated sequence rather than deduplicating it.
    changed = replace(z, inputs={"in": z.inputs["in"][1:] + (z.inputs["in"][0],)})
    assert (
        WorkflowPlan(1, [plan.task("a"), changed], plan.external_inputs).digest
        != plan.digest
    )
    a = task(inputs={"two": (), "in": ()}, semantic_parameters={"a": 1, "b": 2})
    b = task(inputs={"in": (), "two": ()}, semantic_parameters={"b": 2, "a": 1})
    assert WorkflowPlan(1, [a]).to_json() == WorkflowPlan(1, [b]).to_json()
    assert (
        WorkflowPlan(1, [task(semantic_parameters=1)]).digest
        != WorkflowPlan(1, [task(semantic_parameters=1.0)]).digest
    )


@pytest.mark.parametrize(
    "mutation",
    [
        lambda d: d.update(extra=True),
        lambda d: d.pop("plan_digest"),
        lambda d: d.update(plan_digest="wrong"),
        lambda d: d["plan"].update(schema_version=True),
        lambda d: d["plan"].update(schema_version=2),
        lambda d: d["plan"].update(schema_id="wrong"),
        lambda d: d["plan"]["tasks"][0].update(operation_api_version=True),
        lambda d: d["plan"]["tasks"][0].update(extra=1),
        lambda d: d["plan"]["tasks"][0].pop("resources"),
        lambda d: d["plan"]["tasks"][0]["outputs"][0].update(count=True),
        lambda d: d["plan"]["tasks"][0]["plugin_ref"].update(kind="unknown"),
        lambda d: d["plan"]["tasks"][0]["resources"].update(cpu_cores=False),
        lambda d: d["plan"]["tasks"][0]["retry_policy"].update(backoff_seconds=True),
        lambda d: d["plan"]["tasks"][0].update(restart_safety="unsafe-unknown"),
    ],
)
def test_strict_json_rejects_tampering(mutation):
    data = json.loads(rich_plan().to_json())
    mutation(data)
    with pytest.raises(ContractError):
        WorkflowPlan.from_json(json.dumps(data))


@pytest.mark.parametrize(
    "payload",
    [
        '{"plan": {}, "plan": {}}',
        '{"a": {"x": 1, "x": 2}}',
        '{"x": NaN}',
        '{"x": Infinity}',
        '{"x": -Infinity}',
        "[]",
        "null",
        "{",
        b"\xff",
        4,
    ],
)
def test_invalid_json(payload):
    with pytest.raises(ContractError):
        WorkflowPlan.from_json(payload)


def test_float_overflow_and_wrong_nested_shapes():
    data = json.loads(WorkflowPlan(1, [task(semantic_parameters=1)]).to_json())
    payload = json.dumps(data).replace(
        '"semantic_parameters": 1', '"semantic_parameters": 1e999'
    )
    with pytest.raises(ContractError):
        WorkflowPlan.from_json(payload)
    for name in ("inputs", "outputs", "plugin_ref", "resources", "retry_policy"):
        data = json.loads(rich_plan().to_json())
        data["plan"]["tasks"][0][name] = []
        with pytest.raises(ContractError):
            WorkflowPlan.from_json(json.dumps(data))


@pytest.mark.parametrize(
    "secret",
    [
        {"password": "sentinel-private"},
        {"auth-token": "sentinel-private"},
        {"nested": [{"credentials": "sentinel-private"}]},
        "https://user:sentinel-private@example.test/a",
        "https://example.test/a?X-Amz-Signature=sentinel-private",
        "-----BEGIN PRIVATE KEY-----sentinel-private",
    ],
)
def test_secret_rejected_before_any_file_write(secret, tmp_path):
    plan = WorkflowPlan(1, [task(semantic_parameters=secret)])
    path = tmp_path / "plan.json"
    path.write_text("untouched")
    for call in [plan.to_json, lambda: save_plan(plan, path)]:
        with pytest.raises(ContractError, match="PERSISTENCE_SECRET") as caught:
            call()
        assert "sentinel-private" not in str(caught.value)
    assert path.read_text() == "untouched"
    assert list(tmp_path.iterdir()) == [path]


def test_locator_secrets_and_decode_secrets_are_rejected():
    ref = replace(artifact(), locator="https://user:secret@example.test/file")
    with pytest.raises(ContractError, match="PERSISTENCE_SECRET"):
        WorkflowPlan(1, [task(sources=[ref])], [ref]).to_json()
    data = json.loads(rich_plan().to_json())
    data["plan"]["tasks"][0]["semantic_parameters"] = {"password": "secret"}
    with pytest.raises(ContractError, match="PERSISTENCE_SECRET"):
        WorkflowPlan.from_json(json.dumps(data))


def test_pure_planning_has_no_io_or_runtime_calls(monkeypatch):
    reg, adapters, _ = registry()

    def forbidden(*args, **kwargs):
        pytest.fail("I/O during pure planning")

    with monkeypatch.context() as patch:
        for target, name in [
            (builtins, "open"),
            (Path, "open"),
            (Path, "mkdir"),
            (os, "mkdir"),
            (os, "stat"),
            (socket, "socket"),
        ]:
            patch.setattr(target, name, forbidden)
        plan = rich_plan()
        assert validate_plan(plan, reg).is_valid
        assert WorkflowPlan.from_json(plan.to_json()) == plan
        assert plan.topological_order() == ("z", "a")
    assert adapters.calls == {"validate_spec": 2}


def test_file_boundaries_safe_failure_and_revalidation(tmp_path):
    reg, _, _ = registry()
    with pytest.raises(WorkspaceError, match="PLAN_READ_FAILED"):
        load_plan(tmp_path / "absent", reg)
    with pytest.raises(WorkspaceError, match="PLAN_WRITE_FAILED"):
        save_plan(rich_plan(), tmp_path / "missing" / "plan.json")
    bad = WorkflowPlan(
        1, [task(outputs=(OutputDeclaration("other", SCHEMA.schema_id, 1),))]
    )
    path = tmp_path / "plan.json"
    save_plan(bad, path)
    with pytest.raises(ContractError, match="STATIC_VALIDATION_FAILED"):
        load_plan(path, reg)


def test_exact_state_vocabulary():
    for cls, expected in [
        (TaskState, ["PENDING", "RUNNING", "SUCCEEDED", "FAILED", "BLOCKED"]),
        (CompletionDisposition, ["EXECUTED", "CACHE_REUSED"]),
        (AttemptOutcome, ["SUCCEEDED", "FAILED", "INTERRUPTED"]),
        (RestartSafety, ["RESTARTABLE", "UNSAFE"]),
        (CachePolicy, ["AUTO", "DISABLED"]),
    ]:
        assert list(cls.__members__) == expected
        for member in cls:
            assert cls(member.value) is member
            assert member.value == member.name.lower()


def test_hash_seed_independence():
    code = """
from insarforge.contracts.execution import *
from insarforge.contracts.context import ResourceRequest
from insarforge.contracts.identity import PluginRef, PluginKind
tasks = [TaskSpec(1, name, PluginRef(PluginKind.QC, 'test', 1), 'op', 1,
    {}, (OutputDeclaration('out', 'test', 1),), {}, ResourceRequest())
    for name in {'z', 'a', 'm'}]
plan = WorkflowPlan(1, tasks)
print(plan.topological_order(), plan.digest)
"""
    outputs = [
        subprocess.check_output(
            [sys.executable, "-B", "-c", code],
            env={**os.environ, "PYTHONHASHSEED": seed},
            text=True,
        )
        for seed in ("1", "25", "random")
    ]
    assert len(set(outputs)) == 1


@pytest.mark.parametrize("field", [f.name for f in fields(TaskSpec)] + ["schema_id"])
def test_every_task_json_field_is_required(field):
    value = task().to_dict()
    del value[field]
    with pytest.raises(ContractError, match="FIELDS"):
        TaskSpec.from_dict(value)


@pytest.mark.parametrize(
    "field", ["schema_id", "schema_version", "tasks", "external_inputs"]
)
def test_every_plan_json_field_is_required(field):
    value = rich_plan().to_dict()
    del value[field]
    with pytest.raises(ContractError, match="FIELDS"):
        WorkflowPlan.from_dict(value)


def test_json_cycle_and_nonfinite_direct_projection_are_safe():
    value = {}
    value["self"] = value
    with pytest.raises(ContractError):
        TaskSpec.from_dict(value)
    value = task().to_dict()
    value["semantic_parameters"] = float("inf")
    with pytest.raises(ContractError):
        TaskSpec.from_dict(value)


def test_resource_bounds_preserve_existing_constructor_contract():
    for changes in [
        {"cpu_cores": 0},
        {"cpu_cores": True},
        {"gpu_count": -1},
        {"gpu_count": False},
        {"memory_bytes": 0},
        {"memory_bytes": True},
    ]:
        with pytest.raises((TypeError, ValueError)):
            ResourceRequest(**changes)
    value = task(
        resources=ResourceRequest(4, 4096, 2),
        retry_policy=RetryPolicy(3, 0.25),
        restart_safety=RestartSafety.RESTARTABLE,
        cache_policy=CachePolicy.DISABLED,
    )
    assert TaskSpec.from_dict(value.to_dict()) == value


@pytest.mark.parametrize("bad", [None, {}, 1, "tasks"])
def test_plan_container_types(bad):
    with pytest.raises(ContractError):
        WorkflowPlan(1, bad)
    with pytest.raises(ContractError):
        WorkflowPlan(1, (), bad)


def test_ordered_source_type_tags_and_nested_unknown_fields():
    projection = rich_plan().to_dict()
    reference = projection["tasks"][0]["inputs"]["in"][0]
    assert reference["kind"] == "output"
    reference["unexpected"] = 1
    with pytest.raises(ContractError):
        WorkflowPlan.from_dict(projection)
    projection = rich_plan().to_dict()
    projection["tasks"][0]["inputs"]["in"][0]["kind"] = "python.module"
    with pytest.raises(ContractError):
        WorkflowPlan.from_dict(projection)


def test_save_failure_preserves_target_and_removes_owned_temp(monkeypatch, tmp_path):
    path = tmp_path / "plan.json"
    path.write_bytes(b"existing")

    def fail(*args):
        raise OSError("sensitive-error")

    monkeypatch.setattr(os, "replace", fail)
    with pytest.raises(WorkspaceError) as caught:
        save_plan(rich_plan(), path)
    assert str(caught.value) == "PLAN_WRITE_FAILED"
    assert path.read_bytes() == b"existing"
    assert list(tmp_path.iterdir()) == [path]


def test_non_utf8_json_is_rejected():
    payload = rich_plan().to_json().decode("utf-8")
    for encoding in ("utf-16", "utf-32"):
        with pytest.raises(ContractError, match="JSON_INVALID"):
            WorkflowPlan.from_json(payload.encode(encoding))


@pytest.mark.parametrize("error", [RuntimeError, OSError, ContractError])
def test_extension_exception_is_safe_failure_not_retry(error):
    reg, adapters, _ = registry()

    def fail(*args):
        raise error("sensitive-callback-text")

    adapters.validate_spec = fail
    with pytest.raises(ContractError) as caught:
        validate_plan(WorkflowPlan(1, [task()]), reg)
    assert str(caught.value) == "PLAN_HANDLER_VALIDATION"
    assert caught.value.__suppress_context__
