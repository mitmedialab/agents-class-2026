from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest

from course_server.auth import (
    Argon2AccessCodeHasher,
    AuthenticationService,
    InMemoryAuthStore,
    InvalidCredentials,
    InvalidSession,
    LoginRateLimited,
    SessionPolicy,
    UserAdminService,
    UserAlreadyExists,
)


@dataclass
class MutableClock:
    current: datetime

    def __call__(self) -> datetime:
        return self.current

    def advance(self, duration: timedelta) -> None:
        self.current += duration


def services(
    *,
    policy: SessionPolicy | None = None,
) -> tuple[
    InMemoryAuthStore,
    MutableClock,
    UserAdminService,
    AuthenticationService,
]:
    store = InMemoryAuthStore()
    clock = MutableClock(datetime(2026, 8, 23, 12, 0, tzinfo=UTC))
    hasher = Argon2AccessCodeHasher()
    admin = UserAdminService(store, hasher=hasher, clock=clock)
    auth = AuthenticationService(store, hasher=hasher, policy=policy, clock=clock)
    return store, clock, admin, auth


def test_create_login_and_resolve_student_without_storing_secrets() -> None:
    async def scenario() -> None:
        store, clock, admin, auth = services()
        issued = await admin.create_user(
            username="Alice",
            display_name="Alice Example",
            email="alice@mit.edu",
            role="student",
        )
        stored = await store.get_user_by_username("alice")

        assert stored is not None
        encoded_hash = stored.access_code_hash.get_secret_value()
        assert encoded_hash.startswith("$argon2id$")
        assert issued.access_code not in encoded_hash
        assert issued.access_code not in repr(issued)

        credential = await auth.login(username="ALICE", access_code=issued.access_code)
        assert credential.expires_at == clock.current + timedelta(days=30)
        assert credential.token not in repr(credential)
        assert all(credential.token.encode() != token_hash for token_hash in store.auth_sessions)

        principal = await auth.resolve_authenticated(credential.token)
        assert principal.authenticated
        assert principal.user_id == issued.user.id
        assert principal.username == "alice"
        assert principal.roles == ["public", "student"]
        assert principal.session_id == credential.session_id

    asyncio.run(scenario())


def test_invalid_user_and_invalid_code_have_same_public_failure() -> None:
    async def scenario() -> None:
        _, _, admin, auth = services()
        issued = await admin.create_user(
            username="alice",
            display_name="Alice Example",
            email="alice@mit.edu",
            role="student",
        )

        with pytest.raises(InvalidCredentials) as wrong_code:
            await auth.login(username="alice", access_code="incorrect")
        with pytest.raises(InvalidCredentials) as wrong_user:
            await auth.login(username="nobody", access_code=issued.access_code)

        assert str(wrong_code.value) == str(wrong_user.value)

    asyncio.run(scenario())


def test_failed_login_rate_limit_is_enforced_and_cleared_by_success() -> None:
    async def scenario() -> None:
        policy = SessionPolicy(maximum_failed_logins=3)
        store, _, admin, auth = services(policy=policy)
        issued = await admin.create_user(
            username="alice",
            display_name="Alice Example",
            email="alice@mit.edu",
            role="student",
        )

        for _ in range(3):
            with pytest.raises(InvalidCredentials):
                await auth.login(username="alice", access_code="incorrect")
        with pytest.raises(LoginRateLimited):
            await auth.login(username="alice", access_code=issued.access_code)

        store.login_failures.clear()
        await auth.login(username="alice", access_code=issued.access_code)
        assert store.login_failures == {}

    asyncio.run(scenario())


def test_logout_revokes_session() -> None:
    async def scenario() -> None:
        _, _, admin, auth = services()
        issued = await admin.create_user(
            username="alice",
            display_name="Alice Example",
            email="alice@mit.edu",
            role="student",
        )
        credential = await auth.login(username="alice", access_code=issued.access_code)

        await auth.logout(credential.token)

        with pytest.raises(InvalidSession):
            await auth.resolve_authenticated(credential.token)

    asyncio.run(scenario())


