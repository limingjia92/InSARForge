# ADR-0015: Lineage preserves repeated input occurrences

Status: ACCEPTED by the project owner for P4.2-03-R2, 2026-09-20.

## Context

ADR0012 rejects every repeated (role, artifact.record_id) key. The accepted
planning model preserves ordered repeated inputs, and cache validation compares
lineage with every actual input occurrence. These rules conflict when a task
consumes one artifact twice in the same role.

## Decision

This ADR supersedes only ADR0012's duplicate-lineage validation restriction.
Product.lineage remains an ordered immutable tuple of LineageEntry(role,
artifact). Preserve one entry for every resolved input occurrence: input ports
in canonical sorted order, then each port's declared input order, expanding an
OutputRef in the producer output order.

Equal ArtifactRef values may repeat under the same role. They must retain their
positions and multiplicity; never silently deduplicate or reorder them. If the
same (role, record_id) key has non-equal ArtifactRef values, reject the lineage.
Equality covers the complete reference, including schema/version, semantic
identity, manifest identity and locator.

Every occurrence contributes to Product semantic material. Changing count or
order can change Product/artifact semantic identity. Existing serializers and
semantic projection preserve the tuple sequence.

## Boundaries and consequences

Product schema remains insarforge:product version 2. LineageEntry has exactly
role and artifact; no occurrence index is added. Acquisition reference uniqueness
is unchanged. No recursive/transitive ancestry flattening is introduced.
P4.2 planning, fingerprint and cache contracts are unchanged. ADR0012's other
rules and all other frozen P4.1/P4.2 contracts remain authoritative.

This is a narrow provenance consistency amendment, not a change to InSAR
scientific behavior. The R1 runtime implementation stopped at the conflict; R2
explicitly approved this resolution. Tests cover repeated-input finalization,
round-trip preservation, semantic count/order and conflicting reference rejection.
