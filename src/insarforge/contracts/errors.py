from insarforge.core.exceptions import InSARForgeError


class ContractError(InSARForgeError):
    pass


class PluginRegistryError(ContractError):
    pass


class DuplicatePluginRegistrationError(PluginRegistryError):
    pass


class UnknownPluginError(PluginRegistryError):
    pass


class PluginRegistrySealedError(PluginRegistryError):
    pass


class PluginAPIVersionMismatchError(PluginRegistryError):
    pass


class OperationBindingError(ContractError):
    pass


class OperationCapabilityUnsatisfiedError(OperationBindingError):
    pass


class CapabilityUnavailableError(ContractError):
    pass


class InputValidationError(ContractError):
    pass


class ExecutionError(InSARForgeError):
    pass


class RetryableExecutionError(ExecutionError):
    pass


class OutputValidationError(ExecutionError):
    pass


class WorkflowStateError(InSARForgeError):
    pass


class WorkspaceError(InSARForgeError):
    pass
