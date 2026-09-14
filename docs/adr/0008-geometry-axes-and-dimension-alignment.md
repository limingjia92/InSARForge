# ADR-0008 — Geometry Axes and DataLayer Dimension Alignment

**Status: Accepted**

**Relationship:** clarification/addendum to `P4.0-FREEZE-1` and
[ADR-0007](0007-datalayer-selector-dimensions-nodata.md), grounded in
[ADR-0003](0003-product-and-scientific-metadata.md) and
[Phase 4 contracts](../architecture/phase4-contracts.md) §§6.1–6.5 and 16.
This is the documentation-only P4.1B remediation R2-BC2a decision.

## Context and scope

P4.0 freezes GeometryDescriptor's eight field names and generic scientific
representation mechanisms. R2-B0 identifies gaps in the supporting axis schema,
geometry field types, shape invariants and dimension alignment. ADR 0007 freezes
DataLayer dimensions as ordered logical identifiers but defers their geometry
relationship. This addendum resolves those gaps within BC2a's scope;
transitional implementation fields are not architecture authority.

No actual radar/geocoded domain value is selected. No real range/azimuth or
latitude/longitude axis is required. No registration convention or CRS is
selected. `grid_definition` and `reference` remain deferred to ADR 0009 /
R2-BC2b. Their exact public types/schemas and semantic/digest treatment beyond
being P4.0 geometry fields are the **only intended remaining Geometry
architecture items after BC2a**.

## Final AxisDescriptor contract

The exact public field surface is:

```python
AxisDescriptor(
    axis_id: str,
    role: str,
    unit: SemanticValue[UnitSpec],
    direction: SemanticValue[str],
)
```

There is no `size` or generic `extensions` field. Axis length belongs
exclusively to `GeometryDescriptor.shape`, avoiding duplicated size state.
These are explicit slots; the signature introduces no implicit defaults.
P4.0 immutable value-object and construction/decode validation rules apply.

“Identifier” reuses ADR 0007's existing machine-readable identifier grammar,
shared by `contracts.values.validate_identifier`: a non-empty string without
whitespace or Unicode category C characters. No new normalization is defined.

| Field | Final meaning and constraints |
|---|---|
| `axis_id` | Machine-readable identifier, unique within one GeometryDescriptor. Identifies the local logical dimension represented by this axis and is the identifier used to align DataLayer dimensions with geometry axes. |
| `role` | Machine-readable identifier using the existing grammar; open/extensible semantic role/category of the axis, with no closed Core enum. |
| `unit` | `SemanticValue[UnitSpec]`. KNOWN carries UnitSpec; UNKNOWN means the unit is not known; NOT_APPLICABLE means the axis has no meaningful physical unit. |
| `direction` | `SemanticValue[str]`. A KNOWN payload is a machine-readable identifier using the existing grammar, open/extensible. UNKNOWN and NOT_APPLICABLE are allowed. |

`axis_id` and `role` are intentionally distinct: local logical dimension
identity versus semantic role/category. Multiple GeometryDescriptors may use
different axis IDs for the same conceptual role. There is no Core-owned
axis-name enum; names such as range, azimuth, latitude, longitude, x, y or time
are not frozen. Production contracts remain open/extensible. No real scientific
role or direction values are prescribed; direction representation exists while
the actual scientific convention is deferred.

Units must not be inferred from role or domain. No unit conversion occurs in
this contract. Existing SemanticValue rules remain applicable: KNOWN requires
a matching typed payload; UNKNOWN requires a reason; NOT_APPLICABLE requires
a reason and no payload. Unknown and not-applicable remain distinct.

## GeometryDescriptor core contract

The complete field list remains exactly P4.0's eight fields. The following is
contract notation, **not an implementable partial type**:

```text
GeometryDescriptor(
    geometry_id: str,
    domain: str,
    coordinate_reference: SemanticValue[str],
    axes: tuple[AxisDescriptor, ...],
    shape: tuple[int, ...],
    grid_definition: <BC2b type>,
    registration: SemanticValue[str],
    reference: <BC2b type>,
)
```

