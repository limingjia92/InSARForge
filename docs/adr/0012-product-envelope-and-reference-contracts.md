# ADR-0012 — Product Envelope, Producer, Production and Lineage Reference Contracts

**Status: Accepted**

**Relationship:** clarification/addendum to `P4.0-FREEZE-1`, grounded in
[Phase 4 contracts](../architecture/phase4-contracts.md) §§6.1–6.5, 7.6,
7.13, 8 and 13, and accepted ADRs
[0001](0001-core-boundaries-and-dependencies.md),
[0002](0002-plugin-contracts-and-registry.md),
[0003](0003-product-and-scientific-metadata.md),
[0004](0004-workflow-runtime-and-provenance.md),
[0005](0005-native-asset-integrity-and-directory-membership.md),
[0006](0006-directory-member-manifest.md),
[0007](0007-datalayer-selector-dimensions-nodata.md),
[0008](0008-geometry-axes-and-dimension-alignment.md),
[0009](0009-grid-definition-and-geometry-reference.md),
[0010, including R1](0010-semanticvalue-payload-domain-and-deep-ownership.md)
and [0011](0011-extension-namespace-grammar-and-ownership.md).
This is the documentation-only P4.1B R2 Product-envelope decision.

## Context

P4.0 freezes nine construction-side ProductDraft fields and sixteen finalized
Product fields, but leaves their nested producer/production identities and
several reference, metadata and wire rules underspecified. Transitional
implementation shapes are not architecture authority: Product currently has
thirteen fields, while Draft's current nine fields include two wrong fields
and omit two required ones.

ADR0012-D0 returned DECISION_REQUIRED. D1 resolved the Product-envelope choices
except two conflicts: its two-field ProducerRef omitted required implementation
and execution identity information; its mandatory plain task fingerprint could
not represent authority-permitted production with unavailable strong identity.
D2 returned IMPLEMENTATION_READY, resolving both with existing SemanticValue
availability envelopes. D2 supersedes only those conflicting D1 portions and
their necessary integration consequences; all non-conflicting D1 decisions
remain accepted input. This ADR freezes that complete result.

Acceptance resolves architecture only. No production code, tests, model,
serialization, digest, static binding or runtime implementation is performed.
All eight Product findings remain implementation-open; S3a does not begin here.

## Decision

Freeze the exact ProductDraft and Product contracts below and exactly three new
immutable static value concepts: `ProducerRef`, `ProductionRef`, `LineageEntry`.
Reuse existing `PluginRef`, `ArtifactRef`, `SemanticValue` and FrozenJSON
ownership facilities. All listed public fields are required explicit slots;
there are no implicit defaults, omitted-field synthesis or compatibility
properties. Empty collections are valid only where their own contracts allow.
No whole Product/Draft field is made nullable by identity unavailability;
unavailable identities use the specified nested SemanticValue state.

Product content identity remains distinct from implementation/execution and
production-event identity. Strong scientific references have no persistence
identity fallback. Strict Product persistence is the self-describing v2 record.
P4.1B freezes representation, ownership and static validation obligations only.

## ProductDraft Contract

The exact **nine** public fields are:

```text
ProductDraft(
    product_kind: str,
    profile_id: str,
    profile_version: int,
    assets: tuple[NativeAsset, ...],
    layers: tuple[DataLayer, ...],
    geometries: tuple[GeometryDescriptor, ...],
    acquisition_refs: tuple[ArtifactRef, ...],
    semantic_metadata: Mapping[str, SemanticValue[FrozenJSON]],
    extensions: FrozenJSON,
)
```

`extensions` is object-shaped FrozenJSON, logically `Mapping[str, FrozenJSON]`,
under ADR0011. ProductDraft contains semantic Product content supplied by
construction/plugin logic. It is a distinct construction contract.

ProductDraft MUST NOT contain `schema_id`, `schema_version`, `product_id`,
`producer`, `produced_by`, `lineage` or `provenance_ref`. Implementation must
remove transitional `ProductDraft.schema_version` and `ProductDraft.lineage`.
No aliases or compatibility properties may retain them.

### Shared content contracts

