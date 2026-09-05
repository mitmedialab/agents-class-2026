"""Application-owned persistence boundary for authentication."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol
from uuid import UUID

from pydantic import SecretStr

from .exceptions import UserAlreadyExists
from .models import AnonymousSessionRecord, AuthSessionRecord, StoredUser, UserRole


class AuthStore(Protocol):
    async def create_user(self, user: StoredUser) -> None: ...

    async def get_user_by_username(self, username: str) -> StoredUser | None: ...

    async def get_user_by_email(self, email: str) -> StoredUser | None: ...

    async def get_user_by_id(self, user_id: UUID) -> StoredUser | None: ...

    async def list_users(self) -> list[StoredUser]: ...

    async def update_user_access_code(
        self,
        user_id: UUID,
        access_code_hash: str,
        updated_at: datetime,
        *,
        revoke_sessions: bool = False,
    ) -> None: ...

    async def set_user_active(
        self,
        user_id: UUID,
        active: bool,
        updated_at: datetime,
    ) -> None: ...

    async def set_user_role(
        self,
        user_id: UUID,
        role: UserRole,
        updated_at: datetime,
    ) -> None: ...

    async def create_auth_session(self, session: AuthSessionRecord) -> None: ...

    async def get_auth_session(self, token_hash: bytes) -> AuthSessionRecord | None: ...

    async def touch_auth_session(self, session_id: UUID, seen_at: datetime) -> None: ...

    async def revoke_auth_session(self, token_hash: bytes, revoked_at: datetime) -> None: ...

    async def revoke_user_sessions(self, user_id: UUID, revoked_at: datetime) -> None: ...

    async def create_anonymous_session(self, session: AnonymousSessionRecord) -> None: ...

    async def get_anonymous_session(
        self,
        token_hash: bytes,
    ) -> AnonymousSessionRecord | None: ...

    async def touch_anonymous_session(self, session_id: UUID, seen_at: datetime) -> None: ...

    async def revoke_anonymous_session(self, token_hash: bytes, revoked_at: datetime) -> None: ...

    async def count_login_failures(self, key_hash: bytes, since: datetime) -> int: ...

    async def record_login_failure(self, key_hash: bytes, attempted_at: datetime) -> None: ...

    async def clear_login_failures(self, key_hash: bytes) -> None: ...


class InMemoryAuthStore:
    """Deterministic adapter for contract/security tests; not production storage."""

    def __init__(self) -> None:
        self.users: dict[UUID, StoredUser] = {}
        self.auth_sessions: dict[bytes, AuthSessionRecord] = {}
        self.anonymous_sessions: dict[bytes, AnonymousSessionRecord] = {}
        self.login_failures: dict[bytes, list[datetime]] = {}

    async def create_user(self, user: StoredUser) -> None:
        normalized_email = str(user.email).casefold()
        if any(
            existing.username == user.username or str(existing.email).casefold() == normalized_email
            for existing in self.users.values()
        ):
            raise UserAlreadyExists("username or email already exists")
        self.users[user.id] = user

    async def get_user_by_username(self, username: str) -> StoredUser | None:
        return next((user for user in self.users.values() if user.username == username), None)

    async def get_user_by_email(self, email: str) -> StoredUser | None:
        normalized = email.strip().casefold()
        return next(
            (user for user in self.users.values() if str(user.email).casefold() == normalized),
            None,
        )

    async def get_user_by_id(self, user_id: UUID) -> StoredUser | None:
        return self.users.get(user_id)

    async def list_users(self) -> list[StoredUser]:
        return sorted(self.users.values(), key=lambda user: user.username)

    async def update_user_access_code(
        self,
        user_id: UUID,
        access_code_hash: str,
        updated_at: datetime,
        *,
        revoke_sessions: bool = False,
    ) -> None:
        user = self.users[user_id]
        self.users[user_id] = user.model_copy(
            update={"access_code_hash": SecretStr(access_code_hash), "updated_at": updated_at}
        )
        if revoke_sessions:
            await self.revoke_user_sessions(user_id, updated_at)

    async def set_user_active(
        self,
        user_id: UUID,
        active: bool,
        updated_at: datetime,
    ) -> None:
        user = self.users[user_id]
        self.users[user_id] = user.model_copy(update={"active": active, "updated_at": updated_at})
        if not active:
            await self.revoke_user_sessions(user_id, updated_at)

    async def set_user_role(
        self,
        user_id: UUID,
        role: UserRole,
        updated_at: datetime,
    ) -> None:
        user = self.users[user_id]
        self.users[user_id] = user.model_copy(update={"role": role, "updated_at": updated_at})
        await self.revoke_user_sessions(user_id, updated_at)

    async def create_auth_session(self, session: AuthSessionRecord) -> None:
        self.auth_sessions[session.token_hash] = session

    async def get_auth_session(self, token_hash: bytes) -> AuthSessionRecord | None:
        return self.auth_sessions.get(token_hash)

    async def touch_auth_session(self, session_id: UUID, seen_at: datetime) -> None:
        for token_hash, session in self.auth_sessions.items():
            if session.id == session_id:
                self.auth_sessions[token_hash] = session.model_copy(
                    update={"last_seen_at": seen_at}
                )
                return

    async def revoke_auth_session(self, token_hash: bytes, revoked_at: datetime) -> None:
        session = self.auth_sessions.get(token_hash)
        if session is not None and session.revoked_at is None:
            self.auth_sessions[token_hash] = session.model_copy(update={"revoked_at": revoked_at})

    async def revoke_user_sessions(self, user_id: UUID, revoked_at: datetime) -> None:
        for token_hash, session in self.auth_sessions.items():
            if session.user_id == user_id and session.revoked_at is None:
                self.auth_sessions[token_hash] = session.model_copy(
                    update={"revoked_at": revoked_at}
                )

    async def create_anonymous_session(self, session: AnonymousSessionRecord) -> None:
        self.anonymous_sessions[session.token_hash] = session

    async def get_anonymous_session(
        self,
        token_hash: bytes,
    ) -> AnonymousSessionRecord | None:
        return self.anonymous_sessions.get(token_hash)

    async def touch_anonymous_session(self, session_id: UUID, seen_at: datetime) -> None:
        for token_hash, session in self.anonymous_sessions.items():
            if session.id == session_id:
                self.anonymous_sessions[token_hash] = session.model_copy(
                    update={"last_seen_at": seen_at}
                )
                return

    async def revoke_anonymous_session(self, token_hash: bytes, revoked_at: datetime) -> None:
        session = self.anonymous_sessions.get(token_hash)
        if session is not None and session.revoked_at is None:
            self.anonymous_sessions[token_hash] = session.model_copy(
                update={"revoked_at": revoked_at}
            )

    async def count_login_failures(self, key_hash: bytes, since: datetime) -> int:
        return sum(attempt >= since for attempt in self.login_failures.get(key_hash, []))

    async def record_login_failure(self, key_hash: bytes, attempted_at: datetime) -> None:
        self.login_failures.setdefault(key_hash, []).append(attempted_at)

    async def clear_login_failures(self, key_hash: bytes) -> None:
        self.login_failures.pop(key_hash, None)
