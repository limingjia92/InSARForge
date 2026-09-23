"""Explicit family adapters composed with the frozen registry and typed ports."""

import hashlib
from dataclasses import dataclass
from pathlib import Path

from insarforge.contracts.context import ExecutionContext
from insarforge.contracts.errors import InputValidationError, OutputValidationError
from insarforge.contracts.operations import (
    ArtifactDraft,
    InputPortContract,
    OperationBinding,
    OutputPortContract,
    PluginInstance,
    PreparedExecution,
    ProbeContext,
    ProductProfileRef,
    RecordSchemaRef,
    ResolvedInput,
    ResolvedInputs,
    TaskOutcome,
)
from insarforge.contracts.plugins import (
    AcquireRequest,
    AnalysisRequest,
    CorrectionRequest,
    InspectionRequest,
    ProcessingRequest,
    ProductInput,
    QCRequest,
    SearchRequest,
)
from insarforge.contracts.record_serialization import record_from_bytes, record_to_bytes
from insarforge.contracts.records import (
    AcquisitionMetadata,
    CatalogSnapshot,
    CorrectionSpec,
    QCReport,
)
from insarforge.contracts.values import FrozenJSON, freeze_json
from insarforge.core.registry import PluginRegistry
from insarforge.products.models import Product, ProductDraft
from insarforge.products.semantics import SemanticStatus, SemanticValue
from insarforge.products.validation import (
    ProductValidationReport,
    ValidationIssue,
    ValidationIssueKind,
    validate_product_structure,
)

from ._fake_plugins import (
    Controls,
    FakeAnalyzer,
    FakeConfig,
    FakeCorrection,
    FakeMission,
    FakeProcessor,
    FakeProvider,
    FakeQC,
    known,
)

PRODUCT = RecordSchemaRef("insarforge:product", 2)
CATALOG = RecordSchemaRef("synthetic:catalog", 1)
ACQUISITION = RecordSchemaRef("synthetic:acquisition", 1)
QC = RecordSchemaRef("synthetic:qc", 1)
PROFILE = ProductProfileRef("synthetic:profile", 1)


def invalid(code):
    return ProductValidationReport(
        (ValidationIssue(ValidationIssueKind.ERROR, code, "synthetic", {}),)
    )


@dataclass(frozen=True)
class PortValidator:
    def validate(self, value, schema, profile):
        expected = {
            PRODUCT: (Product, ProductDraft),
            CATALOG: (CatalogSnapshot,),
            ACQUISITION: (AcquisitionMetadata,),
            QC: (QCReport,),
        }
        if schema not in expected or type(value) not in expected[schema]:
            return invalid("synthetic:record-type")
        if type(value) is not ProductDraft and (
            value.schema_id,
            value.schema_version,
        ) != (schema.schema_id, schema.schema_version):
            return invalid("synthetic:schema")
        if profile is not None:
            if (
                profile != PROFILE
                or type(value) not in (Product, ProductDraft)
                or (value.profile_id, value.profile_version)
                != (profile.profile_id, profile.profile_version)
            ):
                return invalid("synthetic:profile")
        if type(value) in (Product, ProductDraft):
            return validate_product_structure(value)
        # Exercise the existing strict record wire boundary, without locator I/O.
        try:
            record_to_bytes(value)
        except (TypeError, ValueError):
            return invalid("synthetic:record-wire")
        return ProductValidationReport(())


@dataclass(frozen=True)
class Codec:
    def decode(self, artifact, payload, schema):
        try:
            if (artifact.schema_id, artifact.schema_version) != (
                schema.schema_id,
                schema.schema_version,
            ):
                raise ValueError("schema")
            value = record_from_bytes(artifact, payload)
            if not PortValidator().validate(value, schema, None).is_fully_verified:
                raise ValueError("record")
            return ResolvedInput(artifact, value)
        except Exception:
            raise InputValidationError("SYNTHETIC_INPUT_INVALID") from None

    def encode(self, value, schema):
        if not PortValidator().validate(value, schema, None).is_fully_verified:
            raise OutputValidationError("SYNTHETIC_OUTPUT_INVALID")
        try:
            return ArtifactDraft(schema, value)
        except (TypeError, ValueError):
            raise OutputValidationError("SYNTHETIC_OUTPUT_INVALID") from None


@dataclass(frozen=True)
class Prepared:
    semantic_execution_identity: SemanticValue[FrozenJSON]
    preparation: FrozenJSON

    def __post_init__(self):
        object.__setattr__(self, "preparation", freeze_json(self.preparation))