`product_kind` and `profile_id` retain existing `validate_identifier` rules.
`profile_version` retains the positive integer contract, excluding bool; this
ADR creates no supported scientific profile table or version negotiation.
Schema, profile, plugin API and implementation versions are distinct concepts.

Assets, layers and geometries retain accepted element contracts, defensive
tuple ownership, supplied order, unique local IDs and existing structural graph
validation. Preserve same-Product asset/geometry links, mask checks and exact
ordered DataLayer dimensions/Geometry axes alignment under ADRs 0007–0009.
Collection fields may be empty under their existing rules; individual geometry
axes/shape constraints are unchanged. No scientific defaults are inferred.

## Product Contract

The exact **sixteen** public fields are:

```text
Product(
    product_kind: str,
    profile_id: str,
    profile_version: int,
    assets: tuple[NativeAsset, ...],
    layers: tuple[DataLayer, ...],
    geometries: tuple[GeometryDescriptor, ...],
    acquisition_refs: tuple[ArtifactRef, ...],
    semantic_metadata: Mapping[str, SemanticValue[FrozenJSON]],
    extensions: FrozenJSON,
    schema_id: str,
    schema_version: int,
    product_id: str,
    producer: ProducerRef,
    produced_by: ProductionRef,
    lineage: tuple[LineageEntry, ...],
    provenance_ref: str,
)
```

All sixteen are required. The first nine share Draft's content contracts;
Core finalization supplies the remaining seven. There is no seventeenth public
field, including no separate `production`, self digest, asset-content-identity
map or top-level attempt field.

Transitional `producer_implementation_version` MUST disappear as a Product
top-level field. Its descriptive meaning moves to
`Product.producer.implementation_version`; it is not retained as an alias.

| Product-only scalar | Contract |
|---|---|
| `schema_id` | Required `str`, exactly `"insarforge:product"`. No aliases or negotiation. |
| `schema_version` | Required `int`, exactly `2`; bool is invalid. |
| `product_id` | Preserve the existing required identifier contract. Immutable instance identity; no redesign or content-derived ID generation. |
| `provenance_ref` | Required `str` using existing identifier grammar; identifier-only pointer to associated run/task/attempt provenance. No dereference, nested schema/locator/digest or generic reference framework. |

Neither provenance pointer equality with `produced_by.attempt_id` nor any
cross-field lookup is required. The pointer is supplied explicitly; its storage
and resolution remain deferred. Draft has none of these scalar fields.

## ProducerRef

Freeze exactly four required public fields on an immutable value:

```text
ProducerRef(
    plugin: PluginRef,
    implementation_version: str,
    implementation_identity_digest: SemanticValue[str],
    execution_identity_digest: SemanticValue[str],
)
```

This represents the software, implementation and semantic execution identity
associated with the producer of a finalized Product. No additional public
fields or full execution-identity object are introduced.

`plugin` is the exact existing `PluginRef`, preserving `kind`, `plugin_id`,
`api_version` and their existing validation. Do not duplicate those fields
directly in ProducerRef. Construction performs no registry lookup, capability
availability check, plugin discovery or plugin execution.

`implementation_version` is required nonempty trimmed `str`: an opaque
implementation/build/version label. Internal whitespace is allowed under this
text contract. Do not trim or normalize input, parse semantic versions, impose
`validate_identifier` as a new requirement or negotiate versions. Existing
independently applicable generic string/persistence rules remain binding.
The label is descriptive identity and is NOT a fallback for either digest.

`implementation_identity_digest` records strong implementation-identity digest
availability. `execution_identity_digest` records availability of the digest
of the authority-required SemanticExecutionIdentity concept. These are distinct
identity concerns: neither digest substitutes for the other. No public
SemanticExecutionIdentity wrapper type is required; a digest representation is
sufficient here. Full facts remain the responsibility of their future primary
preparation/attempt records, without copying a full runtime schema into Product.

### Identity digest state rules

Each digest is a required exact `SemanticValue[str]`. At these owners only
KNOWN and UNKNOWN are allowed; NOT_APPLICABLE is invalid.

