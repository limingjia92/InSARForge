# ADR-0013: Static Operation Bindings, Typed Ports and Registration Ownership

**Status: Accepted**

## Context

[Phase 4 contracts](../architecture/phase4-contracts.md), especially §§4, 6, 7.1, 7.3, 7.6, 7.11, 8, 13.1 and 14, and [ADR-0001](0001-core-boundaries-and-dependencies.md), [ADR-0002](0002-plugin-contracts-and-registry.md), [ADR-0003](0003-product-and-scientific-metadata.md), [ADR-0004](0004-workflow-runtime-and-provenance.md) and [ADR-0012](0012-product-envelope-and-reference-contracts.md) govern this decision. Existing Product contracts are reused without modification.

ADR0013-D0 returned DECISION_REQUIRED. D1 returned CONFLICT: singular capability was insufficient; identifier-only handler/codec declarations omitted typed adapters; parameter schema ID/version and validator revision were missing. D2 returned IMPLEMENTATION_READY with no authority conflicts or additional public decisions. This ADR transcribes D2, supersedes the conflicted D1 portions, and preserves D2's revalidated ownership, cardinality, ordering, lookup and lifecycle decisions. It freezes architecture, not implementation completion.

## Decision

Use one programmatic PluginRegistry. Each PluginRegistration owns immutable operation bindings with complete versioned declarations and directly attached typed handler, codec and validator objects. PluginKind remains exactly six; Product is not a plugin kind. Operation adapters do not replace family-specific plugin Protocols or introduce Plugin.run(), Plugin.execute() or a universal plugin business invoke method.

### Authority and representation

| Decision | Classification and authority |
|---|---|
| Complete binding contents; plural capabilities; parameter schema and validator revision | Authority-resolved: §7.1; future fingerprint contribution §7.6 |
| Three handler ports; typed codecs/validators; drafts before Core publication | Authority-resolved: §§4, 7.1, 13.1; ADR0002 |
| One registry, registration ownership, exact API, declared capabilities, pure dry-run and sealed lifecycle | Authority-resolved: §§7.1, 7.11; ADR0001/0002/0004 |
| Schema/profile distinction, ordered sources, fixed positive task outputs | Authority-resolved: §§6.1, 7.3; ADR0012 |
| Flat nine-field shape, wrapper removal, exact scalar types, canonical capability tuple | Authority-compatible gap filling resolved by D2 |
| Exact Protocol signatures, bounded supporting types, direct adapter instances, two codecs and one composite port validator | Authority-compatible gap filling resolved by D2 |
| Reference values, input bounds, separate port shapes, canonical declarations and cross-direction uniqueness | Authority-compatible gap filling; revalidated D1 decisions |
| Atomic ownership, derived key, exact lookup, no binding serialization | Authority-compatible gap filling; revalidated D1 decisions |

No authority amendment or additional public decision is required.

## OperationBinding Contract

The immutable static registration value has **exactly nine required public fields**, with no compatibility defaults:

```text
OperationBinding(
    operation_id: str,
    operation_api_version: int,
    parameter_schema_id: str,
    parameter_schema_version: int,
    inputs: tuple[InputPortContract, ...],
    outputs: tuple[OutputPortContract, ...],
    required_capabilities: tuple[CapabilityId, ...],
    validator_revision: int,
    handler: OperationHandler,
)
```

No requirement, plugin_ref, singular capability, handler_id, codec_id, factory, ResourceRequest, ResourceAllocation, ExecutionContext, TaskSpec or WorkflowPlan field is added. The containing registration supplies plugin identity. The transitional OperationRequirement is not a final public source of truth and must be removed from the final binding path.

operation_id is a required exact str using the existing identifier grammar: nonempty, no whitespace or Unicode category C characters, preserve spelling. Vocabulary is open and extensible, with no mission/backend enum. operation_api_version is an exact int >= 1, rejecting bool, and matches exactly: no ranges, negotiation or semantic-version behavior. Multiple versions of one operation_id may coexist.

Construction snapshots owned collections. Static input/output declaration order is nonsemantic; validate all port IDs, reject duplicates across inputs + outputs, and store each tuple sorted by ascending port_id. Otherwise identical declarations with the same adapter instances do not differ merely because the caller reordered ports. Do not sort or deduplicate sources inside a runtime input port. Empty static input/output tuples are allowed; this does not relax §7.3's requirement that an executable TaskSpec declare at least one result and fulfill fixed positive outputs.

