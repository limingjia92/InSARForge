# Fault injection targets the individual filesystem stages, never blanket errors.
import hashlib
import inspect
import os
import socket
from contextlib import contextmanager
from pathlib import Path

import pytest

from insarforge.contracts.values import ArtifactRef
from insarforge.products import directory_validation as verifier
from insarforge.products.asset_validation import validate_product_assets
from insarforge.products.assets import (
    AssetIntegrity,
    AssetKind,
    AssetLocation,
    AssetLocationKind,
    NativeAsset,
)
from insarforge.products.directory_manifest import (
    DirectoryMember,
    DirectoryMemberManifest,
)
from insarforge.products.directory_validation import validate_directory_members
from insarforge.products.models import ProductDraft
from insarforge.products.validation import ProductValidationReport, ValidationIssueKind


def asset(root, kind=AssetKind.DIRECTORY, ref=None):
    return NativeAsset(
        "a",
        kind,
        AssetLocation(AssetLocationKind.ABSOLUTE_LOCAL, str(root), None),
        None,
        None,
        None,
        ref,
    )


def test_api_and_empty(tmp_path):
    m = DirectoryMemberManifest(1, ())
    assert validate_directory_members(asset(tmp_path), m).is_fully_verified
    with pytest.raises(TypeError):
        validate_directory_members(object(), m)
    with pytest.raises(TypeError):
        validate_directory_members(asset(tmp_path), object())
    with pytest.raises(ValueError):
        validate_directory_members(asset(tmp_path, AssetKind.FILE), m)


def test_nested_and_hash(tmp_path):
    (tmp_path / "d").mkdir()
    p = tmp_path / "d" / "f"
    p.write_text("x")
    d = hashlib.sha256(b"x").hexdigest()
    m = DirectoryMemberManifest(
        1,
        (
            DirectoryMember("d", AssetKind.DIRECTORY, None, None),
            DirectoryMember("d/f", AssetKind.FILE, 1, AssetIntegrity("sha256", d)),
        ),
    )
    r = validate_directory_members(asset(tmp_path), m)
    assert r.is_valid and r.is_fully_verified


def test_mismatches(tmp_path):
    (tmp_path / "x").write_text("xx")
    m = DirectoryMemberManifest(1, (DirectoryMember("y", AssetKind.FILE, None, None),))
    codes = [i.code for i in validate_directory_members(asset(tmp_path), m).issues]
    assert (
        "validation:directory-member-missing" in codes
        and "validation:directory-member-unexpected" in codes
    )


def test_remote(tmp_path):
    loc = AssetLocation(AssetLocationKind.REMOTE_REFERENCE, "https://x", None)
    a = NativeAsset("a", AssetKind.DIRECTORY, loc, None, None, None, None)
    assert (
        validate_directory_members(a, DirectoryMemberManifest(1, ())).issues[0].code
        == "validation:directory-remote-unverified"
    )


GOOD = AssetIntegrity("sha256", hashlib.sha256(b"x").hexdigest())


def file_member(path="f", size=1, integrity=GOOD):
    return DirectoryMember(path, AssetKind.FILE, size, integrity)


def manifest(*members):
    return DirectoryMemberManifest(1, tuple(sorted(members, key=lambda m: m.path)))


def pairs(report):
    return [(i.code, i.location) for i in report.issues]


def expected_pairs(*items):
    return [("validation:directory-" + code, path) for code, path in items]


def assert_only_io(report, location):
    assert pairs(report) == expected_pairs(("io-unverified", location))
    assert report.issues[0].kind is ValidationIssueKind.UNVERIFIED
    assert report.is_valid and not report.is_fully_verified


def forbidden(*args, **kwargs):
    raise AssertionError("unexpected filesystem/content access")


def test_public_annotations():
    sig = inspect.signature(validate_directory_members)
    assert list(sig.parameters) == ["asset", "manifest"]
    assert sig.parameters["asset"].annotation is NativeAsset
    assert sig.parameters["manifest"].annotation is DirectoryMemberManifest
    assert sig.return_annotation is ProductValidationReport
    assert all(p.default is inspect.Parameter.empty for p in sig.parameters.values())


