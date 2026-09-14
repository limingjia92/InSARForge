import hashlib

from insarforge.products.digests import (
    PRODUCT_CONTENT_DIGEST_DOMAIN_TAG,
    sha256_hex,
)


def test_sha256():
    assert sha256_hex(b"abc") == hashlib.sha256(b"abc").hexdigest()


def test_domain_constant():
    assert (
        PRODUCT_CONTENT_DIGEST_DOMAIN_TAG == b"insarforge:product-content-digest:v1\x00"
    )
