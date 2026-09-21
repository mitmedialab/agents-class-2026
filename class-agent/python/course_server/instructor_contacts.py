"""Instructor-only lookup of the active student account directory."""

from collections.abc import Mapping
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field, JsonValue, ValidationError

from course_server.agent.capabilities import (
    INSTRUCTOR_LIST_STUDENTS_TOOL_ID,
    ToolExecutionContext,
    ToolExecutionResult,
    ToolValidationError,
)
from course_server.instructor_messages import (
    InstructorMessageAccessDenied,
    InstructorMessageService,
)


class StudentDirectoryPage(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    # Bound per-turn exposure and pagination, consistent with private communication tools.
    limit: int = Field(default=50, ge=1, le=100)
    offset: int = Field(default=0, ge=0, le=10_000)


class InstructorListStudentsTool:
    id = INSTRUCTOR_LIST_STUDENTS_TOOL_ID
    description = (
        "List active student account names, usernames, and email addresses for the current "
        "instructor. Use this directory to look up message recipients; do not infer addresses. "
        "This directory does not identify the owner of an anonymous question."
    )
    input_schema: ClassVar[dict[str, JsonValue]] = {
        "type": "object",
        "properties": {
            "limit": {"type": "integer", "minimum": 1, "maximum": 100},
            "offset": {"type": "integer", "minimum": 0, "maximum": 10_000},
        },
        "additionalProperties": False,
    }

    def __init__(self, service: InstructorMessageService) -> None:
        self._service = service

    async def execute(
        self, arguments: Mapping[str, JsonValue], context: ToolExecutionContext
    ) -> ToolExecutionResult:
        try:
            page = StudentDirectoryPage.model_validate(arguments)
            students = await self._service.list_students(context.principal)
        except InstructorMessageAccessDenied as error:
            raise ToolValidationError("A current instructor login is required.") from error
        except ValidationError as error:
            raise ToolValidationError("Invalid student directory pagination.") from error
        selected = students[page.offset : page.offset + page.limit]
        next_offset = page.offset + len(selected)
        return ToolExecutionResult(
            content={
                "students": [
                    {
                        "username": user.username,
                        "display_name": user.display_name,
                        "email": str(user.email),
                    }
                    for user in selected
                ],
                "total": len(students),
                "next_offset": next_offset if next_offset < len(students) else None,
            },
            summary=f"Listed {len(selected)} active student contacts for the instructor.",
            storage_policy="server_summary",
        )
