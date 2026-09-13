from insarforge.core.exceptions import InSARForgeError


class ContractError(InSARForgeError):
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
