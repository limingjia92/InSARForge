# ADR-0009 — Grid Definition and Geometry Reference Semantics

**Status: Accepted**

**Relationship:** clarification/addendum to `P4.0-FREEZE-1` and
[ADR-0008](0008-geometry-axes-and-dimension-alignment.md), grounded in
[ADR-0003](0003-product-and-scientific-metadata.md),
[ADR-0007](0007-datalayer-selector-dimensions-nodata.md) and
[Phase 4 contracts](../architecture/phase4-contracts.md) §§6.1–6.5, 7.6 and 16.
This is the documentation-only P4.1B remediation R2-BC2b decision and the final
architecture clarification for R2-B DataLayer/Geometry remediation.

## Context and decision boundary

P4.0 freezes GeometryDescriptor's eight field names. ADR 0008 resolves its
axes, shape, core fields and exact DataLayer dimension alignment, leaving only
`grid_definition` and `reference` types/schemas and their semantic/digest
treatment for this addendum. R2-B0 extraction reports identify those gaps;
transitional implementation shapes are not architecture authority.

This decision **completes the GeometryDescriptor public contract**. It does
not change any ADR 0008 decision, select a real radar/geocoded grid convention
or reference acquisition, or define mission/backend-specific geometry behavior.
All actual scientific values remain supplied by concrete profiles/plugins.

## Final GeometryDescriptor contract

The complete public surface is exactly:

```python
GeometryDescriptor(
    geometry_id: str,
    domain: str,
    coordinate_reference: SemanticValue[str],
    axes: tuple[AxisDescriptor, ...],
    shape: tuple[int, ...],
    grid_definition: SemanticValue[GridDefinition],
    registration: SemanticValue[str],
    reference: SemanticValue[ArtifactRef],
)
```

There is no generic `GeometryDescriptor.extensions` field. These are explicit
slots, with no implicit defaults or fourth semantic state introduced here.
All ADR 0008 invariants remain unchanged: identifier grammar and uniqueness,
non-empty axes/shape, defensive tuple copying, positive integer sizes excluding
bool, positional axis/shape correspondence, semantic axis/shape order, and
exact ordered DataLayer dimension alignment for KNOWN `geometry_ref`.
AxisDescriptor remains exactly `axis_id, role, unit, direction`; sizes belong
exclusively to GeometryDescriptor.shape.

## GridDefinition

Freeze the immutable value object exactly as:

```python
GridDefinition(
    format_id: str,
    parameters: FrozenJSON,
)
```

There is no extensions field and no closed `GridDefinitionKind` enum.
Construction and decoding must enforce the following generic contract.

### Format identity

`format_id` is an open/extensible machine-readable identifier using the
existing grammar shared by `contracts.values.validate_identifier`: a non-empty
string without whitespace or Unicode category C characters. It identifies the
**versioned schema/syntax used by parameters**. Core owns no closed list and
does not introduce identifier normalization.

A concrete format_id contract is responsible for defining its parameter
schema and meaning. Future concrete contracts could describe affine grids,
radar/native grids, lookup-driven geometry or other mission/backend grid
descriptions. No real format ID is defined here. A name such as
`synthetic_grid_v1` is only a synthetic example, with no scientific schema or
parameter names frozen by this ADR.

### Parameter structure and interpretation

`parameters: FrozenJSON` has the additional invariant that its top-level
logical value **must be a JSON object / Mapping**. Scalars, strings, arrays
and null are invalid at the top level. Named structured parameters allow the
format contract to evolve without positional ambiguity.

Construction must pass parameters through `freeze_json(...)`, require a
Mapping at the top level, require string keys, and deeply freeze nested
content. The existing FrozenJSON rules apply recursively, including immutable
nested mappings/arrays and supported JSON values. Nested arrays remain
permitted and ordered; the top-level restriction does not prohibit nested
JSON values. No scientific interpretation occurs during this process.

Core does not infer spacing or origin, parse transforms, perform reprojection,
calculate coordinates, or interpret backend-specific parameter names.

`GridDefinition.parameters` is **not a generic extension escape hatch**. It is
the primary semantic payload of the explicitly named/versioned format_id.
The complete parameter mapping is semantic, and its schema must be defined
by the concrete format contract. A format_id unknown to Core remains
generically representable: Core may preserve, hash and serialize its payload
without understanding it. A producer must not hide unrelated diagnostics or
provenance in parameters; diagnostic data belongs in provenance. This does
not add replacement extension containers or change the semantic-by-default
rule for explicitly allocated extension slots elsewhere.

### Grid-definition states and independent geometry slots

`GeometryDescriptor.grid_definition: SemanticValue[GridDefinition]` has exactly
the existing SemanticValue states:

| State | Meaning |
|---|---|
| KNOWN | An exact GridDefinition payload is available. The format need not be understood by generic Core. |
| UNKNOWN | A grid definition conceptually applies but is not known. |
| NOT_APPLICABLE | This GeometryDescriptor does not require a separate grid-definition payload. |

