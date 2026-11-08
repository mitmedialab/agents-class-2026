"""User-owned agent memories, stored apart from conversation event history."""

from __future__ import annotations

from typing import Any, Protocol
from uuid import UUID

from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

from agent_core import Memory

MAX_SELECTED_MEMORIES = 20


class MemoryReader(Protocol):
    async def list_recent(self, user_id: UUID) -> list[Memory]: ...


class PostgresMemoryStore:
    def __init__(self, pool: AsyncConnectionPool[Any]) -> None:
        self._pool = pool

    async def save(self, memory: Memory) -> None:
        async with self._pool.connection() as connection:
            await connection.execute(
                """
                INSERT INTO user_memories (
                    id, user_id, created_at, updated_at, kind, content,
                    source_event_ids, privacy, metadata
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (user_id, (metadata ->> 'question_id'))
                    WHERE metadata ? 'question_id'
                DO UPDATE SET
                    updated_at = EXCLUDED.updated_at,
                    kind = EXCLUDED.kind,
                    content = EXCLUDED.content,
                    source_event_ids = EXCLUDED.source_event_ids,
                    privacy = EXCLUDED.privacy,
                    metadata = EXCLUDED.metadata
                """,
                (
                    memory.id,
                    memory.user_id,
                    memory.created_at,
                    memory.updated_at,
                    memory.kind,
                    memory.content,
                    memory.source_event_ids,
                    memory.privacy,
                    Jsonb(memory.metadata),
                ),
            )

    async def list_recent(self, user_id: UUID) -> list[Memory]:
        async with self._pool.connection() as connection:
            rows = await (
                await connection.execute(
                    """
                    SELECT id, user_id, created_at, updated_at, kind, content,
                           source_event_ids, privacy, metadata
                    FROM user_memories
                    WHERE user_id = %s
                    ORDER BY updated_at DESC
                    LIMIT %s
                    """,
                    (user_id, MAX_SELECTED_MEMORIES),
                )
            ).fetchall()
        return [Memory.model_validate(row) for row in rows]
