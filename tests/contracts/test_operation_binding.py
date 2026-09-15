from dataclasses import MISSING, FrozenInstanceError, fields, replace
from inspect import signature
from typing import get_type_hints

import pytest

from insarforge.contracts.context import ExecutionContext
from insarforge.contracts.errors import (
    CapabilityUnavailableError,
    ContractError,
    DuplicatePluginRegistrationError,
    OperationBindingError,
    OperationCapabilityUnsatisfiedError,
    PluginAPIVersionMismatchError,
    PluginRegistrySealedError,
    UnknownPluginError,
)
from insarforge.contracts.identity import (
    CapabilityId,
    PluginDescriptor,
    PluginKind,
    PluginRef,
)
from insarforge.contracts.operations import (
    ArtifactDraft,
    InputPortContract,
    OperationBinding,
    OperationHandler,
    OutputPortContract,
    OutputRecord,
    PluginInstance,
    PortRecord,
    PreparedExecution,
    ProbeContext,
    ProductProfileRef,
    RecordSchemaRef,
    ResolvedInput,
    ResolvedInputs,
    TaskOutcome,
)
from insarforge.contracts.values import ArtifactRef, FrozenJSON
from insarforge.core.registry import PluginRegistration, PluginRegistry
from insarforge.products.validation import ProductValidationReport


class StaticHandler:
    def validate_spec(
        self,
        parameters: FrozenJSON,
        inputs: tuple[InputPortContract, ...],
        outputs: tuple[OutputPortContract, ...],
    ) -> ProductValidationReport:
        pytest.fail("validate_spec called")

    def prepare(
        self,
        plugin: PluginInstance,
        resolved_inputs: ResolvedInputs,
        parameters: FrozenJSON,
        probe_context: ProbeContext,
    ) -> PreparedExecution:
        pytest.fail("prepare called")

    def invoke(
        self,
        plugin: PluginInstance,
        prepared: PreparedExecution,
        resolved_inputs: ResolvedInputs,
        parameters: FrozenJSON,
        context: ExecutionContext,
    ) -> TaskOutcome:
        pytest.fail("invoke called")

    def __eq__(self, other):
        pytest.fail("handler equality used")

    def __hash__(self):
        pytest.fail("handler hash used")

    def __repr__(self):
        pytest.fail("handler repr used")


class StaticInputCodec:
    def decode(
        self, artifact: ArtifactRef, payload: bytes, schema: RecordSchemaRef
    ) -> ResolvedInput:
        pytest.fail("decode called")


class StaticOutputCodec:
    def encode(self, value: OutputRecord, schema: RecordSchemaRef) -> ArtifactDraft:
        pytest.fail("encode called")


class StaticValidator:
    def validate(
        self,
        value: PortRecord,
        schema: RecordSchemaRef,
        profile: ProductProfileRef | None,
    ) -> ProductValidationReport:
        pytest.fail("validate called")


def factory():
    pytest.fail("factory called")


def binding(**changes):
    return OperationBinding(
        **(
            dict(
                operation_id="synthetic:operation",
                operation_api_version=1,
                parameter_schema_id="synthetic:parameters",
                parameter_schema_version=1,
                inputs=(),
                outputs=(),
                required_capabilities=(),
                validator_revision=1,
                handler=StaticHandler(),
            )
            | changes
        )
    )


def desc(kind=PluginKind.PROCESSOR, pid="synthetic:plugin", caps=()):
    return PluginDescriptor(kind, pid, 1, "1", "Synthetic", caps)


def input_port(pid):
    return InputPortContract(
        pid,
        RecordSchemaRef("synthetic:record", 1),
        None,
        0,
        None,
        StaticInputCodec(),
        StaticValidator(),
    )


def output_port(pid):
    return OutputPortContract(
        pid,
        RecordSchemaRef("synthetic:record", 1),
        None,
        1,
        StaticOutputCodec(),
        StaticValidator(),
    )