| Status | Payload and reason |
|---|---|
| KNOWN | Required nonempty trimmed `str`, opaque digest representation. Existing optional reason rule: `None` or nonempty trimmed text. |
| UNKNOWN | `value=None`; nonempty trimmed `reason_code` required under existing SemanticValue rules. Do not fabricate a value. |
| NOT_APPLICABLE | Reject at this owner, regardless of payload/reason. |

Existing `evidence_refs` rules apply: defensively owned ordered tuple of exact
ArtifactRef values; empty allowed, order and duplicates preserved, no fetching.
Generic SemanticValue remains unchanged, including its three-state vocabulary.
One unknown producer digest does not erase another independently known digest;
no cross-field derivation or equality rule is introduced.

P4.1B stores and validates supplied representations only. No identifier grammar,
hex-length requirement, digest algorithm negotiation, implementation scanning,
recomputation or runtime verification is added. A syntactically valid KNOWN
string is a supplied claim, not proof that identity was verified. Constructors
and codecs must never generate fallback digests or hash UNKNOWN markers.

The entire `Product.producer` is excluded from Product content digest, including
plugin, version, both digest values and their statuses, reasons and evidence.
Producer remains part of serialized envelope/state and complete manifest bytes.
Semantic execution identity is not Product semantic-content identity.

## ProductionRef

Freeze exactly three required public fields on an immutable value:

```text
ProductionRef(
    task_fingerprint: SemanticValue[str],
    output_port: str,
    attempt_id: str,
)
```

This is the traceability identity of the actual production event that emitted
the finalized Product. `Product.produced_by` requires this value; ProductDraft
has no ProductionRef. No reusable flag, cache policy, full FingerprintResult,
runtime attempt object or additional field is introduced.

`task_fingerprint` follows the same owner state rules as the producer digests:
KNOWN requires a nonempty trimmed opaque `str`; UNKNOWN requires `value=None`
and a nonempty trimmed reason; NOT_APPLICABLE is invalid. Existing KNOWN
optional reason and evidence rules are preserved. A bare string, bare None,
empty string or malformed state envelope is invalid. No algorithm validation,
normalization or fingerprint recomputation occurs in P4.1B.

UNKNOWN is a valid static representation of authority-permitted weak identity,
including actual execution for which sufficient fingerprint identity is
unavailable. It preserves the actual output port and attempt traceability.
Do not use `attempt_id`, `product_id`, record ID, manifest digest or locator as
a fake fingerprint; do not hash None or a fixed UNKNOWN marker into one.

`output_port` is a required nonempty string using existing identifier grammar,
with no normalization. It identifies the producing output port. Merely
constructing ProductionRef requires no PortContract dependency or binding
compatibility lookup.

`attempt_id` is a required string using existing identifier grammar. It is an
identifier-only producing-attempt pointer; no lookup or runtime attempt object
is required. The actual attempt remains traceable when task_fingerprint is
UNKNOWN. It is not a fingerprint substitute.

Fingerprint availability is supplied by the future producer/runtime boundary.
P4.1B does not define the task fingerprint algorithm, cache key generation,
cache eligibility, recomputation, reuse decisions, retry identity or runtime
resolution. Existing P4.0 runtime authority remains deferred to P4.2.
KNOWN alone does not authorize reuse; disabled caching does not imply UNKNOWN
or NOT_APPLICABLE. Planning-only UNRESOLVED must not fabricate a Product or an
attempt. No exception-to-UNKNOWN successful-completion rule is introduced.

The entire `Product.produced_by` is excluded from Product content digest,
including fingerprint availability/value/reason/evidence, output_port and
attempt_id. Changing any of these with otherwise identical semantic Product
content must not change its content digest. P4.2 may use these facts separately
in execution/cache identity.

## LineageEntry

Freeze exactly two required public fields on an immutable value:

```text
LineageEntry(
    role: str,
    artifact: ArtifactRef,
)
```

`role` is required and uses existing identifier grammar, with an open/extensible
vocabulary. `artifact` is an exact existing ArtifactRef; no dereference occurs.
There are no extensions, extra fields or duplicated semantic-digest slot.
The input digest is already carried by `artifact.semantic_digest`.

