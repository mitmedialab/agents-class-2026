"""Authentication and user-administration application services."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from uuid import uuid4

from pydantic import EmailStr, SecretStr, TypeAdapter, ValidationError

from agent_core import PrincipalContext

from .exceptions import (
    InvalidCredentials,
    InvalidSession,
    LoginRateLimited,
    UserNotFound,
)
from .models import (
    AnonymousSessionRecord,
    AuthSessionRecord,
    IssuedAccessCode,
    SessionCredential,
    SessionPolicy,
    StoredUser,
    User,
    Username,
    UserRole,
)
from .security import (
    AccessCodeHasher,
    Argon2AccessCodeHasher,
    generate_access_code,
    generate_session_token,
    hash_rate_limit_key,
    hash_session_token,
)
from .store import AuthStore

Clock = Callable[[], datetime]
_USERNAME_ADAPTER = TypeAdapter(Username)
_EMAIL_ADAPTER = TypeAdapter(EmailStr)


def _system_clock() -> datetime:
    return datetime.now(UTC)


def _read_clock(clock: Clock) -> datetime:
    now = clock()
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("clock must return a timezone-aware datetime")
    return now


def _normalize_username(username: str) -> str:
    return _USERNAME_ADAPTER.validate_python(username.strip().casefold())


class UserAdminService:
    """Administrative user lifecycle without transport or email assumptions."""

    def __init__(
        self,
        store: AuthStore,
        *,
        hasher: AccessCodeHasher | None = None,
        clock: Clock = _system_clock,
    ) -> None:
        self._store = store
        self._hasher = hasher or Argon2AccessCodeHasher()
        self._clock = clock

    async def create_user(
        self,
        *,
        username: str,
        display_name: str,
        email: str,
        role: UserRole,
    ) -> IssuedAccessCode:
        now = _read_clock(self._clock)
        access_code = generate_access_code()
        user = StoredUser(
            id=uuid4(),
            username=_normalize_username(username),
            display_name=display_name,
            email=email,
            role=role,
            active=True,
            created_at=now,
            updated_at=now,
            access_code_hash=SecretStr(self._hasher.hash(access_code)),
        )
        await self._store.create_user(user)
        return IssuedAccessCode(user=user.public(), access_code=access_code)

    async def reset_user_code(self, username: str) -> IssuedAccessCode:
        user = await self._require_user(username)
        now = _read_clock(self._clock)
        access_code = generate_access_code()
        await self._store.update_user_access_code(
            user.id,
            self._hasher.hash(access_code),
            now,
            revoke_sessions=True,
        )
        updated = user.model_copy(update={"updated_at": now})
        return IssuedAccessCode(user=updated.public(), access_code=access_code)

    async def deactivate_user(self, username: str) -> User:
        user = await self._require_user(username)
        now = _read_clock(self._clock)
        await self._store.set_user_active(user.id, False, now)
        return user.model_copy(update={"active": False, "updated_at": now}).public()

    async def activate_user(self, username: str) -> User:
        user = await self._require_user(username)
        now = _read_clock(self._clock)
        await self._store.set_user_active(user.id, True, now)
        return user.model_copy(update={"active": True, "updated_at": now}).public()

    async def change_role(self, username: str, role: UserRole) -> User:
        user = await self._require_user(username)
        now = _read_clock(self._clock)
        await self._store.set_user_role(user.id, role, now)
        return user.model_copy(update={"role": role, "updated_at": now}).public()

    async def list_users(self) -> list[User]:
        return [user.public() for user in await self._store.list_users()]

    async def _require_user(self, username: str) -> StoredUser:
        try:
            normalized = _normalize_username(username)
        except ValidationError as error:
            raise UserNotFound("user not found") from error
        user = await self._store.get_user_by_username(normalized)
        if user is None:
            raise UserNotFound("user not found")
        return user


class AuthenticationService:
    """Access-code login and opaque authenticated/anonymous session handling."""

    def __init__(
        self,
        store: AuthStore,
        *,
        hasher: AccessCodeHasher | None = None,
        policy: SessionPolicy | None = None,
        clock: Clock = _system_clock,
    ) -> None:
        self._store = store
        self._hasher = hasher or Argon2AccessCodeHasher()
        self._policy = policy or SessionPolicy()
        self._clock = clock
        self._dummy_hash = self._hasher.hash(generate_access_code())

    async def login(self, *, username: str, access_code: str) -> SessionCredential:
        now = _read_clock(self._clock)
        normalized_username, user = await self._lookup_login_user(username)
        rate_limit_key = hash_rate_limit_key(normalized_username)
        failures = await self._store.count_login_failures(
            rate_limit_key,
            now - self._policy.failed_login_window,
        )
        if failures >= self._policy.maximum_failed_logins:
            raise LoginRateLimited("too many failed login attempts")

        encoded_hash = (
            user.access_code_hash.get_secret_value() if user is not None else self._dummy_hash
        )
        verified = self._hasher.verify(encoded_hash, access_code)
        if user is None or not user.active or not verified:
            await self._store.record_login_failure(rate_limit_key, now)
            raise InvalidCredentials("invalid username or access code")

        if self._hasher.needs_rehash(encoded_hash):
            await self._store.update_user_access_code(
                user.id,
                self._hasher.hash(access_code),
                now,
            )
        await self._store.clear_login_failures(rate_limit_key)

        session_id = uuid4()
        token = generate_session_token("auth")
        expires_at = now + self._policy.authenticated_ttl
        await self._store.create_auth_session(
            AuthSessionRecord(
                id=session_id,
                user_id=user.id,
                token_hash=hash_session_token(token, kind="authenticated"),
                created_at=now,
                expires_at=expires_at,
                last_seen_at=now,
            )
        )
        return SessionCredential(
            session_id=session_id,
            token=token,
            expires_at=expires_at,
            kind="authenticated",
        )

    async def resolve_authenticated(self, token: str) -> PrincipalContext:
        now = _read_clock(self._clock)
        token_hash = hash_session_token(token, kind="authenticated")
        session = await self._store.get_auth_session(token_hash)
        if session is None or session.revoked_at is not None or now >= session.expires_at:
            raise InvalidSession("invalid authenticated session")
        user = await self._store.get_user_by_id(session.user_id)
        if user is None or not user.active:
            raise InvalidSession("invalid authenticated session")

        await self._store.touch_auth_session(session.id, now)
        return PrincipalContext(
            authenticated=True,
            user_id=user.id,
            username=user.username,
            display_name=user.display_name,
            roles=["public", user.role],
            session_id=session.id,
        )

    async def logout(self, token: str) -> None:
        await self._store.revoke_auth_session(
            hash_session_token(token, kind="authenticated"),
            _read_clock(self._clock),
        )

    async def create_anonymous(self) -> SessionCredential:
        now = _read_clock(self._clock)
        session_id = uuid4()
        token = generate_session_token("anon")
        expires_at = now + self._policy.anonymous_ttl
        await self._store.create_anonymous_session(
            AnonymousSessionRecord(
                id=session_id,
                token_hash=hash_session_token(token, kind="anonymous"),
                created_at=now,
                expires_at=expires_at,
                last_seen_at=now,
            )
        )
        return SessionCredential(
            session_id=session_id,
            token=token,
            expires_at=expires_at,
            kind="anonymous",
        )

    async def resolve_anonymous(self, token: str) -> PrincipalContext:
        now = _read_clock(self._clock)
        token_hash = hash_session_token(token, kind="anonymous")
        session = await self._store.get_anonymous_session(token_hash)
        if session is None or session.revoked_at is not None or now >= session.expires_at:
            raise InvalidSession("invalid anonymous session")

        await self._store.touch_anonymous_session(session.id, now)
        return PrincipalContext(
            authenticated=False,
            anonymous_session_id=session.id,
            roles=["public"],
            session_id=session.id,
        )

    async def revoke_anonymous(self, token: str) -> None:
        await self._store.revoke_anonymous_session(
            hash_session_token(token, kind="anonymous"),
            _read_clock(self._clock),
        )

    async def _lookup_login_user(self, username: str) -> tuple[str, StoredUser | None]:
        identifier = username.strip().casefold()
        if "@" in identifier:
            try:
                normalized_email = str(_EMAIL_ADAPTER.validate_python(identifier)).casefold()
            except ValidationError:
                return "__invalid_email__", None
            user = await self._store.get_user_by_email(normalized_email)
            return (
                f"user:{user.id}" if user is not None else f"email:{normalized_email}",
                user,
            )
        try:
            normalized = _normalize_username(identifier)
        except ValidationError:
            return "__invalid_username__", None
        user = await self._store.get_user_by_username(normalized)
        return (f"user:{user.id}" if user is not None else f"username:{normalized}", user)