## Required Capabilities

required_capabilities is tuple[CapabilityId, ...]. Empty is allowed. Every member must be an exact CapabilityId; reject duplicates rather than silently collapsing them. Its semantics are set-like: caller order is nonsemantic, stored order is canonical ascending CapabilityId.value. There is no competing singular capability field.

Every requirement must belong to the owning descriptor.capabilities. This checks declarations only, never CapabilityAvailability or CapabilityCheckResult. One binding may require zero or more capabilities; multiple operations and multiple plugins may share a capability. CapabilityId alone is not operation identity.

## Parameter Schema / Validator Revision

parameter_schema_id is a required exact str using the existing identifier grammar. It names the semantic-parameter schema, not a class, Pydantic model, callable or Python import path. parameter_schema_version is an exact int >= 1, bool invalid. No schema lookup, runtime model loading or version negotiation occurs at construction.

validator_revision is an exact int >= 1, bool invalid. It versions semantic validation implemented solely by handler.validate_spec. It is not part of the binding lookup key. It participates in future task fingerprint semantics under §7.6; P4.1B does not compute fingerprints. There is no separate competing ParameterValidator.

For new exact integer fields, wrong types (including bool) raise TypeError and invalid bounds raise ValueError. Identifier validation follows existing validate_identifier behavior. Duplicate capability/port declarations raise ValueError. The ProductProfileRef identity exception below deliberately preserves existing ProductProfile behavior.

## RecordSchemaRef / ProductProfileRef

No existing exact equivalent replaces these new immutable references:

```text
RecordSchemaRef(schema_id: str, schema_version: int)
ProductProfileRef(profile_id: str, profile_version: int)
```

RecordSchemaRef uses the existing open schema identifier convention and an exact positive integer version, rejecting bool. It identifies record/wire compatibility; it does not resolve a Python class or codec. Do not restrict generic record schema IDs to the Product literal. A Product target uses the accepted envelope, currently insarforge:product version 2.

ProductProfileRef mirrors current ProductProfile identity validation: profile_id uses existing identifier validation; profile_version is isinstance(int), excludes bool, and is >= 1. All invalid profile versions, including wrong types/bool, raise ValueError as in ProductProfile. This does not change Product contracts.

ProductProfileRef identifies static scientific compatibility. It is independent of record/wire compatibility: never infer one identity from the other. Ports may use profile=None for records without a Product scientific profile. No full ProductProfile or Product instance is embedded, no schema/profile registry is introduced, and no lookup or scientific compatibility evaluation occurs during construction.

## InputPortContract

The immutable contract has exactly seven required fields:

```text
InputPortContract(
    port_id: str,
    schema: RecordSchemaRef,
    profile: ProductProfileRef | None,
    min_count: int,
    max_count: int | None,
    codec: InputCodec,
    validator: PortValidator,
)
```

port_id follows existing identifier grammar. min_count is exact int >= 0, bool invalid. max_count is None (unbounded) or exact int >= 1 and >= min_count, bool invalid. Optional singleton is (0,1), required singleton (1,1), variadic uses max_count=None. These are static bounds, not source collection mechanics. References and direct typed adapter instances are mandatory as annotated; profile=None is explicit. No extra public fields.

## OutputPortContract

The immutable contract has exactly six required fields:

```text
OutputPortContract(
    port_id: str,
    schema: RecordSchemaRef,
    profile: ProductProfileRef | None,
    count: int,
    codec: OutputCodec,
    validator: PortValidator,
)
```

Identifier/reference rules match input ports. count is an exact positive int, bool invalid. Outputs are fixed and positive: no optional, max_count or unbounded output. Separate input/output types prevent invalid cardinality combinations; do not replace them with a direction-tagged PortContract. Cross-direction duplicate IDs are rejected without automatic renaming.

## OperationHandler

These exact Protocol methods, including required arguments and existing canonical report name, are frozen:

```python
class OperationHandler(Protocol):
    def validate_spec(
        self,
        parameters: FrozenJSON,
        inputs: tuple[InputPortContract, ...],
        outputs: tuple[OutputPortContract, ...],
    ) -> ProductValidationReport: ...

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
```

