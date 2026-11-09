"""Student-owned memories and human-confirmed peer introductions.

The Course Agent may save what a student says about their background, goals, preferences,
current project, what they can help with and what they need help with. Every memory belongs to
one student, records the user message it came from, and carries a privacy value from the
constitution's Memory contract:

- ``personal``: only the owner (and the agent acting for the owner) can read it.
- ``course_private``: the owner chose to share it inside the course, so the peer-matching tool
  may show it to classmates looking for help.

An introduction is drafted by the agent, sent only when the requester clicks Send, and answered
only by the helper. Identity always comes from ``PrincipalContext``; no tool accepts a user ID.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, ClassVar, Literal, Protocol
from uuid import UUID, uuid4

from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool
from pydantic import BaseModel, ConfigDict, Field, JsonValue, ValidationError

from agent_core import Memory, MemoryPrivacy, PrincipalContext
from course_server.agent.capabilities import (
    FIND_PEER_HELPERS_TOOL_ID,
    FORGET_MY_MEMORY_TOOL_ID,
    GET_MY_MEMORIES_TOOL_ID,
    REQUEST_PEER_INTRODUCTION_TOOL_ID,
    SAVE_MY_MEMORY_TOOL_ID,
    ToolEmittedEvent,
    ToolExecutionContext,
    ToolExecutionResult,
    ToolValidationError,
)
from course_server.agent.store import ConversationStore
from course_server.workspace.models import OpenWorkspaceCommand, WorkspacePanel

MemoryKind = Literal["background", "goal", "preference", "project", "can_help", "needs_help"]
MEMORY_KINDS: tuple[MemoryKind, ...] = (
    "background",
    "goal",
    "preference",
    "project",
    "can_help",
    "needs_help",
)
IntroductionStatus = Literal["draft", "sent", "accepted", "declined", "cancelled"]
IntroductionAction = Literal["send", "cancel", "accept", "decline"]
REPLY_MAX_LENGTH = 1000  # Matches peer_introductions_reply_bounded (migration 0020).
MESSAGE_MAX_LENGTH = 2000  # Matches peer_introductions_message_bounded (migration 0019).

# Memories injected into every turn are bounded so a long-lived student does not crowd out the
# conversation; the student can still list and edit all of them in the People panel.
PROMPT_MEMORY_LIMIT = 30
MAX_MEMORIES_PER_STUDENT = 100
# A helper is never asked by more than this many open requests, nor more than the weekly
# number, so being generous with "can help" does not turn into a burden.
HELPER_OPEN_REQUEST_LIMIT = 2
HELPER_WEEKLY_REQUEST_LIMIT = 3
SOURCE_EXCERPT_CHARS = 280

_TRANSITIONS: dict[IntroductionAction, tuple[Literal["requester", "helper"], set[str], str]] = {
    "send": ("requester", {"draft"}, "sent"),
    "cancel": ("requester", {"draft", "sent"}, "cancelled"),
    "accept": ("helper", {"sent"}, "accepted"),
    "decline": ("helper", {"sent"}, "declined"),
}


class PeerMemoryAccessDenied(PermissionError):
    """The principal is not an authenticated, active student."""


class PeerMemoryNotFound(LookupError):
    """The item is absent or not owned by the principal; callers must not distinguish these."""


class PeerMemoryConflict(ValueError):
    """The request is valid in shape but not allowed in the current state."""


@dataclass(frozen=True)
class PeerIdentity:
    user_id: UUID
    username: str
    display_name: str
    role: str
    active: bool


@dataclass(frozen=True)
class SharedMemory:
    """A classmate's course_private memory as the matching tool may reveal it."""

    username: str
    display_name: str
    kind: str
    content: str
    updated_at: datetime