`Product.lineage: tuple[LineageEntry, ...]` is required; empty tuple is allowed.
It is a defensively owned tuple of exact LineageEntry members, preserving
supplied order. Order is semantic; do not sort or silently deduplicate.
Reject a duplicate exact key pair `(role, artifact.record_id)`, including when
two references with that pair differ in schema, digest or locator. The same
artifact may appear under different roles; different artifacts may share a
role. Record ID is used for uniqueness, not content identity.

Lineage records actual ordered processing inputs. Core owns completeness with
respect to actual declared inputs; duplicate rejection does not authorize
silently dropping an input. This is not graph traversal, transitive ancestry
flattening or a recursive provenance engine. No role vocabulary beyond the
identifier contract or new binding multiplicity rule is selected.

Each lineage artifact is a strong Product semantic dependency. Material
includes `role`, ordered position and `artifact.semantic_digest`; the sequence
position expresses order without another public index field. If ANY entry's
`semantic_digest is None`, both `product_semantic_material(...)` and
`product_content_digest(...)` return `None`. Never fall back to `record_id`,
`manifest_digest`, `locator` or full reference serialization. Structurally
valid weak references still construct and persist without fetching a digest.

## Acquisition References

Both ProductDraft and Product require
`acquisition_refs: tuple[ArtifactRef, ...]`: empty allowed, ordered, defensively
owned, with exact ArtifactRef members. `ArtifactRef.record_id` must be unique
within acquisition_refs, even if repeated references differ in other fields.
Do not sort, silently deduplicate or normalize. Sequence order is semantic.

The slot identifies the scientific acquisition inventory associated with the
Product. Generic Core does not require a hard-coded AcquisitionMetadata
schema_id, dereference targets or perform provider/registry lookup. Existing
ArtifactRef schema/type validation remains applicable, with open target schema.

Every acquisition reference is a strong Product semantic dependency. Semantic
material includes the ordered target semantic digests. If any required
`semantic_digest` is missing, both content helpers return `None`, with no
persistence identity fallback. A weak reference remains structurally valid.

Acquisition inventory and actual processing-input lineage are independent
semantic concepts. They MAY overlap. Neither must be a subset of the other;
do not auto-generate, synchronize or derive either collection from the other.
No acquisition role or scientific selection policy is invented.

## Semantic Metadata

Both ProductDraft and Product require exactly:

```text
semantic_metadata: Mapping[str, SemanticValue[FrozenJSON]]
```

The empty mapping is valid. Keys must be `str` and pass existing
`validate_identifier`, without normalization or a namespace requirement.
Mapping insertion order is nonsemantic; exact key spelling is semantic.
Every value must be an explicit exact SemanticValue with the field-specific
FrozenJSON payload domain, not an arbitrary typed SemanticValue payload.
Caller raw values must not be implicitly wrapped as KNOWN.

All existing SemanticValue states are supported here: KNOWN has a non-null
FrozenJSON payload; UNKNOWN and NOT_APPLICABLE have `value=None` and required
nonempty trimmed reasons. KNOWN's optional reason follows existing rules.
Evidence references are supported. Finite numbers, int/float distinctions,
nested null and ordered arrays retain existing FrozenJSON rules; a top-level
KNOWN null is invalid. No typed object is converted by reflection into JSON.

The Product/Draft owner must defensively own an immutable independent outer
mapping, including when supplied a caller-backed read-only view. It must not
retain mutable mapping aliases. Each SemanticValue already follows ADR0010/R1:
validate the supported immutable payload domain before snapshotting accepted
FrozenJSON views with existing `freeze_json`; raw mutable payloads are rejected.
Sharing already ownership-safe immutable entries is valid. Do not create
another SemanticValue or freezing mechanism or route metadata through the
extension-key validator.

| Semantic metadata | Extensions |
|---|---|
| Explicit semantic facts with KNOWN / UNKNOWN / NOT_APPLICABLE and evidence_refs. | ADR0011 namespaced opaque FrozenJSON with no automatic SemanticValue envelope. |
| Generic identifier keys; no namespace syntax requirement. | `namespace:local` top-level keys and existing ownership rules. |
| Generic Product semantic projection directly interprets the SemanticValue envelope. | Owner-defined opaque semantics; semantic by default, without invented generic interpretation. |

Do not merge these slots, let one override the other or invent cross-map
matching/synchronization rules. Both contribute independently to content;
pure diagnostics remain in provenance.