@pytest.mark.parametrize("case", ["missing", "file", "symlink", "io", "open_io"])
def test_root_terminal(tmp_path, monkeypatch, case):
    root = tmp_path / "root"
    code = "root-kind-mismatch"
    if case == "file":
        root.write_bytes(b"x")
    elif case == "symlink":
        root.symlink_to(tmp_path, target_is_directory=True)
    elif case == "missing":
        code = "root-missing"
    else:
        root.mkdir()
        code = "io-unverified"

        def fail(*args, **kwargs):
            raise PermissionError("root denied")

        if case == "io":
            monkeypatch.setattr(Path, "lstat", fail)
        else:
            monkeypatch.setattr(verifier, "_open_directory", fail)
    monkeypatch.setattr(os, "scandir", forbidden)
    report = validate_directory_members(asset(root), manifest(file_member()))
    assert pairs(report) == expected_pairs((code, str(root)))
    assert report.is_valid == (code == "io-unverified")
    assert not report.is_fully_verified


def test_remote_no_local_or_network_access(monkeypatch):
    monkeypatch.setattr(Path, "lstat", forbidden)
    monkeypatch.setattr(os, "scandir", forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)
    loc = AssetLocation(
        AssetLocationKind.REMOTE_REFERENCE, "https://example.test/root", None
    )
    a = NativeAsset("a", AssetKind.DIRECTORY, loc, None, None, None, None)
    r = validate_directory_members(a, manifest(file_member()))
    assert pairs(r) == expected_pairs(("remote-unverified", loc.value))
    assert r.is_valid and not r.is_fully_verified


@pytest.mark.parametrize("case", ["missing", "kind"])
def test_missing_and_kind_suppress_content(tmp_path, monkeypatch, case):
    if case == "kind":
        (tmp_path / "f").mkdir()
    monkeypatch.setattr(verifier, "_open_member", forbidden)
    r = validate_directory_members(asset(tmp_path), manifest(file_member(size=999)))
    code = "member-missing" if case == "missing" else "member-kind-mismatch"
    assert pairs(r) == expected_pairs((code, "f"))
    assert not r.is_valid and not r.is_fully_verified


@pytest.mark.parametrize("error", [OSError, PermissionError, FileNotFoundError])
def test_member_classification_io(tmp_path, monkeypatch, error):
    (tmp_path / "f").write_bytes(b"x")
    original = os.stat

    def fail(path, *args, **kwargs):
        if path == "f":
            assert kwargs["follow_symlinks"] is False
            raise error("classification uncertain")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(os, "stat", fail)
    monkeypatch.setattr(verifier, "_open_member", forbidden)
    r = validate_directory_members(asset(tmp_path), manifest(file_member(size=999)))
    assert_only_io(r, "f")


@pytest.mark.parametrize("subtree", [False, True])
def test_enumeration_io_suppresses_missing(tmp_path, monkeypatch, subtree):
    (tmp_path / "d").mkdir()
    (tmp_path / "z").write_bytes(b"x")
    inode = (tmp_path / "d" if subtree else tmp_path).stat().st_ino
    original = os.scandir

    def fail(fd):
        if os.fstat(fd).st_ino == inode:
            raise PermissionError("enumeration denied")
        return original(fd)

    monkeypatch.setattr(os, "scandir", fail)
    r = validate_directory_members(
        asset(tmp_path),
        manifest(
            DirectoryMember("d", AssetKind.DIRECTORY, None, None),
            file_member("d/unknown"),
            file_member("z", size=9),
            file_member("absent"),
        ),
    )
    if subtree:
        assert pairs(r) == expected_pairs(
            ("member-missing", "absent"),
            ("io-unverified", "d"),
            ("member-size-mismatch", "z"),
        )
    else:
        assert_only_io(r, ".")


def test_iteration_failure_retains_observed_unexpected(tmp_path, monkeypatch):
    (tmp_path / "observed").write_bytes(b"x")
    original = os.scandir

    @contextmanager
    def partial(fd):
        with original(fd) as entries:
            first = next(entries)

            def iterate():
                yield first
                raise OSError("iteration interrupted")

            yield iterate()

    monkeypatch.setattr(os, "scandir", partial)
    r = validate_directory_members(asset(tmp_path), manifest(file_member("unknown")))
    assert pairs(r) == expected_pairs(
        ("io-unverified", "."), ("member-unexpected", "observed")
    )


