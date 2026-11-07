"""The Course Agent's read-only access to the current student's own learning trail."""

from __future__ import annotations

from collections.abc import Mapping
from typing import ClassVar
from uuid import UUID

from pydantic import JsonValue

from course_server.agent.capabilities import (
    MEMORY_GET_MINE_TOOL_ID,
    ToolExecutionContext,
    ToolExecutionResult,
    ToolProviderError,
    ToolValidationError,
)

from .models import TrailEntry
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
