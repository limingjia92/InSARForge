"""P4.3-01 T01--T10: formal six-family/seven-operation harness conformance."""

import hashlib
import inspect
import logging
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import fields, replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from insarforge.contracts import plugins
from insarforge.contracts.context import (
    ExecutionContext,
    ResourceAllocation,
    ResourceRequest,
)
from insarforge.contracts.errors import (
    ExecutionError,
    InputValidationError,
    OutputValidationError,
    PluginRegistrySealedError,
    RetryableExecutionError,
)
from insarforge.contracts.execution import (
    CachePolicy,
    OutputDeclaration,
    RestartSafety,
    RetryPolicy,
    TaskSpec,
    WorkflowPlan,
)
from insarforge.contracts.identity import PluginKind
from insarforge.contracts.operations import TaskOutcome
from insarforge.contracts.record_serialization import record_from_bytes, record_to_bytes
from insarforge.contracts.records import (
    AccessStatus,
    AcquisitionMetadata,
    CatalogEntry,
    CatalogSnapshot,
    ProviderAvailability,
    ProviderDelivery,
    QCReport,
)
from insarforge.contracts.values import ArtifactRef, freeze_json
from insarforge.core.fingerprints import execution_identity
from insarforge.core.runtime import Runtime
from insarforge.products.models import ProducerRef, Product, ProductDraft, ProductionRef
from insarforge.products.semantics import SemanticStatus, SemanticValue
from insarforge.products.serialization import canonical_json_bytes
from insarforge.products.validation import validate_product_structure

from ._fake_operations import (
    CATALOG,
    PRODUCT,
    PROFILE,
    Codec,
    PortValidator,
    build_harness,
)
from ._fake_plugins import (
    OPERATIONS,
    CallJournal,
    Controls,
    Failure,
    FakeAnalyzer,
    FakeConfig,
    FakeCorrection,
    FakeMission,
    FakeProcessor,
    FakeProvider,
    FakeQC,
    HoldPoint,
    descriptor,
    draft,
)

ALLOCATION = ResourceAllocation(1, None, 0)
PARAMETERS = freeze_json({"label": "synthetic:sample"})
EXPECTED = {
    "inspect": (
        PluginKind.MISSION,
        FakeMission,
        plugins.InspectionRequest,
        AcquisitionMetadata,
    ),
    "search": (
        PluginKind.PROVIDER,
        FakeProvider,
        plugins.SearchRequest,
        CatalogSnapshot,
    ),
    "acquire": (
        PluginKind.PROVIDER,
        FakeProvider,
        plugins.AcquireRequest,
        ProductDraft,
    ),
    "process": (PluginKind.PROCESSOR, FakeProcessor, plugins.ProcessingRequest, tuple),
    "correct": (
        PluginKind.CORRECTION,
        FakeCorrection,
        plugins.CorrectionRequest,
        tuple,
    ),
    "analyze": (PluginKind.ANALYZER, FakeAnalyzer, plugins.AnalysisRequest, tuple),
    "assess": (PluginKind.QC, FakeQC, plugins.QCRequest, QCReport),
}


def seed_product():
    value = draft(FakeConfig(), "seed", PARAMETERS)
    unknown = SemanticValue(
        SemanticStatus.UNKNOWN, None, "synthetic:seed-unverified", ()
    )
    return Product(
        **{f.name: getattr(value, f.name) for f in fields(value)},
        schema_id="insarforge:product",
        schema_version=2,
        product_id="synthetic:seed",
        producer=ProducerRef(
            descriptor(PluginKind.PROVIDER).ref, "1", unknown, unknown
        ),
        produced_by=ProductionRef(unknown, "out", "synthetic:seed-attempt"),
        lineage=(),
        provenance_ref="synthetic:seed-provenance",
    )


