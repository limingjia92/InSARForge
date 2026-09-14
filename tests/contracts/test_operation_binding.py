import pytest

from insarforge.contracts.errors import (
    CapabilityUnavailableError,
    ContractError,
    OperationCapabilityUnsatisfiedError,
    PluginAPIVersionMismatchError,
    UnknownPluginError,
)
from insarforge.contracts.identity import (
    CapabilityId,
    PluginDescriptor,
    PluginKind,
    PluginRef,
)
from insarforge.contracts.operations import OperationBinding, OperationRequirement
from insarforge.core.operation_binding import resolve_operation_binding
from insarforge.core.registry import PluginRegistry


def desc(kind, pid, caps=("cap:test",)):
    return PluginDescriptor(
        kind, pid, 1, "1", pid, tuple(CapabilityId(c) for c in caps)
    )


def test_requirement_binding_and_resolution():
    d = desc(PluginKind.PROCESSOR, "p1")
    r = PluginRegistry(1)
    r.register(d, lambda: object())
    b = OperationBinding(
        OperationRequirement(
            "operation:test-a", PluginKind.PROCESSOR, CapabilityId("cap:test")
        ),
        d.ref,
    )
    assert resolve_operation_binding(b, r) is d


def test_absent_and_unknown():
    r = PluginRegistry(1)
    d = desc(PluginKind.PROVIDER, "p1", ("cap:other",))
    r.register(d, lambda: object())
    b = OperationBinding(
        OperationRequirement(
            "operation:test", PluginKind.PROVIDER, CapabilityId("cap:req")
        ),
        d.ref,
    )
    with pytest.raises(OperationCapabilityUnsatisfiedError):
        resolve_operation_binding(b, r)
    with pytest.raises(UnknownPluginError):
        resolve_operation_binding(
            OperationBinding(
                b.requirement, PluginRef(PluginKind.PROVIDER, "missing", 1)
            ),
            r,
        )


def test_all_kinds_and_mismatch():
    for k in PluginKind:
        d = desc(k, k.value)
        r = PluginRegistry(1)
        r.register(d, lambda: object())
        b = OperationBinding(
            OperationRequirement("operation:x", k, CapabilityId("cap:test")), d.ref
        )
        assert resolve_operation_binding(b, r) is d
    with pytest.raises(ValueError):
        OperationBinding(
            OperationRequirement(
                "operation:x", PluginKind.PROVIDER, CapabilityId("cap:test")
            ),
            PluginRef(PluginKind.QC, "q", 1),
        )


@pytest.mark.parametrize("declared", [True, False])
def test_binding_requested_api_and_declared_capability_only(declared):
    descriptor = desc(
        PluginKind.PROCESSOR,
        "synthetic:plugin",
        caps=("synthetic:needed",) if declared else (),
    )
    registry = PluginRegistry(1)

    def factory():
        pytest.fail("static binding resolution must not probe runtime availability")

    registry.register(descriptor, factory)
    registry.seal()
    requirement = OperationRequirement(
        "synthetic:operation", descriptor.kind, CapabilityId("synthetic:needed")
    )
    mismatched = OperationBinding(
        requirement, PluginRef(descriptor.kind, descriptor.plugin_id, 2)
    )
    with pytest.raises(ContractError) as caught:
        resolve_operation_binding(mismatched, registry)
    assert type(caught.value) is PluginAPIVersionMismatchError
    binding = OperationBinding(requirement, descriptor.ref)
    if declared:
        assert resolve_operation_binding(binding, registry) is descriptor
    else:
        with pytest.raises(ContractError) as caught:
            resolve_operation_binding(binding, registry)
        assert type(caught.value) is OperationCapabilityUnsatisfiedError
        assert not isinstance(caught.value, CapabilityUnavailableError)
