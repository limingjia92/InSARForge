from pathlib import Path

import pytest

from insarforge.products.assets import (
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
        role="native_output",
        kind=AssetKind.FILE,
        location=loc(),
        media_type=None,
        size_bytes=None,
        checksum_algorithm=None,
        checksum=None,
        extensions={},
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
        kind=AssetKind.DIRECTORY,
        media_type="application/octet-stream",
        size_bytes=0,
        checksum_algorithm="sha256",
        checksum="abc",
    )
    assert a
    with pytest.raises(Exception):
        asset(asset_id="bad id")
    with pytest.raises(Exception):
        asset(role="bad role")
    with pytest.raises(TypeError):
        asset(kind="file")
    with pytest.raises(ValueError):
        asset(size_bytes=-1)
    with pytest.raises(ValueError):
        asset(size_bytes=True)
    with pytest.raises(ValueError):
        asset(media_type=" ")
    with pytest.raises(ValueError):
        asset(checksum_algorithm="sha256")
    with pytest.raises(ValueError):
        asset(checksum="abc")
    source = {"nested": [1, {"x": 2}]}
    frozen = asset(extensions=source)
    source["nested"].append(3)
    assert len(frozen.extensions["nested"]) == 2
    with pytest.raises(TypeError):
        frozen.extensions["nested"] = ()
    with pytest.raises(Exception):
        frozen.asset_id = "x"


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
