from pathlib import Path

import pytest

from insarforge.products.assets import (
    AssetIntegrity,
    AssetKind,
    AssetLocation,
    AssetLocationKind,
    NativeAsset,
)


def loc(value="/data/example.dat", anchor=None):
    kind = (
        AssetLocationKind.MANIFEST_RELATIVE
        if anchor is not None
        else AssetLocationKind.ABSOLUTE_LOCAL
    )
    return AssetLocation(kind, value, anchor)


def asset(**kwargs):
    base = dict(
        asset_id="asset_a",
        asset_kind=AssetKind.FILE,
        location=loc(),
        media_type=None,
        size_bytes=None,
        integrity=None,
        member_manifest_ref=None,
    )
    base.update(kwargs)
    return NativeAsset(**base)


def test_kinds_and_locations():
    assert [(x.name, x.value) for x in AssetKind] == [
        ("FILE", "file"),
        ("DIRECTORY", "directory"),
    ]
    assert [(x.name, x.value) for x in AssetLocationKind] == [
        ("MANIFEST_RELATIVE", "manifest_relative"),
        ("ABSOLUTE_LOCAL", "absolute_local"),
        ("REMOTE_REFERENCE", "remote_reference"),
    ]
    loc()
    with pytest.raises(ValueError):
        loc("/x", Path("/tmp"))
    with pytest.raises(ValueError):
        loc("relative")
    assert loc("relative", Path("/tmp/example-root"))
    with pytest.raises(ValueError):
        loc("relative", Path("relative"))
    with pytest.raises(ValueError):
        loc("relative", "/tmp")
    with pytest.raises(ValueError):
        loc(" /x")
    with pytest.raises(ValueError):
        loc("/x ")
    assert AssetLocation(AssetLocationKind.REMOTE_REFERENCE, "https://example/x", None)
    assert AssetLocation(AssetLocationKind.REMOTE_REFERENCE, "s3://bucket/key", None)
    with pytest.raises(ValueError):
        AssetLocation(AssetLocationKind.REMOTE_REFERENCE, "bucket/key", None)
    with pytest.raises(ValueError):
        AssetLocation(AssetLocationKind.REMOTE_REFERENCE, "https://x", Path("/tmp"))


def test_native_asset_validation_and_freezing():
    a = asset(
        asset_kind=AssetKind.FILE,
        media_type="application/octet-stream",
        size_bytes=0,
        integrity=AssetIntegrity("sha256", "abc"),
    )
    assert a
    with pytest.raises(Exception):
        asset(asset_id="bad id")
    with pytest.raises(Exception):
        asset(asset_kind="file")
    with pytest.raises(TypeError):
        asset(asset_kind="file")
    with pytest.raises(ValueError):
        asset(size_bytes=-1)
    with pytest.raises(ValueError):
        asset(size_bytes=True)
    with pytest.raises(ValueError):
        asset(media_type=" ")


def test_no_io_and_import_boundary():
    import ast
    from pathlib import Path

    tree = ast.parse(Path("src/insarforge/products/assets.py").read_text())
    imports = [n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
    assert imports == [
        "__future__",
        "dataclasses",
        "enum",
        "pathlib",
        "urllib.parse",
        "insarforge.contracts.values",
    ]