@pytest.mark.parametrize("stage", ["open", "read", "fstat"])
def test_file_io_suppresses_content(tmp_path, monkeypatch, stage):
    (tmp_path / "f").write_bytes(b"x")
    if stage == "open":
        original = os.open

        def fail(path, flags, *args, **kwargs):
            if path == "f":
                raise PermissionError("open denied")
            return original(path, flags, *args, **kwargs)

        monkeypatch.setattr(os, "open", fail)
    elif stage == "fstat":
        monkeypatch.setattr(
            os, "fstat", lambda fd: (_ for _ in ()).throw(OSError("stat failed"))
        )
    else:
        original = os.fdopen

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
                raise OSError("read failed")

        monkeypatch.setattr(os, "fdopen", lambda *a, **kw: Reader(original(*a, **kw)))
    assert_only_io(
        validate_directory_members(
            asset(tmp_path),
            manifest(
                file_member(size=999, integrity=AssetIntegrity("sha256", "0" * 64))
            ),
        ),
        "f",
    )


@pytest.mark.parametrize("digest", ["bad", "g" * 64, "0" * 63, "0" * 65])
def test_malformed_sha256_never_opens(tmp_path, monkeypatch, digest):
    (tmp_path / "f").write_bytes(b"x")
    monkeypatch.setattr(verifier, "_open_member", forbidden)
    monkeypatch.setattr(hashlib, "sha256", forbidden)
    r = validate_directory_members(
        asset(tmp_path),
        manifest(file_member(integrity=AssetIntegrity("sha256", digest))),
    )
    assert pairs(r) == expected_pairs(("member-invalid-sha256", "f"))
    assert not r.is_valid and not r.is_fully_verified


@pytest.mark.parametrize("algorithm", [None, "md5", "SHA256"])
def test_unverified_integrity_semantics(tmp_path, monkeypatch, algorithm):
    (tmp_path / "f").write_bytes(b"x")
    integrity = None if algorithm is None else AssetIntegrity(algorithm, GOOD.digest)
    monkeypatch.setattr(hashlib, "sha256", forbidden)
    r = validate_directory_members(
        asset(tmp_path), manifest(file_member(integrity=integrity))
    )
    assert pairs(r) == expected_pairs(("member-integrity-unverified", "f"))
    assert r.is_valid and not r.is_fully_verified


@pytest.mark.parametrize("case", ["verified", "size", "hash", "unexpected"])
def test_content_report_semantics(tmp_path, case):
    (tmp_path / "f").write_bytes(b"x")
    m = manifest(
        file_member(
            size=2 if case == "size" else 1,
            integrity=AssetIntegrity("sha256", "0" * 64) if case == "hash" else GOOD,
        )
    )
    if case == "unexpected":
        m = manifest()
    r = validate_directory_members(asset(tmp_path), m)
    assert r.is_valid == (case == "verified")
    assert r.is_fully_verified == (case == "verified")
    assert pairs(r) == (
        []
        if case == "verified"
        else expected_pairs(
            (
                {
                    "size": "member-size-mismatch",
                    "hash": "member-integrity-mismatch",
                    "unexpected": "member-unexpected",
                }[case],
                "f",
            )
        )
    )
    assert set(vars(r)) == {"issues"}
    assert all(dict(i.details) == {} for i in r.issues)


@pytest.mark.parametrize("kind", ["symlink", "directory_symlink", "fifo", "hardlink"])
def test_ambiguity_semantics_and_no_special_reads(tmp_path, monkeypatch, kind):
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret").write_bytes(b"x")
    p = root / "f"
    if kind == "hardlink":
        os.link(outside / "secret", p)
        code = "hardlink-unverified"
    elif kind == "fifo":
        os.mkfifo(p)
        code = "special-file-unverified"
    else:
        p.symlink_to(outside if kind == "directory_symlink" else outside / "secret")
        code = "symlink-unverified"
    if kind != "hardlink":
        monkeypatch.setattr(verifier, "_open_member", forbidden)
    original = os.scandir
    seen = []

    def scan(fd):
        seen.append(os.fstat(fd).st_ino)
        assert os.fstat(fd).st_ino != outside.stat().st_ino
        return original(fd)

    monkeypatch.setattr(os, "scandir", scan)
    m = manifest(file_member())
    if kind == "directory_symlink":
        m = manifest(
            DirectoryMember("f", AssetKind.DIRECTORY, None, None),
            file_member("f/secret"),
        )
    r = validate_directory_members(asset(root), m)
    assert pairs(r) == expected_pairs((code, "f"))
    assert r.is_valid and not r.is_fully_verified
    assert len(seen) == 1


