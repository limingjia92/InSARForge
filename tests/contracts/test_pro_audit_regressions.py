"""Boundary regressions for the independent Pro findings (01–04)."""

import hashlib
import os
from collections.abc import Mapping
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType

import pytest
from test_directory_validation import asset, file_member, manifest
from test_product_models import populated_product, sv

from insarforge.contracts.values import freeze_json
from insarforge.products import directory_validation
from insarforge.products.asset_validation import validate_product_assets
from insarforge.products.assets import (
    AssetIntegrity,
    AssetKind,
    AssetLocation,
    AssetLocationKind,
    NativeAsset,
)
from insarforge.products.digests import (
    product_content_digest,
    product_semantic_material,
)
from insarforge.products.models import ProductDraft
from insarforge.products.serialization import (
    canonical_json_bytes,
    product_to_manifest_bytes,
)


class MutableOrderText(str):
    def __new__(cls, text, direction):
        value = super().__new__(cls, text)
        value.direction = direction
        return value

    def __lt__(self, other):
        return str.__gt__(self, other) if self.direction[0] else str.__lt__(self, other)


class CustomInt(int):
    pass


class CustomFloat(float):
    pass


@pytest.mark.parametrize("boundary", ["freezer", "semantic", "extensions", "codec"])
@pytest.mark.parametrize("position", ["key", "value"])
def test_f01_subclass_rejected_before_retention(boundary, position):
    text = MutableOrderText("vendor:a", [False])
    payload = {text: 1} if position == "key" else {"vendor:a": text}
    with pytest.raises(TypeError):
        if boundary == "freezer":
            freeze_json(payload)
        elif boundary == "semantic":
            sv(MappingProxyType(payload))
        elif boundary == "extensions":
            replace(populated_product(), extensions=payload)
        else:
            canonical_json_bytes(payload)


@pytest.mark.parametrize("value", [CustomInt(1), CustomFloat(1.0)])
@pytest.mark.parametrize("boundary", [freeze_json, sv, canonical_json_bytes])
def test_f01_numeric_subclasses_rejected(value, boundary):
    with pytest.raises(TypeError):
        boundary(value)


@pytest.mark.parametrize("slot", ["semantic_metadata", "extensions"])
def test_f01_mutable_comparator_cannot_change_accepted_product(slot):
    direction = [False]
    caller = {
        MutableOrderText("vendor:a", direction): 1,
        MutableOrderText("vendor:b", direction): 2,
    }
    # Rejecting this unsafe domain is the explicit admission policy.
    with pytest.raises(TypeError):
        change = (
            {"field": sv(MappingProxyType(caller))}
            if slot == "semantic_metadata"
            else caller
        )
        replace(populated_product(), **{slot: change})


def test_f01_builtin_snapshot_bytes_remain_stable():
    caller = {"z": [1, 1.0, True, None], "a": "测试"}
    frozen = freeze_json(caller)
    expected = '{"a":"测试","z":[1,1.0,true,null]}'.encode()
    assert canonical_json_bytes(frozen) == expected
    product = replace(populated_product(), semantic_metadata={"field": sv(frozen)})
    before = product_to_manifest_bytes(product)
    digest = product_content_digest(product, asset_content_identities={"asset:x": "id"})
    caller["z"].append(99)
    assert canonical_json_bytes(frozen) == expected
    assert product_to_manifest_bytes(product) == before
    assert (
        product_content_digest(product, asset_content_identities={"asset:x": "id"})
        == digest
    )


def test_f02_public_material_is_deeply_frozen_and_composable():
    product = populated_product()
    material = product_semantic_material(
        product, asset_content_identities={"asset:x": "id"}
    )
    assert material is not None
    with pytest.raises(TypeError):
        material["new"] = 1
    with pytest.raises(TypeError):
        material["product"]["product_kind"] = "changed"
    with pytest.raises(TypeError):
        material["product"]["assets"][0] = {}

    def check(value):
        if isinstance(value, Mapping):
            assert isinstance(value, MappingProxyType)
            for child in value.values():
                check(child)
        elif isinstance(value, (list, tuple)):
            assert type(value) is tuple
            for child in value:
                check(child)

    check(material)
    assert sv(material).value == material
    assert canonical_json_bytes(material) == canonical_json_bytes(freeze_json(material))


