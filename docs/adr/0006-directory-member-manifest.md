# ADR-0006 — Directory Member Manifest

**Status: Accepted**

This ADR is a clarification/addendum to P4.0-FREEZE-1 and ADR-0005. It resolves the persisted record schema referenced by `NativeAsset.member_manifest_ref` without thawing unrelated P4.0 decisions. It defines no mission/backend-specific directory layout and no scientific InSAR convention.

## Decision

Freeze the immutable persisted/domain value object:

```text
DirectoryMemberManifest(
    schema_version: int,
    members: tuple[DirectoryMember, ...],
)
```

Version 1 requires `schema_version == 1`, has no generic extensions field, and uses record schema identity `insarforge:directory-member-manifest`. `NativeAsset.member_manifest_ref` remains `ArtifactRef | None` and references a persisted record with that identity. NativeAsset construction validates only ArtifactRef structure and does not dereference it.

`DirectoryMember` is immutable:

```text
DirectoryMember(
    path: str,
    member_kind: AssetKind,
    size_bytes: int | None,
    integrity: AssetIntegrity | None,
)
```

It uses existing `AssetKind.FILE` and `AssetKind.DIRECTORY`; no new member-kind enum is introduced.

### Paths and scope

`path` is a canonical UTF-8 logical path relative to the root of the NativeAsset DIRECTORY, independent of process cwd and host OS semantics. It is non-empty, relative, POSIX-separated, does not start with `/`, rejects `\\`, empty components, `.` or `..`, NUL/control characters, `~`, and environment expansion. The root itself is not represented. Examples include `data/file.bin`, `metadata/config.txt`, `nested/subdir`, and `nested/subdir/file.dat`; `/absolute/file`, `../escape`, `a/../../escape`, `./file`, `a//b`, and `a\\b` are invalid.

Version 1 is a complete recursive inventory: every ordinary file and ordinary subdirectory is represented, with nested paths relative to the asset root. An empty directory has `members == ()`. This declares membership and topology; it is not a recursive directory byte-stream hash.

Members have unique paths and canonical persisted order ascending by Unicode code-point lexical `path`. Implementations must require or canonicalize this order; ordering is serialization canonicalization, not scientific semantics.

For FILE members, `size_bytes` may be a non-negative integer or `None`, and `integrity` may be an `AssetIntegrity` or `None`. Declared integrity is metadata until verified; weak or absent integrity cannot establish verified strong directory content identity. For DIRECTORY members, both fields are required to be `None`; directory entries carry membership/topology only, with no recursive integrity. Nested files carry their own metadata.

Version 1 does not represent symbolic links, hard-link identity, FIFOs, sockets, devices, or other special filesystem objects. A generic verifier must not silently reinterpret them as FILE/DIRECTORY, must not follow symlinks, and cannot fully verify a directory containing them unless a later version/backend-specific contract handles them explicitly.

### Identity and validation boundaries

The manifest record may have its own manifest digest through normal ArtifactRef persistence. Its semantic/content identity is not implied by record existence, `record_id`, locator, path, or declared unverified integrity. A verified complete manifest may later be used to derive an explicit strong `asset_content_identity` for a DIRECTORY NativeAsset; that identity must be passed explicitly to `product_content_digest(...)`. Asset/member machinery never populates Product semantic identity automatically.

Product/NativeAsset construction validates only ArtifactRef structure. Ordinary `validate_product_assets(...)` without a resolved manifest leaves DIRECTORY assets UNVERIFIED and performs no implicit resolver, network, or file fetch. A future explicit generic helper may take an accessible local DIRECTORY and a resolved `DirectoryMemberManifest`, enumerate ordinary files/directories without following symlinks, compare complete membership, compare declared FILE sizes, and verify supported FILE integrity. It must not fetch references automatically, recursively hash directories as byte streams, invent backend-specific files, or generate Product semantic identity. This explicit verifier is deferred to A2.2b.

### Serialization

The manifest envelope is strict:

```text
schema_id: "insarforge:directory-member-manifest"
schema_version: 1
members: [...]
```

Each persisted member contains exactly `path`, `member_kind`, `size_bytes`, and `integrity`. Unknown or missing typed fields are rejected. `AssetIntegrity` uses ADR-0005’s `algorithm`/`digest` representation. Serialization is explicit; generic dataclass reflection is not permitted.

## Planned follow-up

A2.2a will implement `DirectoryMember`, `DirectoryMemberManifest`, strict serializer/decoder, and model/serialization tests. A2.2b will implement an explicit local directory verifier taking both `NativeAsset` and a resolved manifest, with membership/integrity validation and integration regression. Existing ordinary asset validation must not dereference `member_manifest_ref` automatically.