def seed_catalog():
    return CatalogSnapshot(
        "synthetic:seed-catalog",
        CATALOG.schema_id,
        1,
        descriptor(PluginKind.PROVIDER).ref,
        "synthetic:query",
        1,
        PARAMETERS,
        (
            CatalogEntry(
                "synthetic:entry",
                AccessStatus(
                    ProviderAvailability.AVAILABLE, ProviderDelivery.DIRECT, False, None
                ),
                {},
                (),
            ),
        ),
        {},
    )


def resolved(record, port):
    raw = record_to_bytes(record)
    record_id = record.product_id if type(record) is Product else record.record_id
    ref = ArtifactRef(
        record_id,
        record.schema_id,
        record.schema_version,
        None,
        hashlib.sha256(raw).hexdigest(),
        "synthetic:unopened-locator",
    )
    value = port.codec.decode(ref, raw, port.schema)
    assert port.validator.validate(
        value.value, port.schema, port.profile
    ).is_fully_verified
    return value


def context(path, task_id="synthetic:task"):
    return ExecutionContext(
        "synthetic:run",
        task_id,
        "synthetic:attempt",
        path,
        path / "artifacts",
        path / "scratch",
        ALLOCATION,
        logging.getLogger("synthetic"),
        lambda: False,
    )


def inputs_for(binding):
    return {
        port.port_id: (
            ()
            if port.min_count == 0
            else (
                resolved(
                    seed_catalog() if port.schema == CATALOG else seed_product(), port
                ),
            )
        )
        for port in binding.inputs
    }


def exercise(harness, operation, path, task_id="synthetic:task", parameters=PARAMETERS):
    binding = harness.binding(operation)
    plugin = harness.registration(operation).factory()
    inputs = inputs_for(binding)
    assert binding.handler.validate_spec(
        parameters, binding.inputs, binding.outputs
    ).is_fully_verified
    prepared = binding.handler.prepare(
        plugin, inputs, parameters, SimpleNamespace(allocated_resources=ALLOCATION)
    )
    assert execution_identity(prepared, ALLOCATION).reusable
    outcome = binding.handler.invoke(
        plugin, prepared, inputs, parameters, context(path, task_id)
    )
    return binding, inputs, prepared, outcome


@pytest.mark.parametrize("operation", OPERATIONS)
def test_t01_t04_exact_surface_and_formal_lifecycle(operation, tmp_path):
    harness = build_harness()
    kind, fake_type, request_type, result_type = EXPECTED[operation]
    registration = harness.registration(operation)
    assert registration.descriptor.kind is kind
    assert registration.descriptor == descriptor(kind)
    instance = registration.factory()
    assert type(instance) is fake_type
    assert not hasattr(instance, "run") and not hasattr(instance, "execute")
    assert tuple(inspect.signature(getattr(instance, operation)).parameters) == (
        "request",
        "context",
    )
    assert fake_type.__bases__ == (object,)
    binding, inputs, prepared, outcome = exercise(harness, operation, tmp_path)
    assert type(outcome) is TaskOutcome and outcome.evidence == ()
    calls = harness.controls.journal.snapshot()
    business = [c for c in calls if c.stage == "business"]
    assert len(business) == 1
    call = business[0]
    assert call.operation == operation and type(call.request) is request_type
    assert type(call.result) is result_type
    expected_values = call.result if result_type is tuple else (call.result,)
    assert tuple(d.value for d in outcome.outputs["out"]) == expected_values
    port = binding.outputs[0]
    assert len(outcome.outputs["out"]) == port.count
    assert binding.handler.outputs[0] is port
    for value in expected_values:
        assert port.validator.validate(
            value, port.schema, port.profile
        ).is_fully_verified
        if type(value) is ProductDraft:
            assert validate_product_structure(value).is_fully_verified
            assert not hasattr(value, "produced_by")
        else:
            assert resolved(value, port).value == value
    assert [c.stage for c in calls[-4:]] == [
        "validate",
        "prepare",
        "invoke",
        "business",
    ]
    assert harness.controls.journal.count("invoke", operation, "synthetic:task") == 1
    if operation == "inspect":
        assert call.request.source.value is inputs["source"][0].value
        assert call.request.source.artifact is inputs["source"][0].artifact
    if operation in ("process", "correct", "analyze"):
        members = (
            call.request.source_inputs
            if operation == "correct"
            else call.request.product_inputs
        )
        assert members["source"][0].value is inputs["source"][0].value
    if operation == "acquire":
        assert call.request.catalog_ref is inputs["catalog"][0].artifact
        assert call.request.entry_id == "synthetic:entry"
    if operation == "assess":
        assert call.request.target_refs == (inputs["source"][0].artifact,)
    assert not list(tmp_path.iterdir())
    assert prepared.preparation["operation"] == operation


