# ADR-0011 — Extension Namespace Grammar and Ownership

**Status: Accepted**

**Relationship:** clarification/addendum to `P4.0-FREEZE-1`, grounded in
[ADR-0001](0001-core-boundaries-and-dependencies.md),
[ADR-0002](0002-plugin-contracts-and-registry.md),
[ADR-0003](0003-product-and-scientific-metadata.md),
[ADR-0010, including R1](0010-semanticvalue-payload-domain-and-deep-ownership.md),
and [Phase 4 contracts](../architecture/phase4-contracts.md) §§6.4–6.5, 8,
13.1–13.2. This is the documentation-only P4.1B R2 D-NAMESPACE decision.

## Context

P4.0 requires namespaced FrozenJSON extensions, deep ownership, strict
construction/decoding, and semantic treatment by default. B3b.0 identified
B3-REQ-19 / H06: nine allocated public extension slots call `freeze_json`
without enforcing a top-level object or namespace grammar. Its explicit
recommendation was Candidate A. ADR0011-D0 returned DECISION_REQUIRED because
grammar, ownership conventions, reservations, unknown-owner behavior and
migration still required acceptance. The B3b.0/D0 reports are evidence and
decision input; accepted ADRs remain authority.

B3b-S1 is PASS / CLOSED. ADR0010 and ADR0010-R1 are Accepted;
B3b-S2a-R1 is PASS / CLOSED and closes B3-REQ-21. Twelve REQUIRED
implementation findings remain. This ADR settles B3-REQ-19's public
architecture only; it does not claim current implementation conformance.

## Decision

Select **Candidate A: `namespace:local`**, with exactly one literal colon.
A namespace is a stable extension ownership claim and collision domain.
Generic Core validates representation, without authenticating the producer's
authority to use that namespace. Unknown syntactically valid namespaces MUST
be accepted and preserved opaquely. All nine allocated extension slots are
object-shaped FrozenJSON and SEMANTIC by default.

These decisions freeze observable behavior. No production code, tests,
serializer implementation, fixture migration or enforcement helper is changed
by acceptance. B3b-S2b is a separate implementation segment.

## Grammar

The formal logical shape is:

```text
<namespace> ":" <local-name>
count(":") == 1
```

Both `namespace` and `local-name` MUST independently be non-empty strings
satisfying the existing `contracts.values.validate_identifier` semantics:
no whitespace and no Unicode category C characters. Both components MUST
explicitly contain **no colon character**, even though the generic identifier
validator permits colon. Whole-key identifier validation alone is insufficient.
The generic identifier validator itself is unchanged.

Keys are case-sensitive. Preserve original valid spelling, including case,
Unicode and punctuation. Do not normalize case, Unicode, punctuation or
spelling; do not silently trim whitespace. No lowercase DNS semantics,
ASCII-only rule, new closed vocabulary or additional punctuation restriction
is introduced. Slash and dot may occur as component punctuation when the
existing identifier validator permits them; they acquire no special owner or
plugin-kind meaning.

Parsing is deterministic: require a string key and exactly one colon, split
into namespace and local-name, validate both independently, reject empty
components or a component containing another colon, and retain the original
valid key. Do not guess, escape, repair or reinterpret malformed keys.

Synthetic grammar examples (no scientific vocabulary is selected):

| Key | Result |
|---|---|
| `insarforge:quality-flags` | Valid syntax; framework-owned example subject to the reservation below. |
| `vendor-x:diagnostics` | Valid; preserve content as semantic extension data. |
| `vendor-x:future-metadata` | Unknown but valid: accept and preserve opaquely. |
| `Vendor-X:sample` and `vendor-x:sample` | Both valid and distinct. |
| `local` or `future-metadata` | Reject: unnamespaced. |
| `:local` or `:x` | Reject: empty namespace. |
| `namespace:` or `a:` | Reject: empty local-name. |
| `a:b:c` | Reject: multiple colons. |
| ` vendor-x:sample` or `vendor-x:two words` | Reject whitespace; do not trim. |