Complete semantic_metadata contributes keys and existing SemanticValue
material: status, value when KNOWN, reason_code under existing rules and ordered
evidence semantic identities. If required evidence identity is unavailable
strongly, both Product content helpers return `None`. No persistence fallback
or inference from opaque JSON strings is allowed.

## Content Identity

The following matrix freezes Product **content-only** semantic material.
Preserve all accepted R1/B1/B2 asset, DataLayer and Geometry digest rules.

| Product field/material | Content contribution |
|---|---|
| `product_kind`, `profile_id`, `profile_version` | Include exact supplied values. |
| `assets` | Existing accepted semantic NativeAsset material with explicit strong `asset_content_identities`; no inferred identity. |
| `layers` | Existing complete accepted DataLayer material, including structural local IDs and semantic ordered dimensions. |
| `geometries` | Existing accepted Geometry material, including local graph IDs, axes/shape order, grid definition and strong KNOWN reference/evidence identities. |
| `acquisition_refs` | Ordered target semantic digests. |
| `semantic_metadata` | Complete mapping and SemanticValue material as specified above. |
| `extensions` | Complete ADR0011 semantic mapping; object insertion order nonsemantic, arrays ordered. |
| `lineage` | Ordered roles and target semantic digests; sequence position is semantic. |
| `schema_id`, `schema_version`, `product_id` | Exclude Product schema/envelope and instance identity. |
| `producer` | Exclude the entire software/implementation/execution provenance value. |
| `produced_by` | Exclude the entire production-event traceability value. |
| `provenance_ref` | Exclude the provenance identifier pointer. |

Missing any required strong asset identity, acquisition/lineage target digest,
KNOWN Geometry reference digest or required semantic evidence identity makes
both `product_semantic_material` and `product_content_digest` return `None`.
No record ID, manifest digest, locator, declared checksum, path, size or full
persisted reference substitutes for strong content identity. NativeAsset
location/integrity/member-manifest metadata retain ADR0005/0006's persistence
boundary when explicit asset identities are supplied; not every ArtifactRef
slot is automatically a strong content dependency.

Excluded producer/production envelopes are not traversed for content evidence.
Their UNKNOWN states or missing evidence digests alone do not suppress an
otherwise available Product content digest. Another valid plugin or attempt
producing identical semantic Product content does not change that digest.
All serialized envelope fields still participate in complete manifest bytes
and their byte digest.

This is not the final recipe-aware `F_artifact`/ArtifactRef.semantic_digest
computation in P4.0 §7.6. Its schema/recipe/output identity requirements are
unchanged and remain P4.2 work. Available content identity does not assert
available final reusable artifact identity or cache eligibility. Semantic
execution identity must not be confused with Product semantic-content identity.

## Serialization / Wire Contract

The final Product record is a flat self-describing JSON object containing
exactly all sixteen Product fields above: no extras and no omissions. Its
`schema_id` is exactly `"insarforge:product"` and its `schema_version` is integer
`2`. The revision reflects a breaking final envelope relative to transitional
pre-ADR0012 representation. The strict Phase 4 decoder supports this v2
representation only; no old wrapper or second supported transport schema is
introduced. Reject any other schema literal/revision, including bool as version.

Nested objects have exact explicit fields:

| Object | Exact fields |
|---|---|
| ProducerRef | `plugin, implementation_version, implementation_identity_digest, execution_identity_digest` |
| ProductionRef | `task_fingerprint, output_port, attempt_id` |
| LineageEntry | `role, artifact` |
| PluginRef | `kind, plugin_id, api_version` |
| ArtifactRef | `record_id, schema_id, schema_version, semantic_digest, manifest_digest, locator` |
| SemanticValue | `status, value, reason_code, evidence_refs` |

Use existing strict codecs and validation for PluginRef, ArtifactRef and
SemanticValue, with owner-specific type/state validation for each new slot.
Identity/fingerprint SemanticValues are objects, never bare strings or null.
Wire statuses use existing enum values `known`, `unknown`, `not_applicable`;
reject `not_applicable` for both producer digests and task_fingerprint.
Reject malformed fields, unknown or missing nested keys, wrong payload types,
invalid status/value combinations and missing/invalid UNKNOWN reasons.
ArtifactRef's nullable semantic_digest remains valid representation; its
identity availability is handled by the owning semantic boundary.

