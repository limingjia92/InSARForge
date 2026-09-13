from insarforge.contracts.identity import CapabilityId, PluginDescriptor, PluginKind
from insarforge.core.registry import PluginRegistry


def test_registry_stores_metadata_without_factory_invocation():
    called = []
    descriptor = PluginDescriptor(
        PluginKind.MISSION, "plugin:test", 1, "1", "Test", (CapabilityId("cap:test"),)
    )
    registry = PluginRegistry(1)
    registry.register(descriptor, lambda: called.append(True))
    assert registry.get_descriptor(descriptor.ref) == descriptor
    assert called == []