def test_exact_final_fields_required_annotations_and_frozen_value():
    expected = {
        "operation_id": str,
        "operation_api_version": int,
        "parameter_schema_id": str,
        "parameter_schema_version": int,
        "inputs": tuple[InputPortContract, ...],
        "outputs": tuple[OutputPortContract, ...],
        "required_capabilities": tuple[CapabilityId, ...],
        "validator_revision": int,
        "handler": OperationHandler,
    }
    assert [f.name for f in fields(OperationBinding)] == list(expected)
    assert get_type_hints(OperationBinding) == expected
    assert all(
        f.default is MISSING and f.default_factory is MISSING
        for f in fields(OperationBinding)
    )
    value = binding()
    for name in (
        "requirement",
        "plugin_ref",
        "capability",
        "plugin_kind",
        "handler_id",
        "codec_id",
        "resolve",
        "run",
        "execute",
        "prepare",
        "invoke",
    ):
        assert not hasattr(value, name)
    with pytest.raises(FrozenInstanceError):
        value.operation_id = "synthetic:changed"
    for method in ("validate_spec", "prepare", "invoke"):
        assert get_type_hints(vars(StaticHandler)[method]) == get_type_hints(
            vars(OperationHandler)[method]
        )


@pytest.mark.parametrize(
    "name", ["operation_api_version", "parameter_schema_version", "validator_revision"]
)
@pytest.mark.parametrize(
    "value,error",
    [
        (True, TypeError),
        (False, TypeError),
        (0, ValueError),
        (-1, ValueError),
        (1.0, TypeError),
        ("1", TypeError),
    ],
)
def test_exact_positive_versions(name, value, error):
    with pytest.raises(error):
        binding(**{name: value})
    assert getattr(binding(**{name: 7}), name) == 7


@pytest.mark.parametrize("name", ["operation_id", "parameter_schema_id"])
@pytest.mark.parametrize(
    "value,error",
    [
        (None, TypeError),
        (1, TypeError),
        ("", ValueError),
        ("bad id", ValueError),
        ("bad\x00id", ValueError),
        ("bad\u200bid", ValueError),
    ],
)
def test_binding_identifier_validation(name, value, error):
    with pytest.raises(error):
        binding(**{name: value})
    assert getattr(binding(**{name: "Synthetic:Open-ID"}), name) == "Synthetic:Open-ID"


def test_ports_are_canonical_and_defensively_owned():
    inputs = [input_port("synthetic:z"), input_port("synthetic:a")]
    outputs = [output_port("synthetic:y"), output_port("synthetic:b")]
    value = binding(inputs=inputs, outputs=outputs)
    reordered = binding(
        inputs=list(reversed(inputs)),
        outputs=list(reversed(outputs)),
        handler=value.handler,
    )
    assert value == reordered
    assert [p.port_id for p in value.inputs] == ["synthetic:a", "synthetic:z"]
    assert [p.port_id for p in value.outputs] == ["synthetic:b", "synthetic:y"]
    assert value.inputs[0] is inputs[1] and value.outputs[0] is outputs[1]
    inputs.clear()
    outputs.clear()
    assert len(value.inputs) == len(value.outputs) == 2
    assert type(value.inputs) is type(value.outputs) is tuple


@pytest.mark.parametrize("direction", ["input/input", "output/output", "input/output"])
def test_port_duplicates_rejected_including_cross_direction(direction):
    i = input_port("synthetic:same")
    o = output_port("synthetic:same")
    ins, outs = {
        "input/input": ([i, i], []),
        "output/output": ([], [o, o]),
        "input/output": ([i], [o]),
    }[direction]
    with pytest.raises(ValueError, match="duplicate port_id"):
        binding(inputs=ins, outputs=outs)


@pytest.mark.parametrize("name", ["inputs", "outputs"])
@pytest.mark.parametrize("value", [None, [object()], ["synthetic:port"]])
def test_invalid_port_collections(name, value):
    with pytest.raises(TypeError):
        binding(**{name: value})


