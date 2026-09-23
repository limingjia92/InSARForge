import dataclasses

import pytest

from insarforge.products.assets import AssetIntegrity, AssetKind
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


def test_unicode_cc_and_valid_unicode():
    with pytest.raises(ValueError):
        DirectoryMember("a/\x01b", AssetKind.FILE, None, None)
    assert DirectoryMember("数据/文件", AssetKind.FILE, 0, None)


def test_metadata_schema_and_frozen():
    with pytest.raises(ValueError):
        DirectoryMember("x", AssetKind.DIRECTORY, 1, None)
    with pytest.raises(ValueError):
        DirectoryMember("x", AssetKind.DIRECTORY, None, AssetIntegrity("sha256", "x"))
    with pytest.raises(ValueError):
        DirectoryMember("x", AssetKind.FILE, -1, None)
    with pytest.raises(ValueError):
        DirectoryMemberManifest(True, ())
    with pytest.raises(ValueError):
        DirectoryMemberManifest(2, ())
    x = DirectoryMember("x", AssetKind.FILE, None, None)
    with pytest.raises((AttributeError, dataclasses.FrozenInstanceError)):
        x.path = "y"