Lineage, acquisition and evidence collections persist as ordered JSON arrays;
metadata persists as an object of explicit SemanticValue envelopes. Constructor
iterable support does not relax byte-decoder array requirements. Existing
value-codec list/tuple array representations may be retained. An explicit
metadata SemanticValue JSON envelope may have its validated JSON payload frozen
with existing facilities during decoding; that is not raw-value KNOWN inference.

Preserve `canonical_json_v1`: UTF-8, sorted object keys, compact separators,
`ensure_ascii=False`, `allow_nan=False`; reject duplicate JSON keys and
nonfinite numbers at every depth. Preserve Unicode spelling, scalar types and
array order. Use explicit schema branches, not generic reflection, class imports
by name or a universal decoder. Preserve S1's existing bounded safe-persistence
checks over the complete emitted projection and its closed exception boundaries.

Product schema revision 2 does not automatically revise independent target
record schemas, canonical JSON, digest algorithm/domain tags or helper material
revision constants. Preserve existing content-helper constants and accepted
SHA256/domain separation rules; excluding Product.schema_version does not remove
the helper's own material-schema metadata. Full manifest digest remains outside
the Product whose bytes it protects, avoiding a self-hash cycle.

## Ownership / Validation

Product, ProductDraft and the three new reference/value contracts are frozen.
Product/Draft must independently own acquisition_refs, semantic_metadata and,
for Product, lineage. Preserve existing ownership of assets/layers/geometries
and extensions. No caller-owned mutable collection or backing-view alias may
change retained semantics after construction. Reusing deeply immutable elements
is valid; exclusive object identity is not required. Use ADR0010/R1 and ADR0011
facilities, with no generic freezer, deepcopy framework or arbitrary rewriting.

Here “identifier” is existing `contracts.values.validate_identifier`: nonempty
string, no whitespace or Unicode category C characters. Preserve valid spelling;
no normalization or closed vocabulary is introduced. Opaque trimmed version,
digest and fingerprint text does not acquire this stricter identifier grammar.

| Invalid input | Existing failure convention |
|---|---|
| Wrong nested public type, wrong mapping/member/key type | `TypeError`. |
| Identifier violation, invalid scalar content or status/value combination | `ValueError` under existing owner conventions. |
| Duplicate lineage `(role, artifact.record_id)` | `ValueError`. |
| Duplicate acquisition `record_id` | `ValueError`. |
| Wrong Product schema literal/revision at strict decode | Existing serialization exception family; preserve S1 decoder error boundaries. |

No exception hierarchy redesign or blanket error remapping is authorized.
Construction/decode validate exact local types, requiredness, state/value/reason,
identifiers, uniqueness and ownership without target access. Existing
Product-level graph checks remain separate from constructing standalone refs.
Representation validation cannot prove an opaque supplied digest true; do not
invent equality-to-ID heuristics or promise runtime verification.

The existing module DAG remains binding. SemanticValue-dependent ProducerRef
and ProductionRef must be at Product-peer level; existing `products.models`
is sufficient. Do not put them in `contracts.identity`/`contracts.values` by
introducing forbidden leaf imports of `products.semantics`, or move SemanticValue
to force that placement. No new public module or hierarchy is required.
Product must not depend on plugin protocols, operations, Core runtime or
concrete plugins merely to represent these values.

## Finalization Boundary

| Responsible boundary | Supplies |
|---|---|
| Plugin/construction | ProductDraft's exact nine fields: product_kind, profile_id, profile_version, assets, layers, geometries, acquisition_refs, semantic_metadata, extensions. |
| Core finalization | schema_id = `"insarforge:product"`, schema_version = `2`, product_id, producer, produced_by, lineage, provenance_ref. |

Core adds envelope/traceability to validated semantic content and owns actual
processing-input lineage. Lineage is semantic even though Core supplies it.
Plugins must not forge Core-owned facts on Draft. This is a static responsibility
contract only: no finalization orchestration/API, identifier generation, runtime
lookup, output commit or WorkflowPlan execution is defined here. Direct static
construction uses supplied facts and performs no execution to obtain them.

