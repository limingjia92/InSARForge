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
    registry.register(descriptor, lambda: called.append(True))
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
    registry.register(descriptor, factory)
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
        registry.register(replace(descriptor, api_version=2), factory)
    assert type(caught.value) is PluginAPIVersionMismatchError
    assert len(registry) == 0
    registry.register(descriptor, factory)
    with pytest.raises(ContractError) as caught:
        registry.register(descriptor, factory)
    assert type(caught.value) is DuplicatePluginRegistrationError
    registry.seal()
    with pytest.raises(ContractError) as caught:
        registry.register(replace(descriptor, plugin_id="synthetic:other"), factory)
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
        PluginRegistration(object(), lambda: None)
