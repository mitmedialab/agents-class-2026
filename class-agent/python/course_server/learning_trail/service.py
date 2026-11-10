"""Ownership and state transitions for learning trails.

Student methods take the trusted `PrincipalContext` and resolve the owner from it, so neither a
client nor the model can select another student's trail. Staff methods name a student, but they
require a TA or instructor session and only ever reach entries that student chose to share.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from uuid import UUID, uuid4

from pydantic import JsonValue

from agent_core import Memory, PrincipalContext

from .connections import ConnectionDocument, find_connections
from .models import (
    MAX_ENTRIES_PER_STUDENT,
    MAX_FEEDBACK_PER_ENTRY,
    PendingDraft,
    SharedTrailSummary,
    StaffFeedbackDraft,
    TopicCoverage,
    TrailConnection,
    TrailEntry,
    TrailEntryDraft,
    TrailEntryPatch,
    TrailFeedback,
    TrailFeedbackDraft,
    TrailTopic,
)
from .retrieval import select_trail_memories
from .store import FileDraftStore, TrailStore, TrailStoreError

logger = logging.getLogger(__name__)

StudentNameLookup = Callable[[UUID], Awaitable[str | None]]
CourseMaterialLoader = Callable[[], Awaitable[list[ConnectionDocument]]]


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


def _topic_week(document: ConnectionDocument) -> int | None:
    if document.week is not None:
        return document.week
    match = re.fullmatch(r"course://slides/week-0*([0-9]+)", document.target_id)
    return int(match.group(1)) if match else None


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
        course_materials: CourseMaterialLoader | None = None,
        drafts: FileDraftStore | None = None,
        clock: Callable[[], datetime] = _clock,
        id_factory: Callable[[], UUID] = uuid4,
    ) -> None:
        self._store = store
        self._student_name = student_name
        self._course_materials = course_materials
        self._drafts = drafts
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
                topics=draft.topics,
                shared_with_staff=draft.shared_with_staff,
                shared_with_class=draft.shared_with_class,
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

    async def connections(self, principal: PrincipalContext) -> dict[UUID, list[TrailConnection]]:
        """For each of this student's builds: their other builds, course materials, and the
        builds of classmates who chose to share. Feedback and unshared work never take part."""

        owner = _owner(principal)
        own = [
            ConnectionDocument(
                kind="build",
                target_id=str(entry.id),
                title=entry.build_title,
                text=entry.reflection,
                week=entry.week,
                url=entry.build_url,
            )
            for entry in await self._store.read(owner)
        ]
        others = [*await self._classmate_documents(owner)]
        if self._course_materials is not None:
            others.extend(await self._course_materials())
        return {UUID(source.target_id): find_connections(source, [*own, *others]) for source in own}

    async def _classmate_documents(self, owner: UUID) -> list[ConnectionDocument]:
        documents: list[ConnectionDocument] = []
        for student_id in await self._store.owners():
            if student_id == owner:
                continue
            try:
                shared = [e for e in await self._store.read(student_id) if e.shared_with_class]
            except TrailStoreError:
                logger.warning("Skipping an unreadable learning trail", exc_info=True)
                continue
            if not shared:
                continue
            name = await self._student_name(student_id) if self._student_name else None
            documents.extend(
                ConnectionDocument(
                    kind="classmate",
                    target_id=str(entry.id),
                    title=entry.build_title,
                    text=entry.reflection,
                    week=entry.week,
                    url=entry.build_url,
                    owner_name=name or "A classmate",
                )
                for entry in shared
            )
        return documents

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
        titles = {topic.id: topic.title for topic in await self.topics()}
        return select_trail_memories(await self._store.read(owner), owner, topic_titles=titles)

    async def memory_overview(self, principal: PrincipalContext) -> dict[str, JsonValue] | None:
        """Platform-derived facts about the trail for the run: which course topics the
        student's builds have practiced and which none has touched yet."""

        try:
            coverage = await self.coverage(principal)
        except TrailAccessDenied:
            return None
        if not coverage.practiced and not coverage.not_yet:
            return None
        return {
            "topics_practiced": [topic.title for topic in coverage.practiced],
            "topics_not_yet_practiced": [topic.title for topic in coverage.not_yet],
        }

    # Topics and coverage: the open learner model.

    async def topics(self) -> list[TrailTopic]:
        """The course's slide decks and readings, in week order, that a build can be tagged with."""

        if self._course_materials is None:
            return []
        topics = [
            TrailTopic(id=document.target_id, title=document.title, week=_topic_week(document))
            for document in await self._course_materials()
        ]
        return sorted(topics, key=lambda topic: (topic.week is None, topic.week or 0, topic.title))

    async def coverage(self, principal: PrincipalContext) -> TopicCoverage:
        owner = _owner(principal)
        tagged = {
            topic
            for entry in await self._store.read(owner)
            if entry.still_relevant
            for topic in entry.topics
        }
        topics = await self.topics()
        return TopicCoverage(
            practiced=[topic for topic in topics if topic.id in tagged],
            not_yet=[topic for topic in topics if topic.id not in tagged],
        )

    # Drafts: the agent proposes, the student decides.

    async def propose(self, principal: PrincipalContext, draft: TrailEntryDraft) -> PendingDraft:
        owner = _owner(principal)
        if self._drafts is None:
            raise TrailStoreError("drafts are not enabled")
        pending = PendingDraft(draft=draft, proposed_at=self._clock())
        await self._drafts.write(owner, pending)
        return pending

    async def pending_draft(self, principal: PrincipalContext) -> PendingDraft | None:
        owner = _owner(principal)
        return None if self._drafts is None else await self._drafts.read(owner)

    async def discard_draft(self, principal: PrincipalContext) -> None:
        owner = _owner(principal)
        if self._drafts is not None:
            await self._drafts.clear(owner)

    async def accept_draft(self, principal: PrincipalContext, draft: TrailEntryDraft) -> TrailEntry:
        """Save the draft as the student edited it, then forget the proposal."""

        entry = await self.create(principal, draft)
        await self.discard_draft(principal)
        return entry
