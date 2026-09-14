from collections.abc import Mapping

from .assets import AssetIntegrity, AssetKind
from .directory_manifest import DirectoryMember, DirectoryMemberManifest
from .serialization import canonical_json_bytes, strict_json_loads

DIRECTORY_MEMBER_MANIFEST_SCHEMA_ID = "insarforge:directory-member-manifest"
DIRECTORY_MEMBER_MANIFEST_SCHEMA_VERSION = 1


def directory_member_manifest_to_value(m):
    if not isinstance(m, DirectoryMemberManifest):
        raise TypeError("manifest")
    return {
        "schema_id": DIRECTORY_MEMBER_MANIFEST_SCHEMA_ID,
        "schema_version": 1,
        "members": [
            {
                "path": x.path,
                "member_kind": x.member_kind.value,
                "size_bytes": x.size_bytes,
                "integrity": None
                if x.integrity is None
                else {"algorithm": x.integrity.algorithm, "digest": x.integrity.digest},
            }
            for x in m.members
        ],
    }


def directory_member_manifest_to_bytes(m):
    return canonical_json_bytes(directory_member_manifest_to_value(m))


def _fields(v, fields, n):
    if not isinstance(v, Mapping) or set(v) != set(fields):
        raise ValueError(n)
    return v


def directory_member_manifest_from_value(v):
    r = _fields(v, ("schema_id", "schema_version", "members"), "root")
    if r["schema_id"] != DIRECTORY_MEMBER_MANIFEST_SCHEMA_ID:
        raise ValueError("schema_id")
    if not isinstance(r["schema_version"], int) or isinstance(
        r["schema_version"], bool
    ):
        raise TypeError("schema_version")
    if not isinstance(r["members"], (list, tuple)):
        raise TypeError("members")
    out = []
    for x in r["members"]:
        q = _fields(x, ("path", "member_kind", "size_bytes", "integrity"), "member")
        try:
            k = AssetKind(q["member_kind"])
        except (ValueError, TypeError) as e:
            raise ValueError("member_kind") from e
        i = q["integrity"]
        if i is not None:
            z = _fields(i, ("algorithm", "digest"), "integrity")
            i = AssetIntegrity(z["algorithm"], z["digest"])
        out.append(DirectoryMember(q["path"], k, q["size_bytes"], i))
    return DirectoryMemberManifest(r["schema_version"], tuple(out))


def directory_member_manifest_from_bytes(data):
    return directory_member_manifest_from_value(strict_json_loads(data))