validate_spec is the sole semantic-parameter validation owner. It consumes semantic parameters and binding port declarations, not actual records or TaskSpec. It is pure, does not replace/mutate parameters, instantiate native software, execute processing, mutate registry or invoke attached codecs/validators. Generic task wiring/count validation remains the future planner's responsibility.

prepare freezes the future explicit preflight interface, including necessary native identity and effective settings, without producing scientific assets. invoke freezes adaptation to a family method and draft outcome. Neither is executed in P4.1B. OperationBinding stores a direct OperationHandler instance, never an ID, class, naked callable, method-name string, getattr dispatch or import path.

### Supporting typed views and values

Reuse existing ArtifactRef, FrozenJSON, six family Protocols, Product, ProductDraft, CatalogSnapshot, AcquisitionMetadata, QCReport, ResourceAllocation, ExecutionContext, NativeAsset, SemanticValue and products.validation.ProductValidationReport. Do not redefine these values or change family signatures. Add only the following operation-specific aliases and frozen values:

```python
PluginInstance = Mission | Provider | Processor | Correction | Analyzer | QC
InputRecord = Product | CatalogSnapshot | AcquisitionMetadata | QCReport
OutputRecord = ProductDraft | CatalogSnapshot | AcquisitionMetadata | QCReport
PortRecord = Product | ProductDraft | CatalogSnapshot | AcquisitionMetadata | QCReport
ResolvedInputs = Mapping[str, tuple[ResolvedInput, ...]]
```

```text
ResolvedInput(artifact: ArtifactRef, value: InputRecord)
ArtifactDraft(schema: RecordSchemaRef, value: OutputRecord)
TaskOutcome(outputs: Mapping[str, tuple[ArtifactDraft, ...]],
            evidence: tuple[NativeAsset, ...])
```

No Any/object escape or arbitrary imported payload class is permitted at this record boundary. Handler implementations accept PluginInstance and narrow inside their adapter; a narrower Processor-only signature is not automatically conforming. Existing registration factory Callable[[], object] remains unchanged; static registration cannot prove factory results without invoking it. Family/factory pairing is a composition/conformance obligation checked before future business invocation.

ResolvedInput retains the supplied ArtifactRef, checks member-domain types and explicit schema agreement without I/O. Byte/ref identity verification belongs to future Core. ResolvedInputs owners snapshot the mapping and ordered member sequences, retaining input order and intentional duplicate sources.

ArtifactDraft wraps an unfinalized typed construction record and explicit target schema. Product output uses ProductDraft, never finalized Product; its target is the existing Product envelope, not a new persisted Draft schema. Other record schemas must agree. Wrong local types raise TypeError; conflicting schemas raise ValueError. No Core producer/production/lineage is fabricated and no draft serialization/publication is implied.

TaskOutcome owns an immutable mapping with identifier port keys and ordered draft tuples, plus an immutable NativeAsset evidence tuple with unique asset_id (duplicates ValueError). Evidence represents native configuration/diagnostics for future Core provenance, not hidden scientific results or fabricated ArtifactRefs. Existing safe-path/integrity contracts apply. Local collections may be empty; future Core must validate declared names/counts/schema/profile/assets/ownership before finalization and publication.

Minimal read-only Protocol views are fully resolvable static contracts, not undefined future classes:

```python
class ProbeContext(Protocol):
    @property
    def allocated_resources(self) -> ResourceAllocation: ...

class PreparedExecution(Protocol):
    @property
    def semantic_execution_identity(self) -> SemanticValue[FrozenJSON]: ...

    @property
    def preparation(self) -> FrozenJSON: ...
```

ProbeContext exposes only existing allocation, not a scheduler, registry, service/config bag, credentials, attempt state or implemented probe. Future resource-sensitive prepared settings must agree with invocation allocation. No dry-run context is created.

PreparedExecution identity is auditable semantic material, not an opaque digest. KNOWN contains immutable object-shaped FrozenJSON covering §7.6 adapter code, applicable native build/dependencies, effective scientific/native settings, resource-sensitive choices and actual external scientific data identities. UNKNOWN has None and existing reason/evidence obligations; whole-identity NOT_APPLICABLE is rejected. Never fabricate a strong identity. Native components may be explicitly inapplicable within otherwise known non-native material.