@dataclass(frozen=True)
class Adapter:
    """Shared operation lifecycle only; family business dispatch is explicit below."""

    operation: str
    plugin_type: type
    config: FakeConfig
    controls: Controls
    inputs: tuple[InputPortContract, ...]
    outputs: tuple[OutputPortContract, ...]
    wrapper_digest: str

    def validate_spec(
        self,
        parameters: FrozenJSON,
        inputs: tuple[InputPortContract, ...],
        outputs: tuple[OutputPortContract, ...],
    ) -> ProductValidationReport:
        # This in-memory test observer performs no registry/business/codec/I/O work.
        self.controls.journal.record("validate", self.operation)
        if inputs != self.inputs or outputs != self.outputs:
            return invalid("synthetic:declarations")
        if (
            not hasattr(parameters, "keys")
            or set(parameters) != {"label"}
            or type(parameters["label"]) is not str
        ):
            return invalid("synthetic:parameters")
        return ProductValidationReport(())

    def prepare(
        self,
        plugin: PluginInstance,
        resolved_inputs: ResolvedInputs,
        parameters: FrozenJSON,
        probe_context: ProbeContext,
    ) -> PreparedExecution:
        if type(plugin) is not self.plugin_type or plugin.config != self.config:
            raise InputValidationError("SYNTHETIC_PLUGIN_MISMATCH")
        self.controls.journal.record("prepare", self.operation)
        # Failure ordinals and task IDs are observations, not successful-result semantics.
        settings = freeze_json(
            {
                "operation": self.operation,
                "variant": self.config.variant,
                "parameters": parameters,
            }
        )
        return Prepared(
            known(
                {
                    "schema_version": 1,
                    "wrapper_digest": self.wrapper_digest,
                    "native_components": {},
                    "settings": settings,
                    "external_resource_digests": {},
                }
            ),
            settings,
        )

    def invoke(
        self,
        plugin: PluginInstance,
        prepared: PreparedExecution,
        resolved_inputs: ResolvedInputs,
        parameters: FrozenJSON,
        context: ExecutionContext,
    ) -> TaskOutcome:
        if type(plugin) is not self.plugin_type or plugin.config != self.config:
            raise InputValidationError("SYNTHETIC_PLUGIN_MISMATCH")
        if (
            prepared.preparation["operation"] != self.operation
            or prepared.preparation["parameters"] != parameters
        ):
            raise InputValidationError("SYNTHETIC_PREPARATION_MISMATCH")
        self.controls.before_invoke(self.operation, context)
        result = self._business(plugin, resolved_inputs, parameters, context)
        values = result if type(result) is tuple else (result,)
        port = self.outputs[0]
        if len(values) != port.count:
            raise OutputValidationError("SYNTHETIC_OUTPUT_COUNT")
        drafts = []
        for value in values:
            if not port.validator.validate(
                value, port.schema, port.profile
            ).is_fully_verified:
                raise OutputValidationError("SYNTHETIC_OUTPUT_CONTRACT")
            drafts.append(port.codec.encode(value, port.schema))
        return TaskOutcome({port.port_id: tuple(drafts)}, ())


def products(inputs, port="source"):
    return {
        port: tuple(ProductInput(item.artifact, item.value) for item in inputs[port])
    }


class InspectAdapter(Adapter):
    def _business(self, plugin, inputs, parameters, context):
        source = inputs["source"][0]
        return plugin.inspect(
            InspectionRequest(ProductInput(source.artifact, source.value), parameters),
            context,
        )


class SearchAdapter(Adapter):
    def _business(self, plugin, inputs, parameters, context):
        return plugin.search(SearchRequest("synthetic:query", 1, parameters), context)


class AcquireAdapter(Adapter):
    def _business(self, plugin, inputs, parameters, context):
        catalog = inputs["catalog"][0]
        if type(catalog.value) is not CatalogSnapshot or not catalog.value.entries:
            raise InputValidationError("SYNTHETIC_CATALOG_EMPTY")
        return plugin.acquire(
            AcquireRequest(
                catalog.artifact, catalog.value.entries[0].entry_id, parameters
            ),
            context,
        )


class ProcessAdapter(Adapter):
    def _business(self, plugin, inputs, parameters, context):
        return plugin.process(
            ProcessingRequest(
                "synthetic:purpose",
                PROFILE.profile_id,
                1,
                products(inputs),
                tuple(item.artifact for item in inputs["metadata"]),
                {},
                parameters,
            ),
            context,
        )


