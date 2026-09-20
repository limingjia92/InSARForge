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

run(plan, external_manifests=..., config_refs=...) accepts explicitly supplied
manifest bytes keyed by declared external record ID. Typed port codecs validate
them; the runtime never fetches arbitrary external locators. OutputRef expands
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
validates all outputs, flushes files/manifests and atomically publishes result.json
last. Only that receipt commits success. Cache indexes and task/run summaries are
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
