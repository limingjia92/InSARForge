# ADR-0007 — DataLayer Selector, Dimensions, and NoData Semantics

**Status: Accepted**

**Relationship:** clarification/addendum to `P4.0-FREEZE-1`, specifically
[ADR-0003](0003-product-and-scientific-metadata.md) and
[Phase 4 contracts](../architecture/phase4-contracts.md) §§6.1–6.5, 7.6 and 16.
This is the DataLayer-only P4.1B remediation R2-BC1 decision.

## Context and scope

R2-B0 established that P4.0 freezes the DataLayer public field list while
leaving supporting types, dimensions, NoData cases and digest treatment
underspecified. This accepted addendum resolves those DataLayer questions.
Transitional implementation shapes are not architecture authority.

No mission/backend-specific semantics are introduced. No actual InSAR
quantity/unit/sign convention is selected. GeometryDescriptor internal schema
remains deferred to R2-BC2, including the exact invariant between
`DataLayer.dimensions` and `GeometryDescriptor.axes`.

## Final DataLayer contract

The exact public field surface and types are:

```python
DataLayer(
    layer_id: str,
    role: str,
    asset_id: str,
    selector: LayerSelector | None,
    quantity: SemanticValue[str],
    unit: SemanticValue[UnitSpec],
    sign: SemanticValue[SignSpec],
    geometry_ref: SemanticValue[str],
    nodata: SemanticValue[NoDataSpec],
    dimensions: tuple[str, ...],
)
```

These are all ten fields; no other public fields are added. There is no generic
`DataLayer.extensions` field. Transitional `quantity_kind` is replaced by
`quantity`; the transitional selector shape is replaced below. Nullable fields
remain explicit slots; these signatures introduce no implicit defaults.

P4.0 immutable value-object and construction/decode validation rules remain
applicable. `SemanticValue` retains its existing known/unknown/not-applicable
contract: KNOWN requires a matching typed payload; UNKNOWN requires a reason;
NOT_APPLICABLE requires a reason and no payload. Unknown is not zero, and
not-applicable is not unknown. Consumer profiles must reject insufficient
required semantics even when an archived Product may carry unknown values.

### Identifiers, quantity, unit and sign

“Identifier” uses the existing machine-readable identifier grammar, shared by
`contracts.values.validate_identifier`: a non-empty string without whitespace
or Unicode category C characters. This reuses the existing grammar and does
not introduce a closed vocabulary or identifier normalization.

| Field | Contract |
|---|---|
| `layer_id` | Machine-readable identifier for the logical layer. |
| `role` | Machine-readable open/extensible identifier; no Core-owned closed enum or mission/backend-specific role values are defined here. |
| `asset_id` | Machine-readable identifier referencing `NativeAsset.asset_id` in the same Product. |
| `quantity` | `SemanticValue[str]`; a KNOWN payload is a machine-readable quantity identifier using the existing grammar, with an open/extensible vocabulary. |
| `unit` | `SemanticValue[UnitSpec]`; the existing UnitSpec contract remains authoritative. UNKNOWN and NOT_APPLICABLE are valid. |
| `sign` | `SemanticValue[SignSpec]`; the existing SignSpec contract remains authoritative. UNKNOWN and NOT_APPLICABLE are valid. |

`PhysicalQuantity` represents a valued physical quantity and is a different
concept; it is not the DataLayer quantity type. Quantity examples in
documentation/tests must remain synthetic (for example, `synthetic_quantity`).
No actual InSAR unit or sign conventions are chosen.

### Geometry reference

`geometry_ref: SemanticValue[str]` has these distinct meanings:

- KNOWN: an identifier referencing `GeometryDescriptor.geometry_id` in the same Product.
- UNKNOWN: geometry is not currently known.
- NOT_APPLICABLE: this logical layer does not require geometry.

DataLayer construction does not itself need access to the Product collection.
Cross-reference validation, including existence and same-Product linkage,
occurs at the Product/validation layer. This does not define GeometryDescriptor
internals.

## LayerSelector

The exact immutable value-object surface is:

```python
LayerSelector(
    format_id: str,
    selector_string: str,
)
```

`format_id` is a machine-readable identifier naming the selector **syntax/format**.
It uses the existing identifier grammar, is open/extensible, and has no
Core-owned closed enum.

`selector_string` is a non-empty `str` with no leading or trailing whitespace.
It is opaque to generic Core. Core does not execute or interpret it.

`DataLayer.selector` is `LayerSelector | None`. `None` means the logical layer
refers to the whole NativeAsset. A present selector identifies a logical
sub-object using the explicitly named selector format.

Transitional `selector_kind` and `parameters` fields are not retained.
LayerSelector has no generic extensions field. No HDF5, GDAL or backend
selector syntax is defined in Core by this ADR.

## Dimensions

`dimensions: tuple[str, ...]` holds ordered logical dimension identifiers for
this DataLayer. Each uses the existing machine-readable identifier grammar.
Order is semantically significant; duplicate dimension IDs are invalid.
The supplied collection is defensively copied to a tuple. The empty tuple is
valid for scalar/opaque logical layers.

Dimension sizes are not stored here; sizes and geometric axis relationships
belong to geometry/shape contracts. The exact invariant between
`DataLayer.dimensions` and `GeometryDescriptor.axes` is intentionally deferred
to R2-BC2. BC1 establishes no equality, rank, positional alignment, shape or
selector-slicing relationship between them.

## NoDataKind and NoDataSpec

The v1 enum is exactly:

```python
NoDataKind.NONE = "none"
NoDataKind.FINITE_VALUE = "finite_value"
NoDataKind.NAN = "nan"
NoDataKind.MASK = "mask"
```