preparation is independently owned object-shaped FrozenJSON, possibly empty. Result-affecting settings must also occur in semantic identity. Native paths/live handles are excluded from semantic/persisted views. Any future private live handles remain attempt-owned outside shared adapters. These views define no execution-state model, persistence keys, hashing computation or resource lifecycle.

## InputCodec / OutputCodec / PortValidator

```python
class InputCodec(Protocol):
    def decode(
        self,
        artifact: ArtifactRef,
        payload: bytes,
        schema: RecordSchemaRef,
    ) -> ResolvedInput: ...

class OutputCodec(Protocol):
    def encode(
        self,
        value: OutputRecord,
        schema: RecordSchemaRef,
    ) -> ArtifactDraft: ...

class PortValidator(Protocol):
    def validate(
        self,
        value: PortRecord,
        schema: RecordSchemaRef,
        profile: ProductProfileRef | None,
    ) -> ProductValidationReport: ...
```

Directional codecs reflect persisted input versus construction-side output, particularly Product versus ProductDraft; no bidirectional inverse is required. Objects attach directly to ports, with no codec_id, handler_id, codec/handler registry, string/import discovery or supports_schema callback.

Future Core obtains manifest bytes and verifies integrity. InputCodec performs explicit strict decoding with exact schema/reference/wire agreement, returns the same reference with a typed record, and does not open locators, materialize assets, access files/network or infer profiles. Invalid bytes/schema/version use existing InputValidationError at the adapter boundary, distinct from local constructor errors.

OutputCodec converts the supplied typed semantic output to an unfinalized ArtifactDraft with matching target schema, without covert value changes, final JSON, I/O or publication. Invalid conversion/schema uses existing OutputValidationError. Core retains record/profile/count/asset checks, identity/lineage finalization, manifest/receipt writing and publication.

One mandatory PortValidator per port composes typed record/schema consistency and applicable scientific profile validation. The name validator covers non-Product records too. There are no separate competing record_validator/profile_validator fields or port validator revisions. profile=None skips profile-specific checks only. Unsupported declared profiles/schema or missing required scientific content report ERROR; no implicit critical-profile acceptance or scientific matching conventions are invented. Adapters may privately use explicitly supplied existing profile definitions without registry discovery. PortValidator does not validate operation parameters and performs no I/O/probes.

Reuse ProductValidationReport exactly: immutable issues tuple and existing ERROR/UNVERIFIED semantics and properties. is_valid means no ERROR, not verified science; is_fully_verified means no issues. Pending runtime facts may be UNVERIFIED during pure declaration validation, never fabricated as checked. No renamed alias, duplicate report class or automatic cache/QC approval is introduced.

Programmatic composition supplies the same immutable output-port/codec references to handler and binding. Future handler output conversion uses these attached codecs, not a second private selection table. No extra public handler configuration fields are frozen. Future input conversion uses attached input codecs to populate ResolvedInputs.

## Registration Ownership

The existing PluginRegistration owns descriptor, factory and explicit immutable bindings:

```text
PluginRegistration(
    descriptor: PluginDescriptor,
    factory: Callable[[], object],
    bindings: tuple[OperationBinding, ...],
)
```

Retain existing ref property and already-frozen registration behavior. Snapshot bindings; empty is allowed. Supplied binding sequence remains enumeration metadata. No separate OperationBindingRegistry, orphan registration or independent per-binding owner. An immutable binding object may be reused under compatible registrations; contextual ownership does not require exclusive Python object identity.

register(descriptor, factory, bindings) -> None validates the complete registration atomically before publishing either primary entry or derived index. Failure leaves both unchanged. No factory, handler (including validate_spec), codec or validator invocation occurs. There is no binding.plugin_ref consistency check because that field does not exist.

## Registry Keys / Lookup

Primary key remains (PluginKind, plugin_id). Derived binding key is exactly:

```text
(descriptor.kind, descriptor.plugin_id, operation_id, operation_api_version)
```

No capability, parameter_schema_version, validator_revision or handler object identity enters this key. Multiple operation revisions coexist; capability sharing does not collide. Existing registry.required_api_version validation and exact requested PluginRef.api_version == descriptor.api_version equality remain. No negotiation/ranges or fallback.

```python
resolve_binding(
    plugin_ref: PluginRef,
    operation_id: str,
    operation_api_version: int,
) -> OperationBinding
```

