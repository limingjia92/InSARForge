"""Explicit local read-only content verification; never cache/index writes."""

import hashlib
import os
import stat
from collections.abc import Mapping
from contextlib import ExitStack
from pathlib import Path

from insarforge.contracts.errors import ContractError
from insarforge.contracts.fingerprints import FingerprintResult, is_digest, unresolved
from insarforge.core.fingerprints import digest_projection
from insarforge.products.assets import AssetKind, AssetLocationKind, NativeAsset
from insarforge.products.directory_manifest_serialization import (
    directory_member_manifest_from_bytes,
)
from insarforge.products.directory_validation import (
    _open_member,
    _open_root,
    validate_directory_members,
)

CODE_DOMAIN = b"insarforge.code.content.v1\0"
DIRECTORY_DOMAIN = b"insarforge.directory.content.v1\0"


def _file_bytes_digest(path: Path) -> tuple[str, int]:
    # Pin each directory descriptor; no ancestor replacement can redirect reads.
    if not path.is_absolute() or ".." in path.parts:
        raise OSError("absolute unambiguous path required")
    if not hasattr(os, "O_NOFOLLOW"):
        raise OSError("safe no-follow reads unsupported")
    with ExitStack() as stack:
        root_fd = stack.enter_context(_open_root(path.parent))
        stream = stack.enter_context(_open_member(root_fd, path.name))
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise OSError("not a single ordinary file")
        digest = hashlib.sha256()
        size = 0
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            size += len(block)
            digest.update(block)
        after = os.fstat(stream.fileno())

        def identity(s):
            return (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)

        if identity(before) != identity(after) or size != before.st_size:
            raise OSError("changed during read")
    return digest.hexdigest(), size


def code_content_identity(files: Mapping[str, Path]) -> FingerprintResult:
    """Hash explicit logical-name -> absolute-file scope, independent of checkout."""
    if not isinstance(files, Mapping) or not files:
        return unresolved("CODE_SCOPE_MISSING")
    projection = {}
    for name, path in files.items():
        if (
            type(name) is not str
            or not name
            or name.startswith("/")
            or chr(92) in name
            or any(p in ("", ".", "..") for p in name.split("/"))
        ):
            raise ContractError("CODE_LOGICAL_NAME")
        try:
            projection[name] = _file_bytes_digest(Path(path))[0]
        except (OSError, TypeError, ValueError):
            return unresolved("CODE_CONTENT_UNVERIFIED")
    return digest_projection(CODE_DOMAIN, projection)


def engine_code_identity(package_root: Path) -> FingerprintResult:
    """Cover engine/common contract/Product/provenance code and resources only.

    Missing/opaque trees fail closed. Plugins/tests/docs are outside this scope.
    A bytecode-only or partial installation has no verified source identity.
    """
    root = Path(package_root)
    files = {}
    try:
        if not root.is_absolute() or not (root / "__init__.py").is_file():
            return unresolved("ENGINE_SOURCE_MISSING")
        files["__init__.py"] = root / "__init__.py"
        for name in ("core", "contracts", "products", "provenance"):
            base = root / name
            if name != "provenance" and not base.is_dir():
                return unresolved("ENGINE_SOURCE_MISSING")
            if not base.exists():
                continue

            def error(_):
                raise OSError("opaque code tree")

            for directory, dirs, names in os.walk(
                base, followlinks=False, onerror=error
            ):
                parent = Path(directory)
                if parent.is_symlink() or any((parent / d).is_symlink() for d in dirs):
                    return unresolved("ENGINE_SOURCE_UNVERIFIED")
                dirs[:] = sorted(d for d in dirs if d != "__pycache__")
                for entry in sorted(names):
                    p = parent / entry
                    if p.suffix in (".pyc", ".pyo"):
                        continue
                    files[p.relative_to(root).as_posix()] = p
        return code_content_identity(files)
    except OSError:
        return unresolved("ENGINE_SOURCE_UNVERIFIED")


def verify_asset_content(
    asset: NativeAsset, *, member_manifest_bytes: bytes | None = None
) -> FingerprintResult:
    """Verify current explicit local asset; never fetch a manifest locator."""
    if type(asset) is not NativeAsset:
        raise ContractError("ASSET_TYPE")
    if asset.location.kind is AssetLocationKind.REMOTE_REFERENCE:
        return unresolved("ASSET_REMOTE_UNVERIFIED")
    path = (
        asset.location.anchor / asset.location.value
        if asset.location.kind is AssetLocationKind.MANIFEST_RELATIVE
        else Path(asset.location.value)
    )
    if asset.asset_kind is AssetKind.FILE:
        if (
            asset.integrity is None
            or asset.integrity.algorithm != "sha256"
            or not is_digest(asset.integrity.digest)
        ):
            return unresolved("ASSET_IDENTITY_WEAK")
        try:
            digest, size = _file_bytes_digest(path)
        except OSError:
            return unresolved("ASSET_CONTENT_UNVERIFIED")
        if digest != asset.integrity.digest or (
            asset.size_bytes is not None and size != asset.size_bytes
        ):
            return unresolved("ASSET_CONTENT_MISMATCH")
        return FingerprintResult(digest, True)
    ref = asset.member_manifest_ref
    if (
        ref is None
        or type(member_manifest_bytes) is not bytes
        or not is_digest(ref.manifest_digest)
    ):
        return unresolved("DIRECTORY_MANIFEST_MISSING")
    if hashlib.sha256(member_manifest_bytes).hexdigest() != ref.manifest_digest:
        return unresolved("DIRECTORY_MANIFEST_MISMATCH")
    try:
        manifest = directory_member_manifest_from_bytes(member_manifest_bytes)
    except (TypeError, ValueError, UnicodeError, RecursionError):
        raise ContractError("DIRECTORY_MANIFEST_INVALID") from None
    report = validate_directory_members(asset, manifest)
    if not report.is_fully_verified:
        return unresolved("DIRECTORY_CONTENT_UNVERIFIED")
    members = []
    for member in manifest.members:
        digest = None
        if member.member_kind is AssetKind.FILE:
            if (
                member.integrity is None
                or member.integrity.algorithm != "sha256"
                or not is_digest(member.integrity.digest)
            ):
                return unresolved("DIRECTORY_CONTENT_UNVERIFIED")
            digest = member.integrity.digest
        members.append(
            {
                "path": member.path,
                "kind": member.member_kind.value,
                "content_digest": digest,
            }
        )
    return digest_projection(
        DIRECTORY_DOMAIN, {"schema_version": 1, "members": members}
    )
