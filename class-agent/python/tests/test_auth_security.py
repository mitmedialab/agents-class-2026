from __future__ import annotations

import base64

import pytest

from course_server.auth.security import (
    ACCESS_CODE_ENTROPY_BYTES,
    Argon2AccessCodeHasher,
    generate_access_code,
    generate_session_token,
    hash_session_token,
)


def test_access_codes_contain_at_least_128_bits_of_randomness() -> None:
    access_code = generate_access_code()
    encoded = access_code.removeprefix("ca-").replace("-", "").upper()
    padded = encoded + "=" * (-len(encoded) % 8)

    assert len(base64.b32decode(padded)) == ACCESS_CODE_ENTROPY_BYTES
    assert ACCESS_CODE_ENTROPY_BYTES >= 16
    assert access_code != generate_access_code()


def test_access_code_generator_rejects_weak_entropy() -> None:
    with pytest.raises(ValueError, match="128 bits"):
        generate_access_code(entropy_bytes=15)


def test_argon2id_hashing_never_embeds_plaintext() -> None:
    hasher = Argon2AccessCodeHasher()
    access_code = "ca-example-access-code-that-is-not-stored"

    encoded_hash = hasher.hash(access_code)

    assert encoded_hash.startswith("$argon2id$")
    assert access_code not in encoded_hash
    assert hasher.verify(encoded_hash, access_code)
    assert not hasher.verify(encoded_hash, "wrong-code")
    assert not hasher.verify("not-an-argon-hash", access_code)


def test_session_tokens_are_random_hashed_and_domain_separated() -> None:
    authenticated_token = generate_session_token("auth")
    anonymous_token = generate_session_token("anon")
    authenticated_hash = hash_session_token(authenticated_token, kind="authenticated")

    assert authenticated_token.startswith("ca_auth_")
    assert anonymous_token.startswith("ca_anon_")
    assert len(authenticated_hash) == 32
    assert authenticated_token.encode() not in authenticated_hash
    assert authenticated_hash != hash_session_token(authenticated_token, kind="anonymous")
    assert authenticated_token != generate_session_token("auth")