Resolve owner by kind/id, check requested API equality, then exact operation ID/API. Preserve existing resolve(ref). Lookup is allowed before/after seal; future runtime consumes sealed registry. Do not call adapters or probe availability. No broad search, best binding, capability-based plugin selection or version-negotiation API is required.

## Static Validation Responsibilities

| Owner | Responsibility |
|---|---|
| References/ports/binding constructors | Validate explicit types/identifiers/versions/bounds, snapshot collections, reject duplicates, canonicalize declarations; check structural adapter attachment without calls |
| PluginRegistration / register | Validate complete binding structures, local operation-key uniqueness, owner capability subset, primary and derived uniqueness, and atomic publication |
| resolve_binding | Exact owner/API/operation lookup, no selection or runtime verification |
| Pure handler.validate_spec | Operation semantic parameters and static port declarations, for future graph construction/dry-run |
| Future execution Core and adapters | Decode, typed record/profile validation, prepare/invoke, asset checks, finalization and publication; outside P4.1B |

Adapters must be stateless or immutable-configured and safe for sharing; no per-attempt mutable state. Frozen metadata does not freeze arbitrary Python internals. Do not deepcopy/serialize adapters or use their equality/hash/repr for registry identity. Structural method inspection must not evaluate custom properties, descriptors or __getattr__. runtime_checkable alone does not prove signatures; static typing and later neutral conformance tests complete the contract obligation without registration callbacks.

| Failure | Existing error boundary |
|---|---|
| Duplicate primary plugin | DuplicatePluginRegistrationError |
| Duplicate derived binding / missing exact operation | OperationBindingError family |
| Undeclared required capability | OperationCapabilityUnsatisfiedError |
| Unknown plugin | UnknownPluginError, before API mismatch for an absent key |
| Requested API mismatch | PluginAPIVersionMismatchError |

No overwrite, last-write-wins or duplicate aliasing. No CapabilityAvailability, CapabilityCheckResult, license/native/filesystem/network checks at registration. Runtime availability belongs to P4.2.

## Sealing

Retain idempotent seal/read-only lifecycle. Before seal, complete registrations may be added. After seal, no add/remove/replace/mutation. Seal performs no factory/handler/codec/validator callbacks or environment probes and introduces no runtime side effects.

## Dry-Run Boundary

Future graph construction/dry-run may call pure handler.validate_spec on parameters and declarations. It must not call factory, prepare, invoke, InputCodec.decode, OutputCodec.encode, PortValidator on actual records, or native probes. Registration, construction, seal and lookup call none of these adapters, including validate_spec. This ADR does not implement dry-run or load records during planning. Pending identities remain unresolved under accepted Phase 4 rules.

## Dependency Direction

Place new operation-specific references, aliases, frozen support values, port and adapter Protocols in existing insarforge.contracts.operations. Registry remains in insarforge.core.registry. Under §8 and ADR0001, operations may import existing leaf values, execution, plugins, records and Product/report types; products, plugins and leaf contracts must not import operations or registry in reverse. Registry consumes contracts; contracts do not import registry. No new root reexports or public module-path redesign.

Use small RecordSchemaRef/ProductProfileRef rather than embedding ProductProfile. All new annotations must resolve from actual module globals, including ProductDraft and the supporting views; absent TYPE_CHECKING-only P4.2 names are insufficient. Reuse existing family types unchanged. No dependency cycle or mission/backend branch is authorized.

## Compatibility / Migration

This pre-release freeze is deliberately breaking. Remove transitional OperationRequirement, its singular capability, the final binding requirement/plugin_ref path and detached resolution helper during migration. No compatibility alias/constructor, handler_id/codec_id field, singular capability alias, auto-conversion or silent migration. Explicitly migrate callers and fixtures; do not retain two operation declaration sources.

Current migration affects contracts.operations, the detached core.operation_binding resolver and direct operation-binding/registry callers/tests. Preserve canonical existing error reexports required by callers while removing the obsolete helper. No production/test change is performed by this ADR.

No JSON persistence is required for bindings, ports, registration or adapters: these are programmatic static Python contracts, not persisted records. Do not invent serializers for symmetry.

## Alternatives Considered

