"""User-owned agent memories, stored apart from conversation event history."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

from agent_core import Memory

MAX_SELECTED_MEMORIES = 20
MAX_LISTED_MEMORIES = 200
MAX_MEMORY_CONTENT_LENGTH = 2_000  # Matches the CHECK constraint on user_memories.content.


class MemoryReader(Protocol):
    async def list_recent(self, user_id: UUID) -> list[Memory]: ...


class MemoryWriter(Protocol):
    async def save(self, memory: Memory) -> None: ...


class MemoryManager(Protocol):
    """Owner-scoped operations behind the user's own memory list."""

    async def list_recent(self, user_id: UUID, limit: int) -> list[Memory]: ...

    async def update_content(
        self, *, user_id: UUID, memory_id: UUID, content: str, updated_at: datetime
    ) -> Memory | None: ...

    async def delete(self, *, user_id: UUID, memory_id: UUID) -> bool: ...


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

    async def list_recent(
        self, user_id: UUID, limit: int = MAX_SELECTED_MEMORIES
    ) -> list[Memory]:
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
                    (user_id, limit),
                )
            ).fetchall()
        return [Memory.model_validate(row) for row in rows]

    async def update_content(
        self, *, user_id: UUID, memory_id: UUID, content: str, updated_at: datetime
    ) -> Memory | None:
        async with self._pool.connection() as connection:
            row = await (
                await connection.execute(
                    """
                    UPDATE user_memories SET content = %s, updated_at = %s
                    WHERE id = %s AND user_id = %s
                    RETURNING id, user_id, created_at, updated_at, kind, content,
                              source_event_ids, privacy, metadata
                    """,
                    (content, updated_at, memory_id, user_id),
                )
            ).fetchone()
        return Memory.model_validate(row) if row else None

    async def delete(self, *, user_id: UUID, memory_id: UUID) -> bool:
        async with self._pool.connection() as connection:
            cursor = await connection.execute(
                "DELETE FROM user_memories WHERE id = %s AND user_id = %s",
                (memory_id, user_id),
            )
        return cursor.rowcount == 1
