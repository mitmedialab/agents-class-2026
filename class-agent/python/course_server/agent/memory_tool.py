"""Agent tool that saves one memory for the authenticated user."""

from __future__ import annotations

from collections.abc import Mapping
from typing import ClassVar

from pydantic import JsonValue

from agent_core import Memory
from course_server.memory import MAX_MEMORY_CONTENT_LENGTH, MemoryWriter

from .capabilities import (
    SAVE_MY_MEMORY_TOOL_ID,
    ToolExecutionContext,
    ToolExecutionResult,
    ToolValidationError,
)

# Validation bounds matching the CHECK constraints on user_memories.
_MAX_KIND_LENGTH = 80
_MAX_CONTENT_LENGTH = MAX_MEMORY_CONTENT_LENGTH


def _bounded_text(arguments: Mapping[str, JsonValue], name: str, max_length: int) -> str:
    value = arguments.get(name)
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= max_length:
        raise ToolValidationError(f"{name} must be 1 to {max_length} characters.")
    return value.strip()


class SaveMyMemoryTool:
    """Insert one memory owned by the trusted principal; the model never names an owner."""

    id = SAVE_MY_MEMORY_TOOL_ID
    description = (
        "Remember one fact about the signed-in user for their future conversations. Use only "
        "while processing their submitted questionnaire responses or when they explicitly ask "
        "to be remembered. Save only what the user stated."
    )
    redact_arguments_in_events = True
    input_schema: ClassVar[dict[str, JsonValue]] = {
        "type": "object",
        "properties": {
            "kind": {
                "type": "string",
                "minLength": 1,
                "maxLength": _MAX_KIND_LENGTH,
                "description": "Short category, such as preference, goal, or background.",
            },
            "content": {
                "type": "string",
                "minLength": 1,
                "maxLength": _MAX_CONTENT_LENGTH,
                "description": "The single fact to remember, in the user's own terms.",
            },
        },
        "required": ["kind", "content"],
        "additionalProperties": False,
    }

    def __init__(self, memories: MemoryWriter) -> None:
        self._memories = memories

    async def execute(
        self, arguments: Mapping[str, JsonValue], context: ToolExecutionContext
    ) -> ToolExecutionResult:
        user_id = context.principal.user_id
        if not context.principal.authenticated or user_id is None:
            raise PermissionError("A signed-in user is required to save a memory.")
        if set(arguments) != {"kind", "content"}:
            raise ToolValidationError("memory.save_mine requires only kind and content.")
        memory = Memory(
            user_id=user_id,
            kind=_bounded_text(arguments, "kind", _MAX_KIND_LENGTH),
            content=_bounded_text(arguments, "content", _MAX_CONTENT_LENGTH),
            privacy="personal",
            metadata={"source": "agent"},
        )
        await self._memories.save(memory)
        return ToolExecutionResult(
            content={"saved": True, "memory_id": str(memory.id)},
            summary="Saved a memory for the current user.",
            storage_policy="server_summary",
        )