## Ownership Model

Namespace ownership identifies the extension publisher's stable claim and
collision domain. Owners are responsible for choosing a stable namespace they
control and avoiding conflicting claims; distinct owners must not claim the
same namespace as though it were independently theirs. Extensions stay within
allocated `.extensions` maps and cannot override standard contract fields.
This convention does not prove global uniqueness or prevent a dishonest claim.

**Syntactic ownership != runtime authorization.** Generic Core does not
implement ACLs, signatures, registry-backed authorization, network verification,
or organization/domain verification in P4.1. ADR0011 provides no cryptographic
or policy enforcement that a producer truly owns its namespace. Any future
runtime trust policy requires a separate explicit architecture layer, outside
P4.1B.

### Reserved built-in namespace

Reserve exactly **`insarforge`** for framework-defined built-in extensions.
Third-party extensions MUST NOT claim it. A generic validator may reject a
third-party ownership attempt only where caller context actually identifies
the producer as third-party; parsing a key alone cannot establish that fact.
Do not require runtime registry authorization merely to parse a built-in key.

No synonymous namespace such as `core`, `builtin` or `internal` is reserved.
The historical proposal to reserve a synthetic test namespace is not adopted:
fixtures may use synthetic namespaces without creating another reservation.
Reservation follows the exact case-sensitive spelling; there are no aliases.

### Plugin and non-plugin owners

An extension namespace is **not required to equal**
`PluginDescriptor.plugin_id`; do not impose `namespace == plugin_id`.
Extension-bearing records exist outside plugin-owned Product processing.
Plugin IDs form an existing separate identifier domain and may contain
colon/delimiter forms unsuitable for this grammar. For example, synthetic
plugin ID `plugin:sample` cannot be reused unchanged as a namespace. Do not
silently split, shorten, escape or normalize plugin IDs to invent an owner.
A plugin MAY use a stable namespace it controls; this is not generic-Core
authorization.

Non-plugin producers, including future providers, external metadata producers,
catalog adapters, QC producers, and organizations/tools, may own extension
namespaces without registering a PluginDescriptor solely to use a key.
No new owner registry is introduced.

Generic extension validation MUST NOT require PluginRegistry or query
PluginDescriptor, PluginKind or CapabilityAvailability for namespace syntax.
No registry lookup, automatic discovery or runtime capability interaction is
required. This preserves ADR-0001's dependency direction.

### Unknown namespaces

A syntactically valid namespace unknown to the current InSARForge installation
MUST be accepted and preserved opaquely. Core MUST NOT discard or rewrite it,
reject it merely because its owner is unknown, or require plugin/registry
lookup. Unknown owner knowledge and invalid syntax are different conditions:
`vendor-x:future-metadata` is preserved; `future-metadata`, `:x`, `a:` and
`a:b:c` are rejected.

Unknown namespace does not imply trusted or understood semantics. The existing
§6.4 consumer boundary remains: a critical profile lacking required registered
validator support must reject consumption rather than assume scientific
understanding. This does not authorize blanket rejection of unknown stored
extensions or define a new validator registration API.

## Extension Value Contract

The currently frozen extension-bearing public types are exactly:

| Public slot | Logical shape | Semantic classification |
|---|---|---|
| `ProductDraft.extensions` | Object-shaped FrozenJSON | SEMANTIC |
| `Product.extensions` | Object-shaped FrozenJSON | SEMANTIC |
| `AssetRequirement.extensions` | Object-shaped FrozenJSON | SEMANTIC |
| `GeometryRequirement.extensions` | Object-shaped FrozenJSON | SEMANTIC |
| `LayerRequirement.extensions` | Object-shaped FrozenJSON | SEMANTIC |
| `ProductProfile.extensions` | Object-shaped FrozenJSON | SEMANTIC |
| `CatalogSnapshot.extensions` | Object-shaped FrozenJSON | SEMANTIC |
| `AcquisitionMetadata.extensions` | Object-shaped FrozenJSON | SEMANTIC |
| `QCReport.extensions` | Object-shaped FrozenJSON | SEMANTIC |

