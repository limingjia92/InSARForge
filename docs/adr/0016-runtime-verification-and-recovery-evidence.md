# ADR-0016: Runtime verification and recovery evidence

Status: implementation clarification authorized by P4.2-PRO-REMEDIATION-01 R1.
This record explains compliance with existing authority; it does not supersede
ADR0001–0015, Product v2, WorkflowPlan, scientific meaning or independent review.

## Input evidence is not an identity assertion

A caller's ArtifactRef remains the original reference supplied to ResolvedInput
and ProductInput and recorded in lineage. Its semantic digest alone is not proof.
The runtime first strictly decodes and checks the exact manifest bytes before
copying them to durable storage.

ArtifactEvidence is an immutable runtime-only record binding that exact ref to a
producing task fingerprint, output port and full ordered producing input map.
These are the necessary inputs to the frozen recipe-aware artifact digest, not a
new fingerprint formula or a boolean assertion of verification. Runtime rechecks
current typed content and observed asset content and recomputes the digest.
Product production and occurrence-by-occurrence lineage must agree with evidence.
A conflicting strong digest is rejected. Missing material cannot be guessed from
Product content digest, record ID or locator.

Without sufficient evidence, otherwise valid inputs may execute with a separate
non-reusable effective identity. Original refs are never replaced in family inputs
or lineage. The weak recipe propagates to outputs/downstream reuse. Explicit
cross-workspace evidence does not require the historical producer registration.
A matching committed local receipt can supply the same complete evidence.
No arbitrary locator fetching or network lookup is introduced.

## Asset ownership

New assets must belong to the current attempt. An exact NativeAsset descriptor
from a verified actual resolved input may instead be read-only shared. Manifests,
current strong content and directory membership are revalidated. No copying,
aliasing, overwrite permission, re-ownership or fsync of shared/historical assets
is implied. Candidate reconstruction uses the producer's persisted actual inputs,
not a later equivalent input instance, preserving original lineage and ownership.

## Versioned runtime facts

New workspace records use schema_version 2. Runtime v1 records are explicitly
unsupported for resume/reuse; they omit evidence needed for a trustworthy decision.
Unknown versions fail closed. No migration or rewriting of old facts occurs.
Use a separate workspace and a new computation scope, or explicitly provide
complete ArtifactEvidence for a safe supported old record import. An old v1
Product manifest remains Product v2; Product and WorkflowPlan wire versions do not
change. Missing proof implies no reuse, never invented defaults.

A started fact records the complete preparation projection (identity status/value/
reason, ordered evidence refs, object-shaped preparation), allocations and resolved
input evidence. PreparationEvidence has its own strict version 1 codec and can
reconstruct execution_identity exactly. Receipt validation verifies this binding.
Evidence is declared safe data, never arbitrary objects, native handles or raw errors.
Result-affecting preparation choices must also appear in semantic execution identity.

Successful resolutions record adopted recipe/execution identity even when no
attempt was created. Resume validates source run/task/receipt associations and
compares current identity with both executed history and adopted cache identity.
Cache reuse does not consume the producer scope's attempt budget.
Unparseable/unattributed cache candidates cannot poison unrelated first execution;
restart restrictions require matching started computation evidence.

## Interruption

Handled KeyboardInterrupt requests cooperative cancellation, stops admission,
awaits owned threads and writes interrupted unfinished attempts and run state while
holding the writer lock, then propagates the exception. Committed receipts remain
successful. RuntimeCrash fault injection and actual process death are different:
later recovery appends validated recovery evidence without rewriting old facts.
Threads cannot be forcibly killed by this API.

## Required validation

Actual consumption/commit requires affirmative required port/schema/profile
verification. Static dry-run remains pure and may report runtime availability as
unchecked. Weak content identity is a separate non-cache condition. A structurally
valid QCReport FAIL remains a successful quality report, not a retryable exception.

The original eight independent findings and adjacent controls are tested in
test_p42_pro_audit_regressions.py, with existing runtime/fingerprint/planning tests.
Engineering evidence does not constitute independent re-Gate acceptance.