| Rejected alternative | Reason |
|---|---|
| Singular capability only | Cannot express authority-required plural simultaneous requirements |
| Transitional OperationRequirement as final truth | Incomplete and duplicates the complete declaration |
| handler_id / codec_id only | Does not satisfy required typed adapter interfaces |
| Dynamic getattr / import-string adapters | Violates explicit typed dispatch boundary |
| Universal run() plugin interface | Violates six-family Protocol architecture |
| Separate OperationBindingRegistry | Duplicates registration-owned binding authority |
| Full ProductProfile embedding | Unnecessary coupling and dependency burden |
| Capability-based global binding key | Prevents multiple named operations per capability |
| Runtime CapabilityAvailability during registration | Pulls P4.2 runtime probing into static declarations |
| Serialized JSON binding contract | Unnecessary for explicit programmatic registration |
| ResourceRequest on binding | Pulls runtime scheduling into operation declaration |

## Consequences

Benefits are complete versioned operation declarations, plural declared capability requirements, typed handler/codec/validator boundaries without dynamic string dispatch, deterministic port identity/cardinality, atomic plugin ownership and exact lookup. P4.2 receives typed static inputs without runtime availability leaking into registration.

Costs are a breaking transitional API migration, additional static supporting interfaces, deliberately non-JSON adapter objects, explicit caller/test migration, and future runtime implementation against these interfaces. Type declarations do not alone prove arbitrary adapter correctness; composition and conformance tests remain obligations.

## Deferred / Non-Goals

P4.1B freezes values, Protocols, pure validation and registration only. Defer handler.prepare/invoke execution, codec execution, actual workflow record validation, task fingerprints, cache, retry, state, scheduler, provenance runtime, workflow execution and runtime capability availability to P4.2. No ResourceRequest/ResourceAllocation/ExecutionContext field belongs on bindings or ports; referring to existing context/allocation in adapter signatures does not implement scheduling.

No real Product profiles, SAR schemas, mission-specific port IDs, processor parameter schemas, scientific thresholds or backend choices are selected. Open identifiers do not authorize arbitrary dynamic imports. Product contracts remain unchanged.

## Implementation Follow-up

These are separate future authorized segments, not work performed by this ADR:

| Segment | Scope and gate |
|---|---|
| S4a | Additive static foundations: refs, separate ports, handler/codec/validator Protocols, aliases and required frozen values/read-only views. Prepare the final binding contract for integration. Focused tests and full repository green; keep existing binding/resolver unchanged in this additive stage. |
| S4b | Install final nine-field OperationBinding with PluginRegistration/PluginRegistry ownership, atomic capability checks/index, exact lookup and sealing. Remove transitional wrapper/detached helper and migrate every directly affected caller/test together. Focused and full green; preserve existing error/API behavior. |
| S4c | Remaining legacy/caller/test cleanup and cross-interface static integration; full repository green. May be validation-only if S4b completed cleanup. |
| S4d | Validation-only authoritative gate, individually assess and close B3-REQ-15/16/17 only after implementation evidence passes. Failures return to scoped repair, not production edits within this gate. |

D2's dependency-backed green split moves the actual final binding replacement from additive S4a into S4b and brings required caller migration forward from S4c. The current detached resolver reads the removed owner/wrapper fields; replacing binding alone would break it or require forbidden compatibility aliases. Supporting ports/handler declarations are independently additive. No knowingly broken intermediate stage is accepted.

Future focused coverage includes exact types/bool/bounds, canonicalization and snapshots, empty/multiple/duplicate capabilities, cross-direction IDs, operation revision coexistence, shared capabilities, API errors, failed-registration atomicity, seal and callback/property traps, resolvable annotations and typed adapter conformance. No scheduler or prepare/invoke execution is needed for the static gate.

After S4d closes all three findings, run **B3c overall remediation audit** of the complete repaired P4.1B static contract. Then run a **separate P4.1B final closure gate**. Do not collapse B3c into S4d or declare P4.1B closed merely from this ADR.

## Remediation Ledger

| Ledger item | Count/status |
|---|---|
| Original B3 REQUIRED | 21 |
| Closed before ADR0013 implementation | 18 |
| Remaining REQUIRED | 3 |
| B3-REQ-15: complete versioned static binding declaration | Architecture resolved; implementation OPEN |
| B3-REQ-16: registration-owned bindings | Architecture resolved; implementation OPEN |
| B3-REQ-17: typed handler/codec ports | Architecture resolved; implementation OPEN |
| Implementation findings closed by ADR0013 | 0 |

Unresolved ADR0013 architecture decision items: **None**.
