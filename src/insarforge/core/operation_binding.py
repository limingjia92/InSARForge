from insarforge.contracts.errors import OperationBindingError as OperationBindingError
from insarforge.contracts.errors import (
    OperationCapabilityUnsatisfiedError as OperationCapabilityUnsatisfiedError,
)
from insarforge.contracts.identity import PluginDescriptor
from insarforge.contracts.operations import OperationBinding
from insarforge.core.registry import PluginRegistry


def resolve_operation_binding(
    binding: OperationBinding, registry: PluginRegistry
) -> PluginDescriptor:
    if not isinstance(binding, OperationBinding):
        raise TypeError("binding")
    if not isinstance(registry, PluginRegistry):
        raise TypeError("registry")
    descriptor = registry.resolve(binding.plugin_ref).descriptor
    # capabilities are static declarations; runtime availability is deferred to P4.2.
    if binding.capability not in descriptor.capabilities:
        raise OperationCapabilityUnsatisfiedError(
            f"operation {binding.operation_id} requires {binding.plugin_kind.value}/"
            f"{binding.plugin_ref.plugin_id} capability {binding.capability.value}: absent"
        )
    return descriptor
