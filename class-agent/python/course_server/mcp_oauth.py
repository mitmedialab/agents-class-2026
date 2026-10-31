"""Course-account OAuth authorization for the remote Course MCP.

The MCP SDK handles OAuth protocol parsing and PKCE verification. This provider
owns durable, single-use grants and rechecks course membership on every token use.
"""

from __future__ import annotations

import hashlib
import re
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    AuthorizeError,
    RefreshToken,
    RegistrationError,
    TokenError,
    construct_redirect_uri,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool
from pydantic import AnyUrl

from course_server.auth.models import StoredUser
from course_server.auth.store import AuthStore
from course_server.course_roster import CourseRoster

_SCOPE = "course:read"
MESSAGE_DRAFT_SCOPE = "course:message_drafts"
_ACCESS_LIFETIME = timedelta(hours=1)
_REFRESH_LIFETIME = timedelta(days=30)
_REQUEST_LIFETIME = timedelta(minutes=10)
_CODE_LIFETIME = timedelta(minutes=5)
_CHATGPT_CALLBACK = re.compile(r"^/connector/oauth/[A-Za-z0-9_-]+$")
_CLAUDE_CALLBACK = "https://claude.ai/api/mcp/auth_callback"
_GOOGLE_CALLBACK_HOSTS = frozenset(
    f"oauth-redirect{suffix}.googleusercontent.com" for suffix in ("", "-sandbox", "-test")
)


def _digest(value: str) -> bytes:
    return hashlib.sha256(value.encode("utf-8")).digest()


def _new_token() -> str:
    return secrets.token_urlsafe(32)


def _now() -> datetime:
    return datetime.now(UTC)


def _chatgpt_redirect(uri: str) -> bool:
    parsed = urlsplit(uri)
    return (
        parsed.scheme == "https"
        and parsed.netloc == "chatgpt.com"
        and parsed.fragment == ""
        and parsed.query == ""
        and (
            parsed.path == "/connector_platform_oauth_redirect"
            or _CHATGPT_CALLBACK.fullmatch(parsed.path) is not None
        )
    )


def _google_redirect(uri: str) -> bool:
    """Validate an exact, operator-configured Gemini callback URI."""
    parsed = urlsplit(uri)
    return (
        parsed.scheme == "https"
        and parsed.netloc in _GOOGLE_CALLBACK_HOSTS
        and not parsed.query
        and not parsed.fragment
        and re.fullmatch(r"/(?:r|a)/[A-Za-z0-9._-]+", parsed.path) is not None
    )


def _course_client_redirect(uri: str, gemini_redirect_uris: frozenset[str]) -> bool:
    return (
        _chatgpt_redirect(uri)
        or uri == _CLAUDE_CALLBACK
        or (uri in gemini_redirect_uris and _google_redirect(uri))
    )


