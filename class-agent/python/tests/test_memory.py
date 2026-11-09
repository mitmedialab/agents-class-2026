from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg import sql
from psycopg_pool import AsyncConnectionPool
from pydantic import JsonValue

from agent_core import Memory, PrincipalContext
from course_server.agent.capabilities import ToolExecutionContext
from course_server.agent.memory_tool import SaveMyMemoryTool
from course_server.memory import MAX_SELECTED_MEMORIES, PostgresMemoryStore
from course_server.migrations import apply_migrations
from course_server.postgres.auth_store import create_auth_pool

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
NOW = datetime(2026, 11, 8, tzinfo=UTC)


def _schema_url(database_url: str, schema_name: str) -> str:
    parsed = urlsplit(database_url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query["options"] = f"-csearch_path={schema_name}"
    return urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, urlencode(query), parsed.fragment)
    )


async def _create_user(pool: AsyncConnectionPool[Any]) -> UUID:
    user_id = uuid4()
    name = user_id.hex
    async with pool.connection() as connection:
        await connection.execute(
            """
            INSERT INTO users (
                id, username, display_name, email, role, access_code_hash, created_at, updated_at
            )
            VALUES (%s, %s, %s, %s, 'student', 'hash', %s, %s)
            """,
            (user_id, name, name, f"{name}@example.org", NOW, NOW),
        )
    return user_id


def _memory(user_id: UUID, content: str, age: int = 0) -> Memory:
    at = NOW - timedelta(minutes=age)
    return Memory(
        user_id=user_id,
        created_at=at,
        updated_at=at,
        kind="preference",
        content=content,
        privacy="personal",
    )


@pytest.mark.postgres
@pytest.mark.skipif(TEST_DATABASE_URL is None, reason="TEST_DATABASE_URL is not configured")
def test_memories_are_user_scoped_newest_first_bounded_and_never_replaced() -> None:
    assert TEST_DATABASE_URL is not None
    schema_name = f"test_memory_{uuid4().hex}"
    with psycopg.connect(TEST_DATABASE_URL) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema_name)))
    database_url = _schema_url(TEST_DATABASE_URL, schema_name)

    async def scenario() -> None:
        apply_migrations(database_url)
        pool = create_auth_pool(database_url)
        await pool.open()
        await pool.wait()
        try:
            store = PostgresMemoryStore(pool)
            owner, other = await _create_user(pool), await _create_user(pool)

            await store.save(_memory(other, "Theirs"))
            await store.save(_memory(owner, "Hints", age=5))
            await store.save(_memory(owner, "Hints"))

            assert [m.content for m in await store.list_recent(owner)] == ["Hints", "Hints"]
            assert [m.content for m in await store.list_recent(other)] == ["Theirs"]

            theirs = (await store.list_recent(other))[0]
            later = NOW + timedelta(hours=1)
            assert not await store.delete(user_id=owner, memory_id=theirs.id)
            refused = await store.update_content(
                user_id=owner, memory_id=theirs.id, content="No", updated_at=later
            )
            assert refused is None
            edited = await store.update_content(
                user_id=other, memory_id=theirs.id, content="Edited", updated_at=later
            )
            assert edited is not None and edited.content == "Edited"
            assert edited.updated_at == later and edited.created_at == theirs.created_at
            assert await store.delete(user_id=other, memory_id=theirs.id)
            assert await store.list_recent(other) == []

            for index in range(MAX_SELECTED_MEMORIES + 1):
                await store.save(_memory(owner, f"Extra {index}"))
            assert len(await store.list_recent(owner)) == MAX_SELECTED_MEMORIES

            # Tools run on a worker thread with their own event loop; use the pool the same way.
            tool = SaveMyMemoryTool(store)
            context = ToolExecutionContext(
                principal=PrincipalContext(
                    authenticated=True,
                    user_id=other,
                    username="other",
                    roles=["public", "student"],
                    session_id=uuid4(),
                ),
                conversation_id=uuid4(),
                permitted_resource_uris=frozenset(),
            )
            arguments: dict[str, JsonValue] = {"kind": "goal", "content": "Saved by tool"}
            await asyncio.to_thread(lambda: asyncio.run(tool.execute(arguments, context)))
            assert (await store.list_recent(other))[0].content == "Saved by tool"
        finally:
            await pool.close()

    try:
        asyncio.run(scenario())
    finally:
        with psycopg.connect(TEST_DATABASE_URL) as connection:
            connection.execute(
                sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema_name))
            )
