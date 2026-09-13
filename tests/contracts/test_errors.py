from insarforge.contracts.errors import (
    CapabilityUnavailableError,
    ContractError,
    ExecutionError,
    InputValidationError,
    OutputValidationError,
    RetryableExecutionError,
    WorkflowStateError,
    WorkspaceError,
)
from insarforge.core.exceptions import InSARForgeError


def test_hierarchy():
    assert issubclass(ContractError, InSARForgeError)
    assert issubclass(CapabilityUnavailableError, ContractError)
    assert issubclass(InputValidationError, ContractError)
    assert issubclass(ExecutionError, InSARForgeError)
    assert issubclass(RetryableExecutionError, ExecutionError)
    assert issubclass(OutputValidationError, ExecutionError)
    assert issubclass(WorkflowStateError, InSARForgeError)
    assert issubclass(WorkspaceError, InSARForgeError)