Each `.extensions` is logically `Mapping[str, FrozenJSON]`, stored using the
existing immutable FrozenJSON representation. The top level MUST be a
mapping/object, including a valid empty mapping; scalar, array/tuple and null
containers are invalid. Every top-level key follows this ADR's grammar.
Each per-key value belongs to the full existing FrozenJSON domain, including
scalars, null, ordered arrays/tuples and nested objects. Per-key values need
not themselves be objects. Nested JSON object keys retain ordinary FrozenJSON
string-key rules; namespace grammar applies to the top-level extension keys.

The contract owning `.extensions` may accept a caller Mapping and create an
independently owned canonical snapshot using existing `FrozenJSON` /
`freeze_json`. Supported nested caller JSON containers may be frozen by that
owner's explicit mapping contract. Caller mutation after construction,
including mutation through backing aliases of read-only views, MUST NOT alter
stored extension semantics.

This does not violate ADR0010/R1: `.extensions` has an explicit typed mapping
contract, its owner defines the conversion, and its logical type remains an
extension object/map. Generic SemanticValue's admission and ownership rules
are unchanged. No second freezer, arbitrary-object conversion or required
public `ExtensionValue`, `ExtensionKey`, `ExtensionMap` or custom wrapper
hierarchy is introduced.

No extension fields are added to NativeAsset, DataLayer, GeometryDescriptor,
AxisDescriptor, GridDefinition or NoDataSpec, from which bags were deliberately
removed. Other accepted exact field sets, including DirectoryMemberManifest,
DirectoryMember, LayerSelector and ArtifactRef, are unchanged. Parameters,
attributes and other distinct typed payloads are not reclassified as extensions.
There is no B1/B2 redesign.

## Semantic Treatment

All **nine** extension slots are SEMANTIC by default; **zero** are
persistence-only. Extension content is not generic persistence noise, even if
a local name resembles a diagnostic label. Pure diagnostic annotations belong
in the existing separate provenance area under §6.4.

Where a containing object participates in semantic material/content digest,
its extensions participate in semantic identity. Preserve Product's existing
extension inclusion. Where no standalone semantic digest currently exists,
serialization must preserve extensions exactly in logical content, and future
semantic identity must not silently classify them as persistence-only.
Absence of a current dedicated codec/digest does not create a semantic exception
or require building a new codec/digest/storage system in this task.

Under the existing canonical FrozenJSON representation:

- Mapping insertion order is not semantic, including nested object order.
- Array/tuple order remains semantic; do not sort arrays.
- Extension key spelling, namespace/local spelling and values are semantic.
- Preserve case, Unicode spelling and existing scalar distinctions, including
  integer versus float; do not infer scientific equivalence.

No per-key semantic/persistence flags are introduced in P4.1.

### ProductProfile and requirement boundary

`ProductProfile.extensions` obeys the same grammar, FrozenJSON ownership,
strict serialization and semantic treatment as the other eight slots. This
settles the generic enforcement obligation identified in B3-REQ-19; actual
enforcement remains implementation-open.

It is NOT automatically an arbitrary matching language over
`Product.extensions`. Generic Core MUST NOT infer extension-specific predicates
from opaque FrozenJSON values. Future extension-specific matching requires an
explicit typed contract/profile mechanism; none is created in P4.1B.

`AssetRequirement.extensions`, `LayerRequirement.extensions` and
`GeometryRequirement.extensions` likewise remain semantic metadata on their
own requirement contracts. They are not implicitly predicates against target
model extensions. NativeAsset, DataLayer and GeometryDescriptor have no generic
extension bags. No hidden cross-object matching semantics are introduced.

## Serialization / Validation

Constructor and strict codec boundaries must explicitly enforce object shape
and extension-key grammar. `freeze_json` validates/freezes the existing value
domain; it does not validate namespace syntax. A suitable implementation
sequence is:

