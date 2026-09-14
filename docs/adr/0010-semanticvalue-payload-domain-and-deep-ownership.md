# ADR-0010 — SemanticValue Payload Domain and Deep Ownership

**Status: Accepted**

**Relationship:** clarification/addendum to `P4.0-FREEZE-1`, grounded in
[ADR-0001](0001-core-boundaries-and-dependencies.md),
[ADR-0003](0003-product-and-scientific-metadata.md),
[ADR-0007](0007-datalayer-selector-dimensions-nodata.md),
[ADR-0008](0008-geometry-axes-and-dimension-alignment.md),
[ADR-0009](0009-grid-definition-and-geometry-reference.md) and
[Phase 4 contracts](../architecture/phase4-contracts.md) §§6.2, 6.4–6.5, 8
and 13.2. This is the documentation-only P4.1B R2 D-SEMANTIC decision.

## Context

P4.1B R2-B3a returned REVIEW_REQUIRED. B3b.0 identified 21 REQUIRED findings,
including B3-REQ-21 / H08: SemanticValue retains a caller-owned mutable payload
despite its frozen outer dataclass. B3b-S1 closed eight implementation-ready
findings; its committed/pushed baseline and green CI are the supplied task
context. Acceptance here does not claim implementation conformance.

P4.0 requires deeply owned semantic state, while ADRs 0007–0009 require typed
KNOWN payloads. Neither generic `T` nor current constructor acceptance grants
permission to retain arbitrary Python objects. The B3b.0 proposal to snapshot
raw JSON containers inside SemanticValue was provisional evidence, not an
accepted contract. This ADR settles that choice with explicit caller freezing
and type preservation. It clarifies how §6.4 applies to this generic envelope;
dedicated container-owning contracts retain their own freezing rules.

**ADR0010-R1 — FrozenJSON Defensive Snapshot Clarification:** B3b-S2a stopped
with BLOCKED_SCOPE and zero repository edits because canonical FrozenJSON
mappings and caller-backed MappingProxyType views share a runtime representation.
Validation of type and current contents cannot prove independent ownership.
R1 clarifies the validation-before-snapshot boundary below; this ADR's number,
title and Accepted status remain unchanged. No implementation is performed.

## Decision

**SemanticValue is a semantic-state envelope around an ownership-safe payload.**

An accepted payload must already belong to the supported domain below.
For generic FrozenJSON immutable-view input, domain membership is validated
first and independent ownership is then enforced by the canonical snapshot
rule below. Domain validation is not a claim that a read-only view already owns
its backing storage.
SemanticValue owns its envelope; the payload contract owns its payload state.
All retained state contributing to semantics must remain stable after
construction, including when a caller mutates an original input collection.
Sharing an already ownership-safe immutable value is valid; exclusive object
identity and copying every object are not requirements.

SemanticValue must not invent an immutable representation for arbitrary Python
objects or silently change the public logical type `T` to obtain immutability.
In particular, `SemanticValue[list[int]]` must not store a tuple instead, and
`SemanticValue[dict[str, X]]` must not store an unrelated mapping representation.
Raw mutable payloads are rejected, not repaired by implicit generic coercion.

## Detailed contract

The existing public envelope remains:

```text
SemanticValue[T](
    status: SemanticStatus,
    value: T | None,
    reason_code: str | None,
    evidence_refs: tuple[ArtifactRef, ...],
)
```

### Supported payload domain

| Category | Required ownership condition |
|---|---|
| Immutable scalars | `str`, `int`, finite `float`, and `bool`, subject to the typed field's validators. Preserve their values and logical types. |
| Immutable enums and value objects | Their applicable contract guarantees ownership safety of all semantic state; enum membership alone does not establish that guarantee. |
| Dedicated immutable InSARForge contract objects | Their own public contract owns/freezes nested state. Current Phase 4 examples include UnitSpec, SignSpec, NoDataSpec, GridDefinition, ArtifactRef and PhysicalQuantity. Product/value contracts qualify only when they meet the same deep-ownership rule. |
| FrozenJSON values and accepted immutable views | Existing FrozenJSON value constraints apply recursively. Validate the immutable-view domain before an independent canonical snapshot establishes retained ownership; provenance from `freeze_json` is not required. |
| Immutable tuples | Every recursively contained item belongs to this ownership-safe domain. An empty tuple is valid at the generic layer. |

