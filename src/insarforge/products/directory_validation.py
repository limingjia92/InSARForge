import hashlib
import os
import stat
from contextlib import ExitStack, contextmanager
from pathlib import Path

from insarforge.products.assets import AssetKind, AssetLocationKind, NativeAsset
from insarforge.products.directory_manifest import DirectoryMemberManifest
from insarforge.products.validation import (
    ProductValidationReport,
    ValidationIssue,
    ValidationIssueKind,
)

SID = "insarforge:directory-member-manifest"
_NOFOLLOW_SUPPORTED = hasattr(os, "O_NOFOLLOW") and os.open in os.supports_dir_fd


class _RootKindMismatch(OSError):
    pass


@contextmanager
def _open_directory(path, *, dir_fd=None):
    # Fail closed on platforms without descriptor-relative no-follow support.
    if not _NOFOLLOW_SUPPORTED:
        raise OSError("no-follow directory access unavailable")
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=dir_fd)
    try:
        yield fd
    finally:
        os.close(fd)


@contextmanager
def _open_root(path):
    """Anchor at the filesystem root, then open every component no-follow.

    This includes the supplied manifest anchor: no ancestor symlink is trusted.
    Descriptors pin traversal, not a transactional filesystem snapshot.
    """
    if not path.is_absolute() or ".." in path.parts:
        raise OSError("directory root must have an unambiguous absolute path")
    with ExitStack() as stack:
        fd = stack.enter_context(_open_directory(path.anchor))
        for part in path.parts[1:-1]:
            fd = stack.enter_context(_open_directory(part, dir_fd=fd))
        name = path.parts[-1] if len(path.parts) > 1 else "."
        info = os.stat(name, dir_fd=fd, follow_symlinks=False)
        if not stat.S_ISDIR(info.st_mode):
            raise _RootKindMismatch("directory root kind mismatch")
        fd = stack.enter_context(_open_directory(name, dir_fd=fd))
        yield fd


@contextmanager
def _open_member(root_fd, path):
    # Open every parent relative to an anchored descriptor: replacement of any
    # component by a symlink must never redirect traversal outside the root.
    parent, separator, name = path.partition("/")
    if separator:
        with _open_directory(parent, dir_fd=root_fd) as child_fd:
            with _open_member(child_fd, name) as stream:
                yield stream
        return
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=root_fd)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise OSError("opened member is not a regular file")
        stream = os.fdopen(fd, "rb")
    except OSError:
        os.close(fd)
        raise
    with stream:
        yield stream


def _inventory(root_fd, add):
    actual = {}
    uncertain = set()
    opaque = set()

    def visit(fd, prefix):
        try:
            with os.scandir(fd) as entries:
                for entry in entries:
                    path = f"{prefix}/{entry.name}" if prefix else entry.name
                    try:
                        info = os.stat(entry.name, dir_fd=fd, follow_symlinks=False)
                    except OSError:
                        uncertain.add(path)
                        add(
                            ValidationIssueKind.UNVERIFIED,
                            "validation:directory-io-unverified",
                            path,
                        )
                        continue
                    if stat.S_ISLNK(info.st_mode):
                        opaque.add(path)
                        add(
                            ValidationIssueKind.UNVERIFIED,
                            "validation:directory-symlink-unverified",
                            path,
                        )
                    elif stat.S_ISDIR(info.st_mode):
                        actual[path] = ("directory", info)
                        try:
                            with _open_directory(entry.name, dir_fd=fd) as child:
                                visit(child, path)
                        except OSError:
                            uncertain.add(path)
                            add(
                                ValidationIssueKind.UNVERIFIED,
                                "validation:directory-io-unverified",
                                path,
                            )
                    elif stat.S_ISREG(info.st_mode):
                        actual[path] = ("file", info)
                        if info.st_nlink > 1:
                            add(
                                ValidationIssueKind.UNVERIFIED,
                                "validation:directory-hardlink-unverified",
                                path,
                            )
                    else:
                        opaque.add(path)
                        add(
                            ValidationIssueKind.UNVERIFIED,
                            "validation:directory-special-file-unverified",
                            path,
                        )
        except OSError:
            uncertain.add(prefix)
            add(
                ValidationIssueKind.UNVERIFIED,
                "validation:directory-io-unverified",
                prefix or ".",
            )

    visit(root_fd, "")
    # An uncertain prefix includes itself and every descendant. Empty prefix
    # means incomplete root enumeration; known independent entries remain usable.
    return actual, uncertain, opaque


