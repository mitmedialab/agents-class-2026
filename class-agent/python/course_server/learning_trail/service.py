"""Ownership and state transitions for learning trails.

Student methods take the trusted `PrincipalContext` and resolve the owner from it, so neither a
client nor the model can select another student's trail. Staff methods name a student, but they
require a TA or instructor session and only ever reach entries that student chose to share.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from uuid import UUID, uuid4

from agent_core import Memory, PrincipalContext

from .models import (
    MAX_ENTRIES_PER_STUDENT,
    MAX_FEEDBACK_PER_ENTRY,
    SharedTrailSummary,
    StaffFeedbackDraft,
    TrailEntry,
    TrailEntryDraft,
    TrailEntryPatch,
    TrailFeedback,
    TrailFeedbackDraft,
)
from .retrieval import select_trail_memories
from .store import TrailStore, TrailStoreError

logger = logging.getLogger(__name__)

StudentNameLookup = Callable[[UUID], Awaitable[str | None]]


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


def _require_staff(principal: PrincipalContext) -> str:
    """Return the role recorded on feedback a TA or instructor writes."""

    if principal.authenticated:
        if "instructor" in principal.roles:
            return "instructor"
        if "ta" in principal.roles:
            return "ta"
    raise TrailAccessDenied("course staff login required")


def _find_shared(entries: list[TrailEntry], entry_id: UUID) -> TrailEntry:
    entry = _find(entries, entry_id)
    if not entry.shared_with_staff:
        raise TrailEntryNotFound("learning trail entry not found")
    return entry


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
        student_name: StudentNameLookup | None = None,
        clock: Callable[[], datetime] = _clock,
        id_factory: Callable[[], UUID] = uuid4,
    ) -> None:
        self._store = store
        self._student_name = student_name
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
                shared_with_staff=draft.shared_with_staff,
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
                source="pasted_by_student",
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
            removing = [item for item in entry.feedback if item.id == feedback_id]
            if not removing:
                raise TrailEntryNotFound("feedback not found")
            if removing[0].source == "staff":
                raise TrailAccessDenied("feedback written by course staff stays with the entry")
            return self._without_feedback(entries, entry, feedback_id)

        return await self._store.update(_owner(principal), change)

    def _without_feedback(
        self,
        entries: list[TrailEntry],
        entry: TrailEntry,
        feedback_id: UUID,
    ) -> tuple[list[TrailEntry], TrailEntry]:
        remaining = [item for item in entry.feedback if item.id != feedback_id]
        updated = entry.model_copy(update={"feedback": remaining, "updated_at": self._clock()})
        return _replace(entries, updated), updated

    async def list_shared_students(self, principal: PrincipalContext) -> list[SharedTrailSummary]:
        """List students with at least one shared entry. One unreadable file hides only itself."""

        _require_staff(principal)
        summaries: list[SharedTrailSummary] = []
        for student_id in await self._store.owners():
            try:
                shared = [e for e in await self._store.read(student_id) if e.shared_with_staff]
            except TrailStoreError:
                logger.warning("Skipping an unreadable learning trail", exc_info=True)
                continue
            if not shared:
                continue
            name = await self._student_name(student_id) if self._student_name else None
            summaries.append(
                SharedTrailSummary(
                    student_id=student_id,
                    student_name=name or "Unknown student",
                    shared_entries=len(shared),
                    latest_week=max(entry.week for entry in shared),
                )
            )
        return sorted(summaries, key=lambda item: item.student_name.casefold())

    async def list_shared_entries(
        self,
        principal: PrincipalContext,
        student_id: UUID,
    ) -> list[TrailEntry]:
        _require_staff(principal)
        entries = await self._store.read(student_id)
        return _newest_first([entry for entry in entries if entry.shared_with_staff])

    async def add_staff_feedback(
        self,
        principal: PrincipalContext,
        student_id: UUID,
        entry_id: UUID,
        draft: StaffFeedbackDraft,
    ) -> TrailEntry:
        role = _require_staff(principal)

        def change(entries: list[TrailEntry]) -> tuple[list[TrailEntry], TrailEntry]:
            entry = _find_shared(entries, entry_id)
            if len(entry.feedback) >= MAX_FEEDBACK_PER_ENTRY:
                raise TrailLimitExceeded("this entry has reached its feedback limit")
            now = self._clock()
            feedback = TrailFeedback.model_validate(
                {
                    "id": self._id_factory(),
                    "from_role": role,
                    "from_name": principal.display_name or principal.username,
                    "body": draft.body,
                    "received_at": now,
                    "source": "staff",
                    "added_at": now,
                }
            )
            updated = entry.model_copy(
                update={"feedback": [*entry.feedback, feedback], "updated_at": now}
            )
            return _replace(entries, updated), updated

        return await self._store.update(student_id, change)

    async def delete_staff_feedback(
        self,
        principal: PrincipalContext,
        student_id: UUID,
        entry_id: UUID,
        feedback_id: UUID,
    ) -> TrailEntry:
        """Staff can correct what staff wrote. A student's pasted copies stay the student's."""

        _require_staff(principal)

        def change(entries: list[TrailEntry]) -> tuple[list[TrailEntry], TrailEntry]:
            entry = _find_shared(entries, entry_id)
            if not any(i.id == feedback_id and i.source == "staff" for i in entry.feedback):
                raise TrailEntryNotFound("feedback not found")
            return self._without_feedback(entries, entry, feedback_id)

        return await self._store.update(student_id, change)

    async def select_memories(self, principal: PrincipalContext) -> list[Memory]:
        """Fill `AgentContext.selected_memories`. Nobody but a student has any."""

        try:
            owner = _owner(principal)
        except TrailAccessDenied:
            return []
        return select_trail_memories(await self._store.read(owner), owner)
