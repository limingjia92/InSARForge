"""S1 recognizable-secret rejection at existing record emission boundaries."""

import builtins
import io
import socket
from dataclasses import replace
from types import MappingProxyType

import pytest
from test_product_models import populated_product, reference_artifact, sv

from insarforge.contracts.errors import ContractError
from insarforge.contracts.values import ArtifactRef, freeze_json
from insarforge.products.assets import AssetIntegrity, AssetKind
from insarforge.products.digests import product_manifest_digest
from insarforge.products.directory_manifest import (
    DirectoryMember,
    DirectoryMemberManifest,
)
from insarforge.products.directory_manifest_serialization import (
    directory_member_manifest_from_bytes,
    directory_member_manifest_to_bytes,
    directory_member_manifest_to_value,
)
from insarforge.products.models import LineageEntry
from insarforge.products.semantics import SemanticStatus, SemanticValue
from insarforge.products.serialization import (
    canonical_json_bytes,
    product_from_manifest_bytes,
    product_to_manifest_bytes,
    product_to_manifest_value,
)

MARKER = "SYNTHETIC_REVIEW_VALUE_S1"
PRODUCT_EMITTERS = [
    product_to_manifest_value,
    product_to_manifest_bytes,
    product_manifest_digest,
]
# Phase-3 recognizable keys, plus its case/punctuation/percent-encoded regressions.
QUERY_KEYS = [
    "password",
    "passwd",
    "token",
    "accesstoken",
    "refreshtoken",
    "apikey",
    "secret",
    "clientsecret",
    "privatekey",
    "authorization",
    "cookie",
    "credentials",
    "username",
    "authentication",
    "ACCESS-TOKEN",
    "access%5Ftoken",
    "api%2Dkey",
    "client%5Fsecret",
    "private-key",
    # Additional forms already recognized by AssetLocation.
    "auth",
    "credential",
    "signature",
    "sig",
    "x-amz-signature",
    "x-amz-credential",
    "x-amz-security-token",
    "x-goog-signature",
    "x-goog-credential",
    "x-amz-algorithm",
    "x-amz-date",
    "x-amz-expires",
]