def validate_directory_members(
    asset: NativeAsset,
    manifest: DirectoryMemberManifest,
) -> ProductValidationReport:
    if not isinstance(asset, NativeAsset):
        raise TypeError("asset")
    if not isinstance(manifest, DirectoryMemberManifest):
        raise TypeError("manifest")
    if asset.asset_kind is not AssetKind.DIRECTORY:
        raise ValueError("asset_kind")
    issues = []

    def add(k, c, loc):
        issues.append(ValidationIssue(k, c, loc, {}))

    ref = asset.member_manifest_ref
    if ref:
        if ref.schema_id != SID:
            add(
                ValidationIssueKind.ERROR,
                "validation:directory-manifest-schema-mismatch",
                "member_manifest_ref",
            )
        if ref.schema_version != 1:
            add(
                ValidationIssueKind.ERROR,
                "validation:directory-manifest-version-mismatch",
                "member_manifest_ref",
            )
    if asset.location.kind is AssetLocationKind.REMOTE_REFERENCE:
        add(
            ValidationIssueKind.UNVERIFIED,
            "validation:directory-remote-unverified",
            asset.location.value,
        )
        return ProductValidationReport(tuple(issues))
    root = (
        asset.location.anchor / asset.location.value
        if asset.location.kind is AssetLocationKind.MANIFEST_RELATIVE
        else Path(asset.location.value)
    )
    try:
        with _open_root(root) as root_fd:
            _validate_inventory(root_fd, manifest, add)
    except FileNotFoundError:
        add(ValidationIssueKind.ERROR, "validation:directory-root-missing", str(root))
    except _RootKindMismatch:
        add(
            ValidationIssueKind.ERROR,
            "validation:directory-root-kind-mismatch",
            str(root),
        )
    except OSError:
        add(
            ValidationIssueKind.UNVERIFIED,
            "validation:directory-io-unverified",
            str(root),
        )
    return ProductValidationReport(tuple(sorted(issues, key=_issue_key)))


def _validate_inventory(root_fd, manifest, add):
    actual, uncertain, opaque = _inventory(root_fd, add)
    expected = {m.path: m for m in manifest.members}
    for path in sorted(set(expected) | set(actual)):
        m = expected.get(path)
        a = actual.get(path)
        if any(path == prefix or path.startswith(prefix + "/") for prefix in opaque):
            continue
        if a is None:
            if any(
                not prefix or path == prefix or path.startswith(prefix + "/")
                for prefix in uncertain
            ):
                continue
            add(ValidationIssueKind.ERROR, "validation:directory-member-missing", path)
            continue
        if path in uncertain:
            continue
        if m is None:
            add(
                ValidationIssueKind.ERROR,
                "validation:directory-member-unexpected",
                path,
            )
            continue
        if a[0] != m.member_kind.value:
            add(
                ValidationIssueKind.ERROR,
                "validation:directory-member-kind-mismatch",
                path,
            )
            continue
        if a[0] == "file":
            invalid_sha256 = (
                m.integrity is not None
                and m.integrity.algorithm == "sha256"
                and (
                    len(m.integrity.digest) != 64
                    or any(
                        c not in "0123456789abcdefABCDEF" for c in m.integrity.digest
                    )
                )
            )
            if invalid_sha256:
                add(
                    ValidationIssueKind.ERROR,
                    "validation:directory-member-invalid-sha256",
                    path,
                )
                continue
            verify_hash = m.integrity is not None and m.integrity.algorithm == "sha256"
            if m.size_bytes is not None or verify_hash:
                try:
                    with _open_member(root_fd, path) as stream:
                        info = os.fstat(stream.fileno())
                        if info.st_nlink > 1 and a[1].st_nlink <= 1:
                            add(
                                ValidationIssueKind.UNVERIFIED,
                                "validation:directory-hardlink-unverified",
                                path,
                            )
                        h = hashlib.sha256() if verify_hash else None
                        if h is not None:
                            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                                h.update(chunk)
                    # Commit content findings only after all requested I/O succeeds.
                    if m.size_bytes is not None and info.st_size != m.size_bytes:
                        add(
                            ValidationIssueKind.ERROR,
                            "validation:directory-member-size-mismatch",
                            path,
                        )
                    if (
                        h is not None
                        and h.hexdigest().lower() != m.integrity.digest.lower()
                    ):
                        add(
                            ValidationIssueKind.ERROR,
                            "validation:directory-member-integrity-mismatch",
                            path,
                        )
                except OSError:
                    add(
                        ValidationIssueKind.UNVERIFIED,
                        "validation:directory-io-unverified",
                        path,
                    )
                    continue
            if m.integrity is None:
                add(
                    ValidationIssueKind.UNVERIFIED,
                    "validation:directory-member-integrity-unverified",
                    path,
                )
            elif m.integrity.algorithm != "sha256":
                add(
                    ValidationIssueKind.UNVERIFIED,
                    "validation:directory-member-integrity-unverified",
                    path,
                )


def _issue_key(issue):
    priority = {
        "symlink": 0,
        "special-file": 0,
        "hardlink": 0,
        "missing": 1,
        "unexpected": 1,
        "kind-mismatch": 1,
        "size-mismatch": 2,
        "invalid-sha256": 3,
        "integrity-mismatch": 3,
        "integrity-unverified": 3,
        "io-unverified": 4,
    }

    tail = issue.code.rsplit("directory-", 1)[-1]
    return (
        0
        if "manifest-" in issue.code
        or "root-" in issue.code
        or "remote-" in issue.code
        or issue.location == "."
        or Path(issue.location).is_absolute()
        else 1,
        issue.location,
        next((v for k, v in priority.items() if k in tail), 9),
    )