## Compatibility / Migration

Migration is strict and explicit, acceptable in current pre-release Phase 4.
Old transitional Product payloads are not automatically upgraded. Reject the
old v1 wrapper, old producer-only PluginRef shape, top-level producer version,
bare ArtifactRef lineage, nested/nullable provenance reference and bare-string
fingerprint proposal. No legacy decoder, alias, compatibility property,
version negotiation or old-format fallback is retained.

Do not infer acquisition_refs, semantic_metadata, produced_by, lineage or
provenance_ref; heuristically split old producer fields; supply fake fingerprints
or digests; inject empty values for omitted required slots; or silently convert
schema v1 to v2. Repository fixtures must migrate explicitly with supplied facts,
including explicit UNKNOWN reasons when appropriate. Previously accepted D1
proposals do not create another supported wire version or require v3.

ProductDraft currently has no explicit persistence codec. ADR0012 requires none:
only its static nine-field contract is frozen. Do not create a Draft manifest,
serializer or digest API merely for symmetry.

## Alternatives Considered

| Alternative | Rejection rationale |
|---|---|
| A. Keep transitional Product shape | Does not meet frozen sixteen/nine-field authority. |
| B. Put envelope fields on ProductDraft | Blurs construction and Core finalization ownership. |
| C. Producer = PluginRef only | Loses required implementation/execution identity. A version-only ProducerRef also loses those digest concerns. |
| D. Mandatory plain task_fingerprint string | Cannot represent valid weak/unavailable fingerprint outcomes without fabrication. |
| E. task_fingerprint: str or None | Ambiguous unavailable state without an explicit reason. |
| F. Collapse producer and produced_by | Software identity and actual production-event identity differ. |
| G. Derive lineage from acquisition_refs | Acquisition inventory and actual processing inputs differ. |
| H. Merge semantic_metadata into extensions | Explicit SemanticValue state/evidence and opaque extensions have different contracts. |
| I. Persistence fallback for missing semantic digests | Weakens content identity and confuses stored location/instance/bytes with semantic equivalence. |
| J. Universal reference framework | Adds unnecessary coupling; composition of existing values is sufficient. |
| K. Keep old Product decoder compatibility | Conflicts with strict pre-release final shape and encourages guessed missing facts. |
| Full SemanticExecutionIdentity in Product | Duplicates primary runtime facts and introduces an unnecessary execution schema; supplied digest availability suffices. |

## Consequences

Benefits: exact final Product/Draft boundary; explicit producer versus production
identity; weak fingerprint availability representable without fabrication;
strong lineage/acquisition semantic dependencies; semantic metadata distinct
from opaque extensions; strict deterministic wire representation; no persistence
fallback; no P4.2 implementation leakage.

Costs: breaking fixture migration; Product wire revision 2; rejection of old
transitional manifests; three new static value contracts; content digest may
be unavailable when strong referenced semantic digests are missing; explicit
UNKNOWN reasons required for unavailable producer/fingerprint identities.
Architecture acceptance alone provides no implementation conformance claim.

## Deferred / Non-Goals

- P4.2: computation of SemanticExecutionIdentity and implementation identity
  digest; task fingerprint algorithm/resolution/recomputation; cache key
  generation, eligibility and cache/reuse; retry and retry identity; attempt
  lifecycle; provenance storage/runtime; WorkflowPlan execution; scheduler;
  resume and dry-run execution. Existing P4.0 authority is preserved, not
  redefined by this static representation decision.
- Static binding: OperationBinding, PortContract and registration ownership
  are not decided. B3-REQ-15–17 remain outside ADR0012.
- Profile cleanup: no renaming of `selector_kind`, `quantity_kind`,
  `geometry_domain_id` or `domain_id`; those remain CLEANUP.
- Scientific choices: no mission-specific acquisition schemas, SAR wavelength,
  polarization semantics, LOS sign, geometry domain defaults, Product scientific
  quantity defaults or acquisition/lineage role vocabularies beyond open
  identifiers. No scientific convention or real profile is selected.
