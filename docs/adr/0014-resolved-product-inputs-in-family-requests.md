# ADR-0014: Resolved Product Inputs in Family Requests

**Status: Accepted**

## Context and authority

[Phase 4 contracts §13.1](../architecture/phase4-contracts.md#131-允许实现)
requires actual resolved typed inputs together with their ArtifactRefs. The
reference-only Product slots left PRO-P41-05 REQUIRED: operation-side
`ResolvedInput` could hold a Product, but family requests could not receive it.
The user approved this narrow coordination on 2026-09-18.

[ADR-0013](0013-static-operation-bindings-typed-ports-and-registration-ownership.md)
remains valid overall. This ADR amends only its preservation of the existing
family-request data representation, to satisfy §13.1. It does not rewrite
ADR-0013's history or change its operation support types, registration ownership,
registry semantics, or family method signatures. The rest of P4.0-FREEZE-1 stands.

## Decision

Define a frozen pure-data value at `insarforge.contracts.plugins.ProductInput`
with exactly two required fields:

```python
ProductInput(artifact: ArtifactRef, value: Product)
```

Both members must have exactly their approved concrete types, not subclasses,
drafts, other records, or structural lookalikes. Their `schema_id` and
`schema_version` must agree. Retain the original immutable ArtifactRef and
Product objects; do not reinterpret their identities or synthesize digests.
This checks local type/schema agreement only: it neither proves that the
reference's locator contains this Product nor validates a manifest or assets.
Construction performs no I/O, locator reads, registry lookups, Product loading,
or runtime resolution.

Migrate only these existing fields, without renaming or adding family slots:

| Request | Field | Representation |
|---|---|---|
| ProcessingRequest | product_inputs | `Mapping[str, tuple[ProductInput, ...]]` |
| AnalysisRequest | product_inputs | `Mapping[str, tuple[ProductInput, ...]]` |
| CorrectionRequest | source_inputs | `Mapping[str, tuple[ProductInput, ...]]` |
| InspectionRequest | source | `ProductInput` |

Product port maps independently snapshot caller mappings and sequences into
read-only mappings of tuples, preserving port order, element order and
duplicates. Bare ArtifactRef, bare Product, operation-side ResolvedInput and
other records are not implicitly converted. Inspection has no reference-only
fallback. Structured parameters continue to use the existing frozen JSON rules.

§13.1's resolved typed input obligation applies to fields that the family
contract specifies as actual Product/typed-record inputs. Fields explicitly
named or designed as `*_refs` or reference slots retain reference semantics;
they must not all be upgraded to resolved records for uniformity. In particular:

- `ProcessingRequest.acquisition_metadata_refs` and `auxiliary_inputs` remain refs.
- `AnalysisRequest.auxiliary_inputs` remains refs.
- `CorrectionRequest.external_inputs` remains refs.
- `AcquireRequest.catalog_ref` remains a ref.
- `QCRequest.target_refs` and `comparison_refs` remain refs.

## Adaptation and dependencies

An operation-side handler already holding `ResolvedInput(artifact, value)`
explicitly constructs `ProductInput(artifact, value)` for the Product slots
above, then constructs the appropriate family request. The family receives the
same typed Product and its ArtifactRef, without re-reading the locator, lazy
resolution, a services bag, or science data hidden in ExecutionContext.

`contracts.plugins` may import the existing lightweight `products.models`
types. It must not import `contracts.operations`; Product must not import
plugins or operations. Ordinary module-global type hints must resolve. No
operation runtime is introduced to demonstrate the adaptation: narrow fake
handler-to-family tests exercise this data channel only.

## Unchanged boundaries and verification

All public module paths and family method signatures remain unchanged, including
result types. No serialization format, operation support type, registry behavior,
P4.2 executor, TaskSpec execution, cache, retry or state machine changes. No InSAR
algorithm, scientific constant, processing default or frozen Phase 0–3 behavior
changes. This decision does not authorize P4.2.

Tests must reject unpaired/wrong-type/schema-mismatched inputs, verify frozen
exact fields and collection ownership, preserve reference slots, and transfer
the original Product/ref through all four family requests without I/O or context
services. Test import direction, resolvable hints and unchanged method signatures.
Local validation and Python 3.11–3.14 CI establish implementation evidence, not
an independent Gate result. P4.1 still requires independent re-Gate.