class CorrectAdapter(Adapter):
    def _business(self, plugin, inputs, parameters, context):
        absent = SemanticValue(
            SemanticStatus.NOT_APPLICABLE, None, "synthetic:no-science", ()
        )
        spec = CorrectionSpec(
            "synthetic:method",
            "synthetic:input",
            "synthetic:output",
            "synthetic:stage",
            "synthetic:mode",
            absent,
            absent,
            absent,
            {},
        )
        return plugin.correct(
            CorrectionRequest(products(inputs), {}, spec, parameters), context
        )


class AnalyzeAdapter(Adapter):
    def _business(self, plugin, inputs, parameters, context):
        return plugin.analyze(
            AnalysisRequest(products(inputs), {}, PROFILE.profile_id, 1, parameters),
            context,
        )


class AssessAdapter(Adapter):
    def _business(self, plugin, inputs, parameters, context):
        return plugin.assess(
            QCRequest(
                tuple(item.artifact for item in inputs["source"]),
                "synthetic:metrics",
                1,
                {},
                (),
                parameters,
            ),
            context,
        )


def input_port(name, schema, minimum=1, maximum=None):
    return InputPortContract(
        name,
        schema,
        PROFILE if schema == PRODUCT else None,
        minimum,
        maximum,
        Codec(),
        PortValidator(),
    )


@dataclass(frozen=True)
class Factory:
    plugin_type: type
    config: FakeConfig
    controls: Controls

    def __call__(self):
        plugin = self.plugin_type(self.config, self.controls.journal)
        self.controls.journal.record("factory", plugin.descriptor.kind.value)
        return plugin


@dataclass(frozen=True)
class Harness:
    registry: PluginRegistry
    controls: Controls
    config: FakeConfig

    def registration(self, operation):
        return next(
            r
            for r in self.registry.registrations()
            if any(b.operation_id == "synthetic:" + operation for b in r.bindings)
        )

    def binding(self, operation):
        registration = self.registration(operation)
        return self.registry.resolve_binding(
            registration.ref, "synthetic:" + operation, 1
        )


def build_harness(config=None, controls=None):
    config = config if config is not None else FakeConfig()
    controls = controls if controls is not None else Controls()
    # Hash actual test adapter/helper bytes with logical filenames, never local paths.
    identity = hashlib.sha256()
    for name in ("__init__.py", "_fake_plugins.py", "_fake_operations.py"):
        identity.update(
            name.encode() + b"\0" + Path(__file__).with_name(name).read_bytes()
        )
    declarations = (
        (
            FakeMission,
            (
                (
                    "inspect",
                    InspectAdapter,
                    (input_port("source", PRODUCT, 1, 1),),
                    ACQUISITION,
                ),
            ),
        ),
        (
            FakeProvider,
            (
                ("search", SearchAdapter, (), CATALOG),
                (
                    "acquire",
                    AcquireAdapter,
                    (input_port("catalog", CATALOG, 1, 1),),
                    PRODUCT,
                ),
            ),
        ),
        (
            FakeProcessor,
            (
                (
                    "process",
                    ProcessAdapter,
                    (
                        input_port("metadata", ACQUISITION, 0),
                        input_port("source", PRODUCT),
                    ),
                    PRODUCT,
                ),
            ),
        ),
        (
            FakeCorrection,
            (("correct", CorrectAdapter, (input_port("source", PRODUCT),), PRODUCT),),
        ),
        (
            FakeAnalyzer,
            (("analyze", AnalyzeAdapter, (input_port("source", PRODUCT),), PRODUCT),),
        ),
        (FakeQC, (("assess", AssessAdapter, (input_port("source", PRODUCT),), QC),)),
    )
    registry = PluginRegistry(required_api_version=1)
    for plugin_type, operations in declarations:
        factory = Factory(plugin_type, config, controls)
        bindings = []
        for operation, adapter_type, inputs, schema in operations:
            outputs = (
                OutputPortContract(
                    "out",
                    schema,
                    PROFILE if schema == PRODUCT else None,
                    1,
                    Codec(),
                    PortValidator(),
                ),
            )
            handler = adapter_type(
                operation,
                plugin_type,
                config,
                controls,
                inputs,
                outputs,
                identity.hexdigest(),
            )
            bindings.append(
                OperationBinding(
                    "synthetic:" + operation,
                    1,
                    "synthetic:parameters",
                    1,
                    inputs,
                    outputs,
                    (),
                    1,
                    handler,
                )
            )
        registry.register(
            plugin_type(config, controls.journal).descriptor, factory, tuple(bindings)
        )
    registry.seal()
    return Harness(registry, controls, config)
