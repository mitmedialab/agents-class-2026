"""Student-owned weekly feedback, kept outside public course resources and events."""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path
from typing import ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, ValidationError, model_validator

from agent_core import PrincipalContext
from course_server.agent.capabilities import (
    GET_MY_GRADES_TOOL_ID,
    ToolExecutionContext,
    ToolExecutionResult,
)


class WeeklyFeedback(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    week: int = Field(ge=1, le=52)
    date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    reviewer: str = Field(min_length=1, max_length=120)
    feedback: str = Field(min_length=1, max_length=20_000)


class GradeBookData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[2]
    weekly_build_assignment_ids: list[str]
    students: dict[str, list[WeeklyFeedback]]

    @model_validator(mode="after")
    def unique_weeks(self) -> GradeBookData:
        ids = self.weekly_build_assignment_ids
        if len(ids) != len(set(ids)) or any(
            not assignment_id.startswith("week-")
            or not assignment_id[5:].isdigit()
            or int(assignment_id[5:]) < 2
            for assignment_id in ids
        ):
            raise ValueError("weekly build assignment IDs must be unique weeks after Week 1")
        for username, notes in self.students.items():
            if not username or username != username.strip().casefold():
                raise ValueError("gradebook usernames must be normalized")
            weeks = [note.week for note in notes]
            if len(weeks) != len(set(weeks)):
                raise ValueError(f"duplicate feedback week for {username}")
            if any(f"week-{week}" not in ids for week in weeks):
                raise ValueError(f"feedback for {username} is not a graded weekly build")
        return self


class FileGradeBook:
    """Read only the feedback for the trusted authenticated student username."""

    def __init__(
        self,
        path: Path,
        *,
        credit_usernames: frozenset[str],
        preview_username: str | None = None,
        preview_path: Path | None = None,
        preview_only: bool = False,
    ) -> None:
        if (preview_username is None) != (preview_path is None):
            raise ValueError("grade preview username and path must be configured together")
        if preview_username is not None and (
            not re.fullmatch(r"test-[a-z0-9._-]+", preview_username)
            or preview_username in credit_usernames
            or preview_path == path
        ):
            raise ValueError("grade preview must use a separate test account")
        if preview_only and preview_username is None:
            raise ValueError("preview-only grading requires a test account")
        self.path = path
        self.credit_usernames = credit_usernames
        self.preview_username = preview_username
        self.preview_path = preview_path
        self.preview_only = preview_only

    def can_access(self, principal: PrincipalContext) -> bool:
        return bool(
            principal.authenticated
            and "student" in principal.roles
            and principal.username
            and (
                (not self.preview_only and principal.username.casefold() in self.credit_usernames)
                or principal.username.casefold() == self.preview_username
            )
        )

    def _load(self, principal: PrincipalContext) -> GradeBookData:
        preview = (
            principal.username is not None
            and principal.username.casefold() == self.preview_username
        )
        path = self.preview_path if preview else self.path
        assert path is not None
        try:
            data = GradeBookData.model_validate_json(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            if preview:
                raise ValueError("grade preview file is unavailable") from None
            return GradeBookData(schema_version=2, weekly_build_assignment_ids=[], students={})
        except (OSError, ValidationError) as error:
            raise ValueError("private gradebook is unavailable or invalid") from error
        if preview and set(data.students) != {self.preview_username}:
            raise ValueError("grade preview must contain only the configured test account")
        return data

    def get_mine(self, principal: PrincipalContext) -> list[WeeklyFeedback]:
        if not self.can_access(principal):
            raise PermissionError("active credit student login required")
        assert principal.username is not None
        return sorted(
            self._load(principal).students.get(principal.username.casefold(), []),
            key=lambda note: note.week,
        )

    def weekly_build_summary(
        self, principal: PrincipalContext
    ) -> tuple[tuple[str, ...], frozenset[int]]:
        if not self.can_access(principal):
            raise PermissionError("active credit student login required")
        assert principal.username is not None
        data = self._load(principal)
        return (
            tuple(data.weekly_build_assignment_ids),
            frozenset(note.week for note in data.students.get(principal.username.casefold(), [])),
        )

    def feedback_for_assignment(
        self, principal: PrincipalContext, assignment_id: str
    ) -> WeeklyFeedback | None:
        if not self.can_access(principal):
            raise PermissionError("active credit student login required")
        assert principal.username is not None
        data = self._load(principal)
        if assignment_id not in data.weekly_build_assignment_ids:
            raise KeyError(assignment_id)
        week = int(assignment_id[5:])
        return next(
            (
                note
                for note in data.students.get(principal.username.casefold(), [])
                if note.week == week
            ),
            None,
        )

    def markdown_for(self, principal: PrincipalContext) -> str:
        notes = self.get_mine(principal)
        if not notes:
            return (
                "# Grading\n\n## Weekly build feedback\n\n"
                "No weekly feedback has been recorded for you yet.\n"
            )
        sections = ["# Grading", "## Weekly build feedback"]
        for note in notes:
            sections.append(
                f"### Week {note.week}\n\n{note.reviewer} · {note.date}\n\n{note.feedback.strip()}"
            )
        return "\n\n".join(sections) + "\n"


class GetMyGradesTool:
    """Agent-facing own-feedback read with identity derived only from PrincipalContext."""

    id = GET_MY_GRADES_TOOL_ID
    description = (
        "Read the logged-in credit student's own weekly build feedback and checklist. "
        "The feedback is qualitative; do not infer numeric grades."
    )
    input_schema: ClassVar[dict[str, JsonValue]] = {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    }

    def __init__(self, grades: FileGradeBook) -> None:
        self._grades = grades

    async def execute(
        self, arguments: Mapping[str, JsonValue], context: ToolExecutionContext
    ) -> ToolExecutionResult:
        if arguments:
            raise ValueError("grades.get_mine does not accept arguments")
        return ToolExecutionResult(
            content=self._grades.markdown_for(context.principal),
            summary="Read the current student's weekly feedback.",
            storage_policy="server_summary",
        )
