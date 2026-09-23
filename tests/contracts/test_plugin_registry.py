from dataclasses import replace

import pytest

from insarforge.contracts.errors import (
    ContractError,
    DuplicatePluginRegistrationError,
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
from insarforge.core.registry import PluginRegistration, PluginRegistry


def test_registry_stores_metadata_without_factory_invocation():
    called = []
    descriptor = PluginDescriptor(
        PluginKind.MISSION, "plugin:test", 1, "1", "Test", (CapabilityId("cap:test"),)
    )
    registry = PluginRegistry(1)
    registry.register(descriptor, lambda: called.append(True), ())
    assert registry.get_descriptor(descriptor.ref) == descriptor
    assert called == []


@pytest.mark.parametrize("lookup", ["resolve", "get_descriptor"])
def test_requested_api_is_exact_without_factory_invocation(lookup):
    def factory():
        pytest.fail("static registry lookup must not instantiate plugins")

    descriptor = PluginDescriptor(
        PluginKind.PROCESSOR, "synthetic:plugin", 1, "1", "Synthetic", ()
    )
    registry = PluginRegistry(1)
    registry.register(descriptor, factory, ())
    registry.seal()
    resolve = getattr(registry, lookup)
    resolved = resolve(descriptor.ref)
    assert (resolved.descriptor if lookup == "resolve" else resolved) is descriptor
    with pytest.raises(ContractError) as caught:
        resolve(replace(descriptor.ref, api_version=2))
    assert type(caught.value) is PluginAPIVersionMismatchError
    # Unknown keys remain unknown, even when their requested API also differs.
    with pytest.raises(ContractError) as caught:
        resolve(replace(descriptor.ref, plugin_id="synthetic:missing", api_version=2))
    assert type(caught.value) is UnknownPluginError
    assert registry.get_descriptor(descriptor.ref) is descriptor
    assert len(registry) == 1


def test_registration_domain_failures_use_canonical_contract_errors():
    descriptor = PluginDescriptor(
        PluginKind.PROCESSOR, "synthetic:plugin", 1, "1", "Synthetic", ()
    )
    registry = PluginRegistry(1)

    def factory():
        pytest.fail("registration must not instantiate plugins")

    with pytest.raises(ContractError) as caught:
        registry.register(replace(descriptor, api_version=2), factory, ())
    assert type(caught.value) is PluginAPIVersionMismatchError
    assert len(registry) == 0
    registry.register(descriptor, factory, ())
    with pytest.raises(ContractError) as caught:
        registry.register(descriptor, factory, ())
    assert type(caught.value) is DuplicatePluginRegistrationError
    registry.seal()
    with pytest.raises(ContractError) as caught:
        registry.register(replace(descriptor, plugin_id="synthetic:other"), factory, ())
    assert type(caught.value) is PluginRegistrySealedError
    assert registry.descriptors() == (descriptor,)


def test_registry_programmer_argument_errors_remain_builtins():
    for value in (True, "1", 1.0):
        with pytest.raises(TypeError):
            PluginRegistry(value)
        with pytest.raises(TypeError):
            PluginRef(PluginKind.QC, "synthetic:plugin", value)
    with pytest.raises(ValueError):
        PluginRegistry(0)
    registry = PluginRegistry(1)
    with pytest.raises(TypeError):
        registry.resolve(object())
    with pytest.raises(TypeError):
        PluginRegistration(object(), lambda: None, ())


class DeclarationHandler:
    def validate_spec(self, parameters, inputs, outputs):
        pytest.fail("validate_spec called")

    def prepare(self, plugin, resolved_inputs, parameters, probe_context):
        pytest.fail("prepare called")

    def invoke(self, plugin, prepared, resolved_inputs, parameters, context):
        pytest.fail("invoke called")


def final_binding(operation_id):
    from insarforge.contracts.operations import OperationBinding

    return OperationBinding(
        operation_id, 1, "synthetic:parameters", 1, (), (), (), 1, DeclarationHandler()
    )


def test_registration_exact_required_ownership_and_defensive_enumeration_order():
    from dataclasses import MISSING, FrozenInstanceError, fields
    from inspect import signature
    from typing import get_type_hints

    from insarforge.contracts.operations import OperationBinding

    descriptor = PluginDescriptor(
        PluginKind.QC, "synthetic:plugin", 1, "1", "Synthetic", ()
    )

    def factory():
        pytest.fail("factory called")

    assert [f.name for f in fields(PluginRegistration)] == [
        "descriptor",
        "factory",
        "bindings",
    ]
    assert all(
        f.default is MISSING and f.default_factory is MISSING
        for f in fields(PluginRegistration)
    )
    assert (
        get_type_hints(PluginRegistration)["bindings"] == tuple[OperationBinding, ...]
    )
    assert list(signature(PluginRegistry.register).parameters) == [
        "self",
        "descriptor",
        "factory",
        "bindings",
    ]
    with pytest.raises(TypeError):
        PluginRegistration(descriptor, factory)
    registry = PluginRegistry(1)
    with pytest.raises(TypeError):
        registry.register(descriptor, factory)
    assert registry._entries == registry._binding_index == {}
    assert PluginRegistration(descriptor, factory, ()).bindings == ()
    values = [final_binding("synthetic:z"), final_binding("synthetic:a")]
    registration = PluginRegistration(descriptor, factory, values)
    registry.register(descriptor, factory, values)
    values.clear()
    assert type(registration.bindings) is tuple
    assert [b.operation_id for b in registration.bindings] == [
        "synthetic:z",
        "synthetic:a",
    ]
    assert registry.resolve(descriptor.ref).bindings == registration.bindings
    assert registration.ref == descriptor.ref
    assert registration.factory is factory
    assert (
        len(PluginRegistration(descriptor, factory, registration.bindings[:1]).bindings)
        == 1
    )
    with pytest.raises(FrozenInstanceError):
        registration.bindings = ()


def test_registration_checks_local_shape_only_and_exact_member_types():
    from insarforge.contracts.operations import OperationBinding

    class DescriptorSubclass(PluginDescriptor):
        pass

    class BindingSubclass(OperationBinding):
        pass

    descriptor = PluginDescriptor(
        PluginKind.QC, "synthetic:plugin", 1, "1", "Synthetic", ()
    )
    value = final_binding("synthetic:operation")

    def factory():
        pytest.fail("factory called")

    invalid = [
        (object(), factory, ()),
        (DescriptorSubclass(**vars(descriptor)), factory, ()),
        (descriptor, object(), ()),
        (descriptor, factory, None),
        (descriptor, factory, [object()]),
        (descriptor, factory, [BindingSubclass(**vars(value))]),
    ]
    for args in invalid:
        with pytest.raises(TypeError):
            PluginRegistration(*args)
        registry = PluginRegistry(1)
        with pytest.raises(TypeError):
            registry.register(*args)
        assert registry._entries == registry._binding_index == {}
    # Cross-object capability/identity consistency belongs to register, not the
    # immutable local shape constructor.
    undeclared = replace(
        value, required_capabilities=(CapabilityId("synthetic:missing"),)
    )
    registration = PluginRegistration(descriptor, factory, (undeclared, undeclared))
    assert registration.bindings[0] is undeclared
    assert len(registration.bindings) == 2
