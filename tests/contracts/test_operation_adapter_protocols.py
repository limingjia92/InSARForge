import ast
from inspect import Parameter, signature
from pathlib import Path
from typing import Protocol, get_type_hints

import pytest

from insarforge.contracts import operations
from insarforge.contracts.context import ExecutionContext, ResourceAllocation
from insarforge.contracts.operations import (
    ArtifactDraft,
    InputCodec,
    InputPortContract,
    OperationHandler,
    OutputCodec,
    OutputPortContract,
    OutputRecord,
    PortRecord,
    PortValidator,
    PreparedExecution,
    ProbeContext,
    ProductProfileRef,
    RecordSchemaRef,
    ResolvedInput,
    ResolvedInputs,
    TaskOutcome,
)
from insarforge.contracts.plugins import (
    QC,
    Analyzer,
    Correction,
    Mission,
    Processor,
    Provider,
)
from insarforge.contracts.values import ArtifactRef, FrozenJSON
from insarforge.products.semantics import SemanticValue
from insarforge.products.validation import ProductValidationReport

METHODS = [
    (
        InputCodec,
        "decode",
        {"artifact": ArtifactRef, "payload": bytes, "schema": RecordSchemaRef},
        ResolvedInput,
    ),
    (
        OutputCodec,
        "encode",
        {"value": OutputRecord, "schema": RecordSchemaRef},
        ArtifactDraft,
    ),
    (
        PortValidator,
        "validate",
        {
            "value": PortRecord,
            "schema": RecordSchemaRef,
            "profile": ProductProfileRef | None,
        },
        ProductValidationReport,
    ),
    (
        OperationHandler,
        "validate_spec",
        {
            "parameters": FrozenJSON,
            "inputs": tuple[InputPortContract, ...],
            "outputs": tuple[OutputPortContract, ...],
        },
        ProductValidationReport,
    ),
    (
        OperationHandler,
        "prepare",
        {
            "plugin": Mission | Provider | Processor | Correction | Analyzer | QC,
            "resolved_inputs": ResolvedInputs,
            "parameters": FrozenJSON,
            "probe_context": ProbeContext,
        },
        PreparedExecution,
    ),
    (
        OperationHandler,
        "invoke",
        {
            "plugin": Mission | Provider | Processor | Correction | Analyzer | QC,
            "prepared": PreparedExecution,
            "resolved_inputs": ResolvedInputs,
            "parameters": FrozenJSON,
            "context": ExecutionContext,
        },
        TaskOutcome,
    ),
]


@pytest.mark.parametrize("protocol,method,arguments,result", METHODS)
def test_exact_adapter_signatures_resolve_from_normal_module_globals(
    protocol, method, arguments, result
):
    declaration = vars(protocol)[method]
    params = signature(declaration).parameters
    assert tuple(params) == ("self", *arguments)
    assert all(
        p.kind is Parameter.POSITIONAL_OR_KEYWORD and p.default is Parameter.empty
        for p in params.values()
    )
    expected = arguments | {"return": result}
    assert declaration.__annotations__ == expected
    # get_type_hints expands recursive FrozenJSON, so its resolved form is not
    # equal to the original alias expression. Resolution must still succeed
    # without supplying a custom namespace or importing future runtime types.
    assert set(get_type_hints(declaration)) == set(expected)


@pytest.mark.parametrize(
    "protocol,members",
    [
        (ProbeContext, {"allocated_resources"}),
        (PreparedExecution, {"semantic_execution_identity", "preparation"}),
        (InputCodec, {"decode"}),
        (OutputCodec, {"encode"}),
        (PortValidator, {"validate"}),
        (OperationHandler, {"validate_spec", "prepare", "invoke"}),
    ],
)
def test_exact_public_protocol_surfaces_without_runtime_decoration(protocol, members):
    assert protocol.__bases__ == (Protocol,)
    assert {name for name in vars(protocol) if not name.startswith("_")} == members
    assert not {"run", "execute", "__call__"} & set(vars(protocol))
    with pytest.raises(TypeError):
        protocol()
    # Presence validation at construction is separate from runtime Protocol checks.
    with pytest.raises(TypeError):
        isinstance(object(), protocol)


