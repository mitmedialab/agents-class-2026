"""The Course Agent's read-only access to the current student's own learning trail."""

from __future__ import annotations

from collections.abc import Mapping
from typing import ClassVar
from uuid import UUID

from pydantic import JsonValue, ValidationError

from course_server.agent.capabilities import (
    MEMORY_GET_MINE_TOOL_ID,
    MEMORY_PROPOSE_MINE_TOOL_ID,
    ToolExecutionContext,
    ToolExecutionResult,
    ToolProviderError,
    ToolValidationError,
)

from .models import MAX_TOPICS_PER_ENTRY, TrailEntry, TrailEntryDraft
from .service import LearningTrailService, TrailAccessDenied, TrailEntryNotFound
from .store import TrailStoreError

_SUMMARY_CHARACTERS = 240


def _summary(entry: TrailEntry) -> dict[str, JsonValue]:
    return {
        "entry_id": str(entry.id),
        "week": entry.week,
        "build_title": entry.build_title,
        "still_relevant": entry.still_relevant,
        "reflection_start": entry.reflection[:_SUMMARY_CHARACTERS],
        "feedback_count": len(entry.feedback),
        "updated_at": entry.updated_at.isoformat(),
    }


def _entry_id(arguments: Mapping[str, JsonValue]) -> UUID | None:
    if not set(arguments) <= {"entry_id"}:
        raise ToolValidationError("memory.get_mine accepts only entry_id.")
    raw = arguments.get("entry_id")
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise ToolValidationError("entry_id must be an ID returned by memory.get_mine.")
    try:
        return UUID(raw)
    except ValueError as error:
        raise ToolValidationError("entry_id must be an ID returned by memory.get_mine.") from error


class MemoryGetMineTool:
    id = MEMORY_GET_MINE_TOOL_ID
    description = (
        "Read the current student's own learning trail: their saved build reflections and the "
        "instructor or TA feedback they attached. Without arguments, lists every entry, including "
        "ones the student marked as no longer relevant. With entry_id, returns one complete entry. "
        "Identity comes from the login. This tool cannot change anything."
    )
    input_schema: ClassVar[dict[str, JsonValue]] = {
        "type": "object",
        "properties": {
            "entry_id": {
                "type": "string",
                "description": "An entry ID from a previous memory.get_mine listing.",
            }
        },
        "additionalProperties": False,
    }

    def __init__(self, trail: LearningTrailService) -> None:
        self._trail = trail

    async def execute(
        self,
        arguments: Mapping[str, JsonValue],
        context: ToolExecutionContext,
    ) -> ToolExecutionResult:
        entry_id = _entry_id(arguments)
        try:
            if entry_id is None:
                entries = await self._trail.list_mine(context.principal)
                return ToolExecutionResult(
                    content=[_summary(entry) for entry in entries],
                    summary=f"Listed {len(entries)} learning trail entries.",
                    storage_policy="server_summary",
                )
            entry = await self._trail.get_mine(context.principal, entry_id)
        except TrailAccessDenied as error:
            raise PermissionError("Student login is required.") from error
        except TrailEntryNotFound as error:
            raise ToolValidationError("That learning trail entry was not found.") from error
        except TrailStoreError as error:
            raise ToolProviderError(
                "The learning trail is unavailable right now.",
                category="temporary_failure",
            ) from error
        return ToolExecutionResult(
            content=entry.model_dump(mode="json"),
            summary=f"Read a learning trail entry for week {entry.week}.",
            storage_policy="server_summary",
        )


class MemoryProposeMineTool:
    """The write half of the debrief. It only parks a draft: the student saves or discards it."""

    id = MEMORY_PROPOSE_MINE_TOOL_ID
    description = (
        "After debriefing the current student about a weekly build, propose one learning trail "
        "entry in their own words: week, build title, optional https link, the reflection, and "
        "the course topics it practiced (topic IDs from the course slides or readings, such as "
        "course://slides/week-02). Nothing is saved: the draft waits in the My builds panel, "
        "where the student edits and saves or discards it. A new proposal replaces an earlier "
        "unsaved one. After calling this, open the learning-trail workspace component so the "
        "student can review it."
    )
    input_schema: ClassVar[dict[str, JsonValue]] = {
        "type": "object",
        "properties": {
            "week": {"type": "integer", "minimum": 1, "maximum": 20},
            "build_title": {"type": "string", "maxLength": 200},
            "build_url": {"type": "string", "description": "An https:// link, if any."},
            "reflection": {
                "type": "string",
                "maxLength": 20000,
                "description": (
                    "What they built, what broke or surprised them, and what they would change, "
                    "kept in the student's own words and first person."
                ),
            },
            "topics": {
                "type": "array",
                "items": {"type": "string"},
                "maxItems": MAX_TOPICS_PER_ENTRY,
                "description": "Course resource URIs for the slide decks or readings practiced.",
            },
        },
        "required": ["week", "build_title", "reflection"],
        "additionalProperties": False,
    }

    def __init__(self, trail: LearningTrailService) -> None:
        self._trail = trail

    async def execute(
        self,
        arguments: Mapping[str, JsonValue],
        context: ToolExecutionContext,
    ) -> ToolExecutionResult:
        allowed = {"week", "build_title", "build_url", "reflection", "topics"}
        if not set(arguments) <= allowed:
            raise ToolValidationError("memory.propose_mine accepts only the documented fields.")
        try:
            draft = TrailEntryDraft.model_validate(dict(arguments))
        except ValidationError as error:
            raise ToolValidationError(f"The proposed entry is invalid: {error}") from error
        try:
            pending = await self._trail.propose(context.principal, draft)
        except TrailAccessDenied as error:
            raise PermissionError("Student login is required.") from error
        except TrailStoreError as error:
            raise ToolProviderError(
                "The learning trail is unavailable right now.",
                category="temporary_failure",
            ) from error
        return ToolExecutionResult(
            content={
                "status": "awaiting_student_review",
                "week": pending.draft.week,
                "build_title": pending.draft.build_title,
                "topics": list(pending.draft.topics),
                "next_step": (
                    "Open the learning-trail workspace component. The student saves or discards "
                    "the draft there; do not claim it is saved."
                ),
            },
            summary=f"Proposed a week {draft.week} entry for the student to review.",
            storage_policy="server_summary",
        )