BC2a freezes the first five core concepts plus registration. BC2b will freeze
the exact types/schemas of `grid_definition` and `reference`; the placeholders
do not select nullability, defaults, containers or reference semantics. There
is no generic `GeometryDescriptor.extensions` field. Do not implement this
partial type in BC2a.

| Field | Final BC2a contract |
|---|---|
| `geometry_id` | `str` using the existing identifier grammar; unique within one Product and referenced by `DataLayer.geometry_ref`. No automatic generation. |
| `domain` | `str` using the existing identifier grammar; open/extensible, no closed Core enum. Replaces transitional `domain_id`. No actual radar, geocoded, geographic or projected identifiers are frozen; concrete profiles/plugins may supply values later. |
| `coordinate_reference` | `SemanticValue[str]`; KNOWN carries a non-empty string with no leading/trailing whitespace, **not** constrained to identifier grammar. UNKNOWN means the reference system is not known; NOT_APPLICABLE means coordinate reference does not apply. |
| `axes` | `tuple[AxisDescriptor, ...]`, defensively copied to a tuple, preserving supplied order. |
| `shape` | `tuple[int, ...]`, defensively copied to a tuple, preserving supplied order. Every element is an `int`, excluding `bool`, and strictly greater than zero. |
| `registration` | `SemanticValue[str]`; KNOWN carries an open/extensible machine-readable identifier using the existing grammar. UNKNOWN and NOT_APPLICABLE are allowed. This is a representation slot only; no concrete registration value is frozen in Core. |

The coordinate-reference text may eventually contain authority strings,
WKT-like definitions or other versioned textual reference definitions. Core
does not parse or normalize the known string in Phase 4. EPSG is not required;
neither a geographic nor a projected CRS is required.

### Axes, shape and order invariants

- `len(axes) == len(shape)`.
- Axis IDs are unique within the GeometryDescriptor.
- `shape[i]` is the size of `axes[i]`; AxisDescriptor must not duplicate it.
- Empty axes/shape are **invalid for GeometryDescriptor v1**. A layer without
  geometry uses `geometry_ref = NOT_APPLICABLE`, rather than a zero-dimensional
  GeometryDescriptor.
- Axis order is semantically significant. Changing axis order and the
  corresponding shape order changes the interpreted geometry. Core must not
  automatically sort axes; there is no canonical alphabetical axis sorting.

## DataLayer dimensions and geometry alignment

ADR 0007's `DataLayer.dimensions: tuple[str, ...]` remains authoritative:
ordered, unique logical dimension identifiers, defensively copied to a tuple;
an empty tuple is allowed for scalar/opaque logical layers. BC2a now resolves
ADR 0007's deferred geometry alignment rule.

If `DataLayer.geometry_ref.status == KNOWN`, the referenced
GeometryDescriptor **must exist in the same Product**, and:

```python
layer.dimensions == tuple(axis.axis_id for axis in geometry.axes)
```

Equality requires the same number of dimensions, the same identifiers and the
same order. Therefore:

```text
len(DataLayer.dimensions)
    == len(GeometryDescriptor.axes)
    == len(GeometryDescriptor.shape)
```

There is no implicit axis mapping, permutation, subset matching or name
guessing. With KNOWN geometry, empty dimensions cannot match a valid v1
GeometryDescriptor.

| Geometry reference status | Dimensions behavior |
|---|---|
| KNOWN | Resolve the geometry and enforce exact ordered equality with axis IDs. |
| UNKNOWN | Dimensions remain meaningful as the known logical array dimensions, but no GeometryDescriptor alignment can be validated. ADR 0007's local dimension constraints still apply. |
| NOT_APPLICABLE | Dimensions remain allowed, including non-empty dimensions. A non-geometric/scalar/opaque logical layer needs no fake GeometryDescriptor. Do not require empty dimensions solely because geometry is not applicable. |

