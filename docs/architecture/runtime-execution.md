# Local workflow runtime

The programmatic entry points are core.runtime.Runtime and
core.runtime_plan.dry_run. Supply an immutable WorkflowPlan, a sealed
PluginRegistry, a ResourceAllocation budget and explicit implementation_files
mapping from PluginRef to logical filename/local file paths. Each mapping must
cover the binding implementation and its actual helper/dependency content.
Incomplete identity disables reuse; deployment paths and package versions are
not substitutes for strong content identity.

Use an absolute workspace on tested Linux local POSIX storage, outside a Git
checkout. WSL users should use the Linux filesystem, not a Windows drive mount.
NFS, SMB, 9p and unknown filesystem types fail closed. The coordinator checks a
nonblocking flock with a second open handle. The supported boundary is local
cooperative processes, not a distributed lock or arbitrary power-loss guarantee.

## Execution and inputs

Runtime(..., max_workers=1) is the serial reference. Larger limits run the same
coordinator path with bounded thread workers. Admission accounts for CPU/GPU and
declared memory against the supplied budget; it is not an OS RSS limit.

run(plan, external_manifests=..., external_evidence=..., config_refs=...) accepts explicitly supplied
manifest bytes keyed by declared external record ID. Before durable copying, the
runtime strictly decodes the exact supported record and checks persistence safety.
Typed port codecs then affirm required schema/profile obligations before invoke;
the runtime never fetches arbitrary external locators.

external_evidence maps record IDs to immutable
provenance.runtime_evidence.ArtifactEvidence(artifact, producer_fingerprint,
output_port, ordered_inputs). Supply the original producing recipe and complete
ordered inputs, not a Product content digest masquerading as an artifact digest.
Current manifest/content/assets are recomputed against that material. A matching
local committed receipt can supply evidence automatically. Without sufficient
evidence, execution uses a non-reusable effective identity; the original reference
is preserved in family inputs and lineage. Contradictory strong evidence is rejected.
Cross-workspace verified imports do not load their historical producer plugin. OutputRef expands
the original output order. Repeated inputs retain their order and multiplicity.
ADR0015 permits identical repeated Product lineage entries and rejects
conflicting same-role/same-record references.

The exact binding's factory and prepare run before final recipe evaluation.
Only invoke creates an actual attempt. A cache hit retains the original producer,
manifest, attempt and lineage and records a new reuse resolution without an
attempt. CachePolicy.DISABLED never publishes a reusable index.

source_revision may supply the composition layer's known full Git revision
for non-semantic provenance. Missing Git provenance remains null (unknown);
the runtime does not shell out or guess. Package version is also recorded.
Content digests, not these provenance labels, govern semantic identity.

## Ownership, records and recovery

Workers receive an isolated ExecutionContext; they must close output writers
before return and write only in their own attempt area. Plugins are trusted
cooperative Python code, not sandboxed. Inputs are read-only. The coordinator
checks output ownership, rejects symlinks/hardlinks, rechecks input integrity,
validates all outputs, flushes new owned files/manifests and atomically publishes result.json
last. Exact verified input assets may be shared read-only by derived Products;
they are observed without copying, mutation or fsync. Historical cache observation
also does not flush old assets. Only that receipt commits success. Cache indexes and task/run summaries are
projections; missing indexes do not negate a valid receipt.

Runtime records have closed versioned JSON schemas and reuse standard
recognizable-secret checks. Native textual evidence is checked before it is
registered. Plugins remain responsible for sanitizing their files before writing;
Core does not discover every secret in arbitrary binary data or erase evidence.
Raw exception text is never copied into public records or the private no-output
attempt logger. Config remains Phase 3-owned, referenced rather than imported.

resume(source_run_id) acquires the workspace lock, loads the saved plan and
manifests, checks current strong identities and creates a new run linked to the
old scope. Recovery appends a separate record without rewriting old files.
A valid receipt survives missing summary/index updates. Uncommitted started
attempts count against the finite scope budget, including repeated resumes.
Changed or insufficient identity raises RESUME_REPLAN_REQUIRED. An explicitly
new run has a new execution scope; it must not be presented as an unchanged resume.
Unsafe, permanent and exhausted attempts do not restart automatically.

