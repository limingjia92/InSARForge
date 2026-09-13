import pytest
from insarforge.contracts.identity import CapabilityId, PluginDescriptor, PluginKind, PluginRef
from insarforge.contracts.operations import OperationBinding, OperationRequirement
from insarforge.core.operation_binding import OperationCapabilityUnsatisfiedError, resolve_operation_binding
from insarforge.core.registry import PluginRegistry, UnknownPluginError


def desc(kind, pid, caps=("cap:test",)):
    return PluginDescriptor(kind, pid, 1, "1", pid, tuple(CapabilityId(c) for c in caps))


def test_requirement_binding_and_resolution():
    d = desc(PluginKind.PROCESSOR, "p1")
    r = PluginRegistry(1); r.register(d, lambda: object())
    b = OperationBinding(OperationRequirement("operation:test-a", PluginKind.PROCESSOR, CapabilityId("cap:test")), d.ref)
    assert resolve_operation_binding(b, r) is d


def test_absent_and_unknown():
    r = PluginRegistry(1); d = desc(PluginKind.PROVIDER, "p1", ("cap:other",)); r.register(d, lambda: object())
    b = OperationBinding(OperationRequirement("operation:test", PluginKind.PROVIDER, CapabilityId("cap:req")), d.ref)
    with pytest.raises(OperationCapabilityUnsatisfiedError): resolve_operation_binding(b, r)
    with pytest.raises(UnknownPluginError): resolve_operation_binding(OperationBinding(b.requirement, PluginRef(PluginKind.PROVIDER, "missing", 1)), r)


def test_all_kinds_and_mismatch():
    for k in PluginKind:
        d = desc(k, k.value); r = PluginRegistry(1); r.register(d, lambda: object())
        b = OperationBinding(OperationRequirement("operation:x", k, CapabilityId("cap:test")), d.ref)
        assert resolve_operation_binding(b, r) is d
    with pytest.raises(ValueError): OperationBinding(OperationRequirement("operation:x", PluginKind.PROVIDER, CapabilityId("cap:test")), PluginRef(PluginKind.QC, "q", 1))