def test_ports_require_exact_direction_and_member_types():
    class InputSubclass(InputPortContract):
        pass

    class OutputSubclass(OutputPortContract):
        pass

    for name, value in (
        ("inputs", output_port("synthetic:a")),
        ("outputs", input_port("synthetic:b")),
        ("inputs", InputSubclass(**vars(input_port("synthetic:c")))),
        ("outputs", OutputSubclass(**vars(output_port("synthetic:d")))),
    ):
        with pytest.raises(TypeError):
            binding(**{name: [value]})


def test_capabilities_are_set_like_canonical_owned_and_empty_allowed():
    caps = [CapabilityId("synthetic:z"), CapabilityId("synthetic:a")]
    value = binding(required_capabilities=caps)
    assert value.required_capabilities == tuple(reversed(caps))
    reordered = binding(
        required_capabilities=list(reversed(caps)), handler=value.handler
    )
    assert value == reordered
    caps.clear()
    assert len(value.required_capabilities) == 2
    assert binding().required_capabilities == ()
    with pytest.raises(ValueError, match="duplicate required_capabilities"):
        binding(required_capabilities=[CapabilityId("synthetic:a")] * 2)


def test_capabilities_require_exact_members():
    class CapabilitySubclass(CapabilityId):
        pass

    for caps in (
        None,
        ["synthetic:a"],
        [object()],
        [CapabilitySubclass("synthetic:a")],
    ):
        with pytest.raises(TypeError):
            binding(required_capabilities=caps)


@pytest.mark.parametrize(
    "handler", [None, object(), StaticHandler, "synthetic:handler", lambda: None]
)
def test_handler_requires_direct_static_attachment(handler):
    with pytest.raises(TypeError):
        binding(handler=handler)


@pytest.mark.parametrize("method", ["validate_spec", "prepare", "invoke"])
def test_handler_inspection_never_evaluates_properties_or_dynamic_attributes(method):
    def explode(*args):
        pytest.fail("dynamic adapter attribute executed")

    for member in (None, property(explode)):
        trap = type(
            "Trap", (StaticHandler,), {method: member, "__getattr__": explode}
        )()
        with pytest.raises(TypeError):
            binding(handler=trap)


@pytest.mark.parametrize("kind", list(PluginKind))
def test_complete_registration_seal_and_lookup_never_call_adapters(kind):
    value = binding(
        inputs=[input_port("synthetic:input")],
        outputs=[output_port("synthetic:output")],
    )
    descriptor = desc(kind)
    registration = PluginRegistration(descriptor, factory, [value])
    assert registration.bindings[0] is value
    registry = PluginRegistry(1)
    registry.register(
        registration.descriptor, registration.factory, registration.bindings
    )
    for _ in range(2):
        registry.seal()
        assert registry.is_sealed
        assert registry.resolve(descriptor.ref).descriptor is descriptor
        assert registry.resolve_binding(descriptor.ref, value.operation_id, 1) is value
    with pytest.raises(PluginRegistrySealedError):
        registry.register(desc(kind, "synthetic:other"), factory, (value,))
    assert len(registry) == 1
    assert len(registry._binding_index) == 1


