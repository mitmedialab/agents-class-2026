from __future__ import annotations

import asyncio
import os
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql

from agent_core import Conversation, Event
from course_server.auth import AuthenticationService, UserAdminService
from course_server.auth.security import hash_session_token
from course_server.index_resources import index_resources
from course_server.migrations import apply_migrations
from course_server.postgres.auth_store import PostgresAuthStore, create_auth_pool
from course_server.postgres.conversation_store import PostgresConversationStore

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

pytestmark = [
    pytest.mark.postgres,
    pytest.mark.skipif(
        TEST_DATABASE_URL is None,
        reason="TEST_DATABASE_URL is not configured",
    ),
]


def _database_url_for_schema(database_url: str, schema_name: str) -> str:
    parsed = urlsplit(database_url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query["options"] = f"-csearch_path={schema_name}"
    return urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, urlencode(query), parsed.fragment)
    )


def test_postgres_auth_store_roundtrip() -> None:
    assert TEST_DATABASE_URL is not None
    schema_name = f"test_auth_{uuid4().hex}"
    with psycopg.connect(TEST_DATABASE_URL) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema_name)))

    scoped_url = _database_url_for_schema(TEST_DATABASE_URL, schema_name)
    try:
        assert apply_migrations(scoped_url) == [
            "0001_authentication",
            "0002_conversations_events",
            "0003_course_resources",
            "0004_anonymous_quotas",
        ]
        assert apply_migrations(scoped_url) == []
        assert index_resources(scoped_url) == [
            "course://syllabus",
            "course://schedule",
            "course://repositories",
            "course://faq",
            "course://instructors",
            "course://application",
        ]
        with psycopg.connect(scoped_url) as connection:
            assert connection.execute("SELECT count(*) FROM course_resources").fetchone() == (6,)
            assert connection.execute(
                "SELECT count(*) FROM faq_entries WHERE active"
            ).fetchone() == (5,)

        async def scenario() -> None:
            pool = create_auth_pool(scoped_url)
            await pool.open()
            await pool.wait()
            try:
                store = PostgresAuthStore(pool)
                admin = UserAdminService(store)
                auth = AuthenticationService(store)
                issued = await admin.create_user(
                    username="alice",
                    display_name="Alice Example",
                    email="alice@mit.edu",
                    role="student",
                )
                stored = await store.get_user_by_username("alice")
                assert stored is not None
                assert stored.access_code_hash.get_secret_value().startswith("$argon2id$")
                assert issued.access_code not in stored.access_code_hash.get_secret_value()

                credential = await auth.login(
                    username="alice",
                    access_code=issued.access_code,
                )
                principal = await auth.resolve_authenticated(credential.token)
                assert principal.user_id == issued.user.id
                assert principal.roles == ["public", "student"]

                conversations = PostgresConversationStore(pool)
                conversation = Conversation(user_id=principal.user_id)
                await conversations.create_conversation(conversation)
                event = Event(
                    type="user.message",
                    actor="user",
                    principal_user_id=principal.user_id,
                    conversation_id=conversation.id,
                    payload={"text": "Hello"},
                )
                await conversations.append_events(conversation.id, [event])
                assert await conversations.get_conversation(conversation.id) is not None
                assert await conversations.list_events(conversation.id) == [event]
                assert [item.id for item in await conversations.list_conversations(principal)] == [
                    conversation.id
                ]

                anonymous = await auth.create_anonymous()
                assert (await auth.resolve_anonymous(anonymous.token)).roles == ["public"]

                await auth.logout(credential.token)
                session = await store.get_auth_session(
                    hash_session_token(credential.token, kind="authenticated")
                )
                assert session is not None and session.revoked_at is not None
            finally:
                await pool.close()

        asyncio.run(scenario())
    finally:
        with psycopg.connect(TEST_DATABASE_URL) as connection:
            connection.execute(
                sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema_name))
            )