This is an ownership domain, not permission to bypass field-specific type
checks. `SemanticValue[UnitSpec]` still requires UnitSpec when KNOWN. A generic
annotation alone does not enforce that runtime rule; typed owners must do so.
Numeric fields retain their existing bool exclusions and int/float distinctions.
No additional arbitrary-object or unordered set payload category is introduced.

### Unsupported containers and opaque objects

Direct caller-owned `list`, `dict`, `set`, and `bytearray` payloads are invalid,
as are equivalent mutable Mapping, Sequence and Set containers. Wrapping such
a value in a tuple or frozen dataclass does not make it supported. A read-only
view of caller-owned mutable storage is not proof of ownership safety either.

Arbitrary opaque mutable custom objects are not automatically supported.
SemanticValue must not call arbitrary `deepcopy`, introspect and rewrite
application objects, pickle them, serialize them, or trust their mutability
because the envelope is frozen. A custom domain object qualifies only when
its applicable InSARForge boundary contract establishes immutable, deeply owned
semantic state. A caller assertion or class name alone does not establish it.

For a nested dataclass, `frozen=True` is necessary evidence of the dataclass
immutability convention, but is insufficient if nested semantic state remains
mutable. Contract authors must own that state. SemanticValue does not recursively
rewrite arbitrary dataclass fields. No marker Protocol, universal base class,
plugin registration mechanism or inheritance hierarchy is introduced.

### FrozenJSON and tuples

FrozenJSON remains the single canonical mechanism for generic structured
JSON-like semantic data. The conceptual path is explicit:

```text
caller structured data -> freeze_json(...) -> FrozenJSON
    -> SemanticValue[FrozenJSON]
```

The existing mechanism preserves JSON scalar values, requires string object
keys, owns nested mappings and represents arrays as ordered immutable tuples.
Its handling of nested nulls remains unchanged. Top-level `value=None` still
cannot be KNOWN, including for `SemanticValue[FrozenJSON]`; the existing status
rule takes precedence. Nested null does not create an additional semantic state.

#### R1: immutable-view validation and defensive snapshot

FrozenJSON is a structural type alias, not an ownership certificate. A read-only
interface does not establish ownership. In particular:

```python
source = {"a": 1}
view = MappingProxyType(source)
# view["a"] = 2 is forbidden, but:
source["a"] = 2
# view["a"] now observes 2.
```

Canonical `freeze_json` object mappings and these caller-backed views have the
same runtime representation. SemanticValue must not retain an accepted
FrozenJSON mapping/view by alias when mutation of hidden backing state could
change the stored semantic value after construction.

The mandatory order for the generic FrozenJSON structured-data path is:

```text
validate the complete input's ownership-domain structure
    -> reject any prohibited raw mutable node
    -> create an independent canonical snapshot with existing freeze_json
    -> store the snapshot
```

This path accepts the existing FrozenJSON value language in immutable-view
form: immutable JSON scalar values, tuples of recursively valid FrozenJSON
values, and canonical/read-only mapping representations such as MappingProxyType
with string keys and recursively valid FrozenJSON values. It does not accept
arbitrary objects merely because they expose a Mapping interface. The existing
scalar, key, finite-number and nested-null rules remain binding; no second JSON
value language is defined.

Validation must reject a raw `dict`, `list`, `set`, `bytearray`, or equivalent
unsupported mutable node anywhere in the input tree, before any snapshot is
created. For example, a KNOWN payload `{"a": 1}` remains invalid, as does
`MappingProxyType({"x": [1, 2, 3]})`: its nested list is prohibited even though
`freeze_json` could convert it to a tuple. Wrapping a raw mutable node in a
read-only mapping or tuple does not make it valid. Do not freeze first and
validate later. Raw mutable nodes raise `TypeError`; nonfinite floats raise
`ValueError`. Status/value consistency and reason rules are unchanged.

After the entire input passes this pre-validation, SemanticValue is authorized
and required to establish independent ownership of accepted FrozenJSON
structured state using the existing canonical `freeze_json` mechanism.
This is ownership enforcement within the logical FrozenJSON domain. It is not
acceptance or coercion of unsupported raw mutable `T`. The prohibition on
`dict -> mappingproxy` and `list -> tuple` as implicit payload acceptance remains
unchanged; an accepted FrozenJSON immutable representation becoming an
independently owned canonical FrozenJSON representation preserves its logical
payload domain.

SemanticValue is not required to determine whether a MappingProxyType originally
came from `freeze_json`. Such runtime provenance is not reliably distinguishable;
the independent canonical snapshot makes provenance irrelevant. Do not use
object identity, provenance, reference-count or similar heuristics as ownership
proof. Do not trust the read-only facade as inherently deep-owned.