Do not use `None` as a fourth state. Standard SemanticValue rules apply:
KNOWN requires a matching typed payload; UNKNOWN requires a reason;
NOT_APPLICABLE requires a reason and no payload. Unknown and not-applicable
remain distinct. Do not infer grid definition from axes, shape, domain,
coordinate_reference or registration; these remain independent explicit slots.

`registration: SemanticValue[str]` stays separate: it expresses grid/pixel
registration semantics, while GridDefinition expresses format-specific
structured grid parameters. A format may contain parameters whose
interpretation depends on registration, but Core must not duplicate or infer
the registration value. Do not move registration into GridDefinition.

`coordinate_reference: SemanticValue[str]` also stays separate: coordinate
reference semantics and grid parameterization are distinct. The generic
representation permits all of these combinations:

| coordinate_reference | grid_definition |
|---|---|
| KNOWN | KNOWN |
| UNKNOWN | KNOWN |
| NOT_APPLICABLE | KNOWN, including a future native/radar grid description |

GridDefinition does not imply CRS. These combinations select no actual domain,
CRS, format or scientific parameter values.

## Geometry reference

`GeometryDescriptor.reference: SemanticValue[ArtifactRef]` is a generic
semantic reference to **another persisted domain record required to interpret
the geometry**. A KNOWN payload is ArtifactRef. The actual record type is
expressed by `ArtifactRef.schema_id` and `ArtifactRef.schema_version`; Core
does not restrict it to one schema.

`reference` is not synonymous with a coordinate reference system, grid origin,
pixel registration, Product provenance or arbitrary evidence. Those have
separate contract surfaces. It is an explicit external/upstream semantic
reference needed to interpret geometry. It is also distinct from the local
`DataLayer.geometry_ref` link to a geometry in the same Product.

A future concrete geometry/profile may use this slot for a concept such as
reference acquisition. This ADR freezes no such concrete use, reference
acquisition value or schema, and no master/reference image policy.

### Reference states

| State | Meaning |
|---|---|
| KNOWN | ArtifactRef is explicitly known; record type remains open via schema_id/schema_version. |
| UNKNOWN | A reference concept applies but the concrete reference is not known. |
| NOT_APPLICABLE | This GeometryDescriptor requires no such external semantic reference. |

The existing SemanticValue reason/payload rules apply. `None` is not another
state. UNKNOWN and NOT_APPLICABLE are represented explicitly and participate
in content semantics as those states.

### No automatic dereference

GeometryDescriptor construction validates ArtifactRef structure only. It does
not load the referenced record, open its locator or access the filesystem or
network. Generic Product structural validation may verify reference
shape/status, but must not automatically fetch the target. Runtime, backend
or profile logic may explicitly resolve it later when required. A KNOWN
reference is not a claim that its target has been fetched or verified.

## Product content identity and digest boundaries

### Grid-definition projection

The following are **PRODUCT CONTENT SEMANTICS**:

- `GridDefinition.format_id`.
- The complete `GridDefinition.parameters` mapping.
- The grid_definition SemanticValue status, reason_code and evidence semantic
  identities.

Changing format_id, any parameter value, semantic status/reason or semantic
evidence identity changes Product content semantics. Mapping insertion order
does not change semantic identity because canonical JSON object ordering
applies, including nested mappings. Arrays inside parameters remain ordered
and semantic. Existing strict canonical JSON rules apply; no scientific
normalization or equivalence inference is introduced.

### Reference projection and unavailable identity

The following are **PRODUCT CONTENT SEMANTICS**:

- The reference SemanticValue status and reason_code.
- Its evidence semantic identities.
- For KNOWN, the referenced `ArtifactRef.semantic_digest`.

For a reusable Product content digest, a KNOWN reference **must have an
available semantic_digest**. After R2-B3 migration, if that ArtifactRef has
`semantic_digest is None`, both `product_semantic_material(...)` and
`product_content_digest(...)` must return `None`. This is unavailable content
identity, not a substitute digest of a null/unknown marker. Such a structurally
valid reference remains persistable; lack of reusable identity does not
authorize a constructor to fetch its target.

Do not fall back to `record_id`, `manifest_digest` or `locator` for scientific
or content equivalence. Reference selection is semantic through referenced
content identity without making locator or record ID scientific identity.
Schema fields still express the persisted reference's record type; they do
not replace its missing semantic digest.

UNKNOWN and NOT_APPLICABLE reference states contribute their explicit
SemanticValue states; neither asserts a KNOWN target with unavailable
identity. This distinction does not bypass other required identity checks or
consumer profile requirements. SemanticValue evidence references use semantic
identities under the existing evidence projection rules; missing required
evidence semantic identities likewise cannot be replaced by persistence
identities to produce reusable material.

### Complete geometry projection

After BC2b, GeometryDescriptor Product-content semantics consist of all eight
fields:

