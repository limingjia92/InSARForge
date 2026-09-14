from insarforge.products.assets import AssetKind
from insarforge.products.directory_manifest import (
    DirectoryMember,
    DirectoryMemberManifest,
)
from insarforge.products.directory_manifest_serialization import (
    directory_member_manifest_from_bytes,
    directory_member_manifest_to_bytes,
)


def test_roundtrip():
    m = DirectoryMemberManifest(1, (DirectoryMember("x", AssetKind.FILE, 1, None),))
    assert (
        directory_member_manifest_from_bytes(directory_member_manifest_to_bytes(m)) == m
    )