No nominal FrozenJSON, FrozenJSONObject or FrozenArray class, marker Protocol,
or wrapper hierarchy is required or introduced for P4.1B. A nominal
representation remains a future design option only if later requirements need
type/provenance distinction; it is not this clarification's implementation
requirement. Existing `freeze_json` remains the single canonical generic JSON
freezing/snapshot mechanism. A private pre-validation helper followed by that
existing function is permitted; a competing freezer is not.

This clarification applies to generic FrozenJSON structured state. It does not
change FrozenJSON's existing representation, GridDefinition's explicit parameter
freezing, or other typed owners' contracts. SemanticValue must not snapshot or
reconstruct UnitSpec, SignSpec, ArtifactRef, NoDataSpec, GridDefinition or
arbitrary dataclasses under this generic JSON rule unless their own contract
explicitly requires it. Compositional ownership remains: SemanticValue owns the
envelope, and each typed payload contract owns its nested state. No B1/B2,
Product, DataLayer or Geometry redesign is required.

Tuples are validated recursively: `("a", 1)` is ownership-safe;
`("a", mutable_list)` is not. A tuple of supported typed contract values retains
those values' types and relies compositionally on their contracts. Tuple order
is preserved; no set semantics or implicit mutable-member conversion is added.
A tuple containing an accepted FrozenJSON read-only mapping must have that
structured state independently snapshotted after complete input validation.
This applies recursively, preserving tuple order and logical member types;
typed contract members retain their own compositional ownership boundary and
must not be passed through a generic JSON conversion. Any nested list, dict,
set, bytearray or other unsupported mutable node still causes rejection.

### Finite floats

Raw scalar float payloads must be finite, including those reached through
supported tuples. NaN and positive/negative infinity are invalid, consistent
with Phase 4 canonical persistence and semantic hashing. NaN is not a semantic
sentinel. `NoDataKind.NAN` remains the explicit NoData NaN representation under
ADR 0007; NoDataSpec is unchanged.

### Status and reason_code

| Status | Payload | reason_code |
|---|---|---|
| KNOWN | Non-null, satisfies the typed field and this ownership domain. | `None` or non-empty trimmed text, under the existing contract. |
| UNKNOWN | `None` / existing persisted null. | Required non-empty trimmed text. |
| NOT_APPLICABLE | `None` / existing persisted null. | Required non-empty trimmed text. |

The three statuses and their meanings are unchanged. Unknown is not zero;
not-applicable is not unknown. No fourth state or inferred payload is added.
`reason_code` belongs to the envelope and is immutable text under its existing
contract; no mutable structure is permitted inside it. No new identifier
grammar, vocabulary, normalization or reason-code redesign is specified.

### evidence_refs

SemanticValue owns `evidence_refs` as an immutable ordered tuple. Construction
must defensively separate the collection from caller-owned mutable collections
and validate that every element is an existing ArtifactRef. Mutation of the
source collection after construction must not affect the stored tuple. Sharing
ownership-safe ArtifactRef elements is valid.

Preserve supplied order and duplicates. Do not sort, deduplicate, or convert to
a set; no uniqueness rule is introduced. Constructor iterable handling does
not relax the strict codec's JSON-array requirements.

ArtifactRef public fields remain unchanged and references are not dereferenced.
Existing accepted semantic identity rules remain authoritative, including use
of evidence semantic identities and no fallback from an unavailable required
semantic identity to record ID, manifest digest or locator. No digest behavior
or calculation is implemented here.

## Validation / ownership rules

| Responsible boundary | Checks |
|---|---|
| Generic SemanticValue layer | Status/value consistency, existing reason rules, envelope ownership, ArtifactRef evidence elements, and supported generic payload-domain safety, including recursive tuple safety and FrozenJSON ownership. |
| Typed owner contracts | Exact KNOWN payload type, identifiers, and field-specific scientific/semantic constraints. Payload contract authors ensure deep ownership of their own semantic state. |

For example, DataLayer.quantity requires SemanticValue with a KNOWN `str`
identifier; DataLayer.nodata requires a KNOWN NoDataSpec; and
GeometryDescriptor.grid_definition requires a KNOWN GridDefinition. Generic
acceptance of a string or immutable descriptor does not satisfy another field's
type contract.

