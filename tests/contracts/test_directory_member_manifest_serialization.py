import pytest

from insarforge.products.assets import AssetKind
from insarforge.products.directory_manifest import (
    DirectoryMember,
    DirectoryMemberManifest,
)
from insarforge.products.directory_manifest_serialization import (
    directory_member_manifest_from_bytes,
    directory_member_manifest_from_value,
    directory_member_manifest_to_bytes,
    directory_member_manifest_to_value,
)


def manifest():
    return DirectoryMemberManifest(
        1,
        (
            DirectoryMember("b", AssetKind.FILE, 1, None),
            DirectoryMember("a", AssetKind.DIRECTORY, None, None),
        ),
    )


def test_roundtrips():
    for m in (DirectoryMemberManifest(1, ()), manifest()):
        assert (
            directory_member_manifest_from_bytes(directory_member_manifest_to_bytes(m))
            == m
        )


def test_canonical():
    assert directory_member_manifest_to_bytes(
        manifest()
    ) == directory_member_manifest_to_bytes(
        DirectoryMemberManifest(1, tuple(reversed(manifest().members)))
    )


def test_invalid():
    v = directory_member_manifest_to_value(manifest())
    for k, val in [("schema_id", "x"), ("schema_version", 2), ("members", {})]:
        q = dict(v)
        q[k] = val
        with pytest.raises((ValueError, TypeError)):
            directory_member_manifest_from_value(q)
    q = dict(v)
    q["extra"] = 1
    with pytest.raises(ValueError):
        directory_member_manifest_from_value(q)
    q = dict(v)
    del q["members"]
    with pytest.raises(ValueError):
        directory_member_manifest_from_value(q)
    x = dict(v["members"][0])
    x["extra"] = 1
    q = dict(v)
    q["members"] = [x]
    with pytest.raises(ValueError):
        directory_member_manifest_from_value(q)
    for field in ("path", "member_kind", "size_bytes", "integrity"):
        x = dict(v["members"][0])
        del x[field]
        q = dict(v)
        q["members"] = [x]
        with pytest.raises(ValueError):
            directory_member_manifest_from_value(q)
    q = dict(v)
    q["members"] = [dict(v["members"][0], member_kind="bad", path="../x")]
    with pytest.raises((ValueError, TypeError)):
        directory_member_manifest_from_value(q)


def test_duplicate_keys():
    with pytest.raises(ValueError):
        directory_member_manifest_from_bytes(
            b'{"schema_id":"insarforge:directory-member-manifest","schema_id":"x"}'
        )
