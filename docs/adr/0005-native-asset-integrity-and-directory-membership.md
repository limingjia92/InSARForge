# ADR-0005 — Native Asset Integrity and Directory Membership

**Status: Accepted**

This ADR is a clarification/addendum to **P4.0-FREEZE-1**. It resolves the
underspecified public shapes and optionality for NativeAsset integrity and
directory membership. It does not thaw unrelated P4.0 architecture and selects
no scientific InSAR convention.

## Decision

`NativeAsset` has exactly these public fields:

```text
asset_id: str
asset_kind: AssetKind
location: AssetLocation
media_type: str | None
size_bytes: int | None
integrity: AssetIntegrity | None
member_manifest_ref: ArtifactRef | None
```

The transitional fields `kind`, `role`, `checksum_algorithm`, `checksum`, and
`extensions` are not part of the final contract. `asset_kind` replaces `kind`.
NativeAsset has no independent logical role; scientific role belongs to
DataLayer or higher semantic contracts. NativeAsset has no generic extensions
field.

`AssetIntegrity` is an immutable value object:

```text
algorithm: str
digest: str
```

Both values are non-empty, trimmed strings. Names are not normalized. The
object records declared metadata only and performs no calculation, verification,
filesystem access, or network access.

For FILE assets, `size_bytes` is an optional non-negative byte-length value,
`integrity` is optional declared file-stream integrity, and
`member_manifest_ref` must be `None`. For DIRECTORY assets, `size_bytes` and
`integrity` must both be `None`; membership/content scope is represented only
by optional `member_manifest_ref`, an `ArtifactRef` to an immutable, versioned
directory-member manifest. NativeAsset does not dereference that reference.

Core does not invent recursive directory hashing, tar normalization, child-order
hashing, or directory `stat().st_size` semantics. Missing or unverifiable
directory membership remains UNVERIFIED.

Remote references retain the R2-A1 behavior: no download or network access and
no assumption that declared integrity has been verified. Remote FILE metadata
may be declared; remote DIRECTORY member references may be declared, but Core
does not fetch them.

## Identity boundary

`location`, `media_type`, `size_bytes`, `integrity`, and
`member_manifest_ref` are persisted integrity/reference metadata and therefore
participate in the complete Product manifest digest. They do not automatically
become Product content semantic identity. The existing Product content digest
continues to require explicit `asset_content_identities`. A verified backend or
runtime may derive and supply a strong identity; no fallback to path, size,
declared checksum, record ID, or locator is permitted.

## Follow-up

R2-A2.1 implements AssetIntegrity and migrates NativeAsset and strict codecs.
R2-A2.2 adapts validation and defines member-manifest validation. Transitional
profile logic that matches NativeAsset.role is non-final and is remediated in a
later segment; this ADR does not redesign ProductProfile.