@pytest.mark.parametrize(
    "failure,error",
    [
        ("api", PluginAPIVersionMismatchError),
        ("capability", OperationCapabilityUnsatisfiedError),
        ("duplicate", OperationBindingError),
        ("descriptor", TypeError),
        ("factory", TypeError),
        ("bindings", TypeError),
        ("sealed", PluginRegistrySealedError),
    ],
)
def test_failed_registration_is_atomic_for_both_stores(failure, error):
    registry = PluginRegistry(1)
    old = desc(pid="synthetic:existing")
    good = binding()
    registry.register(old, factory, (good,))
    entries = registry._entries.copy()
    index = registry._binding_index.copy()
    descriptor = desc()
    bindings = (good, binding(operation_id="synthetic:second"))
    make = factory
    if failure == "api":
        descriptor = replace(descriptor, api_version=2)
    elif failure == "capability":
        bindings = (
            good,
            binding(
                operation_id="synthetic:second",
                required_capabilities=(CapabilityId("synthetic:missing"),),
            ),
        )
    elif failure == "duplicate":
        bindings = (
            good,
            replace(
                good,
                validator_revision=2,
                parameter_schema_version=2,
                handler=StaticHandler(),
            ),
        )
    elif failure == "descriptor":
        descriptor = object()
    elif failure == "factory":
        make = object()
    elif failure == "bindings":
        bindings = (good, object())
    elif failure == "sealed":
        registry.seal()
    with pytest.raises(error) as caught:
        registry.register(descriptor, make, bindings)
    assert type(caught.value) is error
    assert not isinstance(caught.value, CapabilityUnavailableError)
    assert registry._entries == entries
    assert registry._binding_index == index
    assert registry.resolve_binding(old.ref, good.operation_id, 1) is good
    with pytest.raises(UnknownPluginError):
        registry.resolve(desc().ref)
    with pytest.raises(UnknownPluginError):
        registry.resolve_binding(desc().ref, good.operation_id, 1)
    assert not any(
        key[:2] == (desc().kind, desc().plugin_id) for key in registry._binding_index
    )


def test_duplicate_plugin_precedes_binding_consistency_and_never_overwrites():
    registry = PluginRegistry(1)
    descriptor = desc()
    value = binding()
    registry.register(descriptor, factory, (value,))
    bad = binding(required_capabilities=(CapabilityId("synthetic:missing"),))
    with pytest.raises(DuplicatePluginRegistrationError):
        registry.register(descriptor, factory, (bad, bad))
    assert registry.resolve_binding(descriptor.ref, value.operation_id, 1) is value
    assert len(registry._entries) == len(registry._binding_index) == 1


def test_derived_duplicate_guard_is_atomic_even_if_index_already_has_key():
    registry = PluginRegistry(1)
    descriptor = desc()
    value = binding()
    key = (descriptor.kind, descriptor.plugin_id, value.operation_id, 1)
    # Normally the primary duplicate guard wins. Exercise the defensive derived
    # collision guard explicitly without adding an orphan-registration API.
    registry._binding_index[key] = value
    with pytest.raises(OperationBindingError, match="^duplicate operation binding$"):
        registry.register(descriptor, factory, (value,))
    assert registry._entries == {}
    assert registry._binding_index == {key: value}


@pytest.mark.parametrize("declared", [True, False])
def test_all_required_capabilities_must_be_declared_statically(declared):
    needed = (CapabilityId("synthetic:a"), CapabilityId("synthetic:b"))
    descriptor = desc(caps=needed if declared else needed[:1])
    value = binding(required_capabilities=needed)
    registry = PluginRegistry(1)
    if not declared:
        with pytest.raises(ContractError) as caught:
            registry.register(descriptor, factory, (value,))
        assert type(caught.value) is OperationCapabilityUnsatisfiedError
        assert not isinstance(caught.value, CapabilityUnavailableError)
        assert registry._entries == registry._binding_index == {}
    else:
        registry.register(descriptor, factory, (value,))
        assert registry.resolve_binding(descriptor.ref, value.operation_id, 1) is value


