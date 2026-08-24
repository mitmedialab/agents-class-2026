"""Cryptographic operations for access codes and opaque session tokens."""

from __future__ import annotations

import base64
import hashlib
import secrets
from typing import Protocol

from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

ACCESS_CODE_ENTROPY_BYTES = 20
SESSION_TOKEN_ENTROPY_BYTES = 32


class AccessCodeHasher(Protocol):
    def hash(self, access_code: str) -> str: ...

    def verify(self, encoded_hash: str, access_code: str) -> bool: ...

    def needs_rehash(self, encoded_hash: str) -> bool: ...


class Argon2AccessCodeHasher:
    """Argon2id access-code hashing with explicit, replaceable parameters."""

    def __init__(self) -> None:
        self._hasher = PasswordHasher(
            time_cost=3,
            memory_cost=65_536,
            parallelism=4,
            hash_len=32,
            salt_len=16,
            type=Type.ID,
        )

    def hash(self, access_code: str) -> str:
        if not access_code:
            raise ValueError("access code must not be empty")
        return self._hasher.hash(access_code)

    def verify(self, encoded_hash: str, access_code: str) -> bool:
        try:
            return self._hasher.verify(encoded_hash, access_code)
        except (InvalidHashError, VerificationError, VerifyMismatchError):
            return False

    def needs_rehash(self, encoded_hash: str) -> bool:
        try:
            return self._hasher.check_needs_rehash(encoded_hash)
        except InvalidHashError:
            return True


def generate_access_code(entropy_bytes: int = ACCESS_CODE_ENTROPY_BYTES) -> str:
    """Generate a grouped Base32 code with at least 128 bits of entropy."""

    if entropy_bytes < 16:
        raise ValueError("access codes require at least 128 bits of entropy")
    encoded = base64.b32encode(secrets.token_bytes(entropy_bytes)).decode("ascii").rstrip("=")
    grouped = "-".join(encoded[index : index + 4] for index in range(0, len(encoded), 4))
    return f"ca-{grouped.lower()}"


def generate_session_token(prefix: str) -> str:
    if prefix not in {"auth", "anon"}:
        raise ValueError("unknown session-token domain")
    return f"ca_{prefix}_{secrets.token_urlsafe(SESSION_TOKEN_ENTROPY_BYTES)}"


def hash_session_token(token: str, *, kind: str) -> bytes:
    if kind not in {"authenticated", "anonymous"}:
        raise ValueError("unknown session-token kind")
    domain = f"class-agent:{kind}:session:v1\0".encode()
    return hashlib.sha256(domain + token.encode()).digest()


def hash_rate_limit_key(normalized_username: str) -> bytes:
    domain = b"class-agent:login-rate-limit:v1\0"
    return hashlib.sha256(domain + normalized_username.encode()).digest()