class PeerIntroduction(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    requester_user_id: UUID
    helper_user_id: UUID
    topic: str
    message: str
    status: IntroductionStatus
    created_at: datetime
    updated_at: datetime
    sent_at: datetime | None = None
    responded_at: datetime | None = None
    reply: str | None = None


class MemoryUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str | None = Field(default=None, min_length=1, max_length=500)
    privacy: MemoryPrivacy | None = None
    kind: MemoryKind | None = None


class PeerMemoryStore(Protocol):
    async def identity_by_id(self, user_id: UUID) -> PeerIdentity | None: ...

    async def identity_by_username(self, username: str) -> PeerIdentity | None: ...

    async def add_memory(self, memory: Memory) -> None: ...

    async def list_memories(self, user_id: UUID) -> list[Memory]: ...

    async def replace_memory(self, memory: Memory) -> None: ...

    async def delete_memory(self, *, user_id: UUID, memory_id: UUID) -> bool: ...

    async def list_shared_memories(self, *, exclude_user_id: UUID) -> list[SharedMemory]: ...

    async def add_introduction(self, introduction: PeerIntroduction) -> None: ...

    async def list_introductions(self, user_id: UUID) -> list[PeerIntroduction]: ...

    async def get_introduction(self, introduction_id: UUID) -> PeerIntroduction | None: ...

    async def replace_introduction(self, introduction: PeerIntroduction) -> None: ...

    async def helper_requests_since(self, *, helper_user_id: UUID, since: datetime) -> int: ...

    async def helper_open_requests(self, helper_user_id: UUID) -> int: ...


class InMemoryPeerMemoryStore:
    """Test and fixture store with the same visibility rules as PostgreSQL."""

    def __init__(self, identities: Mapping[UUID, PeerIdentity] | None = None) -> None:
        self.identities = dict(identities or {})
        self.memories: dict[UUID, Memory] = {}
        self.introductions: dict[UUID, PeerIntroduction] = {}

    async def identity_by_id(self, user_id: UUID) -> PeerIdentity | None:
        return self.identities.get(user_id)

    async def identity_by_username(self, username: str) -> PeerIdentity | None:
        normalized = username.strip().casefold()
        return next(
            (item for item in self.identities.values() if item.username.casefold() == normalized),
            None,
        )

    async def add_memory(self, memory: Memory) -> None:
        self.memories[memory.id] = memory

    async def list_memories(self, user_id: UUID) -> list[Memory]:
        return sorted(
            (item for item in self.memories.values() if item.user_id == user_id),
            key=lambda item: item.updated_at,
            reverse=True,
        )

    async def replace_memory(self, memory: Memory) -> None:
        self.memories[memory.id] = memory

    async def delete_memory(self, *, user_id: UUID, memory_id: UUID) -> bool:
        memory = self.memories.get(memory_id)
        if memory is None or memory.user_id != user_id:
            return False
        del self.memories[memory_id]
        return True

    async def list_shared_memories(self, *, exclude_user_id: UUID) -> list[SharedMemory]:
        shared: list[SharedMemory] = []
        for memory in self.memories.values():
            owner = self.identities.get(memory.user_id)
            if (
                memory.privacy != "course_private"
                or memory.user_id == exclude_user_id
                or owner is None
                or owner.role != "student"
                or not owner.active
            ):
                continue
            shared.append(
                SharedMemory(
                    username=owner.username,
                    display_name=owner.display_name,
                    kind=memory.kind,
                    content=memory.content,
                    updated_at=memory.updated_at,
                )
            )
        return sorted(shared, key=lambda item: item.updated_at, reverse=True)

    async def add_introduction(self, introduction: PeerIntroduction) -> None:
        self.introductions[introduction.id] = introduction

    async def list_introductions(self, user_id: UUID) -> list[PeerIntroduction]:
        return sorted(
            (
                item
                for item in self.introductions.values()
                if user_id in {item.requester_user_id, item.helper_user_id}
            ),
            key=lambda item: item.created_at,
            reverse=True,
        )

    async def get_introduction(self, introduction_id: UUID) -> PeerIntroduction | None:
        return self.introductions.get(introduction_id)

    async def replace_introduction(self, introduction: PeerIntroduction) -> None:
        self.introductions[introduction.id] = introduction

    async def helper_requests_since(self, *, helper_user_id: UUID, since: datetime) -> int:
        return sum(
            1
            for item in self.introductions.values()
            if item.helper_user_id == helper_user_id
            and item.sent_at is not None
            and item.sent_at >= since
        )

    async def helper_open_requests(self, helper_user_id: UUID) -> int:
        return sum(
            1
            for item in self.introductions.values()
            if item.helper_user_id == helper_user_id and item.status == "sent"
        )


def _memory_from_row(row: Mapping[str, Any]) -> Memory:
    return Memory(
        id=row["id"],
        user_id=row["user_id"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        kind=row["kind"],
        content=row["content"],
        source_event_ids=list(row["source_event_ids"] or []),
        privacy=row["privacy"],
        metadata=row["metadata"] or {},
    )


def _identity_from_row(row: Mapping[str, Any]) -> PeerIdentity:
    return PeerIdentity(
        user_id=row["id"],
        username=row["username"],
        display_name=row["display_name"],
        role=row["role"],
        active=row["active"],
    )


_INTRODUCTION_COLUMNS = (
    "id, requester_user_id, helper_user_id, topic, message, status, created_at, updated_at, "
    "sent_at, responded_at, reply"
)


class PostgresPeerMemoryStore:
    def __init__(self, pool: AsyncConnectionPool[Any]) -> None:
        self._pool = pool

    async def _identity(self, where: str, value: object) -> PeerIdentity | None:
        async with self._pool.connection() as connection:
            row = await (
                await connection.execute(
                    f"SELECT id, username, display_name, role, active FROM users WHERE {where}",
                    (value,),
                )
            ).fetchone()
        return None if row is None else _identity_from_row(row)

    async def identity_by_id(self, user_id: UUID) -> PeerIdentity | None:
        return await self._identity("id = %s", user_id)

    async def identity_by_username(self, username: str) -> PeerIdentity | None:
        return await self._identity("lower(username) = lower(%s)", username.strip())

    async def add_memory(self, memory: Memory) -> None:
        async with self._pool.connection() as connection:
            await connection.execute(
                """
                INSERT INTO memories (
                    id, user_id, kind, content, source_event_ids, privacy, metadata,
                    created_at, updated_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    memory.id,
                    memory.user_id,
                    memory.kind,
                    memory.content,
                    memory.source_event_ids,
                    memory.privacy,
                    Jsonb(memory.metadata),
                    memory.created_at,
                    memory.updated_at,
                ),
            )

    async def list_memories(self, user_id: UUID) -> list[Memory]:
        async with self._pool.connection() as connection:
            rows = await (
                await connection.execute(
                    "SELECT * FROM memories WHERE user_id = %s ORDER BY updated_at DESC",
                    (user_id,),
                )
            ).fetchall()
        return [_memory_from_row(row) for row in rows]

    async def replace_memory(self, memory: Memory) -> None:
        async with self._pool.connection() as connection:
            await connection.execute(
                """
                UPDATE memories SET kind = %s, content = %s, privacy = %s, metadata = %s,
                    updated_at = %s
                WHERE id = %s AND user_id = %s
                """,
                (
                    memory.kind,
                    memory.content,
                    memory.privacy,
                    Jsonb(memory.metadata),
                    memory.updated_at,
                    memory.id,
                    memory.user_id,
                ),
            )

    async def delete_memory(self, *, user_id: UUID, memory_id: UUID) -> bool:
        async with self._pool.connection() as connection:
            cursor = await connection.execute(
                "DELETE FROM memories WHERE id = %s AND user_id = %s",
                (memory_id, user_id),
            )
        return bool(cursor.rowcount == 1)

    async def list_shared_memories(self, *, exclude_user_id: UUID) -> list[SharedMemory]:
        async with self._pool.connection() as connection:
            rows = await (
                await connection.execute(
                    """
                    SELECT u.username, u.display_name, m.kind, m.content, m.updated_at
                    FROM memories m JOIN users u ON u.id = m.user_id
                    WHERE m.privacy = 'course_private' AND m.user_id <> %s
                      AND u.role = 'student' AND u.active
                    ORDER BY m.updated_at DESC
                    """,
                    (exclude_user_id,),
                )
            ).fetchall()
        return [
            SharedMemory(
                username=row["username"],
                display_name=row["display_name"],
                kind=row["kind"],
                content=row["content"],
                updated_at=row["updated_at"],
            )
            for row in rows
        ]

    async def add_introduction(self, introduction: PeerIntroduction) -> None:
        async with self._pool.connection() as connection:
            await connection.execute(
                f"""
                INSERT INTO peer_introductions ({_INTRODUCTION_COLUMNS})
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    introduction.id,
                    introduction.requester_user_id,
                    introduction.helper_user_id,
                    introduction.topic,
                    introduction.message,
                    introduction.status,
                    introduction.created_at,
                    introduction.updated_at,
                    introduction.sent_at,
                    introduction.responded_at,
                    introduction.reply,
                ),
            )

    async def list_introductions(self, user_id: UUID) -> list[PeerIntroduction]:
        async with self._pool.connection() as connection:
            rows = await (
                await connection.execute(
                    f"""
                    SELECT {_INTRODUCTION_COLUMNS} FROM peer_introductions
                    WHERE requester_user_id = %s OR helper_user_id = %s
                    ORDER BY created_at DESC
                    """,
                    (user_id, user_id),
                )
            ).fetchall()
        return [PeerIntroduction.model_validate(dict(row)) for row in rows]

    async def get_introduction(self, introduction_id: UUID) -> PeerIntroduction | None:
        async with self._pool.connection() as connection:
            row = await (
                await connection.execute(
                    f"SELECT {_INTRODUCTION_COLUMNS} FROM peer_introductions WHERE id = %s",
                    (introduction_id,),
                )
            ).fetchone()
        return None if row is None else PeerIntroduction.model_validate(dict(row))

    async def replace_introduction(self, introduction: PeerIntroduction) -> None:
        async with self._pool.connection() as connection:
            await connection.execute(
                """
                UPDATE peer_introductions
                SET status = %s, updated_at = %s, sent_at = %s, responded_at = %s, reply = %s,
                    message = %s
                WHERE id = %s
                """,
                (
                    introduction.status,
                    introduction.updated_at,
                    introduction.sent_at,
                    introduction.responded_at,
                    introduction.reply,
                    introduction.message,
                    introduction.id,
                ),
            )

    async def helper_requests_since(self, *, helper_user_id: UUID, since: datetime) -> int:
        async with self._pool.connection() as connection:
            row = await (
                await connection.execute(
                    """
                    SELECT count(*) AS n FROM peer_introductions
                    WHERE helper_user_id = %s AND sent_at >= %s
                    """,
                    (helper_user_id, since),
                )
            ).fetchone()
        return int(row["n"]) if row else 0

    async def helper_open_requests(self, helper_user_id: UUID) -> int:
        async with self._pool.connection() as connection:
            row = await (
                await connection.execute(
                    """
                    SELECT count(*) AS n FROM peer_introductions
                    WHERE helper_user_id = %s AND status = 'sent'
                    """,
                    (helper_user_id,),
                )
            ).fetchone()
        return int(row["n"]) if row else 0


def _utc_now() -> datetime:
    return datetime.now(UTC)


class PeerMemoryService:
    """Owns every authorization and state rule; tools and routes only adapt it."""

    def __init__(
        self,
        store: PeerMemoryStore,
        *,
        student_access: Callable[[str], bool] | None = None,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._store = store
        self._student_access = student_access
        self._clock = clock

    def can_access(self, principal: PrincipalContext) -> bool:
        return (
            principal.authenticated
            and principal.user_id is not None
            and principal.username is not None
            and "student" in principal.roles
            and (self._student_access is None or self._student_access(principal.username))
        )

    def _require_student(self, principal: PrincipalContext) -> UUID:
        if not self.can_access(principal):
            raise PeerMemoryAccessDenied("an active student login is required")
        assert principal.user_id is not None
        return principal.user_id

    def _peer_allowed(self, identity: PeerIdentity | None) -> bool:
        return (
            identity is not None
            and identity.role == "student"
            and identity.active
            and (self._student_access is None or self._student_access(identity.username))
        )

    # Memories -----------------------------------------------------------------------------

    async def list_mine(self, principal: PrincipalContext) -> list[Memory]:
        return await self._store.list_memories(self._require_student(principal))

    async def save_mine(
        self,
        principal: PrincipalContext,
        *,
        kind: MemoryKind,
        content: str,
        privacy: MemoryPrivacy,
        source_event_ids: list[UUID],
        source_excerpt: str | None,
    ) -> Memory:
        user_id = self._require_student(principal)
        existing = await self._store.list_memories(user_id)
        normalized = " ".join(content.split())
        duplicate = next(
            (item for item in existing if item.kind == kind and item.content == normalized), None
        )
        if duplicate is not None:
            return duplicate
        if len(existing) >= MAX_MEMORIES_PER_STUDENT:
            raise PeerMemoryConflict(
                "This student already has the maximum number of memories; ask them to remove "
                "some in the People panel."
            )
        now = self._clock()
        metadata: dict[str, JsonValue] = {"saved_by": "agent"}
        if source_excerpt:
            metadata["source_excerpt"] = source_excerpt[:SOURCE_EXCERPT_CHARS]
        memory = Memory(
            user_id=user_id,
            created_at=now,
            updated_at=now,
            kind=kind,
            content=normalized,
            source_event_ids=source_event_ids,
            privacy=privacy,
            metadata=metadata,
        )
        await self._store.add_memory(memory)
        return memory

    async def update_mine(
        self, principal: PrincipalContext, memory_id: UUID, update: MemoryUpdate
    ) -> Memory:
        user_id = self._require_student(principal)
        memory = next(
            (item for item in await self._store.list_memories(user_id) if item.id == memory_id),
            None,
        )
        if memory is None:
            raise PeerMemoryNotFound("memory not found")
        changes: dict[str, object] = {"updated_at": self._clock()}
        if update.content is not None:
            changes["content"] = " ".join(update.content.split())
        if update.privacy is not None:
            changes["privacy"] = update.privacy
        if update.kind is not None:
            changes["kind"] = update.kind
        if len(changes) > 1:
            # A student's own edit is the strongest evidence; keep a mark for the UI and the agent.
            changes["metadata"] = {**memory.metadata, "edited_by_student": True}
        updated = Memory.model_validate({**memory.model_dump(), **changes})
        await self._store.replace_memory(updated)
        return updated

    async def forget_mine(self, principal: PrincipalContext, memory_id: UUID) -> None:
        user_id = self._require_student(principal)
        if not await self._store.delete_memory(user_id=user_id, memory_id=memory_id):
            raise PeerMemoryNotFound("memory not found")

    async def selected_memories(self, principal: PrincipalContext) -> list[Memory]:
        """The owner's newest memories for the agent context; others' are never included."""
        if not self.can_access(principal):
            return []
        return (await self.list_mine(principal))[:PROMPT_MEMORY_LIMIT]

    # Matching ------------------------------------------------------------------------------

    async def _helper_capacity(self, helper_user_id: UUID) -> bool:
        week_ago = self._clock() - timedelta(days=7)
        if await self._store.helper_open_requests(helper_user_id) >= HELPER_OPEN_REQUEST_LIMIT:
            return False
        recent = await self._store.helper_requests_since(
            helper_user_id=helper_user_id, since=week_ago
        )
        return recent < HELPER_WEEKLY_REQUEST_LIMIT

    async def classmate_offers(self, principal: PrincipalContext) -> list[dict[str, JsonValue]]:
        """Classmates who chose to share what they can help with, grouped per person."""
        user_id = self._require_student(principal)
        shared = await self._store.list_shared_memories(exclude_user_id=user_id)
        people: dict[str, dict[str, JsonValue]] = {}
        for item in shared:
            identity = await self._store.identity_by_username(item.username)
            if not self._peer_allowed(identity):
                continue
            entry = people.setdefault(
                item.username,
                {
                    "username": item.username,
                    "display_name": item.display_name,
                    "can_help": [],
                    "shared_context": [],
                },
            )
            bucket = "can_help" if item.kind == "can_help" else "shared_context"
            values = entry[bucket]
            assert isinstance(values, list)
            values.append(item.content if bucket == "can_help" else f"{item.kind}: {item.content}")
        offers: list[dict[str, JsonValue]] = []
        for entry in people.values():
            if not entry["can_help"]:
                continue
            identity = await self._store.identity_by_username(str(entry["username"]))
            assert identity is not None
            entry["accepting_requests"] = await self._helper_capacity(identity.user_id)
            offers.append(entry)
        return offers

    # Introductions -------------------------------------------------------------------------

    async def draft_introduction(
        self, principal: PrincipalContext, *, helper_username: str, topic: str, message: str
    ) -> tuple[PeerIntroduction, PeerIdentity]:
        user_id = self._require_student(principal)
        helper = await self._store.identity_by_username(helper_username)
        if helper is None or helper.user_id == user_id or not self._peer_allowed(helper):
            raise PeerMemoryNotFound("That classmate is not available for introductions.")
        offers = await self.classmate_offers(principal)
        offer = next((item for item in offers if item["username"] == helper.username), None)
        if offer is None:
            raise PeerMemoryNotFound("That classmate has not shared anything they can help with.")
        if offer.get("accepting_requests") is not True:
            raise PeerMemoryConflict(
                "That classmate already has the maximum number of open requests; suggest "
                "someone else or try again later."
            )
        now = self._clock()
        introduction = PeerIntroduction(
            id=uuid4(),
            requester_user_id=user_id,
            helper_user_id=helper.user_id,
            topic=" ".join(topic.split()),
            message=message.strip(),
            status="draft",
            created_at=now,
            updated_at=now,
        )
        await self._store.add_introduction(introduction)
        return introduction, helper

    async def transition(
        self,
        principal: PrincipalContext,
        introduction_id: UUID,
        action: IntroductionAction,
        *,
        reply: str | None = None,
        message: str | None = None,
    ) -> PeerIntroduction:
        user_id = self._require_student(principal)
        edited = message.strip() if message is not None else None
        if edited is not None and action != "send":
            raise PeerMemoryConflict("The message can only be edited when sending a draft.")
        if edited == "" or (edited is not None and len(edited) > MESSAGE_MAX_LENGTH):
            raise PeerMemoryConflict(
                f"The message must be between 1 and {MESSAGE_MAX_LENGTH} characters."
            )
        note = reply.strip() if reply is not None else ""
        if note and action != "accept":
            raise PeerMemoryConflict("A note can only be added when accepting a request.")
        if len(note) > REPLY_MAX_LENGTH:
            raise PeerMemoryConflict(f"A note can be at most {REPLY_MAX_LENGTH} characters.")
        introduction = await self._store.get_introduction(introduction_id)
        if introduction is None or user_id not in {
            introduction.requester_user_id,
            introduction.helper_user_id,
        }:
            raise PeerMemoryNotFound("introduction not found")
        side, allowed_from, target = _TRANSITIONS[action]
        actor = (
            introduction.requester_user_id if side == "requester" else introduction.helper_user_id
        )
        if actor != user_id:
            raise PeerMemoryNotFound("introduction not found")
        if introduction.status not in allowed_from:
            raise PeerMemoryConflict(
                f"An introduction that is {introduction.status} cannot {action}."
            )
        if action == "send" and not await self._helper_capacity(introduction.helper_user_id):
            raise PeerMemoryConflict("That classmate cannot take another request right now.")
        now = self._clock()
        changes: dict[str, object] = {"status": target, "updated_at": now}
        if action == "send":
            changes["sent_at"] = now
            if edited is not None:
                # The requester's own edit of the drafted text, made before Send.
                changes["message"] = edited
        if action in {"accept", "decline"}:
            changes["responded_at"] = now
        if action == "accept" and note:
            changes["reply"] = note
        updated = introduction.model_copy(update=changes)
        await self._store.replace_introduction(updated)
        return updated

    async def introductions_view(self, principal: PrincipalContext) -> list[dict[str, JsonValue]]:
        """Introductions as each side may see them; drafts are visible only to the requester."""
        user_id = self._require_student(principal)
        views: list[dict[str, JsonValue]] = []
        for item in await self._store.list_introductions(user_id):
            outgoing = item.requester_user_id == user_id
            if not outgoing and item.status in {"draft", "cancelled"}:
                continue
            other = await self._store.identity_by_id(
                item.helper_user_id if outgoing else item.requester_user_id
            )
            status: str = item.status
            if outgoing and item.status == "declined":
                # The requester learns only that this classmate is not available; no reason.
                status = "unavailable"
            views.append(
                {
                    "id": str(item.id),
                    "direction": "outgoing" if outgoing else "incoming",
                    "other": {
                        "username": other.username if other else "former-student",
                        "display_name": other.display_name if other else "Former student",
                    },
                    "topic": item.topic,
                    "message": item.message,
                    "status": status,
                    "created_at": item.created_at.isoformat(),
                    "responded_at": item.responded_at.isoformat() if item.responded_at else None,
                    # The helper's note; it exists only on accepted introductions.
                    "reply": item.reply if item.status == "accepted" else None,
                }
            )
        return views


def memory_view(memory: Memory) -> dict[str, JsonValue]:
    return {
        "id": str(memory.id),
        "kind": memory.kind,
        "content": memory.content,
        "privacy": memory.privacy,
        "source_excerpt": memory.metadata.get("source_excerpt"),
        "edited_by_student": memory.metadata.get("edited_by_student") is True,
        "created_at": memory.created_at.isoformat(),
        "updated_at": memory.updated_at.isoformat(),
    }


def memories_for_prompt(memories: list[Memory]) -> list[dict[str, JsonValue]]:
    return [
        {
            "id": str(memory.id),
            "kind": memory.kind,
            "content": memory.content,
            "privacy": memory.privacy,
            "edited_by_student": memory.metadata.get("edited_by_student") is True,
            "updated_at": memory.updated_at.date().isoformat(),
        }
        for memory in memories[:PROMPT_MEMORY_LIMIT]
    ]


def people_workspace_command() -> OpenWorkspaceCommand:
    """The People panel is rendered by the web client from the owner-scoped API."""
    return OpenWorkspaceCommand(
        panel=WorkspacePanel(
            id=uuid4(),
            component_id="draft-document",
            title="People",
            props={
                "title": "People",
                "content": (
                    "What the Course Agent remembers about you, who can see it, and "
                    "introductions to classmates."
                ),
            },
            state={"document_kind": "people-overview"},
        )
    )


def _panel_event() -> ToolEmittedEvent:
    return ToolEmittedEvent(
        type="workspace.panel.opened",
        payload={"command": people_workspace_command().model_dump(mode="json", exclude_none=True)},
    )


async def _source_event(
    conversations: ConversationStore, context: ToolExecutionContext
) -> tuple[list[UUID], str | None]:
    """The latest user message in this trusted conversation is the memory's source."""
    events = await conversations.list_events(context.conversation_id)
    for event in reversed(events):
        if event.type == "user.message":
            text = event.payload.get("text")
            return [event.id], text if isinstance(text, str) else None
    return [], None


def _tool_error(error: Exception) -> ToolValidationError:
    if isinstance(error, PeerMemoryAccessDenied):
        return ToolValidationError("Memories and introductions are available to active students.")
    return ToolValidationError(str(error))


class GetMyMemoriesTool:
    id = GET_MY_MEMORIES_TOOL_ID
    description = (
        "List everything the Course Agent remembers about the logged-in student, with each "
        "memory's id, kind and privacy. The current turn already includes recent memories; use "
        "this when the student asks what you remember or before forgetting one."
    )
    input_schema: ClassVar[dict[str, JsonValue]] = {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    }

    def __init__(self, service: PeerMemoryService) -> None:
        self._service = service

    async def execute(
        self, arguments: Mapping[str, JsonValue], context: ToolExecutionContext
    ) -> ToolExecutionResult:
        if arguments:
            raise ToolValidationError("memory.get_mine does not accept arguments")
        try:
            memories = await self._service.list_mine(context.principal)
        except PeerMemoryAccessDenied as error:
            raise _tool_error(error) from error
        return ToolExecutionResult(
            content={"memories": [memory_view(memory) for memory in memories]},
            summary=f"Listed {len(memories)} memories of the current student.",
            storage_policy="server_summary",
        )


class _SaveMemoryArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: MemoryKind
    content: str = Field(min_length=1, max_length=500)
    share_with_classmates: bool = False


class SaveMyMemoryTool:
    id = SAVE_MY_MEMORY_TOOL_ID
    description = (
        "Remember one durable fact the logged-in student just told you about themself: "
        "background, goal, preference, current project, something they can help classmates "
        "with (can_help), or something they need help with (needs_help). Write it as a short "
        "sentence in your own words that uses the student's name and no pronouns. Save only "
        "what the student said, never guesses, grades or third parties' information. Set "
        "share_with_classmates true only when the student agreed that classmates may see it "
        "for introductions; otherwise it stays private to the student. Tell the student what "
        "you saved."
    )
    input_schema: ClassVar[dict[str, JsonValue]] = {
        "type": "object",
        "properties": {
            "kind": {"type": "string", "enum": list(MEMORY_KINDS)},
            "content": {"type": "string", "minLength": 1, "maxLength": 500},
            "share_with_classmates": {
                "type": "boolean",
                "description": "True only with the student's explicit agreement.",
            },
        },
        "required": ["kind", "content"],
        "additionalProperties": False,
    }

    def __init__(self, service: PeerMemoryService, conversations: ConversationStore) -> None:
        self._service = service
        self._conversations = conversations

    async def execute(
        self, arguments: Mapping[str, JsonValue], context: ToolExecutionContext
    ) -> ToolExecutionResult:
        try:
            parsed = _SaveMemoryArguments.model_validate(arguments)
        except ValidationError as error:
            raise ToolValidationError(
                "Invalid memory: use a listed kind and short content."
            ) from error
        source_ids, excerpt = await _source_event(self._conversations, context)
        try:
            memory = await self._service.save_mine(
                context.principal,
                kind=parsed.kind,
                content=parsed.content,
                privacy="course_private" if parsed.share_with_classmates else "personal",
                source_event_ids=source_ids,
                source_excerpt=excerpt,
            )
        except (PeerMemoryAccessDenied, PeerMemoryConflict) as error:
            raise _tool_error(error) from error
        return ToolExecutionResult(
            content={
                "memory": memory_view(memory),
                "visible_to": (
                    "the student and classmates looking for help"
                    if memory.privacy == "course_private"
                    else "only the student"
                ),
            },
            summary=f"Saved a {memory.kind} memory ({memory.privacy}).",
            storage_policy="server_summary",
            emitted_events=[
                ToolEmittedEvent(
                    type="memory.created",
                    payload={"memory_id": str(memory.id), "kind": memory.kind},
                    metadata={"visibility": "private"},
                )
            ],
        )


class ForgetMyMemoryTool:
    id = FORGET_MY_MEMORY_TOOL_ID
    description = (
        "Permanently delete one of the logged-in student's memories by id when the student "
        "asks you to forget it or says it is wrong. Use memory.get_mine first if you need ids."
    )
    input_schema: ClassVar[dict[str, JsonValue]] = {
        "type": "object",
        "properties": {"memory_id": {"type": "string", "format": "uuid"}},
        "required": ["memory_id"],
        "additionalProperties": False,
    }

    def __init__(self, service: PeerMemoryService) -> None:
        self._service = service

    async def execute(
        self, arguments: Mapping[str, JsonValue], context: ToolExecutionContext
    ) -> ToolExecutionResult:
        if set(arguments) != {"memory_id"}:
            raise ToolValidationError("memory.forget_mine requires only memory_id")
        try:
            memory_id = UUID(str(arguments["memory_id"]))
            await self._service.forget_mine(context.principal, memory_id)
        except ValueError as error:
            raise ToolValidationError(
                "memory_id must be a memory id from memory.get_mine"
            ) from error
        except (PeerMemoryAccessDenied, PeerMemoryNotFound) as error:
            raise _tool_error(error) from error
        return ToolExecutionResult(
            content={"deleted": True, "memory_id": str(memory_id)},
            summary="Deleted one memory at the student's request.",
            storage_policy="server_summary",
        )


class FindPeerHelpersTool:
    id = FIND_PEER_HELPERS_TOOL_ID
    description = (
        "List classmates who chose to share what they can help with, plus any other context "
        "they shared, so you can suggest who might help the logged-in student with a problem. "
        "Only shared (course_private) memories of active students are returned; never reveal "
        "anything else about a classmate. Explain why each suggestion fits, and ask the student "
        "before drafting an introduction."
    )
    input_schema: ClassVar[dict[str, JsonValue]] = {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    }

    def __init__(self, service: PeerMemoryService) -> None:
        self._service = service

    async def execute(
        self, arguments: Mapping[str, JsonValue], context: ToolExecutionContext
    ) -> ToolExecutionResult:
        if arguments:
            raise ToolValidationError("peers.find_helpers does not accept arguments")
        try:
            offers = await self._service.classmate_offers(context.principal)
        except PeerMemoryAccessDenied as error:
            raise _tool_error(error) from error
        return ToolExecutionResult(
            content={"classmates": offers},
            summary=f"Found {len(offers)} classmates who shared what they can help with.",
            storage_policy="server_summary",
        )


class _IntroductionArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    helper_username: str = Field(min_length=1, max_length=200)
    topic: str = Field(min_length=1, max_length=200)
    message: str = Field(min_length=1, max_length=MESSAGE_MAX_LENGTH)


class RequestPeerIntroductionTool:
    id = REQUEST_PEER_INTRODUCTION_TOOL_ID
    description = (
        "After the student agrees, draft an introduction asking one classmate from "
        "peers.find_helpers for help. The draft is not sent: it opens in the People panel, "
        "where the student reviews it and clicks Send. The classmate can then accept or "
        "decline. Write the message in the student's voice: what they are stuck on and why "
        "this classmate's shared experience fits. Never include the student's private memories "
        "unless the student asked you to."
    )
    input_schema: ClassVar[dict[str, JsonValue]] = {
        "type": "object",
        "properties": {
            "helper_username": {"type": "string", "minLength": 1, "maxLength": 200},
            "topic": {"type": "string", "minLength": 1, "maxLength": 200},
            "message": {"type": "string", "minLength": 1, "maxLength": MESSAGE_MAX_LENGTH},
        },
        "required": ["helper_username", "topic", "message"],
        "additionalProperties": False,
    }

    def __init__(self, service: PeerMemoryService) -> None:
        self._service = service

    async def execute(
        self, arguments: Mapping[str, JsonValue], context: ToolExecutionContext
    ) -> ToolExecutionResult:
        try:
            parsed = _IntroductionArguments.model_validate(arguments)
        except ValidationError as error:
            raise ToolValidationError(
                "Invalid introduction: helper_username, topic, message."
            ) from error
        try:
            introduction, helper = await self._service.draft_introduction(
                context.principal,
                helper_username=parsed.helper_username,
                topic=parsed.topic,
                message=parsed.message,
            )
        except (PeerMemoryAccessDenied, PeerMemoryNotFound, PeerMemoryConflict) as error:
            raise _tool_error(error) from error
        return ToolExecutionResult(
            content={
                "introduction_id": str(introduction.id),
                "helper": {"username": helper.username, "display_name": helper.display_name},
                "status": "draft",
                "confirmation_required": True,
                "message": "Nothing was sent. The student must click Send in the People panel.",
            },
            summary="Drafted a peer introduction awaiting the student's Send.",
            storage_policy="server_summary",
            emitted_events=[_panel_event()],
        )