def test_reset_code_revokes_sessions_and_replaces_old_code() -> None:
    async def scenario() -> None:
        _, _, admin, auth = services()
        original = await admin.create_user(
            username="alice",
            display_name="Alice Example",
            email="alice@mit.edu",
            role="student",
        )
        credential = await auth.login(username="alice", access_code=original.access_code)

        replacement = await admin.reset_user_code("alice")

        assert replacement.access_code != original.access_code
        with pytest.raises(InvalidSession):
            await auth.resolve_authenticated(credential.token)
        with pytest.raises(InvalidCredentials):
            await auth.login(username="alice", access_code=original.access_code)
        await auth.login(username="alice", access_code=replacement.access_code)

    asyncio.run(scenario())


def test_deactivation_and_role_change_revoke_existing_sessions() -> None:
    async def scenario() -> None:
        _, _, admin, auth = services()
        issued = await admin.create_user(
            username="tom",
            display_name="Tom Example",
            email="tom@mit.edu",
            role="student",
        )
        first_session = await auth.login(username="tom", access_code=issued.access_code)
        changed = await admin.change_role("tom", "ta")

        assert changed.role == "ta"
        with pytest.raises(InvalidSession):
            await auth.resolve_authenticated(first_session.token)

        second_session = await auth.login(username="tom", access_code=issued.access_code)
        assert (await auth.resolve_authenticated(second_session.token)).roles == ["public", "ta"]

        await admin.deactivate_user("tom")
        with pytest.raises(InvalidSession):
            await auth.resolve_authenticated(second_session.token)
        with pytest.raises(InvalidCredentials):
            await auth.login(username="tom", access_code=issued.access_code)

        activated = await admin.activate_user("tom")
        assert activated.active
        await auth.login(username="tom", access_code=issued.access_code)

    asyncio.run(scenario())


def test_authenticated_session_expires() -> None:
    async def scenario() -> None:
        _, clock, admin, auth = services()
        issued = await admin.create_user(
            username="alice",
            display_name="Alice Example",
            email="alice@mit.edu",
            role="student",
        )
        credential = await auth.login(username="alice", access_code=issued.access_code)
        clock.advance(timedelta(days=30))

        with pytest.raises(InvalidSession):
            await auth.resolve_authenticated(credential.token)

    asyncio.run(scenario())


def test_anonymous_sessions_are_isolated_revocable_and_expire() -> None:
    async def scenario() -> None:
        _, clock, _, auth = services()
        first = await auth.create_anonymous()
        second = await auth.create_anonymous()

        first_principal = await auth.resolve_anonymous(first.token)
        second_principal = await auth.resolve_anonymous(second.token)
        assert first.session_id != second.session_id
        assert first_principal.anonymous_session_id != second_principal.anonymous_session_id
        assert first_principal.roles == ["public"]
        assert not first_principal.authenticated

        await auth.revoke_anonymous(first.token)
        with pytest.raises(InvalidSession):
            await auth.resolve_anonymous(first.token)
        assert (await auth.resolve_anonymous(second.token)).session_id == second.session_id

        clock.advance(timedelta(days=7))
        with pytest.raises(InvalidSession):
            await auth.resolve_anonymous(second.token)

    asyncio.run(scenario())


def test_admin_list_never_returns_hashes_and_duplicate_identity_is_rejected() -> None:
    async def scenario() -> None:
        _, _, admin, _ = services()
        await admin.create_user(
            username="alice",
            display_name="Alice Example",
            email="alice@mit.edu",
            role="student",
        )

        users = await admin.list_users()
        assert len(users) == 1
        assert "access_code_hash" not in type(users[0]).model_fields

        with pytest.raises(UserAlreadyExists):
            await admin.create_user(
                username="ALICE",
                display_name="Other Alice",
                email="other@mit.edu",
                role="student",
            )

    asyncio.run(scenario())