- No `BaseRef`, `GenericRef`, `TypedRef`, `ReferenceProtocol`, `ProducerBase`,
  `LineageGraph`, generic hierarchy, recursive provenance engine or new universal
  reference framework. No new SemanticExecutionIdentity public wrapper or
  ProductDraft persistence requirement.

## Implementation Follow-up

Define these separate future segments; **do not execute them in this ADR task**.
Each implementation segment must finish additive/full green as applicable,
with no intentionally broken intermediate completion. Existing S1 strictness,
safe persistence, ADR0010/R1 ownership and ADR0011 enforcement stay intact.

| Segment | Scope and future validation |
|---|---|
| S3a | Add static ProducerRef, ProductionRef and LineageEntry foundations at an allowed Product-level location. Focused exact-field/type/state/identifier/immutability/no-lookup tests, including UNKNOWN and NOT_APPLICABLE rejection at identity owners. Additive and full repository green; no integrated finding closure assumed. |
| S3b | Migrate ProductDraft to the final nine fields: acquisition_refs and semantic_metadata, remove Draft.schema_version and Draft.lineage, split shared content versus Product-only validation as needed. Explicit downstream fixture migration; focused ownership/uniqueness/content tests and full green. No Draft persistence. |
| S3c | Migrate Product to all sixteen fields and final references/envelope, strict v2 serialization, semantic projection/content digest, validation and explicit fixture migration. Cover malformed nested schemas, strong missing-digest propagation, semantic ordering and envelope exclusion invariance; full green. |
| S3d | Validation-only authoritative Product-envelope gate after S3a–S3c. Verify exact fields, strict codecs, ownership, content boundaries and all B3-REQ-01–08 obligations; close those findings only if all pass. Failures return to scoped implementation. |

The Draft portion of acquisition_refs/semantic_metadata does not close findings
that also require Product integration. Future full-green gates belong to those
separately authorized implementation tasks; this documentation task runs no
pytest and begins neither S3a nor P4.2.

## Remediation Ledger

| Accounting | Count / disposition |
|---|---|
| B3b.0 REQUIRED total | 21 |
| Closed by S1 | 8: B3-REQ-09–14, 18, 20 |
| Closed by S2a-R1 | 1: B3-REQ-21 |
| Closed by S2b.4 | 1: B3-REQ-19 |
| Remaining before Product implementation | 11 |
| Closed by ADR0012 documentation | 0 |
| Remaining after this ADR | 11 |

| Open finding | Outstanding implementation |
|---|---|
| B3-REQ-01 | acquisition_refs on both Draft and Product, ownership, codec and identity. |
| B3-REQ-02 | semantic_metadata on both, explicit states, ownership, codec and identity. |
| B3-REQ-03 | Remove Draft.schema_version and Draft.lineage; exact nine-field migration. |
| B3-REQ-04 | Product schema literal/revision and strict v2 representation. |
| B3-REQ-05 | Complete ProducerRef and remove top-level producer_implementation_version. |
| B3-REQ-06 | ProductionRef and weak fingerprint availability in produced_by. |
| B3-REQ-07 | Role-aware ordered lineage and strong identity. |
| B3-REQ-08 | Identifier-only provenance_ref. |
| B3-REQ-15–17 | Non-Product static binding/registration/ports; all OPEN and excluded. |

**B3-REQ-01 through B3-REQ-08 remain OPEN.** Architecture resolution closes zero
implementation findings. Earlier strict-decoder, extension and SemanticValue
closures are not reopened by new Product integration obligations.

Unresolved ADR0012 decision items: **None**.

## Evidence Basis

External decision evidence is in sibling
`InSARForge_dev_notes/phase4/P4.1B/R2/ADR0012_D0/`, `ADR0012_D1/` and
`ADR0012_D2/`, at baseline `acaa19a2f410cd0468c5366ac97c845d80cf015b` on
`feature/p04-core-workflow-contracts`. D0 extracts gaps, D1 accepts the
non-conflicting choices, and D2 resolves C1/C2 with the final producer and
production contracts. Historical candidates and tentative implementation
locations yield to this accepted decision and the existing module DAG.
Review reports for this documentation-only freeze are outside the repository
under `InSARForge_dev_notes/phase4/P4.1B/R2/ADR0012/`.