Only RetryableExecutionError plus RESTARTABLE plus remaining budget permits
automatic retry, with fixed finite backoff. Other exceptions are permanent safe
error codes. Independent branches continue; dependent branches become BLOCKED.
The five TaskState values are unchanged; completion/attempt/run status are
separate. Completion order records actual worker completion, not a sorted fiction.

## Pure inspection and limits

dry_run validates declarations, exact bindings, schemas/profiles, DAG and resource
feasibility. It performs no factory/prepare/invoke, I/O, workspace creation or
native probing, and returns unresolved recipe reasons with availability UNCHECKED.
Bindings' static validators must honor their pure contract.

This module establishes P4.2 engineering semantics. It does not implement the
P4.3 six-family Fake E2E, real SAR processing, distributed scheduling, databases,
cloud/object storage or native checkpoint recovery. No InSAR scientific defaults
or Phase 3 configuration behavior are changed.

## Runtime evidence compatibility and interruption

Workspace records now use explicit schema version 2. The earlier v1 lacks complete
preparation/input/adoption evidence and is refused for runtime recovery/reuse;
unknown versions are refused too. Existing bytes are not migrated or rewritten.
Product v2 and WorkflowPlan v1 remain unchanged. Old safe manifests can be imported
into a new workspace with complete explicit ArtifactEvidence, or run without reuse
when evidence is insufficient.

PreparationEvidence serializes and reconstructs the full semantic identity,
ordered evidence refs and object-shaped preparation plus actual allocation facts
in started records. Resolution records retain adopted recipe/execution identity
and safe cache/preflight reasons. Cache-only and mixed resume chains compare these
facts before accepting the current prepared identity. Unattributed damaged receipts
are rejected locally and cannot prevent an unrelated UNSAFE task's first execution.

Handled KeyboardInterrupt closes interrupted state after cooperative worker
shutdown and before writer-lock release, then propagates. Already committed
receipts survive; unresolved actual attempts consume scope budget. True process
death is handled by a later append-only recovery. No thread killing is attempted.
See ADR0016 and the independent-audit regression suite for boundary tests.


## Scope attribution and handled terminal exits

Fresh execution scopes have no retry history. Resume first selects attributable
runs by validated run metadata and matching scope/plan, before reading their
attempt payloads. All runs in that scope contribute to the attempt sequence,
including sibling resumes: choosing an older source cannot replenish a budget.
Attempt paths must agree with run, scope, task and attempt identities. Missing or
damaged attributed started/finished records fail closed before a new run is
created. RUNNING transition counts also expose a missing whole attempt directory.
Run-level metadata used for scope attribution remains strictly validated.
Unrelated attempt damage is confined to its cache candidate; a later valid
candidate can still be selected. Bad historical bytes are never deleted.

An orderly whole-run refusal such as RESUME_REPLAN_REQUIRED remains an exception.
Reliable history/identity prevalidation runs before creating the new run. If an
orderly exception occurs later, the coordinator stops admission, requests
cooperative cancellation and awaits its owned workers, then closes the new run as
FAILED under the writer lock before rethrowing. Existing successful receipts and
resolutions remain authoritative; uncommitted cancelled attempts are INTERRUPTED,
and observed worker exceptions keep their normal failed/retryable classification.
Safe resolution reasons explain refusal without persisting raw exception text or
inventing cache-hit attempts. KeyboardInterrupt instead closes the run as
INTERRUPTED and is rethrown. RuntimeCrash and true process loss remain unhandled
crash boundaries for subsequent recovery. A persistence/validation failure during
closure propagates; it is never reported as successful closure.

Terminal task projections fold validated attempts by their recorded sequence,
then preserve validated accepted resolutions, including cache-only successes.
Random UUID or filesystem enumeration order does not determine chronology.
Earlier failed attempts remain immutable history and cannot demote later
committed success. Completion order keeps actual coordinator-observed completion
events, including repeats and worker completions observed during safe shutdown;
it is neither sorted nor deduplicated.