def test_t02_t03_complete_registry_bindings_and_factory_isolation():
    harness = build_harness()
    registry = harness.registry
    assert registry.is_sealed and registry.required_api_version == 1
    assert len(registry) == 6
    assert {r.ref.kind for r in registry.registrations()} == set(PluginKind)
    assert harness.controls.journal.snapshot() == ()
    assert sum(len(r.bindings) for r in registry.registrations()) == 7
    for operation in OPERATIONS:
        registration = harness.registration(operation)
        assert registry.resolve(registration.ref) is registration
        assert registry.resolve_binding(
            registration.ref, "synthetic:" + operation, 1
        ) is harness.binding(operation)
        first, second = registration.factory(), registration.factory()
        assert first is not second and type(first) is EXPECTED[operation][1]
        assert first.descriptor == registration.descriptor
    with pytest.raises(PluginRegistrySealedError):
        registry.register(
            registration.descriptor, registration.factory, registration.bindings
        )


def declarations(harness):
    return tuple(
        (
            r.descriptor,
            tuple(
                (
                    b.operation_id,
                    b.operation_api_version,
                    b.parameter_schema_id,
                    b.parameter_schema_version,
                    b.required_capabilities,
                    b.validator_revision,
                    tuple(
                        (p.port_id, p.schema, p.profile, p.min_count, p.max_count)
                        for p in b.inputs
                    ),
                    tuple((p.port_id, p.schema, p.profile, p.count) for p in b.outputs),
                )
                for b in r.bindings
            ),
        )
        for r in harness.registry.registrations()
    )


@pytest.mark.parametrize("operation", OPERATIONS)
def test_t05_semantics_and_preparation_repeat_across_paths_and_attempts(
    operation, tmp_path
):
    first, second = build_harness(), build_harness(FakeConfig())
    assert declarations(first) == declarations(second)
    _, _, a, out_a = exercise(first, operation, tmp_path / "one", "synthetic:first")
    _, _, b, out_b = exercise(second, operation, tmp_path / "two", "synthetic:second")
    assert a == b and out_a == out_b
    raw = canonical_json_bytes(a.preparation)
    assert str(tmp_path).encode() not in raw
    assert b"synthetic:first" not in raw and b"synthetic:second" not in raw
    changed = build_harness(FakeConfig("synthetic:changed"))
    _, _, c, _ = exercise(changed, operation, tmp_path)
    assert execution_identity(a, ALLOCATION) != execution_identity(c, ALLOCATION)


def test_t06_atomic_journal_counts_and_order():
    journal = CallJournal()
    with ThreadPoolExecutor(max_workers=8) as pool:
        ordinals = tuple(
            pool.map(
                lambda _: journal.record("invoke", "search", "synthetic:task"),
                range(200),
            )
        )
    calls = journal.snapshot()
    assert len(calls) == journal.count("invoke", "search", "synthetic:task") == 200
    assert sorted(ordinals) == list(range(1, 201))
    assert (
        [c.sequence for c in calls] == [c.ordinal for c in calls] == list(range(1, 201))
    )
    saved = journal.snapshot()
    journal.record("invoke", "search", "synthetic:other")
    assert (
        len(saved) == 200 and journal.count("invoke", "search", "synthetic:task") == 200
    )


