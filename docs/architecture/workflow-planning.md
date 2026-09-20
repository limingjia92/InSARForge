# Static workflow planning

P4.2-01 implements the static part of P4.0-FREEZE-1 §§6.4–6.5,
7.1, 7.3–7.5 and 8, with ADR0013 operation validation and ADR0014
resolved Product inputs preserved. It does not execute tasks.

## Public API

Import values from `insarforge.contracts.execution`:

- `TaskSpec(schema_version, task_id, plugin_ref, operation_id,
  operation_api_version, inputs, outputs, semantic_parameters, resources,
  retry_policy=RetryPolicy(), restart_safety=RestartSafety.UNSAFE,
  cache_policy=CachePolicy.AUTO)`.
- `OutputRef(task_id, port)` identifies the complete ordered output tuple.
- `OutputDeclaration(port, schema_id, schema_version, count=1,
  profile_id=None, profile_version=None)` is pure data. It does not replace
  the existing operation RecordSchemaRef or ProductProfileRef types.
- `RetryPolicy(max_attempts=1, backoff_seconds=0)` includes the first attempt
  in its positive integer budget. Backoff must be finite and nonnegative.
- `WorkflowPlan(schema_version, tasks, external_inputs=())`.

Both schema versions currently support exactly integer 1. Identifiers reuse
the existing identifier rule. Resources reuse ResourceRequest: CPU >= 1,
GPU >= 0, memory absent or positive. Booleans cannot stand in for integers.
Sequence arguments accept lists/tuples and snapshot them. JSON containers
are deeply frozen through the existing FrozenJSON rules. Instances do not
promise hashability, and hold no registry, adapter or execution state.

TaskState values are `pending/running/succeeded/failed/blocked`.
CompletionDisposition separately has `executed/cache_reused`; AttemptOutcome
has `succeeded/failed/interrupted`. RestartSafety has `restartable/unsafe`,
and CachePolicy has `auto/disabled`. These enums are declarations only.

## Structural graph validation

Dependencies derive exclusively from OutputRefs. Task/port duplicates,
unknown references, self references and cycles (including disconnected
cycles) fail with safe ContractError codes. Every task has at least one
positive-count output declaration. Input/output port names cannot overlap,
consistent with OperationBinding. An empty plan is valid and has an empty
order, but does not waive the output requirement for actual tasks.

`task(id)`, `dependencies(id)`, `dependents(id)` and
`topological_order()` expose immutable results. Topological traversal chooses
the lexicographically smallest task ID among all current zero-indegree
candidates, including newly eligible candidates, using a min-heap.
Task/declaration tables are canonicalized by identifier; input source order
and repetitions are preserved. Repeated references create one graph edge
but retain every data occurrence. A reference to a count-N output contributes
N records each time it appears.

External inputs form an exact unique set by record ID of all direct
ArtifactRef sources. Repeated consumption is allowed; conflicting locator,
manifest, schema or semantic information for the same ID is rejected.
Missing semantic digests remain None and do not prevent static validation.
No placeholder task fingerprint or cache key is computed.

## Registry-aware validation

`insarforge.core.planning.validate_plan(plan, sealed_registry)` returns the
existing ProductValidationReport. Exact plugin kind/ID/API and operation
ID/API lookup uses the existing registry; missing identity raises its
existing domain error. No latest-version selection occurs.

Static capability declarations, complete port sets, schema/profile
agreements, output counts and expanded input bounds are checked.
The only callback is
`handler.validate_spec(parameters, binding.inputs, binding.outputs)`.
Its ERROR and UNVERIFIED issues are retained; report truthiness is never
used as validity. Callback exceptions become PLAN_HANDLER_VALIDATION without
echoing arbitrary exception text; they are never treated as success or retry. `report.is_valid` means no ERROR, while
`is_fully_verified` means no issues.

Each task records PLAN_RUNTIME_ENVIRONMENT_UNVERIFIED. External sources
also record PLAN_EXTERNAL_RECORD_UNVERIFIED and, when a profile is required,
PLAN_EXTERNAL_PROFILE_UNVERIFIED. ArtifactRef carries no profile evidence:
a locator is never opened to fill that gap. A valid static report therefore
does not establish environment availability, resource budget feasibility,
record/asset integrity, scientific compatibility or execution identity.

No factory, prepare/invoke, codec or actual-record validator is called.
No plugin instance, ExecutionContext, directory, native probe, credential
lookup or network request is created by in-memory planning or codecs.
Later adapters resolve records and explicitly construct ProductInput for
family requests; planning does not weaken ADR0014.

## Strict JSON and digest

TaskSpec.to_dict()/from_dict() and WorkflowPlan.to_dict()/from_dict()
use explicit schema IDs `insarforge:task-spec` and
`insarforge:workflow-plan`, each independently versioned at 1.
These are full data projections, not arbitrary dataclass reflection.
All fields are required, including nullable and default-valued fields.

WorkflowPlan.to_json() returns UTF-8 bytes for the envelope
`{"plan": <complete projection>, "plan_digest": <hex SHA-256>}`.
WorkflowPlan.from_json() strictly reconstructs values and verifies the digest.
Unknown/missing fields, duplicate JSON keys at any depth, nonfinite numbers,
unsupported versions, unknown enum values and invalid scalar types fail.
Reference source tags are exactly `artifact` (full ArtifactRef) or
`output` (task_id and port); they never name importable Python classes.

Canonical JSON sorts object keys, uses compact separators, ensure_ascii=False
and allow_nan=False. Tasks sort by task_id, external refs by record_id and
output declarations by port. Ordered input sources remain unchanged.
There is no Unicode normalization or numerical/scientific equivalence:
1 and 1.0 may have different digests.

The plan digest is SHA-256 of
`b"insarforge.workflow-plan.v1\0" + canonical_json(plan_projection)`.
The envelope digest is outside that projection, so there is no hash cycle.
It protects the full plan description, including locators and policies; it
is not a scientific computation fingerprint and must not enter a task's
future recipe. It is an integrity check, not a cryptographic signature.

Projection and JSON boundaries apply the existing persistence secret scanner
to all explicit fields, including nested semantic parameters and locators.
Errors use safe codes and do not echo rejected material. This recognizes
known secret patterns; it cannot certify absence of arbitrary secrets.

## Explicit files and later runtime

`save_plan(plan, path)` validates and serializes before opening a temporary
file in the target directory, then flushes/fsyncs and replaces the target.
It creates no directories. `load_plan(path, registry)` reads only that file,
reconstructs/checks the digest, then performs static operation validation
with the caller's sealed registry. ERROR reports reject loading; UNVERIFIED
obligations remain available via validate_plan. Relative locators retain
their exact text and are never resolved against the process cwd.

File failures use WorkspaceError safe codes. This small plan-file write
does not claim multi-file transactions, workspace locking or runtime receipt
semantics. Callers explicitly control file paths and registry composition.

Final computation fingerprints, semantic result identities, cache decisions
and invalidation belong to P4.2-02. Execution/resource admission, bounded
concurrency, receipts, attempts/retry/resume, provenance and a complete
dry-run interface belong to P4.2-03. Static policies here implement none of
those behaviors.