The GeometryDescriptor describes the geometry of the DataLayer **logical
array**, not merely an unrelated spatial subset. Exact alignment prevents
ambiguity such as DataLayer dimensions `(a, b, c)` and geometry axes `(x, y)`
with no frozen mapping (synthetic identifiers only). Future products requiring
separate non-geometric dimensions plus spatial geometry axes require an
explicit future versioned mapping contract rather than implicit guessing.

### Single source of truth

| Owner | Stores |
|---|---|
| `DataLayer.dimensions` | Logical dimension **identifiers only**. |
| `GeometryDescriptor.axes` | Axis **semantics**. |
| `GeometryDescriptor.shape` | Dimension **sizes**. |

Sizes must not be duplicated in DataLayer or AxisDescriptor. This contract
does not derive dimensions or sizes from selector strings or backend layout.

## Extensions and semantic identity

AxisDescriptor and GeometryDescriptor have no generic extensions fields, and
no replacement extension containers are introduced. This does not revoke the
general P4.0 rule that explicitly defined extension slots elsewhere are
semantic by default.

The following fields are **PRODUCT CONTENT SEMANTICS**:

| Object | Fields |
|---|---|
| AxisDescriptor | `axis_id, role, unit, direction` |
| GeometryDescriptor core | `domain, coordinate_reference, axes, shape, registration` |

`geometry_id` remains a structural local graph identifier and participates in
the Product graph/current semantic projection. It is not excluded as a
Product/record instance ID. Axis order and shape order are semantic and must
not be sorted away. `grid_definition` and `reference` semantic/digest
classification beyond their P4.0 field presence remains BC2b; no exclusion or
inclusion rule for their contents is selected here.

## Downstream validation and serialization consequences

Future structural validation must check geometry axes/shape count equality,
unique axis IDs, positive integer dimensions excluding bool, non-empty
geometry, KNOWN geometry-reference resolution and exact DataLayer dimension
identifier/order alignment. Local construction/decode checks enforce field
invariants; same-Product resolution and alignment belong at Product/validation
level, without requiring DataLayer construction to access the Product.
**No validation is implemented in BC2a.**

Future persisted field sets are exactly:

| Object | Persisted fields |
|---|---|
| AxisDescriptor | `axis_id, role, unit, direction` |
| GeometryDescriptor | `geometry_id, domain, coordinate_reference, axes, shape, grid_definition, registration, reference` |

Old transitional persisted fields to remove later are `domain_id`,
`AxisDescriptor.size`, `AxisDescriptor.extensions` and
`GeometryDescriptor.extensions`. They are not final-contract aliases.
Serialization must preserve SemanticValue states and axis/shape order under
the existing strict JSON rules. Exact codecs for the two deferred slots await
BC2b. No codecs, schema revision numbers, migration implementation or digest
algorithms are changed here.

## Scientific non-decisions and deferral boundary

Only generic representation and invariants are frozen. This ADR does not
freeze actual radar/geocoded domain identifiers; range/azimuth or lat/lon axes;
axis direction conventions; CRS; grid registration values; grid spacing or
origin; LOS sign; phase sign; or wavelength/frequency. No real scientific
values or backend transforms are selected.

ADR 0009 / R2-BC2b alone will resolve `grid_definition` exact public type/schema,
`reference` exact public type/schema, and their semantic/digest treatment
beyond being P4.0 geometry fields. Neither field is conflated with
`coordinate_reference` or `DataLayer.geometry_ref`. No other BC2a architecture
item remains unresolved. This acceptance does not claim production
conformance or begin BC2b/B1; production code and tests remain unchanged.

## Evidence basis

The authoritative P4.0 and ADR 0007 documents are linked above. External
R2-B0 extraction reports under
`InSARForge_dev_notes/phase4/P4.1B/R2/B0/`, notably
`p40_geometry_contract.md`, `p40_datalayer_contract.md` and
`contract_delta_matrix.md`, identify the original underspecification at
baseline `120c188b6759005c45dad1f5b7711a1c930fd718`. They are extraction evidence,
not authority to promote transitional code into architecture. BC2a review
evidence is recorded outside the repository under
`InSARForge_dev_notes/phase4/P4.1B/R2/BC2a/`.
