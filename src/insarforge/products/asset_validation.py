from __future__ import annotations

import hashlib
from pathlib import Path

from insarforge.products.assets import AssetKind, AssetLocationKind
from insarforge.products.models import Product, ProductDraft
from insarforge.products.validation import (
    ProductValidationReport,
    ValidationIssue,
    ValidationIssueKind,
)


def _issue(kind, code, location, details=None):
    return ValidationIssue(kind, code, location, details or {})


def _path(location):
    value = Path(location.value)
    return value if value.is_absolute() else location.anchor / value


def validate_product_assets(product: ProductDraft | Product) -> ProductValidationReport:
    if not isinstance(product, (ProductDraft, Product)):
        raise TypeError("product")
    issues = []
    for asset in product.assets:
        location = f"assets[{asset.asset_id}]"
        if asset.location.kind is AssetLocationKind.URI:
            issues.append(
                _issue(
                    ValidationIssueKind.UNVERIFIED,
                    "validation:uri-asset-unverified",
                    location,
                )
            )
            continue
        path = _path(asset.location)
        try:
            info = path.stat()
        except FileNotFoundError:
            issues.append(
                _issue(
                    ValidationIssueKind.ERROR,
                    "validation:missing-local-asset",
                    location,
                )
            )
            continue
        except OSError:
            issues.append(
                _issue(
                    ValidationIssueKind.UNVERIFIED,
                    "validation:asset-io-unverified",
                    location,
                )
            )
            continue
        actual_kind = (
            AssetKind.FILE
            if path.is_file()
            else AssetKind.DIRECTORY
            if path.is_dir()
            else None
        )
        if actual_kind is not asset.kind:
            issues.append(
                _issue(
                    ValidationIssueKind.ERROR,
                    "validation:asset-kind-mismatch",
                    location,
                    {
                        "expected_kind": asset.kind.value,
                        "actual_kind": actual_kind.value if actual_kind else "other",
                    },
                )
            )
            continue
        if asset.kind is AssetKind.DIRECTORY:
            issues.append(
                _issue(
                    ValidationIssueKind.UNVERIFIED,
                    "validation:directory-content-unverified",
                    location,
                )
            )
            continue
        if asset.size_bytes is not None and info.st_size != asset.size_bytes:
            issues.append(
                _issue(
                    ValidationIssueKind.ERROR,
                    "validation:file-size-mismatch",
                    location,
                    {"expected_size": asset.size_bytes, "actual_size": info.st_size},
                )
            )
            continue
        if asset.checksum_algorithm is None:
            issues.append(
                _issue(
                    ValidationIssueKind.UNVERIFIED,
                    "validation:checksum-not-declared",
                    location,
                )
            )
            continue
        if asset.checksum_algorithm != "sha256":
            issues.append(
                _issue(
                    ValidationIssueKind.UNVERIFIED,
                    "validation:checksum-algorithm-unverified",
                    location,
                    {"checksum_algorithm": asset.checksum_algorithm},
                )
            )
            continue
        checksum = asset.checksum
        if (
            checksum is None
            or len(checksum) != 64
            or any(c not in "0123456789abcdefABCDEF" for c in checksum)
        ):
            issues.append(
                _issue(
                    ValidationIssueKind.ERROR,
                    "validation:invalid-sha256-checksum",
                    location,
                )
            )
            continue
        try:
            digest = hashlib.sha256()
            with path.open("rb") as stream:
                while chunk := stream.read(1024 * 1024):
                    digest.update(chunk)
        except OSError:
            issues.append(
                _issue(
                    ValidationIssueKind.UNVERIFIED,
                    "validation:asset-io-unverified",
                    location,
                )
            )
            continue
        if digest.hexdigest().lower() != checksum.lower():
            issues.append(
                _issue(
                    ValidationIssueKind.ERROR, "validation:checksum-mismatch", location
                )
            )
    return ProductValidationReport(tuple(issues))
