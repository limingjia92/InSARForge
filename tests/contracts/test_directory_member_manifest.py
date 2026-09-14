import pytest
from insarforge.products.assets import AssetKind, AssetIntegrity
from insarforge.products.directory_manifest import (
    DirectoryMember,
    DirectoryMemberManifest,
)


def test_model():
    a = DirectoryMember("b/file", AssetKind.FILE, 2, AssetIntegrity("sha256", "x"))
    d = DirectoryMember("a", AssetKind.DIRECTORY, None, None)
    m = DirectoryMemberManifest(1, (a, d))
    assert [x.path for x in m.members] == ["a", "b/file"]


@pytest.mark.parametrize(
    "p",
    [
        "/absolute",
        "../escape",
        "a/../b",
        "./file",
        "a//b",
        r"a\b",
        "~",
        "~/file",
        "$ROOT/file",
        "${ROOT}/file",
    ],
)
def test_bad_path(p):
    with pytest.raises((ValueError, TypeError)):
        DirectoryMember(p, AssetKind.FILE, None, None)


def test_dupe():
    x = DirectoryMember("x", AssetKind.FILE, None, None)
    with pytest.raises(ValueError):
        DirectoryMemberManifest(1, (x, x))