@pytest.mark.parametrize("relative", [False, True])
def test_f03_root_ancestor_symlink_never_traversed(tmp_path, monkeypatch, relative):
    outside = tmp_path / "outside"
    (outside / "data").mkdir(parents=True)
    (outside / "data" / "f").write_bytes(b"x")
    anchor = tmp_path / "anchor"
    anchor.mkdir()
    (anchor / "link").symlink_to(outside, target_is_directory=True)
    candidate = asset(anchor / "link" / "data")
    if relative:
        candidate = replace(
            candidate,
            location=AssetLocation(
                AssetLocationKind.MANIFEST_RELATIVE, "link/data", anchor
            ),
        )
    original = os.scandir
    visited = []

    def scan(fd):
        visited.append(os.fstat(fd).st_ino)
        return original(fd)

    monkeypatch.setattr(os, "scandir", scan)
    report = directory_validation.validate_directory_members(
        candidate, manifest(file_member())
    )
    assert report.issues and not report.is_fully_verified
    assert visited == []


def test_f03_opened_hardlink_rechecked(tmp_path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    (root / "f").write_bytes(b"x")
    outside = tmp_path / "other"
    outside.write_bytes(b"x")
    original = directory_validation._open_member

    @contextmanager
    def swapped(fd, path):
        (root / "f").unlink()
        os.link(outside, root / "f")
        with original(fd, path) as stream:
            yield stream

    monkeypatch.setattr(directory_validation, "_open_member", swapped)
    report = directory_validation.validate_directory_members(
        asset(root), manifest(file_member())
    )
    assert not report.is_fully_verified
    assert [i.code for i in report.issues] == [
        "validation:directory-hardlink-unverified"
    ]


def file_product(path, size, data):
    native = NativeAsset(
        "file",
        AssetKind.FILE,
        AssetLocation(AssetLocationKind.ABSOLUTE_LOCAL, str(path), None),
        None,
        size,
        AssetIntegrity("sha256", hashlib.sha256(data).hexdigest()),
        None,
    )
    return ProductDraft("generic", "profile", 1, (native,), (), (), (), {}, {})


def test_f04_size_and_hash_describe_same_open_file(tmp_path, monkeypatch):
    path = tmp_path / "f"
    path.write_bytes(b"x")
    product = file_product(path, 1, b"long")
    original = Path.open

    def swapped(self, mode="r", *args, **kwargs):
        if self == path and mode == "rb":
            path.write_bytes(b"long")
        return original(self, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", swapped)
    report = validate_product_assets(product)
    assert not report.is_fully_verified
    assert [i.code for i in report.issues] == ["validation:file-size-mismatch"]
    assert report.errors[0].details["actual_size"] == 4


@pytest.mark.parametrize("case", ["bounded", "change", "read_error", "fstat_error"])
def test_f04_read_observations_and_errors(tmp_path, monkeypatch, case):
    path = tmp_path / "f"
    data = b"x" * (2 * 1024 * 1024 + 7)
    path.write_bytes(data)
    product = file_product(path, len(data), data)
    original = Path.open
    sizes = []

    class Reader:
        def __init__(self, stream):
            self.stream = stream

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.stream.close()

        def fileno(self):
            return self.stream.fileno()

        def read(self, size):
            assert 0 < size <= 1024 * 1024
            sizes.append(size)
            if case == "read_error":
                raise OSError("injected read failure")
            chunk = self.stream.read(size)
            if case == "change" and not chunk:
                with original(path, "ab") as writer:
                    writer.write(b"changed after last read")
            return chunk

    def wrapped(self, mode="r", *args, **kwargs):
        stream = original(self, mode, *args, **kwargs)
        return Reader(stream) if self == path and mode == "rb" else stream

    monkeypatch.setattr(Path, "open", wrapped)
    if case == "fstat_error":

        def fail(fd):
            raise OSError("injected fstat failure")

        monkeypatch.setattr(os, "fstat", fail)
    report = validate_product_assets(product)
    if case == "bounded":
        assert report.is_fully_verified
        assert len(sizes) == 4
    else:
        assert report.is_valid and not report.is_fully_verified
        assert [i.code for i in report.issues] == ["validation:asset-io-unverified"]
