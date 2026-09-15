from collections.abc import Mapping
from dataclasses import dataclass
from inspect import getattr_static
from types import (
    BuiltinFunctionType,
    FunctionType,
    MappingProxyType,
    MethodDescriptorType,
    MethodType,
    WrapperDescriptorType,
)
from typing import Protocol, TypeAlias

from insarforge.contracts.context import ExecutionContext, ResourceAllocation
from insarforge.contracts.identity import CapabilityId, PluginKind, PluginRef
from insarforge.contracts.plugins import (
    QC,
    Analyzer,
    Correction,
    Mission,
    Processor,
    Provider,
)
from insarforge.contracts.records import AcquisitionMetadata, CatalogSnapshot, QCReport
from insarforge.contracts.values import ArtifactRef, FrozenJSON, validate_identifier
from insarforge.products.assets import NativeAsset
from insarforge.products.models import Product, ProductDraft
from insarforge.products.semantics import SemanticValue
from insarforge.products.validation import ProductValidationReport


@dataclass(frozen=True)
class OperationRequirement:
    operation_id: str
    plugin_kind: PluginKind
    capability: CapabilityId

    def __post_init__(self):
        validate_identifier(self.operation_id)
        if not isinstance(self.plugin_kind, PluginKind):
            raise TypeError("plugin_kind")
        if not isinstance(self.capability, CapabilityId):
            raise TypeError("capability")


@dataclass(frozen=True)
class OperationBinding:
    requirement: OperationRequirement
    plugin_ref: PluginRef

    def __post_init__(self):
        if not isinstance(self.requirement, OperationRequirement):
            raise TypeError("requirement")
        if not isinstance(self.plugin_ref, PluginRef):
            raise TypeError("plugin_ref")
        if self.plugin_ref.kind is not self.requirement.plugin_kind:
            raise ValueError("plugin kind mismatch")

    @property
    def operation_id(self):
        return self.requirement.operation_id

    @property
    def plugin_kind(self):
        return self.requirement.plugin_kind

    @property
    def capability(self):
        return self.requirement.capability


@dataclass(frozen=True)
class RecordSchemaRef:
    """Static record schema identity, without decoding or schema lookup."""

    schema_id: str
    schema_version: int

    def __post_init__(self) -> None:
        if type(self.schema_id) is not str:
            raise TypeError("schema_id")
        validate_identifier(self.schema_id)
        if type(self.schema_version) is not int:
            raise TypeError("schema_version")
        if self.schema_version < 1:
            raise ValueError("schema_version")


@dataclass(frozen=True)
class ProductProfileRef:
    """Scientific profile identity with the existing ProductProfile rules."""

    profile_id: str
    profile_version: int

    def __post_init__(self) -> None:
        validate_identifier(self.profile_id)
        if (
            isinstance(self.profile_version, bool)
            or not isinstance(self.profile_version, int)
            or self.profile_version < 1
        ):
            raise ValueError("profile_version")


PluginInstance: TypeAlias = Mission | Provider | Processor | Correction | Analyzer | QC
InputRecord: TypeAlias = Product | CatalogSnapshot | AcquisitionMetadata | QCReport
OutputRecord: TypeAlias = (
    ProductDraft | CatalogSnapshot | AcquisitionMetadata | QCReport
)
PortRecord: TypeAlias = (
    Product | ProductDraft | CatalogSnapshot | AcquisitionMetadata | QCReport
)


@dataclass(frozen=True)
class ResolvedInput:
    """A supplied reference and typed record; no byte integrity claim or I/O."""

    artifact: ArtifactRef
    value: InputRecord

    def __post_init__(self) -> None:
        if type(self.artifact) is not ArtifactRef:
            raise TypeError("artifact")
        if type(self.value) not in (
            Product,
            CatalogSnapshot,
            AcquisitionMetadata,
            QCReport,
        ):
            raise TypeError("value")
        if (self.artifact.schema_id, self.artifact.schema_version) != (
            self.value.schema_id,
            self.value.schema_version,
        ):
            raise ValueError("input schema mismatch")


# Concrete owners snapshot their mappings and preserve ordered, repeated sources.
ResolvedInputs: TypeAlias = Mapping[str, tuple[ResolvedInput, ...]]


@dataclass(frozen=True)
class ArtifactDraft:
    """An unfinalized construction record and explicit target record schema."""

    schema: RecordSchemaRef
    value: OutputRecord

    def __post_init__(self) -> None:
        if type(self.schema) is not RecordSchemaRef:
            raise TypeError("schema")
        if type(self.value) not in (
            ProductDraft,
            CatalogSnapshot,
            AcquisitionMetadata,
            QCReport,
        ):
            raise TypeError("value")
        # ProductDraft targets the accepted Product envelope, not a Draft schema.
        target = (
            ("insarforge:product", 2)
            if type(self.value) is ProductDraft
            else (self.value.schema_id, self.value.schema_version)
        )
        if (self.schema.schema_id, self.schema.schema_version) != target:
            raise ValueError("output schema mismatch")