SemanticValue must not import Product, DataLayer or Geometry types to interpret
their scientific meaning. Foundation helpers in `contracts/values.py` must not
import upper-level Product/domain implementations. ADR 0001 and the module DAG
remain binding. Ownership is established compositionally within the supported
contract boundary, without arbitrary-object rewriting or domain execution.

Constructor failure is deterministic under the existing conventions:

| Invalid input | Failure |
|---|---|
| Unsupported payload-domain/type category, including raw mutable containers or unsupported custom objects | `TypeError` |
| Nonfinite scalar float under the generic rule | `ValueError` |
| Invalid status type or non-ArtifactRef evidence element | `TypeError` |
| Status/value inconsistency or missing/invalid reason under the existing reason validator | `ValueError` |
| Wrong exact KNOWN payload type at a typed owner | `TypeError` |
| Invalid scalar semantic value at its owner | Existing field-specific validation convention, ordinarily `ValueError`. |

The existing reason validator's `ValueError` behavior is preserved, including
non-text reasons. This scoped payload decision does not recategorize all
existing constructor errors. No new exception hierarchy or blanket conversion
to ContractError is introduced.

## Alternatives considered

| Rejected alternative | Reason |
|---|---|
| Deepcopy every payload | Does not make the exposed copy immutable; invokes arbitrary object behavior and leaves type/domain ambiguity. |
| Automatically convert every mutable container | Changes `T`, surprises callers, and creates a second structural-data freezing system. |
| Trust only the frozen outer dataclass | Nested caller-owned semantic state remains mutable. |
| Make every payload FrozenJSON | Destroys typed domain contracts such as UnitSpec, ArtifactRef and GridDefinition. |
| Introduce a universal SemanticPayload base class | Adds unnecessary inheritance coupling; current structural ownership responsibilities need no universal hierarchy. |
| Trust every mappingproxy directly | Read-only access is not ownership; another reference can mutate the backing mapping. |
| Introduce nominal FrozenJSON wrappers now | Unnecessary P4.1B migration cost for GridDefinition, serialization, digests, extensions and existing FrozenJSON users; validation followed by canonical snapshot addresses aliasing. |
| Call freeze_json before validating input | Silently legitimizes prohibited raw mutable nodes, including nested lists inside mappingproxy views. |
| Reject all mapping-based FrozenJSON payloads | Contradicts the intentional support for canonical FrozenJSON structured semantic data. |

## Consequences

Supported values have stable owned semantic state: caller mutation cannot
silently change retained payloads or evidence. Typed contracts remain intact,
FrozenJSON remains the single generic structured-data mechanism, and no new
dependency from foundation contracts to Product/domain implementations is
required. Stable ownership strengthens existing deterministic persistence and
semantic-hashing assumptions without extending their domains.

Costs: callers cannot pass raw mutable generic containers; generic structured
payloads require explicit `freeze_json`; contract authors must ensure their own
nested state is deeply owned. Existing generic tests/usages relying on raw
mutable acceptance require migration.

## Compatibility / migration

Current Phase 4 SemanticValue usage is predominantly ownership-safe typed
payloads: `str`, UnitSpec, SignSpec, NoDataSpec, GridDefinition and ArtifactRef.
Implementation repair is expected to be narrow and must not require B1/B2
public-model redesign. Those contracts, including their field surfaces and
scientific rules, remain unchanged.

The current SemanticValue implementation already copies evidence_refs to a
tuple and validates ArtifactRef elements. Preserve and regression-test that
behavior. Its unchanged-by-reference generic payload handling does not yet
enforce this ADR. Future repair must reject unsupported mutable payloads,
validate supported tuple/FrozenJSON/contract ownership as needed, and prove
caller-mutation isolation. Existing typed owners that explicitly freeze their
own structured inputs retain that responsibility; do not move all validation
into SemanticValue or normalize arbitrary `T`.

## Deferred / non-goals

- Universal hashability is not required. Stable owned semantic state is the
  requirement; normal dataclass hashing applies where contained values support
  it. No new equality model or cache design is introduced.
- No generic arbitrary-object serializer, deepcopy framework, type-changing
  container normalizer, persistence engine, or runtime/plugin abstraction.
- No Product JSON schema, reference schema, storage backend, file writing,
  database persistence, runtime-state persistence or pickle behavior is defined.
  Serialization remains governed by existing strict codecs and later Product
  decisions; payload acceptance does not promise codec support for every `T`.
- No Product 16-field or ProductDraft 9-field final representation, producer or
  produced_by schema, production/lineage reference, acquisition_refs, or
  semantic_metadata representation is decided here. These belong to the later
  Product Envelope ADR.
