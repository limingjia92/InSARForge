import pytest

from insarforge.contracts import errors
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
from insarforge.core import operation_binding, registry
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


@pytest.mark.parametrize(
    "name,parent,old_module",
    [
        ("PluginRegistryError", "ContractError", registry),
        ("DuplicatePluginRegistrationError", "PluginRegistryError", registry),
        ("UnknownPluginError", "PluginRegistryError", registry),
        ("PluginRegistrySealedError", "PluginRegistryError", registry),
        ("PluginAPIVersionMismatchError", "PluginRegistryError", registry),
        ("OperationBindingError", "ContractError", operation_binding),
        (
            "OperationCapabilityUnsatisfiedError",
            "OperationBindingError",
            operation_binding,
        ),
    ],
)
def test_canonical_registry_binding_errors(name, parent, old_module):
    exception = getattr(errors, name)
    assert getattr(old_module, name) is exception
    assert exception.__module__ == "insarforge.contracts.errors"
    assert exception.__bases__ == (getattr(errors, parent),)
    assert issubclass(exception, InSARForgeError)
    assert not issubclass(exception, RuntimeError)
    with pytest.raises(ContractError) as caught:
        raise exception("synthetic failure")
    assert type(caught.value) is exception
