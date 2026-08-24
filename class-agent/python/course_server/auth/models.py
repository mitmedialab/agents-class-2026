"""Authentication records independent of PostgreSQL and HTTP frameworks."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    SecretStr,
    StringConstraints,
)

UserRole = Literal["student", "ta", "instructor", "admin"]
Username = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        to_lower=True,
        min_length=2,
        max_length=64,
        pattern=r"^[a-z][a-z0-9._-]*$",
    ),
]
NonEmptyString = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


def _require_timezone(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must include a timezone")
    return value


AwareDatetime = Annotated[datetime, AfterValidator(_require_timezone)]


class AuthModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class User(AuthModel):
    id: UUID
    username: Username
    display_name: NonEmptyString
    email: EmailStr
    role: UserRole
    active: bool
    created_at: AwareDatetime
    updated_at: AwareDatetime


class StoredUser(User):
    """Internal persistence record; never return this from public APIs."""

    access_code_hash: SecretStr = Field(repr=False)

    def public(self) -> User:
        return User.model_validate(self.model_dump(exclude={"access_code_hash"}))


class AuthSessionRecord(AuthModel):
    id: UUID
    user_id: UUID
    token_hash: bytes = Field(repr=False)
    created_at: AwareDatetime
    expires_at: AwareDatetime
    last_seen_at: AwareDatetime
    revoked_at: AwareDatetime | None = None


class AnonymousSessionRecord(AuthModel):
    id: UUID
    token_hash: bytes = Field(repr=False)
    created_at: AwareDatetime
    expires_at: AwareDatetime
    last_seen_at: AwareDatetime
    revoked_at: AwareDatetime | None = None


@dataclass(frozen=True, repr=False)
class IssuedAccessCode:
    """Ephemeral plaintext access code returned only at creation/reset."""

    user: User
    access_code: str

    def __repr__(self) -> str:
        return f"IssuedAccessCode(user={self.user!r}, access_code=<redacted>)"


@dataclass(frozen=True, repr=False)
class SessionCredential:
    """Ephemeral opaque credential returned to the future HTTP cookie layer."""

    session_id: UUID
    token: str
    expires_at: datetime
    kind: Literal["authenticated", "anonymous"]

    def __repr__(self) -> str:
        return (
            "SessionCredential("
            f"session_id={self.session_id!r}, token=<redacted>, "
            f"expires_at={self.expires_at!r}, kind={self.kind!r})"
        )


@dataclass(frozen=True)
class SessionPolicy:
    authenticated_ttl: timedelta = timedelta(days=30)
    anonymous_ttl: timedelta = timedelta(days=7)
    maximum_failed_logins: int = 5
    failed_login_window: timedelta = timedelta(minutes=15)

    def __post_init__(self) -> None:
        if self.authenticated_ttl <= timedelta(0):
            raise ValueError("authenticated_ttl must be positive")
        if self.anonymous_ttl <= timedelta(0):
            raise ValueError("anonymous_ttl must be positive")
        if self.maximum_failed_logins < 1:
            raise ValueError("maximum_failed_logins must be positive")
        if self.failed_login_window <= timedelta(0):
            raise ValueError("failed_login_window must be positive")
