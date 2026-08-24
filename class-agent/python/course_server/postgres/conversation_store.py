"""PostgreSQL conversation/event adapter using portable core contracts."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

from agent_core import Conversation, Event, PrincipalContext
from course_server.agent.store import ConversationAccessDenied


class PostgresConversationStore:
    """Explicit SQL adapter; no PostgreSQL records cross the store boundary."""

    def __init__(self, pool: AsyncConnectionPool[Any]) -> None:
        self._pool = pool

    async def create_conversation(self, conversation: Conversation) -> None:
        async with self._pool.connection() as connection:
            await connection.execute(
                """
                INSERT INTO conversations (
                    id, user_id, anonymous_session_id, created_at,
                    updated_at, title, archived_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    conversation.id,
                    conversation.user_id,
                    conversation.anonymous_session_id,
                    conversation.created_at,
                    conversation.updated_at,
                    conversation.title,
                    conversation.archived_at,
                ),
            )

    async def get_conversation(self, conversation_id: UUID) -> Conversation | None:
        async with self._pool.connection() as connection:
            cursor = await connection.execute(
                """
                SELECT id, user_id, anonymous_session_id, created_at,
                       updated_at, title, archived_at
                FROM conversations
                WHERE id = %s
                """,
                (conversation_id,),
            )
            row = await cursor.fetchone()
        return Conversation.model_validate(row) if row is not None else None

    async def list_conversations(self, principal: PrincipalContext) -> list[Conversation]:
        if principal.authenticated:
            owner_column = "user_id"
            owner_id = principal.user_id
        else:
            owner_column = "anonymous_session_id"
            owner_id = principal.anonymous_session_id
        query = f"""
            SELECT id, user_id, anonymous_session_id, created_at,
                   updated_at, title, archived_at
            FROM conversations
            WHERE {owner_column} = %s
            ORDER BY updated_at DESC
        """
        async with self._pool.connection() as connection:
            cursor = await connection.execute(query, (owner_id,))
            rows = await cursor.fetchall()
        return [Conversation.model_validate(row) for row in rows]

    async def append_events(self, conversation_id: UUID, events: list[Event]) -> None:
        if not events:
            return
        if any(event.conversation_id != conversation_id for event in events):
            raise ValueError("every persisted event must reference its conversation")

        async with self._pool.connection() as connection, connection.transaction():
            exists_cursor = await connection.execute(
                "SELECT 1 FROM conversations WHERE id = %s",
                (conversation_id,),
            )
            if await exists_cursor.fetchone() is None:
                raise ConversationAccessDenied("conversation not found")
            for event in events:
                await connection.execute(
                    """
                    INSERT INTO events (
                        id, schema_version, timestamp, type, actor,
                        principal_user_id, anonymous_session_id,
                        conversation_id, node_id, payload, metadata
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        event.id,
                        event.schema_version,
                        event.timestamp,
                        event.type,
                        event.actor,
                        event.principal_user_id,
                        event.anonymous_session_id,
                        event.conversation_id,
                        event.node_id,
                        Jsonb(event.payload),
                        Jsonb(event.metadata),
                    ),
                )
            await connection.execute(
                """
                UPDATE conversations
                SET updated_at = GREATEST(updated_at, %s)
                WHERE id = %s
                """,
                (max(event.timestamp for event in events), conversation_id),
            )

    async def list_events(self, conversation_id: UUID) -> list[Event]:
        async with self._pool.connection() as connection:
            cursor = await connection.execute(
                """
                SELECT id, schema_version, timestamp, type, actor,
                       principal_user_id, anonymous_session_id,
                       conversation_id, node_id, payload, metadata
                FROM events
                WHERE conversation_id = %s
                ORDER BY timestamp, id
                """,
                (conversation_id,),
            )
            rows = await cursor.fetchall()
        return [Event.model_validate(row) for row in rows]