@pytest.mark.parametrize("retryable", [True, False])
def test_t07_t08_failure_exact_operation_task_and_ordinal(retryable, tmp_path):
    control = Controls(failures=(Failure("search", "synthetic:task", 2, retryable),))
    harness = build_harness(controls=control)
    exercise(harness, "search", tmp_path)
    expected = RetryableExecutionError if retryable else ExecutionError
    with pytest.raises(expected) as error:
        exercise(harness, "search", tmp_path)
    assert type(error.value) is expected
    exercise(harness, "search", tmp_path)
    exercise(harness, "search", tmp_path, "synthetic:other")
    exercise(harness, "analyze", tmp_path)
    assert control.journal.count("invoke", "search", "synthetic:task") == 3
    assert control.journal.count("business", "search", "synthetic:task") == 2
    assert control.journal.count("business", "analyze", "synthetic:task") == 1


def test_t09_two_real_adapter_invocations_held_until_explicit_release(tmp_path):
    hold = HoldPoint((("search", "synthetic:a"), ("search", "synthetic:b")))
    harness = build_harness(controls=Controls(hold=hold))
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(exercise, harness, "search", tmp_path, task)
            for task in ("synthetic:a", "synthetic:b")
        ]
        try:
            assert hold.all_entered.wait(10), "both adapter invocations must enter"
            assert not any(f.done() for f in futures)
            assert not any(
                c.stage == "business" for c in harness.controls.journal.snapshot()
            )
        finally:
            hold.release.set()
        assert all(type(f.result(timeout=10)[-1]) is TaskOutcome for f in futures)
    assert {
        c.task_id for c in harness.controls.journal.snapshot() if c.stage == "business"
    } == {"synthetic:a", "synthetic:b"}


def test_output_codec_and_validator_reject_wrong_type_schema_profile():
    codec = Codec()
    with pytest.raises(OutputValidationError):
        codec.encode(seed_catalog(), PRODUCT)
    with pytest.raises(OutputValidationError):
        codec.encode(seed_product(), PRODUCT)
    with pytest.raises(InputValidationError):
        ref = ArtifactRef(
            "synthetic:x",
            PRODUCT.schema_id,
            2,
            None,
            "synthetic:digest",
            "synthetic:none",
        )
        codec.decode(ref, b"{}", PRODUCT)
    value = draft(FakeConfig(), "search", PARAMETERS)
    assert (
        not PortValidator()
        .validate(value, PRODUCT, replace(PROFILE, profile_id="synthetic:unsupported"))
        .is_valid
    )


@pytest.mark.parametrize("operation", OPERATIONS)
def test_validation_and_wrong_family_refuse_before_business(operation, tmp_path):
    harness = build_harness()
    binding = harness.binding(operation)
    assert not binding.handler.validate_spec(
        {}, binding.inputs, binding.outputs
    ).is_valid
    other = harness.registration(
        "search" if operation != "search" and operation != "acquire" else "inspect"
    ).factory()
    with pytest.raises(InputValidationError):
        binding.handler.prepare(
            other,
            inputs_for(binding),
            PARAMETERS,
            SimpleNamespace(allocated_resources=ALLOCATION),
        )
    assert not any(c.stage == "business" for c in harness.controls.journal.snapshot())