@pytest.mark.parametrize(
    "protocol,member,result",
    [
        (ProbeContext, "allocated_resources", ResourceAllocation),
        (PreparedExecution, "semantic_execution_identity", SemanticValue[FrozenJSON]),
        (PreparedExecution, "preparation", FrozenJSON),
    ],
)
def test_support_views_are_read_only_properties(protocol, member, result):
    view = vars(protocol)[member]
    assert type(view) is property
    assert view.fset is None and view.fdel is None
    assert tuple(signature(view.fget).parameters) == ("self",)
    assert view.fget.__annotations__ == {"return": result}
    assert set(get_type_hints(view.fget)) == {"return"}


class DeclarationOnlyHandler:
    def validate_spec(
        self,
        parameters: FrozenJSON,
        inputs: tuple[InputPortContract, ...],
        outputs: tuple[OutputPortContract, ...],
    ) -> ProductValidationReport:
        pytest.fail("semantic validation must not execute in this gate")

    def prepare(
        self,
        plugin: operations.PluginInstance,
        resolved_inputs: ResolvedInputs,
        parameters: FrozenJSON,
        probe_context: ProbeContext,
    ) -> PreparedExecution:
        pytest.fail("preparation must not execute in this gate")

    def invoke(
        self,
        plugin: operations.PluginInstance,
        prepared: PreparedExecution,
        resolved_inputs: ResolvedInputs,
        parameters: FrozenJSON,
        context: ExecutionContext,
    ) -> TaskOutcome:
        pytest.fail("invocation must not execute in this gate")


def test_neutral_handler_declarations_conform_without_execution_or_family_narrowing():
    handler: OperationHandler = DeclarationOnlyHandler()
    assert type(handler) is DeclarationOnlyHandler
    for method in ("validate_spec", "prepare", "invoke"):
        assert get_type_hints(vars(DeclarationOnlyHandler)[method]) == get_type_hints(
            vars(OperationHandler)[method]
        )
        assert tuple(
            signature(vars(DeclarationOnlyHandler)[method]).parameters
        ) == tuple(signature(vars(OperationHandler)[method]).parameters)
    assert get_type_hints(DeclarationOnlyHandler.invoke)["plugin"] != Processor


def test_shared_values_and_report_are_reused_without_alias_classes():
    assert operations.ExecutionContext is ExecutionContext
    assert operations.ResourceAllocation is ResourceAllocation
    assert operations.FrozenJSON is FrozenJSON
    assert operations.SemanticValue is SemanticValue
    assert operations.ProductValidationReport is ProductValidationReport
    assert (
        OperationHandler.validate_spec.__annotations__["return"]
        is ProductValidationReport
    )
    assert PortValidator.validate.__annotations__["return"] is ProductValidationReport


def test_protocols_have_no_execution_bodies_and_new_ports_only_validate_locally():
    tree = ast.parse(Path(operations.__file__).read_text())
    approved = {
        "ProbeContext",
        "PreparedExecution",
        "OperationHandler",
        "InputCodec",
        "OutputCodec",
        "PortValidator",
    }
    declarations = {
        node.name: node for node in tree.body if isinstance(node, ast.ClassDef)
    }
    for name in approved:
        for method in declarations[name].body:
            if isinstance(method, ast.FunctionDef):
                # Docstrings and ellipses only: no executed adapter implementation.
                assert all(
                    isinstance(statement, ast.Expr)
                    and isinstance(statement.value, ast.Constant)
                    and (
                        statement.value.value is Ellipsis
                        or isinstance(statement.value.value, str)
                    )
                    for statement in method.body
                )
    for name in ("InputPortContract", "OutputPortContract"):
        assert {
            node.name
            for node in declarations[name].body
            if isinstance(node, ast.FunctionDef)
        } == {"__post_init__"}
    assert (
        not {"Plugin", "PluginProtocol", "BasePlugin", "TaskSpec", "WorkflowPlan"}
        & declarations.keys()
    )
    assert not {
        "handler_id",
        "codec_id",
        "ParameterValidator",
        "OperationBindingRegistry",
    } & set(vars(operations))


def test_port_member_inspection_does_not_pretend_to_validate_signatures():
    # No runtime_checkable decoration or callback can prove an adapter body.
    # These tests validate frozen type/signature declarations, while port tests
    # independently exercise safe method-presence checks and descriptor traps.
    declaration = get_type_hints(InputCodec.decode)
    assert declaration["payload"] is bytes
    assert (
        get_type_hints(OperationHandler.validate_spec)["inputs"]
        == tuple[InputPortContract, ...]
    )
    assert "parameters" not in get_type_hints(PortValidator.validate)