@dataclass(frozen=True)
class TaskOutcome:
    """Owned draft outputs and native evidence, without execution or publication."""

    outputs: Mapping[str, tuple[ArtifactDraft, ...]]
    evidence: tuple[NativeAsset, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.outputs, Mapping):
            raise TypeError("outputs")
        outputs = {}
        for port_id, members in self.outputs.items():
            validate_identifier(port_id)
            drafts = tuple(members)
            if any(type(draft) is not ArtifactDraft for draft in drafts):
                raise TypeError("outputs")
            outputs[port_id] = drafts
        evidence = tuple(self.evidence)
        if any(type(asset) is not NativeAsset for asset in evidence):
            raise TypeError("evidence")
        if len({asset.asset_id for asset in evidence}) != len(evidence):
            raise ValueError("duplicate evidence asset_id")
        object.__setattr__(self, "outputs", MappingProxyType(outputs))
        object.__setattr__(self, "evidence", evidence)


class ProbeContext(Protocol):
    """Read-only allocation view; no probing implementation or attempt state."""

    @property
    def allocated_resources(self) -> ResourceAllocation: ...


class PreparedExecution(Protocol):
    """Read-only semantic material and independently owned JSON preparation.

    Identity is object-shaped FrozenJSON when KNOWN, or UNKNOWN with the
    existing reason/evidence obligations; whole-identity NOT_APPLICABLE is
    invalid. Preparation is object-shaped too. Result-affecting settings must
    also appear in identity; neither view contains native paths/live handles.
    Concrete ownership, identity computation and execution remain deferred.
    """

    @property
    def semantic_execution_identity(self) -> SemanticValue[FrozenJSON]: ...

    @property
    def preparation(self) -> FrozenJSON: ...


class InputCodec(Protocol):
    """Typed bytes-to-record boundary; never opens an artifact locator."""

    def decode(
        self,
        artifact: ArtifactRef,
        payload: bytes,
        schema: RecordSchemaRef,
    ) -> ResolvedInput: ...


class OutputCodec(Protocol):
    """Typed construction-side conversion, without finalization/publication."""

    def encode(
        self,
        value: OutputRecord,
        schema: RecordSchemaRef,
    ) -> ArtifactDraft: ...


class PortValidator(Protocol):
    """Pure record/schema/profile compatibility, not operation parameters."""

    def validate(
        self,
        value: PortRecord,
        schema: RecordSchemaRef,
        profile: ProductProfileRef | None,
    ) -> ProductValidationReport: ...


def _require_adapter_method(adapter: object, method_name: str) -> None:
    """Check static attachment only, without binding arbitrary descriptors.

    This does not prove signatures, immutability or implementation correctness.
    Adapters must remain stateless or immutable-configured and safe to share.
    """
    if issubclass(type(adapter), (type, str, bytes, bytearray)) or type(adapter) in (
        FunctionType,
        MethodType,
        BuiltinFunctionType,
    ):
        raise TypeError("adapter instance required")
    method = getattr_static(adapter, method_name, None)
    if type(method) in (staticmethod, classmethod):
        method = method.__func__
    if type(method) not in (
        FunctionType,
        MethodType,
        BuiltinFunctionType,
        MethodDescriptorType,
        WrapperDescriptorType,
    ):
        raise TypeError("adapter method required: " + method_name)


@dataclass(frozen=True)
class InputPortContract:
    """One static input declaration; attached adapters are never invoked."""

    port_id: str
    schema: RecordSchemaRef
    profile: ProductProfileRef | None
    min_count: int
    max_count: int | None
    codec: InputCodec
    validator: PortValidator

    def __post_init__(self) -> None:
        validate_identifier(self.port_id)
        if type(self.schema) is not RecordSchemaRef:
            raise TypeError("schema")
        if self.profile is not None and type(self.profile) is not ProductProfileRef:
            raise TypeError("profile")
        if type(self.min_count) is not int:
            raise TypeError("min_count")
        if self.min_count < 0:
            raise ValueError("min_count")
        if self.max_count is not None:
            if type(self.max_count) is not int:
                raise TypeError("max_count")
            if self.max_count < 1 or self.max_count < self.min_count:
                raise ValueError("max_count")
        _require_adapter_method(self.codec, "decode")
        _require_adapter_method(self.validator, "validate")


@dataclass(frozen=True)
class OutputPortContract:
    """One fixed positive output declaration, without output conversion."""

    port_id: str
    schema: RecordSchemaRef
    profile: ProductProfileRef | None
    count: int
    codec: OutputCodec
    validator: PortValidator

    def __post_init__(self) -> None:
        validate_identifier(self.port_id)
        if type(self.schema) is not RecordSchemaRef:
            raise TypeError("schema")
        if self.profile is not None and type(self.profile) is not ProductProfileRef:
            raise TypeError("profile")
        if type(self.count) is not int:
            raise TypeError("count")
        if self.count < 1:
            raise ValueError("count")
        _require_adapter_method(self.codec, "encode")
        _require_adapter_method(self.validator, "validate")


class OperationHandler(Protocol):
    """Operation adapter ports; no common business method on plugin families."""

    def validate_spec(
        self,
        parameters: FrozenJSON,
        inputs: tuple[InputPortContract, ...],
        outputs: tuple[OutputPortContract, ...],
    ) -> ProductValidationReport:
        """Sole semantic-parameter validator; pure declarations only."""
        ...

    def prepare(
        self,
        plugin: PluginInstance,
        resolved_inputs: ResolvedInputs,
        parameters: FrozenJSON,
        probe_context: ProbeContext,
    ) -> PreparedExecution: ...

    def invoke(
        self,
        plugin: PluginInstance,
        prepared: PreparedExecution,
        resolved_inputs: ResolvedInputs,
        parameters: FrozenJSON,
        context: ExecutionContext,
    ) -> TaskOutcome: ...