@pytest.mark.parametrize(
    "retryable, expected_count, status", [(True, 2, "SUCCEEDED"), (False, 1, "FAILED")]
)
def test_failure_controls_follow_real_runtime_classification(
    tmp_path, retryable, expected_count, status
):
    harness = build_harness(
        controls=Controls(failures=(Failure("search", "synthetic:task", 1, retryable),))
    )
    registration = harness.registration("search")
    binding = harness.binding("search")
    task = TaskSpec(
        schema_version=1,
        task_id="synthetic:task",
        operation_id=binding.operation_id,
        operation_api_version=1,
        plugin_ref=registration.ref,
        inputs={},
        outputs=(OutputDeclaration("out", CATALOG.schema_id, 1),),
        semantic_parameters=PARAMETERS,
        resources=ResourceRequest(),
        retry_policy=RetryPolicy(2, 0),
        restart_safety=RestartSafety.RESTARTABLE,
        cache_policy=CachePolicy.DISABLED,
    )
    files = {
        name: Path(__file__).with_name(name)
        for name in ("__init__.py", "_fake_plugins.py", "_fake_operations.py")
    }
    runtime = Runtime(
        harness.registry,
        tmp_path / "workspace",
        budget=ALLOCATION,
        implementation_files={registration.ref: files},
    )
    result = runtime.run(WorkflowPlan(1, (task,)))
    assert result.status == status
    assert (
        harness.controls.journal.count("invoke", "search", "synthetic:task")
        == expected_count
    )
    if retryable:
        ref = result.outputs["synthetic:task"]["out"][0]
        assert (
            type(record_from_bytes(ref, runtime.store.read_bytes(ref.locator)))
            is CatalogSnapshot
        )


def test_t10_cold_import_and_all_operations_without_backends_network_or_processes(
    tmp_path,
):
    code = """
import sys, socket, subprocess, importlib.abc
from pathlib import Path
blocked = ('insarforge.missions', 'insarforge.providers', 'insarforge.processors', 'insarforge.corrections', 'insarforge.analyzers', 'insarforge.qc', 'isce', 'isce2', 'isce3', 'gamma', 'gmtsar', 'stamps', 'mintpy')
class RejectBackend(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if any(fullname == p or fullname.startswith(p + '.') for p in blocked):
            raise AssertionError('backend import forbidden: ' + fullname)
sys.meta_path.insert(0, RejectBackend())
def forbidden(*args, **kwargs):
    raise AssertionError('external activity forbidden')
socket.socket = forbidden
socket.create_connection = forbidden
subprocess.Popen = forbidden
sys.path.insert(0, sys.argv[1])
from integration.test_fake_plugin_harness import exercise, build_harness, OPERATIONS
for operation in OPERATIONS:
    exercise(build_harness(), operation, Path(sys.argv[2]))
assert not any(k == p or k.startswith(p + '.') for k in sys.modules for p in blocked)
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
        capture_output=True,
        text=True,
        env={},
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert not list(tmp_path.iterdir())


def test_failure_controls_do_not_pollute_semantic_preparation(tmp_path):
    a = build_harness()
    b = build_harness(
        controls=Controls(
            failures=(Failure("search", "synthetic:other-task", 8, True),)
        )
    )
    _, _, first, one = exercise(a, "search", tmp_path)
    _, _, second, two = exercise(b, "search", tmp_path)
    assert first == second and one == two
    assert b"synthetic:other-task" not in canonical_json_bytes(second.preparation)


def test_process_transfers_ordered_repeated_products_and_metadata(tmp_path):
    harness = build_harness()
    binding = harness.binding("process")
    inputs = inputs_for(binding)
    source = inputs["source"][0]
    metadata = AcquisitionMetadata(
        "synthetic:metadata",
        "synthetic:acquisition",
        1,
        source.artifact,
        descriptor(PluginKind.MISSION).ref,
        {},
        (),
        {},
    )
    inputs["source"] = (source, source)
    inputs["metadata"] = (resolved(metadata, binding.inputs[0]),)
    plugin = harness.registration("process").factory()
    prepared = binding.handler.prepare(
        plugin, inputs, PARAMETERS, SimpleNamespace(allocated_resources=ALLOCATION)
    )
    binding.handler.invoke(plugin, prepared, inputs, PARAMETERS, context(tmp_path))
    call = harness.controls.journal.snapshot()[-1]
    assert tuple(p.value for p in call.request.product_inputs["source"]) == (
        source.value,
        source.value,
    )
    assert tuple(p.artifact for p in call.request.product_inputs["source"]) == (
        source.artifact,
        source.artifact,
    )
    assert call.request.acquisition_metadata_refs == (inputs["metadata"][0].artifact,)
