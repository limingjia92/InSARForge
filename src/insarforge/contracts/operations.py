from dataclasses import dataclass
from insarforge.contracts.identity import CapabilityId, PluginKind, PluginRef
from insarforge.contracts.values import validate_identifier

@dataclass(frozen=True)
class OperationRequirement:
    operation_id: str
    plugin_kind: PluginKind
    capability: CapabilityId
    def __post_init__(self):
        validate_identifier(self.operation_id)
        if not isinstance(self.plugin_kind, PluginKind): raise TypeError("plugin_kind")
        if not isinstance(self.capability, CapabilityId): raise TypeError("capability")

@dataclass(frozen=True)
class OperationBinding:
    requirement: OperationRequirement
    plugin_ref: PluginRef
    def __post_init__(self):
        if not isinstance(self.requirement, OperationRequirement): raise TypeError("requirement")
        if not isinstance(self.plugin_ref, PluginRef): raise TypeError("plugin_ref")
        if self.plugin_ref.kind is not self.requirement.plugin_kind: raise ValueError("plugin kind mismatch")
    @property
    def operation_id(self): return self.requirement.operation_id
    @property
    def plugin_kind(self): return self.requirement.plugin_kind
    @property
    def capability(self): return self.requirement.capability