def assert_safe_rejection(emit, record):
    with pytest.raises(ContractError) as caught:
        emit(record)
    assert type(caught.value) is ContractError
    assert str(caught.value) == "PERSISTENCE_SECRET"
    assert MARKER not in repr(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


@pytest.mark.parametrize("emit", PRODUCT_EMITTERS)
@pytest.mark.parametrize("key", QUERY_KEYS)
def test_product_emitters_reject_recognized_credential_query_keys(emit, key):
    url = f"https://example.invalid/record?{key}={MARKER}"
    product = replace(
        populated_product(),
        extensions=MappingProxyType(
            {"synthetic:data": (MappingProxyType({"url": url}),)}
        ),
    )
    assert_safe_rejection(emit, product)
    # Rejection never redacts or rewrites the source scientific data.
    assert product.extensions["synthetic:data"][0]["url"] == url


@pytest.mark.parametrize("emit", PRODUCT_EMITTERS)
@pytest.mark.parametrize(
    "payload",
    [
        {"synthetic-access-token": MARKER},
        {"nested": [{"Client_Secret": MARKER}]},
        f"https://user:{MARKER}@example.invalid/record",
        f"diagnostic https://user:{MARKER}@example.invalid/record",
        f"-----BEGIN PRIVATE KEY----- {MARKER}",
        f"-----BEGIN RSA PRIVATE KEY----- {MARKER}",
        f"-----BEGIN ENCRYPTED PRIVATE KEY----- {MARKER}",
        f"https://example.invalid/record?field=1;access_token={MARKER}",
        "https://example.invalid/record?access_token=",
        f"https://example.invalid/record?X-AMZ-SIGNATURE={MARKER}",
        {f"https://user:{MARKER}@example.invalid/record": "synthetic:value"},
    ],
)
def test_product_emitters_reject_nested_keys_userinfo_and_private_key_markers(
    emit, payload
):
    product = replace(populated_product(), extensions={"synthetic:data": payload})
    assert_safe_rejection(emit, product)


@pytest.mark.parametrize("emit", PRODUCT_EMITTERS)
@pytest.mark.parametrize("surface", ["locator", "coordinate_reference", "integrity"])
def test_persistence_guard_covers_declared_strings_beyond_extensions(emit, surface):
    product = populated_product()
    url = f"https://example.invalid/record?access_token={MARKER}"
    if surface == "locator":
        product = replace(
            product,
            acquisition_refs=(
                ArtifactRef("synthetic:r", "synthetic:s", 1, None, "m", url),
            ),
        )
    elif surface == "coordinate_reference":
        geometry = product.geometries[0]
        product = replace(
            product,
            geometries=(
                replace(
                    geometry,
                    coordinate_reference=replace(
                        geometry.coordinate_reference, value=url
                    ),
                ),
            ),
        )
    else:
        product = replace(
            product,
            assets=(
                replace(
                    product.assets[0],
                    integrity=AssetIntegrity("synthetic:algorithm", url),
                ),
            ),
        )
    assert_safe_rejection(emit, product)


@pytest.mark.parametrize(
    "emit", [directory_member_manifest_to_value, directory_member_manifest_to_bytes]
)
@pytest.mark.parametrize(
    "value",
    [
        f"https://example.invalid/record?access%5Ftoken={MARKER}",
        f"https://user:{MARKER}@example.invalid/record",
        f"-----BEGIN PRIVATE KEY----- {MARKER}",
        f"https://example.invalid/record?x-amz-signature={MARKER}",
    ],
)
def test_directory_emitters_reject_recognized_secret_material(emit, value):
    manifest = DirectoryMemberManifest(
        1,
        (
            DirectoryMember(
                "synthetic-file",
                AssetKind.FILE,
                1,
                AssetIntegrity("synthetic:algo", value),
            ),
        ),
    )
    assert_safe_rejection(emit, manifest)
    assert manifest.members[0].integrity.digest == value


@pytest.mark.parametrize(
    "extensions",
    [
        {"test-owner:value": 7},
        {"test-owner:bare": [1, True, None, 1.0, "科学"]},
        {"synthetic:data": {"url": "https://example.invalid/record?field=value"}},
        {"test-owner:a/b": "opaque", "org.example:field": "safe"},
        {
            "test-owner:text": "ordinary diagnostic text; token is a word, not a credential URL"
        },
        {"test-owner:sig": "an ordinary mapping key outside URL-query rules"},
    ],
)
def test_safe_namespaced_values_remain_byte_stable(extensions):
    product = replace(populated_product(), extensions=extensions)
    data = product_to_manifest_bytes(product)
    assert canonical_json_bytes(product_to_manifest_value(product)) == data
    decoded = product_from_manifest_bytes(data)
    assert decoded == product
    assert product_to_manifest_bytes(decoded) == data
    assert product_manifest_digest(decoded) == product_manifest_digest(product)


def test_emitters_have_no_io_or_environment_discovery(monkeypatch):
    product = populated_product()
    unsafe = replace(
        product,
        extensions={"synthetic:data": f"https://example.invalid/?token={MARKER}"},
    )
    manifest = DirectoryMemberManifest(
        1, (DirectoryMember("synthetic-file", AssetKind.FILE, 1, None),)
    )
    expected = product_to_manifest_bytes(product)
    directory_bytes = directory_member_manifest_to_bytes(manifest)
    # Presence of a secret-like environment entry does not trigger discovery.
    monkeypatch.setenv("SYNTHETIC_TOKEN", MARKER)

    def forbidden(*args, **kwargs):
        pytest.fail("record emission must not access files or networks")

    with monkeypatch.context() as patch:
        patch.setattr(builtins, "open", forbidden)
        patch.setattr(io, "open", forbidden)
        patch.setattr(socket, "socket", forbidden)
        for emit in PRODUCT_EMITTERS:
            assert_safe_rejection(emit, unsafe)
        assert product_to_manifest_bytes(product) == expected
        assert directory_member_manifest_to_bytes(manifest) == directory_bytes
        assert directory_member_manifest_from_bytes(directory_bytes) == manifest


@pytest.mark.parametrize("emit", PRODUCT_EMITTERS)
@pytest.mark.parametrize(
    "surface",
    [
        "producer-plugin",
        "producer-version",
        "producer-implementation",
        "producer-execution-reason",
        "fingerprint",
        "output-port",
        "attempt-id",
        "lineage-role",
        "lineage-artifact",
        "acquisition",
        "metadata-value",
        "metadata-reason",
        "metadata-evidence",
        "provenance",
    ],
)
def test_final_v2_nested_fields_pass_through_existing_persistence_guard(emit, surface):
    product = populated_product()
    url = f"https://example.invalid/record?access_token={MARKER}"
    ref = reference_artifact(None)
    if surface == "producer-plugin":
        product = replace(
            product,
            producer=replace(
                product.producer, plugin=replace(product.producer.plugin, plugin_id=url)
            ),
        )
    elif surface == "producer-version":
        product = replace(
            product, producer=replace(product.producer, implementation_version=url)
        )
    elif surface == "producer-implementation":
        product = replace(
            product,
            producer=replace(product.producer, implementation_identity_digest=sv(url)),
        )
    elif surface == "producer-execution-reason":
        identity = SemanticValue(SemanticStatus.UNKNOWN, None, url, ())
        product = replace(
            product,
            producer=replace(product.producer, execution_identity_digest=identity),
        )
    elif surface in {"fingerprint", "output-port", "attempt-id"}:
        field = {
            "fingerprint": "task_fingerprint",
            "output-port": "output_port",
            "attempt-id": "attempt_id",
        }[surface]
        product = replace(
            product,
            produced_by=replace(
                product.produced_by,
                **{field: sv(url) if surface == "fingerprint" else url},
            ),
        )
    elif surface == "lineage-role":
        product = replace(product, lineage=(LineageEntry(url, ref),))
    elif surface == "lineage-artifact":
        product = replace(
            product,
            lineage=(LineageEntry("synthetic:role", replace(ref, locator=url)),),
        )
    elif surface == "acquisition":
        product = replace(product, acquisition_refs=(replace(ref, locator=url),))
    elif surface == "metadata-value":
        product = replace(
            product,
            semantic_metadata={"quality": sv(freeze_json({"nested": [{"url": url}]}))},
        )
    elif surface == "metadata-reason":
        product = replace(
            product,
            semantic_metadata={
                "quality": SemanticValue(SemanticStatus.UNKNOWN, None, url, ())
            },
        )
    elif surface == "metadata-evidence":
        product = replace(
            product,
            semantic_metadata={
                "quality": SemanticValue(
                    SemanticStatus.UNKNOWN,
                    None,
                    "synthetic:reason",
                    (replace(ref, locator=url),),
                )
            },
        )
    else:
        product = replace(product, provenance_ref=url)
    assert_safe_rejection(emit, product)


def test_safe_final_v2_metadata_and_envelope_roundtrip_without_redaction():
    product = replace(
        populated_product(),
        semantic_metadata={
            "quality": sv(
                freeze_json(
                    {"text": "token is an ordinary word", "values": [None, 1, "科学"]}
                )
            )
        },
        acquisition_refs=(reference_artifact(None),),
        lineage=(LineageEntry("role:synthetic", reference_artifact(None)),),
    )
    value = product_to_manifest_value(product)
    assert "product" not in value
    assert value["schema_id"] == "insarforge:product" and value["schema_version"] == 2
    data = product_to_manifest_bytes(product)
    assert product_from_manifest_bytes(data) == product
    assert product_to_manifest_bytes(product_from_manifest_bytes(data)) == data
