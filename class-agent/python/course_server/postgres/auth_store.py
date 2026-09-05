"""PostgreSQL implementation of the application-owned AuthStore protocol."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from psycopg import errors
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool
from pydantic import SecretStr

from course_server.auth.exceptions import UserAlreadyExists
from course_server.auth.models import (
    AnonymousSessionRecord,
    AuthSessionRecord,
    StoredUser,
    UserRole,
)


class PostgresAuthStore:
    """Small explicit SQL adapter; no ORM objects cross the boundary."""

    def __init__(self, pool: AsyncConnectionPool[Any]) -> None:
        self._pool = pool

    async def create_user(self, user: StoredUser) -> None:
        try:
            async with self._pool.connection() as connection:
                await connection.execute(
                    """
                    INSERT INTO users (
                        id, username, display_name, email, role,
                        access_code_hash, active, created_at, updated_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        user.id,
                        user.username,
                        user.display_name,
                        str(user.email),
                        user.role,
                        user.access_code_hash.get_secret_value(),
                        user.active,
                        user.created_at,
                        user.updated_at,
                    ),
                )
        except errors.UniqueViolation as error:
            raise UserAlreadyExists("username or email already exists") from error

    async def get_user_by_username(self, username: str) -> StoredUser | None:
        async with self._pool.connection() as connection:
            cursor = await connection.execute(
                """
                SELECT id, username, display_name, email, role, access_code_hash,
                       active, created_at, updated_at
                FROM users
                WHERE lower(username) = lower(%s)
                """,
                (username,),
            )
            row = await cursor.fetchone()
        return self._stored_user(row)

    async def get_user_by_email(self, email: str) -> StoredUser | None:
        async with self._pool.connection() as connection:
            cursor = await connection.execute(
                """
                SELECT id, username, display_name, email, role, access_code_hash,
                       active, created_at, updated_at
                FROM users
                WHERE lower(email) = lower(%s)
                """,
                (email,),
            )
            row = await cursor.fetchone()
        return self._stored_user(row)

    async def get_user_by_id(self, user_id: UUID) -> StoredUser | None:
        async with self._pool.connection() as connection:
            cursor = await connection.execute(
                """
                SELECT id, username, display_name, email, role, access_code_hash,
                       active, created_at, updated_at
                FROM users
                WHERE id = %s
                """,
                (user_id,),
            )
            row = await cursor.fetchone()
        return self._stored_user(row)

    async def list_users(self) -> list[StoredUser]:
        async with self._pool.connection() as connection:
            cursor = await connection.execute(
                """
                SELECT id, username, display_name, email, role, access_code_hash,
                       active, created_at, updated_at
                FROM users
                ORDER BY username
                """
            )
            rows = await cursor.fetchall()
        return [user for row in rows if (user := self._stored_user(row)) is not None]

    async def update_user_access_code(
        self,
        user_id: UUID,
        access_code_hash: str,
        updated_at: datetime,
        *,
        revoke_sessions: bool = False,
    ) -> None:
        async with self._pool.connection() as connection:
            await connection.execute(
                """
                UPDATE users
                SET access_code_hash = %s, updated_at = %s
                WHERE id = %s
                """,
                (access_code_hash, updated_at, user_id),
            )
            if revoke_sessions:
                await connection.execute(
                    """
                    UPDATE auth_sessions
                    SET revoked_at = COALESCE(revoked_at, %s)
                    WHERE user_id = %s
                    """,
                    (updated_at, user_id),
                )

    async def set_user_active(
        self,
        user_id: UUID,
        active: bool,
        updated_at: datetime,
    ) -> None:
        async with self._pool.connection() as connection:
            await connection.execute(
                "UPDATE users SET active = %s, updated_at = %s WHERE id = %s",
                (active, updated_at, user_id),
            )
            if not active:
                await connection.execute(
                    """
                    UPDATE auth_sessions
                    SET revoked_at = COALESCE(revoked_at, %s)
                    WHERE user_id = %s
                    """,
                    (updated_at, user_id),
                )

    async def set_user_role(
        self,
        user_id: UUID,
        role: UserRole,
        updated_at: datetime,
    ) -> None:
        async with self._pool.connection() as connection:
            await connection.execute(
                "UPDATE users SET role = %s, updated_at = %s WHERE id = %s",
                (role, updated_at, user_id),
            )
            await connection.execute(
                """
                UPDATE auth_sessions
                SET revoked_at = COALESCE(revoked_at, %s)
                WHERE user_id = %s
                """,
                (updated_at, user_id),
            )

    async def create_auth_session(self, session: AuthSessionRecord) -> None:
        async with self._pool.connection() as connection:
            await connection.execute(
                """
                INSERT INTO auth_sessions (
                    id, user_id, token_hash, created_at, expires_at, last_seen_at, revoked_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    session.id,
                    session.user_id,
                    session.token_hash,
                    session.created_at,
                    session.expires_at,
                    session.last_seen_at,
                    session.revoked_at,
                ),
            )

    async def get_auth_session(self, token_hash: bytes) -> AuthSessionRecord | None:
        async with self._pool.connection() as connection:
            cursor = await connection.execute(
                """
                SELECT id, user_id, token_hash, created_at, expires_at, last_seen_at, revoked_at
                FROM auth_sessions
                WHERE token_hash = %s
                """,
                (token_hash,),
            )
            row = await cursor.fetchone()
        if row is None:
            return None
        return AuthSessionRecord.model_validate(row)

    async def touch_auth_session(self, session_id: UUID, seen_at: datetime) -> None:
        async with self._pool.connection() as connection:
            await connection.execute(
                "UPDATE auth_sessions SET last_seen_at = %s WHERE id = %s",
                (seen_at, session_id),
            )

    async def revoke_auth_session(self, token_hash: bytes, revoked_at: datetime) -> None:
        async with self._pool.connection() as connection:
            await connection.execute(
                """
                UPDATE auth_sessions
                SET revoked_at = COALESCE(revoked_at, %s)
                WHERE token_hash = %s
                """,
                (revoked_at, token_hash),
            )

    async def revoke_user_sessions(self, user_id: UUID, revoked_at: datetime) -> None:
        async with self._pool.connection() as connection:
            await connection.execute(
                """
                UPDATE auth_sessions
                SET revoked_at = COALESCE(revoked_at, %s)
                WHERE user_id = %s
                """,
                (revoked_at, user_id),
            )

    async def create_anonymous_session(self, session: AnonymousSessionRecord) -> None:
        async with self._pool.connection() as connection:
            await connection.execute(
                """
                INSERT INTO anonymous_sessions (
                    id, token_hash, created_at, expires_at, last_seen_at, revoked_at
                )
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    session.id,
                    session.token_hash,
                    session.created_at,
                    session.expires_at,
                    session.last_seen_at,
                    session.revoked_at,
                ),
            )

    async def get_anonymous_session(
        self,
        token_hash: bytes,
    ) -> AnonymousSessionRecord | None:
        async with self._pool.connection() as connection:
            cursor = await connection.execute(
                """
                SELECT id, token_hash, created_at, expires_at, last_seen_at, revoked_at
                FROM anonymous_sessions
                WHERE token_hash = %s
                """,
                (token_hash,),
            )
            row = await cursor.fetchone()
        if row is None:
            return None
        return AnonymousSessionRecord.model_validate(row)

    async def touch_anonymous_session(self, session_id: UUID, seen_at: datetime) -> None:
        async with self._pool.connection() as connection:
            await connection.execute(
                "UPDATE anonymous_sessions SET last_seen_at = %s WHERE id = %s",
                (seen_at, session_id),
            )

    async def revoke_anonymous_session(self, token_hash: bytes, revoked_at: datetime) -> None:
        async with self._pool.connection() as connection:
            await connection.execute(
                """
                UPDATE anonymous_sessions
                SET revoked_at = COALESCE(revoked_at, %s)
                WHERE token_hash = %s
                """,
                (revoked_at, token_hash),
            )

    async def count_login_failures(self, key_hash: bytes, since: datetime) -> int:
        async with self._pool.connection() as connection:
            cursor = await connection.execute(
                """
                SELECT count(*) AS failure_count
                FROM auth_login_failures
                WHERE rate_limit_key_hash = %s AND attempted_at >= %s
                """,
                (key_hash, since),
            )
            row = await cursor.fetchone()
        return int(row["failure_count"]) if row is not None else 0

    async def record_login_failure(self, key_hash: bytes, attempted_at: datetime) -> None:
        async with self._pool.connection() as connection:
            await connection.execute(
                """
                INSERT INTO auth_login_failures (rate_limit_key_hash, attempted_at)
                VALUES (%s, %s)
                """,
                (key_hash, attempted_at),
            )

    async def clear_login_failures(self, key_hash: bytes) -> None:
        async with self._pool.connection() as connection:
            await connection.execute(
                "DELETE FROM auth_login_failures WHERE rate_limit_key_hash = %s",
                (key_hash,),
            )

    @staticmethod
    def _stored_user(row: Any | None) -> StoredUser | None:
        if row is None:
            return None
        values = dict(row)
        values["access_code_hash"] = SecretStr(values["access_code_hash"])
        return StoredUser.model_validate(values)


def create_auth_pool(database_url: str) -> AsyncConnectionPool[Any]:
    """Construct a closed pool so the caller controls its lifecycle."""

    return AsyncConnectionPool(
        conninfo=database_url,
        min_size=1,
        max_size=5,
        open=False,
        kwargs={"row_factory": dict_row},
    )