No other v1 values exist. These describe a KNOWN NoDataSpec. UNKNOWN and
NOT_APPLICABLE belong to the enclosing SemanticValue, not extra enum values.

The exact immutable value-object surface is:

```python
NoDataSpec(
    kind: NoDataKind,
    value: int | float | None,
    mask_layer_ref: str | None,
)
```

NoDataSpec has no extensions field. Construction and decoding validate these
combinations:

| Kind | `value` | `mask_layer_ref` | Meaning |
|---|---|---|---|
| `NONE` | `None` | `None` | It is explicitly known that this layer has no NoData representation. |
| `FINITE_VALUE` | Finite `int` or `float`; `bool` is invalid | `None` | A known finite sentinel. Preserve int versus float; do not normalize. |
| `NAN` | `None` | `None` | NaN is explicitly the NoData representation. Do not serialize an actual NaN float as the specification value. |
| `MASK` | `None` | Machine-readable `DataLayer.layer_id` reference | A known mask-layer reference, resolved structurally at Product/validation level. |

`DataLayer.nodata: SemanticValue[NoDataSpec]` preserves six distinct cases:

| State | Meaning |
|---|---|
| KNOWN + `NONE` | Known no-NoData representation. |
| KNOWN + `FINITE_VALUE` | Known finite sentinel. |
| KNOWN + `NAN` | Known NaN representation. |
| KNOWN + `MASK` | Known mask-layer reference. |
| UNKNOWN | NoData semantics are not known. |
| NOT_APPLICABLE | NoData semantics do not apply. |

These states must not be collapsed. KNOWN + NONE is neither UNKNOWN nor
NOT_APPLICABLE.

### Mask cross-reference boundary

For KNOWN + MASK, `mask_layer_ref` must reference another `DataLayer.layer_id`
in the same Product. Product/validation structural checks require that the
referenced layer exists and that a layer does not reference itself as its mask.
NoDataSpec construction itself does not need Product access; identifier validity
is local, while reference resolution is a collection check.

BC1 does not define recursive mask-cycle detection. A future need for that
rule requires a separate clarification. Mask scientific meaning, polarity and
alignment are not selected here.

## Extensions and semantic identity

DataLayer, LayerSelector and NoDataSpec have no generic extensions fields.
No replacement extension containers are introduced. This does not revoke
P4.0 §6.4: extension slots explicitly allocated elsewhere are semantic by
default and retain their existing rules.

The following DataLayer fields are **PRODUCT CONTENT SEMANTICS**:

`role, selector, quantity, unit, sign, geometry_ref, nodata, dimensions`.

LayerSelector format and string are semantic. NoDataSpec contents are semantic.
Dimension ordering is semantic and must not be sorted away in projection.
There is no persistence-only exception for any of these fields.

Structural local identifiers `layer_id` and `asset_id` remain part of the
explicit Product graph and current semantic projection unless a later
architecture revision defines identifier normalization. They are not excluded
by P4.0's exclusion of Product/record instance IDs. Existing explicit scientific
asset-content identity requirements remain applicable; local references do
not substitute for asset content identity. Full persisted records remain
protected by their manifest byte digests.

## Serialization consequences — follow-up only

The persisted field sets are exactly:

| Object | Persisted fields |
|---|---|
| DataLayer | `layer_id, role, asset_id, selector, quantity, unit, sign, geometry_ref, nodata, dimensions` |
| LayerSelector | `format_id, selector_string` |
| NoDataSpec | `kind, value, mask_layer_ref` |

The strict current codec must reject old transitional fields `quantity_kind`,
`selector_kind`, `selector.parameters`, and `DataLayer.extensions`; these are
not aliases for the final contract. Absent extension slots on LayerSelector
and NoDataSpec likewise cannot accept extra extension keys.

The follow-up codec must preserve nullable selectors, SemanticValue states,
dimension order and the NoData combinations above, including int/float
distinctions and the explicit nan discriminator. P4.0 strict JSON rules continue
to reject bare nonfinite numbers and duplicate keys. No codec changes are
implemented in BC1. This ADR does not select a schema-version or digest-algorithm
revision number or introduce a legacy upgrader.

## Downstream consequences

- **R2-B1:** implement NoDataKind/NoDataSpec; migrate LayerSelector and DataLayer to the exact contracts above.
- **R2-B3:** migrate strict serialization, Product structural validation, mask-layer cross-reference validation, profiles and digest projections to the clarified types, fields, optional selector and semantic states.
- **R2-BC2:** resolve GeometryDescriptor internal schema and the geometry relationship to dimensions. BC1 does not decide those relationships or authorize their implementation.

This decision is documentation only. No production code, tests or codecs are
changed, and acceptance does not claim downstream implementation conformance.

## Scientific non-decisions

Only representation mechanisms are frozen. This ADR does not freeze:

- Phase/displacement/coherence quantity identifiers.
- Metric/radian or other actual unit choices.
- LOS sign, phase sign or wavelength.
- Radar/geocoded domains.
- Range/azimuth or latitude/longitude dimension names.
- Actual NoData sentinel values or mask scientific meaning.

## Evidence basis

R2-B0 extraction reports under the external notes directory
`InSARForge_dev_notes/phase4/P4.1B/R2/B0/`, at baseline
`120c188b6759005c45dad1f5b7711a1c930fd718`, identify the gaps:
`p40_datalayer_contract.md`, `contract_delta_matrix.md`, `digest_impact.md` and
`downstream_impact.md` (with `serialization_impact.md` for codec consequences).
They are extraction evidence; this accepted decision clarifies P4.0 architecture
without promoting transitional code into a contract.