class CourseOAuthProvider:
    """SDK authorization provider backed by the course PostgreSQL database."""

    def __init__(
        self,
        pool: AsyncConnectionPool[Any],
        auth_store: AuthStore,
        *,
        public_base_url: str,
        roster: CourseRoster | None,
        messaging_enabled: bool = False,
        gemini_redirect_uris: tuple[str, ...] = (),
    ) -> None:
        if any(not _google_redirect(uri) for uri in gemini_redirect_uris):
            raise ValueError("Gemini OAuth redirects must be exact Google callback URIs")
        self._pool = pool
        self._auth_store = auth_store
        self._base_url = public_base_url.rstrip("/")
        self.resource = f"{self._base_url}/mcp"
        self._roster = roster
        self._messaging_enabled = messaging_enabled
        self._gemini_redirect_uris = frozenset(gemini_redirect_uris)

    def _allowed_scopes(self, scopes: list[str]) -> bool:
        allowed = {_SCOPE, MESSAGE_DRAFT_SCOPE} if self._messaging_enabled else {_SCOPE}
        return _SCOPE in scopes and len(scopes) == len(set(scopes)) and set(scopes) <= allowed

    async def _active_student(
        self, user_id: UUID, *, credential_created_at: datetime | None = None
    ) -> StoredUser | None:
        user = await self._auth_store.get_user_by_id(user_id)
        if user is None or not user.active or user.role != "student":
            return None
        if credential_created_at is not None and user.updated_at > credential_created_at:
            return None
        if self._roster is not None and self._roster.identifies_inactive_username(user.username):
            return None
        return user

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        async with self._pool.connection() as connection:
            cursor = await connection.execute(
                "SELECT client_info FROM mcp_oauth_clients WHERE client_id = %s",
                (client_id,),
            )
            row = await cursor.fetchone()
        return OAuthClientInformationFull.model_validate(row["client_info"]) if row else None

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        if (
            not client_info.client_id
            or not client_info.redirect_uris
            or any(
                not _course_client_redirect(str(uri), self._gemini_redirect_uris)
                for uri in client_info.redirect_uris
            )
            or client_info.token_endpoint_auth_method
            not in {"client_secret_basic", "client_secret_post", "none"}
        ):
            raise RegistrationError(
                "invalid_client_metadata",
                "Only approved AI-client callbacks and supported client methods are allowed.",
            )
        async with self._pool.connection() as connection:
            await connection.execute(
                "INSERT INTO mcp_oauth_clients (client_id, client_info) VALUES (%s, %s)",
                (client_info.client_id, Jsonb(client_info.model_dump(mode="json"))),
            )

    async def authorize(
        self, client: OAuthClientInformationFull, params: AuthorizationParams
    ) -> str:
        if params.resource != self.resource or not client.client_id:
            raise AuthorizeError("invalid_request", "The requested resource is unavailable.")
        scopes = params.scopes or [_SCOPE]
        if not self._allowed_scopes(scopes):
            raise AuthorizeError("invalid_scope", "The requested course scopes are unavailable.")
        request_token = _new_token()
        async with self._pool.connection() as connection:
            await connection.execute(
                """
                INSERT INTO mcp_oauth_requests (
                    request_hash, client_id, redirect_uri, redirect_uri_explicit,
                    client_state, code_challenge, scopes, resource, expires_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    _digest(request_token),
                    client.client_id,
                    str(params.redirect_uri),
                    params.redirect_uri_provided_explicitly,
                    params.state,
                    params.code_challenge,
                    scopes,
                    self.resource,
                    _now() + _REQUEST_LIFETIME,
                ),
            )
        return f"{self._base_url}/connect?request={request_token}"

    async def pending_request(self, request_token: str) -> dict[str, Any] | None:
        if len(request_token) > 128:
            return None
        async with self._pool.connection() as connection:
            cursor = await connection.execute(
                """
                SELECT client_id, redirect_uri, client_state, expires_at
                FROM mcp_oauth_requests
                WHERE request_hash = %s AND consumed_at IS NULL AND expires_at > now()
                """,
                (_digest(request_token),),
            )
            return cast("dict[str, Any] | None", await cursor.fetchone())

    async def approve(self, request_token: str, user_id: UUID) -> str | None:
        if len(request_token) > 128 or await self._active_student(user_id) is None:
            return None
        code = _new_token()
        async with self._pool.connection() as connection, connection.transaction():
            cursor = await connection.execute(
                """
                UPDATE mcp_oauth_requests SET consumed_at = now()
                WHERE request_hash = %s AND consumed_at IS NULL AND expires_at > now()
                RETURNING client_id, redirect_uri, redirect_uri_explicit,
                          client_state, code_challenge, scopes, resource
                """,
                (_digest(request_token),),
            )
            pending = await cursor.fetchone()
            if pending is None:
                return None
            await connection.execute(
                """
                INSERT INTO mcp_oauth_codes (
                    code_hash, client_id, user_id, redirect_uri,
                    redirect_uri_explicit, code_challenge, scopes, resource, expires_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    _digest(code),
                    pending["client_id"],
                    user_id,
                    pending["redirect_uri"],
                    pending["redirect_uri_explicit"],
                    pending["code_challenge"],
                    pending["scopes"],
                    pending["resource"],
                    _now() + _CODE_LIFETIME,
                ),
            )
        return construct_redirect_uri(
            pending["redirect_uri"], code=code, state=pending["client_state"]
        )

    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> AuthorizationCode | None:
        if not client.client_id or len(authorization_code) > 128:
            return None
        async with self._pool.connection() as connection:
            cursor = await connection.execute(
                """
                SELECT client_id, user_id, redirect_uri, redirect_uri_explicit,
                       code_challenge, scopes, resource, expires_at
                FROM mcp_oauth_codes
                WHERE code_hash = %s AND client_id = %s AND consumed_at IS NULL
                  AND expires_at > now()
                """,
                (_digest(authorization_code), client.client_id),
            )
            row = await cursor.fetchone()
        if row is None:
            return None
        return AuthorizationCode(
            code=authorization_code,
            scopes=row["scopes"],
            expires_at=row["expires_at"].timestamp(),
            client_id=row["client_id"],
            code_challenge=row["code_challenge"],
            redirect_uri=AnyUrl(row["redirect_uri"]),
            redirect_uri_provided_explicitly=row["redirect_uri_explicit"],
            resource=row["resource"],
            subject=str(row["user_id"]),
        )

    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode
    ) -> OAuthToken:
        if not client.client_id or not authorization_code.subject:
            raise TokenError("invalid_grant", "Authorization failed.")
        user_id = UUID(authorization_code.subject)
        if await self._active_student(user_id) is None:
            raise TokenError("invalid_grant", "Course access is unavailable.")
        async with self._pool.connection() as connection, connection.transaction():
            cursor = await connection.execute(
                """
                UPDATE mcp_oauth_codes SET consumed_at = now()
                WHERE code_hash = %s AND client_id = %s AND user_id = %s
                  AND consumed_at IS NULL AND expires_at > now()
                RETURNING resource, scopes, created_at
                """,
                (_digest(authorization_code.code), client.client_id, user_id),
            )
            row = await cursor.fetchone()
            if row is None or row["resource"] != self.resource:
                raise TokenError("invalid_grant", "Authorization code is unavailable.")
            if await self._active_student(user_id, credential_created_at=row["created_at"]) is None:
                raise TokenError("invalid_grant", "Course access has changed.")
            return await self._issue_tokens(
                connection,
                client_id=client.client_id,
                user_id=user_id,
                scopes=row["scopes"],
                resource=row["resource"],
                family_id=uuid4(),
            )

    async def load_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: str
    ) -> RefreshToken | None:
        if not client.client_id:
            return None
        row = await self._token_row(refresh_token, "refresh", client.client_id)
        if (
            row is None
            or await self._active_student(row["user_id"], credential_created_at=row["created_at"])
            is None
        ):
            return None
        return RefreshToken(
            token=refresh_token,
            client_id=client.client_id,
            scopes=row["scopes"],
            expires_at=int(row["expires_at"].timestamp()),
            resource=row["resource"],
            subject=str(row["user_id"]),
        )

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: RefreshToken,
        scopes: list[str],
    ) -> OAuthToken:
        if (
            not client.client_id
            or not refresh_token.subject
            or not self._allowed_scopes(scopes)
            or set(scopes) != set(refresh_token.scopes)
        ):
            raise TokenError("invalid_grant", "Refresh is unavailable.")
        user_id = UUID(refresh_token.subject)
        if await self._active_student(user_id) is None:
            raise TokenError("invalid_grant", "Course access is unavailable.")
        async with self._pool.connection() as connection, connection.transaction():
            cursor = await connection.execute(
                """
                UPDATE mcp_oauth_tokens SET revoked_at = now()
                WHERE token_hash = %s AND kind = 'refresh' AND client_id = %s
                  AND user_id = %s AND revoked_at IS NULL AND expires_at > now()
                RETURNING family_id, resource, created_at
                """,
                (_digest(refresh_token.token), client.client_id, user_id),
            )
            row = await cursor.fetchone()
            if row is None or row["resource"] != self.resource:
                raise TokenError("invalid_grant", "Refresh token is unavailable.")
            if await self._active_student(user_id, credential_created_at=row["created_at"]) is None:
                raise TokenError("invalid_grant", "Course access has changed.")
            return await self._issue_tokens(
                connection,
                client_id=client.client_id,
                user_id=user_id,
                scopes=scopes,
                resource=self.resource,
                family_id=row["family_id"],
            )

    async def _issue_tokens(
        self,
        connection: Any,
        *,
        client_id: str,
        user_id: UUID,
        scopes: list[str],
        resource: str,
        family_id: UUID,
    ) -> OAuthToken:
        access = _new_token()
        refresh = _new_token()
        now = _now()
        for token, kind, lifetime in (
            (access, "access", _ACCESS_LIFETIME),
            (refresh, "refresh", _REFRESH_LIFETIME),
        ):
            await connection.execute(
                """
                INSERT INTO mcp_oauth_tokens (
                    token_hash, kind, family_id, client_id, user_id,
                    scopes, resource, expires_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    _digest(token),
                    kind,
                    family_id,
                    client_id,
                    user_id,
                    scopes,
                    resource,
                    now + lifetime,
                ),
            )
        return OAuthToken(
            access_token=access,
            refresh_token=refresh,
            expires_in=int(_ACCESS_LIFETIME.total_seconds()),
            scope=" ".join(scopes),
        )

    async def _token_row(
        self, token: str, kind: str, client_id: str | None = None
    ) -> dict[str, Any] | None:
        if len(token) > 128:
            return None
        async with self._pool.connection() as connection:
            cursor = await connection.execute(
                """
                SELECT client_id, user_id, scopes, resource, expires_at, family_id, created_at
                FROM mcp_oauth_tokens
                WHERE token_hash = %s AND kind = %s AND revoked_at IS NULL
                  AND expires_at > now() AND (%s::text IS NULL OR client_id = %s)
                """,
                (_digest(token), kind, client_id, client_id),
            )
            return cast("dict[str, Any] | None", await cursor.fetchone())

    async def load_access_token(self, token: str) -> AccessToken | None:
        row = await self._token_row(token, "access")
        if row is None or row["resource"] != self.resource:
            return None
        if (
            await self._active_student(row["user_id"], credential_created_at=row["created_at"])
            is None
        ):
            return None
        return AccessToken(
            token=token,
            client_id=row["client_id"],
            scopes=row["scopes"],
            expires_at=int(row["expires_at"].timestamp()),
            resource=row["resource"],
            subject=str(row["user_id"]),
            claims={"family_id": str(row["family_id"])},
        )

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        async with self._pool.connection() as connection:
            await connection.execute(
                """
                UPDATE mcp_oauth_tokens SET revoked_at = now()
                WHERE family_id = (
                    SELECT family_id FROM mcp_oauth_tokens WHERE token_hash = %s
                ) AND revoked_at IS NULL
                """,
                (_digest(token.token),),
            )

    async def revoke_user_connections(self, user_id: UUID) -> int:
        """Revoke every ChatGPT connection belonging to one trusted account."""
        async with self._pool.connection() as connection, connection.transaction():
            await connection.execute(
                """
                UPDATE mcp_oauth_codes SET consumed_at = now()
                WHERE user_id = %s AND consumed_at IS NULL
                """,
                (user_id,),
            )
            cursor = await connection.execute(
                """
                UPDATE mcp_oauth_tokens SET revoked_at = now()
                WHERE user_id = %s AND revoked_at IS NULL
                RETURNING token_hash
                """,
                (user_id,),
            )
            return len(await cursor.fetchall())

    async def principal_for_access_token(self, access: AccessToken) -> StoredUser | None:
        if not access.subject or access.resource != self.resource or _SCOPE not in access.scopes:
            return None
        row = await self._token_row(access.token, "access")
        if row is None or row["user_id"] != UUID(access.subject):
            return None
        return await self._active_student(row["user_id"], credential_created_at=row["created_at"])