```text
inspect top-level mapping
    -> validate all extension keys
    -> validate/freeze values using canonical freeze_json
    -> store independently owned immutable snapshot
```

The observable shape, grammar, failure and ownership requirements are frozen;
private function structure is not. A shared private validator/snapshot helper
is sufficient.

Strict codecs for extension-bearing records MUST require an object-shaped
extension container, reject malformed and unnamespaced keys, preserve unknown
valid namespaces and round-trip extension values. Retain strict record
field/version boundaries, JSON duplicate-key and nonfinite-value rejection
at all depths. Logical content, exact valid strings and array order survive
round-trip; original JSON whitespace, object insertion order and escape spelling
need not survive canonical encoding. No compatibility decoder for legacy bare
keys is permitted.

Preserve B3b-S1's bounded recognizable-secret safe-persistence checks on emitted
record projections. Namespaced keys/values do not gain permission to persist
recognizable secrets. Namespace ownership is no security bypass. Existing
rejection applies without introducing a general secret scanner or asserting
that S1 adds an ingress authorization gate.

Use existing constructor/contract conventions:

| Invalid input | Failure |
|---|---|
| Wrong top-level extension container type | `TypeError` |
| Non-string extension key | `TypeError` |
| Malformed namespace/local grammar, including empty components or wrong colon count | `ValueError` |
| Unsupported FrozenJSON value | Existing FrozenJSON failure behavior; no new value-domain error policy. |

Built-in errors remain valid where current constructor conventions allow.
Preserve any existing ContractError boundary mandated for decoder APIs; no
new extension-specific exception hierarchy or blanket error conversion is
required.

## Compatibility / Migration

This tightens existing extension validation. Empty maps and already valid
namespaced mappings remain valid, subject to existing value/persistence rules
and the explicit built-in reservation. Unknown valid namespaces remain
forward-compatible. No B1/B2 public model changes or profile naming changes
are introduced.

Legacy unnamespaced keys are invalid. Migration MUST be explicit and preserve
extension values. Never silently map `local` to `insarforge:local`, infer an
owner, add compatibility aliases, or introduce a dual-format decoder.
Only known framework-owned existing keys, if any, may explicitly migrate to
`insarforge:<local>`. Do not assume every existing bare key is framework-owned.
Third-party owners choose a namespace they control; fixtures/tests may choose
synthetic namespaces. Invalid scalar/array/null bags must be explicitly
re-expressed as valid extension objects by their owners, without guessed keys
or ownership. No schema-version or digest-revision number is selected here.

## Alternatives Considered

| Alternative | Disposition and rationale |
|---|---|
| Candidate A: `namespace:local` | Selected: deterministic single delimiter, reuses existing identifier semantics, supports plugin and non-plugin ownership with minimal migration. |
| Candidate B: `reverse-domain-owner:local` | Rejected as the generic Phase 4 grammar: introduces a new organization/domain identity grammar, higher validation complexity and unnecessary migration burden. Plugin/non-plugin identity does not currently depend on DNS ownership; global ownership verification is outside P4.1. An owner may choose a reverse-domain-looking namespace value if it satisfies the accepted component grammar; lowercase DNS semantics are not imposed. |
| Candidate C: `plugin-kind/plugin-id:local` | Rejected: couples generic extensions to plugin registry identity, although not all extension-bearing records are naturally plugin-owned; needs extra delimiter/ownership rules, risks existing plugin-ID delimiter ambiguity and creates unnecessary Core/registry coupling. A slash-containing Candidate A token does not acquire this rejected interpretation. |
| Arbitrary unnamespaced keys | Rejected: no collision domain, unclear ownership and poor long-term third-party interoperability. |
| Mandatory public ExtensionKey / ExtensionMap wrappers | Rejected for P4.1B: a private validation helper is sufficient. A nominal type may be reconsidered later only if proven necessary. |

## Consequences

Extension spelling, ownership claims and invalid-input behavior now have one
representation contract across nine public slots. Opaque unknown namespaces
support forward-compatible preservation without registry coupling. Independent
canonical snapshots keep semantic identity stable under caller mutation.