@pytest.mark.parametrize("replacement", ["symlink", "fifo"])
def test_file_replacement_race(tmp_path, monkeypatch, replacement):
    root = tmp_path / "root"
    root.mkdir()
    (root / "f").write_bytes(b"x")
    outside = tmp_path / "secret"
    outside.write_bytes(b"outside target must not be read")
    original = os.open
    attempted = []

    def replace(path, flags, *args, **kwargs):
        if path == "f":
            attempted.append(path)
            assert flags & os.O_NOFOLLOW
            assert kwargs["dir_fd"] is not None
            (root / "f").unlink()
            if replacement == "symlink":
                (root / "f").symlink_to(outside)
            else:
                os.mkfifo(root / "f")
        return original(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", replace)
    monkeypatch.setattr(os, "fdopen", forbidden)
    assert_only_io(
        validate_directory_members(asset(root), manifest(file_member())), "f"
    )
    assert attempted == ["f"]


@pytest.mark.parametrize("stage", ["traversal", "content"])
def test_directory_replacement_race(tmp_path, monkeypatch, stage):
    root = tmp_path / "root"
    root.mkdir()
    (root / "d").mkdir()
    (root / "d" / "f").write_bytes(b"x")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "f").write_bytes(b"secret")
    original = os.open
    calls = 0

    def replace(path, flags, *args, **kwargs):
        nonlocal calls
        if path == "d":
            calls += 1
            assert flags & os.O_NOFOLLOW and flags & os.O_DIRECTORY
            if calls == (1 if stage == "traversal" else 2):
                (root / "d").rename(root / "old")
                (root / "d").symlink_to(outside, target_is_directory=True)
        return original(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", replace)
    monkeypatch.setattr(os, "fdopen", forbidden)
    r = validate_directory_members(
        asset(root),
        manifest(
            DirectoryMember("d", AssetKind.DIRECTORY, None, None), file_member("d/f")
        ),
    )
    assert_only_io(r, "d" if stage == "traversal" else "d/f")


def test_bounded_reads_and_uppercase_digest(tmp_path, monkeypatch):
    data = b"x" * (2 * 1024 * 1024 + 7)
    (tmp_path / "f").write_bytes(data)
    original = os.fdopen
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
            return self.stream.read(size)

    monkeypatch.setattr(os, "fdopen", lambda *a, **kw: Reader(original(*a, **kw)))
    r = validate_directory_members(
        asset(tmp_path),
        manifest(
            file_member(
                size=len(data),
                integrity=AssetIntegrity(
                    "sha256", hashlib.sha256(data).hexdigest().upper()
                ),
            )
        ),
    )
    assert r.is_valid and r.is_fully_verified
    assert len(sizes) == 4


def test_relative_anchor_hidden_recursive_and_cwd(tmp_path, monkeypatch):
    root = tmp_path / "root"
    (root / ".hidden").mkdir(parents=True)
    (root / ".hidden" / "f").write_bytes(b"x")
    (root / "empty").mkdir()
    m = manifest(
        DirectoryMember(".hidden", AssetKind.DIRECTORY, None, None),
        file_member(".hidden/f"),
        DirectoryMember("empty", AssetKind.DIRECTORY, None, None),
    )
    a = NativeAsset(
        "a",
        AssetKind.DIRECTORY,
        AssetLocation(AssetLocationKind.MANIFEST_RELATIVE, "root", tmp_path),
        None,
        None,
        None,
        None,
    )
    monkeypatch.chdir(tmp_path.parent)
    assert validate_directory_members(a, m).is_fully_verified
    assert validate_directory_members(asset(root), m).is_fully_verified


@pytest.mark.parametrize(
    "schema,version", [(verifier.SID, 1), ("other:schema", 1), (verifier.SID, 2)]
)
def test_reference_linkage_without_dereference(tmp_path, monkeypatch, schema, version):
    ref = ArtifactRef(
        "record", schema, version, None, "digest", "https://invalid.test/not-fetched"
    )
    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(verifier, "_open_member", forbidden)
    r = validate_directory_members(asset(tmp_path, ref=ref), manifest())
    want = []
    if schema != verifier.SID:
        want = expected_pairs(("manifest-schema-mismatch", "member_manifest_ref"))
    if version != 1:
        want = expected_pairs(("manifest-version-mismatch", "member_manifest_ref"))
    assert pairs(r) == want


def test_ordinary_validator_separation(tmp_path, monkeypatch):
    ref = ArtifactRef("record", verifier.SID, 1, None, "digest", "missing-manifest")
    a = asset(tmp_path, ref=ref)
    draft = ProductDraft(
        product_kind="generic",
        profile_id="profile",
        profile_version=1,
        assets=(a,),
        layers=(),
        geometries=(),
        acquisition_refs=(),
        semantic_metadata={},
        extensions={},
    )
    monkeypatch.setattr(verifier, "validate_directory_members", forbidden)
    monkeypatch.setattr(os, "scandir", forbidden)
    r = validate_product_assets(draft)
    assert pairs(r) == [("validation:directory-content-unverified", "assets[a]")]
    assert r.is_valid and not r.is_fully_verified


def test_exact_issue_order_independent_of_creation_and_traversal(tmp_path, monkeypatch):
    original = os.scandir

    @contextmanager
    def scan(fd):
        with original(fd) as entries:
            yield iter(sorted(entries, key=lambda e: e.name, reverse=reverse_scan))

    monkeypatch.setattr(os, "scandir", scan)
    expected = expected_pairs(
        ("manifest-schema-mismatch", "member_manifest_ref"),
        ("symlink-unverified", "a"),
        ("hardlink-unverified", "b"),
        ("member-size-mismatch", "b"),
        ("member-integrity-mismatch", "b"),
        ("member-kind-mismatch", "c"),
        ("member-missing", "d"),
        ("member-invalid-sha256", "e"),
        ("special-file-unverified", "f"),
        ("member-unexpected", "z"),
    )
    for reverse_create in (False, True):
        root = tmp_path / str(reverse_create)
        root.mkdir()
        source = tmp_path / (str(reverse_create) + "-source")
        source.write_bytes(b"x")
        actions = {
            "a": lambda: (root / "a").symlink_to(source),
            "b": lambda: os.link(source, root / "b"),
            "c": lambda: (root / "c").mkdir(),
            "e": lambda: (root / "e").write_bytes(b"x"),
            "f": lambda: os.mkfifo(root / "f"),
            "z": lambda: (root / "z").write_bytes(b"x"),
        }
        for name in sorted(actions, reverse=reverse_create):
            actions[name]()
        m = manifest(
            file_member("a"),
            file_member("b", size=2, integrity=AssetIntegrity("sha256", "0" * 64)),
            file_member("c"),
            file_member("d"),
            file_member("e", integrity=AssetIntegrity("sha256", "bad")),
            file_member("f"),
        )
        ref = ArtifactRef("record", "wrong:schema", 1, None, "digest", "unread")
        for reverse_scan in (False, True):
            assert (
                pairs(validate_directory_members(asset(root, ref=ref), m)) == expected
            )


def test_uncertain_directory_classification_suppresses_descendant_missing(
    tmp_path, monkeypatch
):
    (tmp_path / "d").mkdir()
    (tmp_path / "independent").write_bytes(b"x")
    original = os.stat

    def fail(path, *args, **kwargs):
        if path == "d":
            raise PermissionError("unknown kind")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(os, "stat", fail)
    r = validate_directory_members(
        asset(tmp_path),
        manifest(
            DirectoryMember("d", AssetKind.DIRECTORY, None, None),
            file_member("d/f"),
            file_member("independent"),
        ),
    )
    assert_only_io(r, "d")


def test_size_uses_opened_descriptor(tmp_path, monkeypatch):
    (tmp_path / "f").write_bytes(b"stale size")
    original = os.open

    def replace(path, flags, *args, **kwargs):
        if path == "f":
            (tmp_path / "f").unlink()
            (tmp_path / "f").write_bytes(b"x")
        return original(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", replace)
    r = validate_directory_members(asset(tmp_path), manifest(file_member()))
    assert r.is_valid and r.is_fully_verified


def test_no_follow_unavailable_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setattr(verifier, "_NOFOLLOW_SUPPORTED", False)
    monkeypatch.setattr(os, "scandir", forbidden)
    assert_only_io(
        validate_directory_members(asset(tmp_path), manifest(file_member())),
        str(tmp_path),
    )


def test_programming_error_not_swallowed(tmp_path, monkeypatch):
    (tmp_path / "f").write_bytes(b"x")

    def fail(*args, **kwargs):
        raise RuntimeError("programming error")

    monkeypatch.setattr(verifier, "_open_member", fail)
    with pytest.raises(RuntimeError, match="programming error"):
        validate_directory_members(asset(tmp_path), manifest(file_member()))