- No extension namespace grammar, plugin namespace ownership or extension key
  syntax is defined. These belong to the dedicated extension ADR; future use of
  FrozenJSON does not pre-decide those choices.
- No OperationBinding supporting schema, PortContract schema, registry/binding
  contract or registration ownership is changed or decided. These belong to
  the later static-binding ADR.
- No P4.2 runtime execution, cache, retry, state, provenance runtime, runtime
  capability availability, scheduler, task fingerprint, resume, or dry-run
  runtime semantics is implemented or decided. P4.2 does not begin here.
- No real scientific conventions or defaults are selected.

## Implementation follow-up

Recommend a separately authorized future segment:
**B3b-S2a — SemanticValue Deep Ownership Enforcement**.

Source inspection locates SemanticValue in
`src/insarforge/products/semantics.py` and canonical FrozenJSON/value helpers in
`src/insarforge/contracts/values.py`. Expected scope is limited to the actual
SemanticValue/value helper modules and focused contract tests, unless concrete
implementation evidence proves a necessary expansion. No new public import
path, marker API or supporting class is prescribed.

The segment must enforce this domain, retain evidence defensive ownership and
order/duplicates, preserve typed objects and reason/status behavior, and test
raw/nested mutable rejection, FrozenJSON alias isolation, safe/unsafe tuples,
nonfinite floats, unsupported opaque objects, and typed-owner validation.
Existing evidence handling is a regression obligation, not a claim that the
baseline lacks tuple copying. No implementation or test change is authorized
by this documentation task. Extension remediation remains separate.

**R1 retry consequence:** a separately authorized B3b-S2a retry can implement
recursive ownership-domain pre-validation, rejection of every raw mutable node,
then defensive canonical snapshots of accepted FrozenJSON structured state,
alongside existing evidence_refs defensive tuple ownership. This explicitly
resolves the prior validation-only snapshot blocker. The retry must not
auto-freeze raw dict/list input, deepcopy arbitrary objects, introduce nominal
FrozenJSON wrappers, or change B1/B2 public contracts. It must cover both live
mappingproxy backing-alias isolation and rejection of mutable nodes nested in
read-only views or tuples. This R1 task does not retry S2a or alter any
extension, Product, binding or P4.2 decision.

### Remaining REQUIRED finding ledger

| Accounting before ADR 0010 implementation | Count / disposition |
|---|---|
| B3a/B3b.0 final REQUIRED findings | 21 |
| Closed by B3b-S1 | 8: B3-REQ-09–14, 18, 20 |
| Remaining REQUIRED | 13 |
| Of those, ADR-dependent at B3b.0 | 12: B3-REQ-01, 02, 04–08, 15–17, 19, 21 |
| Locally ready but assigned to a later dependency segment | 1: B3-REQ-03, coordinated with Product migration |
| Implementation findings closed by ADR 0010 documentation alone | 0 |

ADR 0010 resolves D-SEMANTIC's architecture choices. B3-REQ-21 remains open
until implementation and validation; any later metadata dependency remains
conditional on the Product decision. The remaining implementation count stays
13. No finding is closed merely because this ADR is accepted.
ADR0010-R1 clarifies architecture only: B3-REQ-21 remains **OPEN** for
implementation, and the blocked S2a attempt and R1 documentation close zero
implementation findings. The remaining REQUIRED implementation count is 13.

Unresolved ADR 0010 decision items: **None**.
Unresolved ADR0010-R1 clarification items: **None**.

## Evidence basis

External B3b.0 evidence is under
`InSARForge_dev_notes/phase4/P4.1B/R2/B3b_0/`: notably
`semanticvalue_freezing_decision.md`, `required_finding_matrix.md`,
`dependency_graph.md`, `implementation_segment_plan.md`,
`B3b_0_decision_freeze.md`, and `adr_decision.md`. Their proposed raw-container
snapshot policy is superseded by this accepted domain decision, not by current
code behavior. Review records for this docs-only task are outside the repository
under `InSARForge_dev_notes/phase4/P4.1B/R2/ADR0010/`.
R1's blocker evidence is under `InSARForge_dev_notes/phase4/P4.1B/R2/B3b_S2a/`,
especially `S2a_summary.md`, `finding_scope.md`,
`semanticvalue_usage_inventory.md`, `ownership_rule_matrix.md`, and
`remaining_finding_ledger.md`. R1 review records are outside the repository
under `InSARForge_dev_notes/phase4/P4.1B/R2/ADR0010_R1/`.