```text
geometry_id, domain, coordinate_reference, axes, shape,
grid_definition, registration, reference
```

ArtifactRef/reference identity follows the boundary above. Per ADR 0008,
geometry_id remains a structural local graph identifier participating in the
Product graph/current semantic projection; it is not an excluded Product or
record instance ID. Axis order and shape order remain semantic. There is no
Geometry extensions mapping. Full persisted fields, including ArtifactRef
persistence identities, remain protected by manifest byte digests, distinct
from Product content identity.

## Strict serialization consequences — future implementation only

Future persisted field sets are exactly:

| Object | Persisted fields |
|---|---|
| GridDefinition | `format_id, parameters` |
| AxisDescriptor (unchanged ADR 0008) | `axis_id, role, unit, direction` |
| GeometryDescriptor | `geometry_id, domain, coordinate_reference, axes, shape, grid_definition, registration, reference` |

`grid_definition` persists as the standard explicit SemanticValue envelope
(`status, value, reason_code, evidence_refs`), containing GridDefinition when
KNOWN. `reference` persists as the same standard envelope, containing
ArtifactRef when KNOWN. ArtifactRef retains its existing persisted fields:
`record_id, schema_id, schema_version, semantic_digest, manifest_digest, locator`.
Its nullable semantic_digest remains representable; digest unavailability is
handled by the semantic identity boundary, not by inventing another state.

The future strict codec must reject unknown or missing fields in these exact
object/envelope contracts, preserve the distinct SemanticValue states and
ordered arrays, and enforce the parameters object requirement. This exact
field checking does not give Core a closed list of keys inside parameters:
that mapping follows the named format's schema, with format-specific
validation only when explicitly supplied. Existing strict JSON rules, including
duplicate-key and nonfinite-number rejection, remain applicable.

The eventual R2 migration must remove transitional `domain_id`,
`AxisDescriptor.size`, `AxisDescriptor.extensions` and
`GeometryDescriptor.extensions`, and add/finalize `domain`, `grid_definition`
and `reference`. No compatibility aliases remain after migration. No codecs,
production types, tests or schema/digest revision constants are modified in
BC2b.

## Validation and profile consequences

Future generic validation responsibilities are:

| Surface | Required generic validation and boundary |
|---|---|
| GridDefinition | KNOWN grid_definition payload must be GridDefinition; format_id uses existing identifier grammar; parameters must pass freeze_json and be a top-level Mapping with string keys and deeply immutable JSON content. Core does not validate the format-specific parameter schema unless a profile/format-specific validator is explicitly supplied. |
| Reference | KNOWN payload must be ArtifactRef; validate structure and SemanticValue status/payload rules without dereferencing; no generic requirement for a particular schema_id. |
| ADR 0008 invariants | Retain axes/shape invariants and exact ordered DataLayer dimension alignment for KNOWN geometry_ref, including same-Product resolution. |

Generic Product profiles may later constrain explicit known values such as
geometry domain, grid_definition format_id or registration, only when supplied
declaratively by the caller/profile. No concrete radar/geocoded requirements
are added. Generic Core profiles must not require a reference schema. Exact
profile migration belongs to R2-B3. No validation or profile implementation
occurs in this ADR.

## Implementation sequence and architecture completion

| Segment | Final implementation scope |
|---|---|
| R2-B1 | NoDataKind, NoDataSpec, LayerSelector, final DataLayer. |
| R2-B2 | Final AxisDescriptor, GridDefinition, final GeometryDescriptor. |
| R2-B3a | Strict Product serialization migration. |
| R2-B3b | Product/digest/profile/validation migration. |
| R2-B4 | Final architecture/regression gate. |

There is no remaining architecture ambiguity required before B1/B2
implementation. Unresolved BC2b architecture items: **None**. Concrete
scientific contracts remain future profile/plugin work, not unresolved generic
representation choices. This documentation decision does not begin B1/B2/B3
implementation or claim production conformance.

## Scientific non-decisions

Only representation mechanisms and identity boundaries are frozen. This ADR
does not freeze affine-grid or radar-grid parameter names; range or azimuth
spacing; origin; transform; EPSG; WKT syntax; pixel/node registration values;
reference acquisition; master/reference image policy; stack network;
wavelength; phase sign; or LOS sign. No real format ID, grid convention or
reference schema is selected. Concrete profiles/plugins supply actual
scientific values.

## Evidence basis

The linked accepted ADRs and Phase 4 contracts are authoritative. External
R2-B0 extraction reports under
`InSARForge_dev_notes/phase4/P4.1B/R2/B0/`, especially
`p40_geometry_contract.md`, `digest_impact.md` and `contract_delta_matrix.md`,
record the original gaps at baseline
`120c188b6759005c45dad1f5b7711a1c930fd718`. BC2b resolves these final geometry
gaps without promoting transitional code into architecture. Review evidence
is recorded outside the repository under
`InSARForge_dev_notes/phase4/P4.1B/R2/BC2b/`.
