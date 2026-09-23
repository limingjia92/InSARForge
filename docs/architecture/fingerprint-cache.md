# P4.2-02 fingerprint and cache decisions

This implements Phase 4 §§7.6–7.8 on the immutable P4.2-01 planning values.
It adds no coordinator, executor, workspace index, receipt writer, state transition,
retry/resume loop or provenance persistence. P4.1 contracts and scientific defaults
are unchanged.

## Three identities

The existing plan digest protects a persisted plan. It is never a cache key.
A task recipe is SHA-256 of canonical JSON prefixed with the domain
insarforge.task.recipe.v1 followed by a NUL byte. Its projection contains core
semantics revision, engine content identity, operation ID/API and validator revision,
plugin kind/ID/API, implementation content identity, prepared execution identity,
validated semantic parameters, ordered input-port semantic digests and complete
output declarations. Port names are canonicalized; source order and duplicates
within each port remain. The caller supplies actual resolved references, expanding
OutputRef sources in their declared order, after exact registry binding resolution.
This layer does not execute resolution, materialize inputs or look up plugins.

Task ID, plan digest, input record IDs, manifest hashes and locators, retry policy,
requested resources, preparation-only data and cache policy are absent from the
recipe. Allocated CPU/GPU counts are present through execution identity; scheduling
memory limits are not result identity. Result-affecting memory/native settings must
be included explicitly in prepared settings.

FingerprintResult has either a lowercase SHA-256 value and reusable=true, or no
value and stable safe reason codes. Unknown, placeholder or incomplete identities
never become reusable sentinel hashes. A disabled cache policy does not prevent
computing a strong recipe or result identity.

## Explicit code and execution evidence

code_content_identity hashes an explicit logical-name-to-file scope, with sorted
canonical keys and file bytes. Physical checkout/installation paths are excluded.
The composition layer must enumerate all relevant plugin source, imported helpers
and resources; an incomplete list cannot establish trustworthy implementation identity.
engine_code_identity covers package initialization plus core, contracts, products
and provenance trees, excluding bytecode caches. It excludes config/CLI/version
metadata, plugin families, tests and docs. Imports of new shared semantic code outside
these scopes require updating the identity scope and its regression tests.
No Git commit, package version, stat tuple or installation path substitutes for bytes.
Missing/opaque/linked files fail closed. Development trees can have verified content.

The existing PreparedExecution protocol remains unchanged. The fingerprint consumer
accepts KNOWN object-shaped identity in this explicit v1 projection:

- schema_version: integer 1
- wrapper_digest: SHA-256 content identity
- native_components: named objects containing executable_digest and a
  dependency_digests name-to-SHA-256 map
- settings: canonical result-affecting effective defaults, precision, threading,
  seeds and other settings
- external_resource_digests: name-to-SHA-256 map for resources outside explicit inputs

Empty native/resource maps assert that none are used. Adapters are responsible for
completeness and truthful current evidence, including build/runtime dependencies.
Absent fields, weak digests and UNKNOWN identities refuse reuse. This module consumes
evidence; it never probes native installations or calls prepare/invoke. Allocated
CPU/GPU and semantic evidence-reference digests join this projection under the domain
insarforge.execution.identity.v1 plus NUL. No resource equivalence exemption is introduced.

## Actual semantic result and local invalidation

artifact_semantic_digest uses the domain insarforge.artifact.semantic.v1 plus NUL,
schema/version, Product profile, producer recipe, output port, typed record projection,
scientific asset content identities and ordered input lineage. Product content uses the
existing Product semantic projection, preserving geometry, layers, metadata and extensions.
Catalog includes provider/query/selectors/entries/access/evidence; Acquisition includes
source/mission/attributes/evidence; QC includes status/method/inputs/metrics/findings.
Instance record/product IDs and Product provenance/attempt/version labels are excluded.
The Catalog projection names the authentication-required boolean access_required;
no authentication material is included. Scientific JSON remains semantic.
Nested typed references need strong digests. Required unknown asset/reference identity
returns non-reusable. Explicit UNKNOWN scientific values retain their frozen meaning.

Same recipe can produce different actual results. Those different artifact digests
become downstream input digests and change downstream recipes. Independent branches
keep their recipes even if the whole plan digest changes. There is no second graph,
invalidation tree or global purge.

## Pure candidate decision and evidence trust

CacheCandidate, CachedOutput, AssetEvidence and CommitEvidence snapshot owned
immutable inputs. validate_cache_candidate performs no I/O. AUTO requires a strong
matching recipe/execution identity, matching actual ordered inputs, committed evidence,
exact output ports/count/schema/profile, exact manifest byte hashes, strict structured
decoding, attached port validation and recomputed semantic result identity.
Product production recipe, execution identity, plugin, record ID and ordered lineage
must agree. Every asset declaration must have strong matching evidence. Missing,
unverified or malformed evidence rejects reuse with safe codes.

Product manifests use the existing strict decoder. Other frozen record types require
an explicit strict decoder supplied by the composition layer; no reflection or plugin
discovery occurs. That decoder must validate the complete supplied bytes against the
schema, and the attached validator must establish profile/record compatibility.
Decoder/validator failures reject the candidate. Manifest safety checks permit only
the exact authentication_required boolean/null field; credential strings remain rejected. A successful hash is not proof that
an adapter's schema validation or scientific claims are correct.

CommitEvidence is a trusted assertion from a validated committed receipt, bound to
the exact output manifest digests. It is not a receipt publication mechanism or
authentication proof. P4.2-03 must load/validate the actual committed receipt, bind it
to the candidate recipe/execution/inputs/outputs and supply current asset observations.
An arbitrary constructed assertion or stale observation is insufficient at that
composition boundary. Eligibility from can_publish_cache performs no publication.
DISABLED refuses both reuse and publication eligibility.

## Explicit integrity I/O

verify_asset_content is the separate read-only local I/O boundary. Files require
declared SHA-256 and actual byte hashing, optionally checking declared size. It pins
directory descriptors, disallows symlink traversal/hardlinks and checks for mutation
during the read; stat data never serves as content identity. Same-size replacement
with restored mtime fails. Platforms lacking safe no-follow reads refuse reuse.

Directories require explicitly supplied manifest bytes with a matching manifest hash,
strict existing member-manifest decoding and complete existing directory validation.
Added/removed/changed members, weak member digests or unsafe traversal refuse reuse.
The directory identity covers sorted member paths/kinds/file digests; manifest locator
is never fetched. Remote assets refuse reuse here. Verification observes current
content, not a transactional snapshot or guarantee against future concurrent writes.
The future runtime must maintain stability between observation and use.

Focused tests: tests/contracts/test_fingerprint_cache.py. Existing planning, Product,
registry, directory validation and architecture suites remain applicable.

## Runtime verification boundary (ADR0016)

Pure fingerprint/cache functions consume verified evidence; an arbitrary supplied
ArtifactRef digest does not establish verification. The runtime checks exact safe
manifest bytes and recomputes artifact identity with complete recipe-aware
ArtifactEvidence and current asset observations. It keeps original references for
ProductInput/lineage and uses a separate effective identity for cache decisions.
Insufficient material yields no reuse and propagates weak identity; conflicting
declared strong identity is rejected. Product content digest alone is insufficient.

Required runtime input/output port/profile checks use affirmative full verification,
consistent with candidate acceptance. Weak asset identity may still allow otherwise
valid execution without cache; it is distinct from unresolved required compatibility.
Only attributed matching damaged results invoke restart safety restrictions.