def test_exact_lookup_supports_revisions_operations_plugins_and_shared_capabilities():
    cap = CapabilityId("synthetic:shared")
    first = binding(required_capabilities=(cap,))
    revision = replace(
        first, operation_api_version=2, validator_revision=7, parameter_schema_version=4
    )
    other = replace(first, operation_id="synthetic:other")
    registry = PluginRegistry(1)
    owners = [
        desc(pid="synthetic:z", caps=(cap,)),
        desc(pid="synthetic:a", caps=(cap,)),
        desc(PluginKind.QC, "synthetic:a", (cap,)),
    ]
    for owner in owners:
        registry.register(owner, factory, (revision, other, first))
    assert set(registry._entries) == {(o.kind, o.plugin_id) for o in owners}
    assert set(registry._binding_index) == {
        (o.kind, o.plugin_id, b.operation_id, b.operation_api_version)
        for o in owners
        for b in (first, revision, other)
    }
    for owner in owners:
        registration = registry.resolve(owner.ref)
        assert registration.ref == owner.ref
        assert [b.operation_id for b in registration.bindings] == [
            revision.operation_id,
            other.operation_id,
            first.operation_id,
        ]
        for b in (first, revision, other):
            assert (
                registry.resolve_binding(
                    owner.ref, b.operation_id, b.operation_api_version
                )
                is b
            )
        for oid, version in ((first.operation_id, 3), ("synthetic:absent", 1)):
            with pytest.raises(
                OperationBindingError, match="^unknown operation binding$"
            ) as caught:
                registry.resolve_binding(owner.ref, oid, version)
            assert type(caught.value) is OperationBindingError
    assert [r.ref.plugin_id for r in registry.registrations(PluginKind.PROCESSOR)] == [
        "synthetic:a",
        "synthetic:z",
    ]


@pytest.mark.parametrize(
    "ref,error",
    [
        (
            PluginRef(PluginKind.PROCESSOR, "synthetic:plugin", 2),
            PluginAPIVersionMismatchError,
        ),
        (PluginRef(PluginKind.PROCESSOR, "synthetic:missing", 2), UnknownPluginError),
    ],
)
def test_owner_resolution_error_precedes_missing_binding(ref, error):
    registry = PluginRegistry(1)
    registry.register(desc(), factory, (binding(),))
    with pytest.raises(error) as caught:
        registry.resolve_binding(ref, "synthetic:absent", 9)
    assert type(caught.value) is error


@pytest.mark.parametrize(
    "oid,version,error",
    [
        ("", 1, ValueError),
        ("bad id", 1, ValueError),
        ("bad\x00id", 1, ValueError),
        (None, 1, TypeError),
        (1, 1, TypeError),
        ("synthetic:o", True, TypeError),
        ("synthetic:o", False, TypeError),
        ("synthetic:o", "1", TypeError),
        ("synthetic:o", 1.0, TypeError),
        ("synthetic:o", 0, ValueError),
        ("synthetic:o", -1, ValueError),
    ],
)
def test_lookup_argument_validation(oid, version, error):
    with pytest.raises(error):
        PluginRegistry(1).resolve_binding(desc().ref, oid, version)


def test_lookup_requires_exact_plugin_ref_and_exact_scalar_types():
    class RefSubclass(PluginRef):
        pass

    class StrSubclass(str):
        pass

    class IntSubclass(int):
        pass

    registry = PluginRegistry(1)
    for ref in (object(), None, RefSubclass(PluginKind.QC, "synthetic:p", 1)):
        with pytest.raises(TypeError):
            registry.resolve_binding(ref, "synthetic:o", 1)
    for oid, version in (
        (StrSubclass("synthetic:o"), 1),
        ("synthetic:o", IntSubclass(1)),
    ):
        with pytest.raises(TypeError):
            registry.resolve_binding(desc().ref, oid, version)
    for name in ("operation_id", "parameter_schema_id"):
        with pytest.raises(TypeError):
            binding(**{name: StrSubclass("synthetic:value")})
    for name in (
        "operation_api_version",
        "parameter_schema_version",
        "validator_revision",
    ):
        with pytest.raises(TypeError):
            binding(**{name: IntSubclass(1)})


def test_final_lookup_signature_is_explicit_and_has_no_defaults():
    assert list(signature(PluginRegistry.resolve_binding).parameters) == [
        "self",
        "plugin_ref",
        "operation_id",
        "operation_api_version",
    ]
    assert get_type_hints(PluginRegistry.resolve_binding) == {
        "plugin_ref": PluginRef,
        "operation_id": str,
        "operation_api_version": int,
        "return": OperationBinding,
    }