Callers with bare keys or non-object bags must migrate explicitly. Namespace
owners retain responsibility for collision avoidance; syntax alone does not
establish authority or scientific understanding. Supporting all FrozenJSON
values does not supply generic matching semantics. These costs do not justify
new public wrappers, a registry or a second freezing mechanism.

## Deferred / Non-Goals

- Product envelope/reference schemas, producer/production/lineage schemas and
  final Product/Draft field representation remain separate Product decisions.
- OperationBinding / PortContract schemas, codec/validator attachment and
  registration ownership remain separate binding decisions.
- Profile public naming cleanup and B1/B2 public model redesign are excluded.
- SemanticValue ownership beyond accepted ADR0010/R1 is unchanged.
- No P4.2 runtime behavior, capability probing, execution, cache, retry,
  scheduler, task fingerprint, state, resume or dry-run behavior is decided or
  implemented; P4.2 does not begin here.
- No scientific conventions, values, defaults or real profiles are selected.
- No new owner registry, authorization layer, public wrapper, per-key semantic
  flag, extension predicate mechanism or general secret scanner is introduced.

## Implementation Follow-up

The next separately authorized segment is
**B3b-S2b — Extension Namespace Enforcement**. Expected responsibilities:

- One shared private namespaced-extension validator/snapshot helper using
  existing `validate_identifier` and canonical `freeze_json`, respecting the
  leaf dependency boundary.
- Migrate all nine allocated contracts to use it, including ProductProfile and
  its three requirement contracts; validate object shape, keys and ownership.
- Enforce strict serialization/decoding where codecs exist and extension
  digest/semantic projection where applicable; retain unknown namespace
  preservation, ordered arrays and S1 safe-persistence guards.
- Explicitly migrate affected fixtures with known or synthetic ownership,
  preserving values and intended test meanings.
- Focused tests for all nine constructors, invalid containers/key types and
  grammar, empty maps, unknown namespaces, contextual built-in reservation,
  independent nested/backing-alias ownership, round-trip and semantic order.
- Finish with full repository green, including the established regression and
  lint gates. No intentionally broken intermediate completion.

No public wrapper is prescribed. Do not build missing profile/record codecs,
new standalone digests or P4.2 storage merely to fill an inventory gap.
This documentation task does not begin B3b-S2b or implement B3-REQ-19.

### Remaining REQUIRED finding ledger

| Accounting | Count / disposition |
|---|---|
| B3b.0 REQUIRED total | 21 |
| Closed by B3b-S1 | 8: B3-REQ-09–14, 18, 20 |
| Closed by B3b-S2a-R1 | 1: B3-REQ-21 |
| Remaining before ADR0011 implementation | 12: B3-REQ-01–08, 15–17, 19 |
| Closed by ADR0011 documentation | 0 |
| Remaining after this ADR | 12 |

**B3-REQ-19 remains OPEN** until implementation passes. ADR0011 resolves its
public architecture decision only. **B3-REQ-03 remains OPEN**, coordinated
with the later Product migration. No finding is closed by acceptance alone.

Unresolved ADR0011 decision items: **None**.

### Evidence basis

External evidence is under sibling
`InSARForge_dev_notes/phase4/P4.1B/R2/`:
`B3b_0/extension_namespace_decision.md`, `required_finding_matrix.md`,
`implementation_segment_plan.md`; and `ADR0011_D0/ADR0011_D0_summary.md`,
`extension_finding_ledger.md`, `extension_slot_inventory.md`,
`namespace_candidate_matrix.md`, `identifier_compatibility.md`,
`ownership_boundary.md`, `semantic_persistence_matrix.md`,
`productprofile_extension_gap.md`, `adr0011_question_matrix.md`.
Historical proposals yield to this accepted decision; they are not authority
for extra reserved namespaces or runtime ownership checks. Review evidence
for this docs-only decision is outside the repository in `ADR0011/`.
