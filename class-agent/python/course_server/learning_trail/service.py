"""Ownership and state transitions for learning trails.

Every method takes the trusted `PrincipalContext` and resolves the owner from it. No method
accepts a user ID, so neither a client nor the model can select another student's trail.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID, uuid4

from agent_core import Memory, PrincipalContext

from .models import (
    MAX_ENTRIES_PER_STUDENT,
    MAX_FEEDBACK_PER_ENTRY,
    TrailEntry,
    TrailEntryDraft,
    TrailEntryPatch,
    TrailFeedback,
    TrailFeedbackDraft,
)
from .retrieval import select_trail_memories
from .store import TrailStore


class TrailAccessDenied(PermissionError):
    """Only a logged-in student has a learning trail."""


class TrailEntryNotFound(LookupError):
    """The entry is not in the current student's trail."""


class TrailLimitExceeded(ValueError):
    """The bounded number of entries or feedback items has been reached."""


def _clock() -> datetime:
    return datetime.now(UTC)


def _owner(principal: PrincipalContext) -> UUID:
    if not principal.authenticated or principal.user_id is None or "student" not in principal.roles:
        raise TrailAccessDenied("student login required")
    return principal.user_id


def _newest_first(entries: list[TrailEntry]) -> list[TrailEntry]:
    return sorted(entries, key=lambda entry: (entry.week, entry.updated_at), reverse=True)


def _replace(entries: list[TrailEntry], updated: TrailEntry) -> list[TrailEntry]:
    return [updated if entry.id == updated.id else entry for entry in entries]


def _find(entries: list[TrailEntry], entry_id: UUID) -> TrailEntry:
    for entry in entries:
        if entry.id == entry_id:
            return entry
    raise TrailEntryNotFound("learning trail entry not found")


class LearningTrailService:
    def __init__(
        self,
        store: TrailStore,
        *,
        clock: Callable[[], datetime] = _clock,
        id_factory: Callable[[], UUID] = uuid4,
    ) -> None:
        self._store = store
        self._clock = clock
        self._id_factory = id_factory

    async def list_mine(self, principal: PrincipalContext) -> list[TrailEntry]:
        return _newest_first(await self._store.read(_owner(principal)))

    async def get_mine(self, principal: PrincipalContext, entry_id: UUID) -> TrailEntry:
        return _find(await self._store.read(_owner(principal)), entry_id)

    async def create(self, principal: PrincipalContext, draft: TrailEntryDraft) -> TrailEntry:
        def change(entries: list[TrailEntry]) -> tuple[list[TrailEntry], TrailEntry]:
            if len(entries) >= MAX_ENTRIES_PER_STUDENT:
                raise TrailLimitExceeded("learning trail is full")
            now = self._clock()
            entry = TrailEntry(
                id=self._id_factory(),
                week=draft.week,
                build_title=draft.build_title,
                build_url=draft.build_url,
                reflection=draft.reflection,
                created_at=now,
                updated_at=now,
            )
            return [*entries, entry], entry

        return await self._store.update(_owner(principal), change)

    async def update(
        self,
        principal: PrincipalContext,
        entry_id: UUID,
        patch: TrailEntryPatch,
    ) -> TrailEntry:
        def change(entries: list[TrailEntry]) -> tuple[list[TrailEntry], TrailEntry]:
            changes = {name: getattr(patch, name) for name in patch.model_fields_set}
            updated = _find(entries, entry_id).model_copy(
                update={**changes, "updated_at": self._clock()}
            )
            return _replace(entries, updated), updated

        return await self._store.update(_owner(principal), change)

    async def delete(self, principal: PrincipalContext, entry_id: UUID) -> None:
        def change(entries: list[TrailEntry]) -> tuple[list[TrailEntry], None]:
            _find(entries, entry_id)
            return [entry for entry in entries if entry.id != entry_id], None

        await self._store.update(_owner(principal), change)

    async def add_feedback(
        self,
        principal: PrincipalContext,
        entry_id: UUID,
        draft: TrailFeedbackDraft,
    ) -> TrailEntry:
        def change(entries: list[TrailEntry]) -> tuple[list[TrailEntry], TrailEntry]:
            entry = _find(entries, entry_id)
            if len(entry.feedback) >= MAX_FEEDBACK_PER_ENTRY:
                raise TrailLimitExceeded("this entry has reached its feedback limit")
            now = self._clock()
            feedback = TrailFeedback(
                id=self._id_factory(),
                from_role=draft.from_role,
                from_name=draft.from_name,
                body=draft.body,
                received_at=draft.received_at,
                added_at=now,
            )
            updated = entry.model_copy(
                update={"feedback": [*entry.feedback, feedback], "updated_at": now}
            )
            return _replace(entries, updated), updated

        return await self._store.update(_owner(principal), change)

    async def delete_feedback(
        self,
        principal: PrincipalContext,
        entry_id: UUID,
        feedback_id: UUID,
    ) -> TrailEntry:
        def change(entries: list[TrailEntry]) -> tuple[list[TrailEntry], TrailEntry]:
            entry = _find(entries, entry_id)
            remaining = [item for item in entry.feedback if item.id != feedback_id]
            if len(remaining) == len(entry.feedback):
                raise TrailEntryNotFound("feedback not found")
            updated = entry.model_copy(update={"feedback": remaining, "updated_at": self._clock()})
            return _replace(entries, updated), updated

        return await self._store.update(_owner(principal), change)

    async def select_memories(self, principal: PrincipalContext) -> list[Memory]:
        """Fill `AgentContext.selected_memories`. Nobody but a student has any."""

        try:
            owner = _owner(principal)
        except TrailAccessDenied:
            return []
        return select_trail_memories(await self._store.read(owner), owner)
