"""Validated file-backed course assignments and role-scoped read tools."""

from __future__ import annotations

import asyncio
import json
import os
import re
import unicodedata
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import ClassVar, Literal, Protocol
from uuid import UUID, uuid4

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, JsonValue, ValidationError

from agent_core import PrincipalContext
from course_server.agent.capabilities import (
    COURSE_GET_ASSIGNMENT_TOOL_ID,
    COURSE_LIST_ASSIGNMENTS_TOOL_ID,
    ToolEmittedEvent,
    ToolExecutionContext,
    ToolExecutionResult,
    ToolValidationError,
)
from course_server.workspace.models import OpenWorkspaceCommand, WorkspacePanel

MAX_ASSIGNMENTS = 500
MAX_ASSIGNMENT_BYTES = 128 * 1024
ASSIGNMENT_ROLES = frozenset({"student", "ta", "instructor"})
ASSIGNMENT_ID_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def _legacy_assignment_markdown(
    *,
    title: str,
    summary: str,
    instructions: str,
    submission_requirements: str,
) -> str:
    return (
        f"# {title}\n\n{summary}\n\n## Instructions\n\n{instructions}\n\n"
        f"## Submission requirements\n\n{submission_requirements}"
    )


def _plain_markdown(value: str) -> str:
    text = re.sub(r"\[([^\]]+)]\([^)]+\)", r"\1", value)
    text = re.sub(r"[*_`]+", "", text)
    text = re.sub(r"^\s*(?:[-*]|\d+[.)])\s+", "", text)
    text = re.sub(r"\\([\\`*{}\[\]()#+\-.!_>])", r"\1", text)
    return " ".join(text.split())


def assignment_summary(content_markdown: str, *, fallback: str) -> str:
    """Derive bounded notification text without creating a second authored summary."""

    for block in re.split(r"\n\s*\n", content_markdown):
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        prose = " ".join(line for line in lines if not line.startswith("#"))
        summary = _plain_markdown(prose)
        if summary:
            return summary[:1_000]
    return fallback[:1_000]


def generated_assignment_id(title: str, identity: UUID) -> str:
    """Create a readable opaque-enough ID without asking the instructor for one."""

    ascii_title = (
        unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode("ascii").lower()
    )
    stem = re.sub(r"[^a-z0-9]+", "-", ascii_title).strip("-") or "assignment"
    suffix = identity.hex[-8:]
    return f"{stem[:71].rstrip('-')}-{suffix}"


def _clock() -> datetime:
    return datetime.now(UTC)


def _assignment_deadline_description(value: datetime) -> str:
    """Present an aware deadline as compact, readable assignment metadata."""

    date = f"{value:%A, %B} {value.day}, {value.year}"
    time = value.strftime("%I:%M %p").lstrip("0")
    return f"Due {date} · {time}"


class AssignmentModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class AssignmentDraft(AssignmentModel):
    title: str = Field(min_length=1, max_length=200)
    summary: str | None = Field(default=None, min_length=1, max_length=1_000)
    content_markdown: str = Field(min_length=1, max_length=30_000)
    release_at: AwareDatetime
    due_at: AwareDatetime
    publish: bool

    def validate_dates(self) -> None:
        if self.due_at <= self.release_at:
            raise ValueError("due_at must be later than release_at")


class Assignment(AssignmentModel):
    schema_version: Literal[3] = 3
    assignment_id: str = Field(
        min_length=1,
        max_length=80,
        pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$",
    )
    revision: int = Field(ge=1)
    status: Literal["draft", "published"]
    title: str = Field(min_length=1, max_length=200)
    summary: str = Field(min_length=1, max_length=1_000)
    content_markdown: str = Field(min_length=1, max_length=32_000)
    release_at: AwareDatetime
    due_at: AwareDatetime
    created_at: AwareDatetime
    updated_at: AwareDatetime
    created_by_user_id: UUID

    def validate_dates(self) -> None:
        if self.due_at <= self.release_at:
            raise ValueError("due_at must be later than release_at")


class LegacyAssignmentV1(AssignmentModel):
    """Read-only compatibility shape for records created before grading was removed."""

    schema_version: Literal[1] = 1
    assignment_id: str = Field(
        min_length=1,
        max_length=80,
        pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$",
    )
    revision: int = Field(ge=1)
    status: Literal["draft", "published"]
    title: str = Field(min_length=1, max_length=200)
    summary: str = Field(min_length=1, max_length=1_000)
    instructions: str = Field(min_length=1, max_length=20_000)
    submission_requirements: str = Field(min_length=1, max_length=10_000)
    grading_criteria: str = Field(min_length=1, max_length=10_000)
    release_at: AwareDatetime
    due_at: AwareDatetime
    created_at: AwareDatetime
    updated_at: AwareDatetime
    created_by_user_id: UUID

    def into_current(self) -> Assignment:
        if self.due_at <= self.release_at:
            raise ValueError("due_at must be later than release_at")
        return Assignment(
            assignment_id=self.assignment_id,
            revision=self.revision,
            status=self.status,
            title=self.title,
            summary=self.summary,
            content_markdown=_legacy_assignment_markdown(
                title=self.title,
                summary=self.summary,
                instructions=self.instructions,
                submission_requirements=self.submission_requirements,
            ),
            release_at=self.release_at,
            due_at=self.due_at,
            created_at=self.created_at,
            updated_at=self.updated_at,
            created_by_user_id=self.created_by_user_id,
        )


class LegacyAssignmentV2(AssignmentModel):
    """Read-only compatibility shape for grading-free structured assignment records."""

    schema_version: Literal[2] = 2
    assignment_id: str = Field(
        min_length=1,
        max_length=80,
        pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$",
    )
    revision: int = Field(ge=1)
    status: Literal["draft", "published"]
    title: str = Field(min_length=1, max_length=200)
    summary: str = Field(min_length=1, max_length=1_000)
    instructions: str = Field(min_length=1, max_length=20_000)
    submission_requirements: str = Field(min_length=1, max_length=10_000)
    release_at: AwareDatetime
    due_at: AwareDatetime
    created_at: AwareDatetime
    updated_at: AwareDatetime
    created_by_user_id: UUID

    def into_current(self) -> Assignment:
        if self.due_at <= self.release_at:
            raise ValueError("due_at must be later than release_at")
        return Assignment(
            assignment_id=self.assignment_id,
            revision=self.revision,
            status=self.status,
            title=self.title,
            summary=self.summary,
            content_markdown=_legacy_assignment_markdown(
                title=self.title,
                summary=self.summary,
                instructions=self.instructions,
                submission_requirements=self.submission_requirements,
            ),
            release_at=self.release_at,
            due_at=self.due_at,
            created_at=self.created_at,
            updated_at=self.updated_at,
            created_by_user_id=self.created_by_user_id,
        )


class AssignmentStoreError(RuntimeError):
    """Stored assignment data is invalid, unavailable, or conflicts with an existing record."""


class AssignmentStore(Protocol):
    async def create(
        self,
        draft: AssignmentDraft,
        *,
        created_by_user_id: UUID,
    ) -> Assignment: ...

    async def list_for_principal(
        self,
        principal: PrincipalContext,
        *,
        now: datetime,
    ) -> list[Assignment]: ...

    async def list_all(self) -> list[Assignment]: ...

    async def get_for_principal(
        self,
        assignment_id: str,
        principal: PrincipalContext,
        *,
        now: datetime,
    ) -> Assignment | None: ...


class FileAssignmentStore:
    """One validated JSON record per assignment under a configured server directory."""

    def __init__(
        self,
        directory: Path,
        *,
        clock: Callable[[], datetime] = _clock,
        id_factory: Callable[[], UUID] = uuid4,
    ) -> None:
        self._directory = directory
        self._clock = clock
        self._id_factory = id_factory
        self._write_lock = Lock()

    async def create(
        self,
        draft: AssignmentDraft,
        *,
        created_by_user_id: UUID,
    ) -> Assignment:
        draft.validate_dates()
        now = self._clock()
        assignment = Assignment(
            assignment_id=generated_assignment_id(draft.title, self._id_factory()),
            revision=1,
            status="published" if draft.publish else "draft",
            title=draft.title,
            summary=draft.summary
            or assignment_summary(draft.content_markdown, fallback=draft.title),
            content_markdown=draft.content_markdown,
            release_at=draft.release_at,
            due_at=draft.due_at,
            created_at=now,
            updated_at=now,
            created_by_user_id=created_by_user_id,
        )
        await asyncio.to_thread(self._write, assignment)
        return assignment

    async def list_for_principal(
        self,
        principal: PrincipalContext,
        *,
        now: datetime,
    ) -> list[Assignment]:
        if not principal.authenticated or not ASSIGNMENT_ROLES.intersection(principal.roles):
            return []
        assignments = await self.list_all()
        if "instructor" in principal.roles:
            return assignments
        return [
            assignment
            for assignment in assignments
            if assignment.status == "published" and assignment.release_at <= now
        ]

    async def list_all(self) -> list[Assignment]:
        return await asyncio.to_thread(self._read_all)

    async def get_for_principal(
        self,
        assignment_id: str,
        principal: PrincipalContext,
        *,
        now: datetime,
    ) -> Assignment | None:
        assignments = await self.list_for_principal(principal, now=now)
        return next(
            (assignment for assignment in assignments if assignment.assignment_id == assignment_id),
            None,
        )

    def _write(self, assignment: Assignment) -> None:
        with self._write_lock:
            if self._directory.is_symlink():
                raise AssignmentStoreError("assignment storage directory is invalid")
            self._directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            self._directory.chmod(0o700)
            destination = self._directory / f"{assignment.assignment_id}.json"
            if destination.exists():
                raise AssignmentStoreError(f"assignment {assignment.assignment_id} already exists")
            descriptor = os.open(
                destination,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
            )
            try:
                with os.fdopen(descriptor, "w", encoding="utf-8") as output:
                    output.write(assignment.model_dump_json(indent=2))
                    output.write("\n")
            except Exception:
                destination.unlink(missing_ok=True)
                raise

    def _read_all(self) -> list[Assignment]:
        if not self._directory.exists():
            return []
        if not self._directory.is_dir() or self._directory.is_symlink():
            raise AssignmentStoreError("assignment storage directory is invalid")
        paths = sorted(self._directory.glob("*.json"))
        if len(paths) > MAX_ASSIGNMENTS:
            raise AssignmentStoreError("assignment storage exceeds its record limit")
        assignments = [self._read(path) for path in paths]
        assignments.sort(key=lambda assignment: (assignment.due_at, assignment.assignment_id))
        return assignments

    def _read(self, path: Path) -> Assignment:
        root = self._directory.resolve()
        resolved = path.resolve()
        if path.is_symlink() or not resolved.is_relative_to(root) or not resolved.is_file():
            raise AssignmentStoreError("stored assignment path is invalid")
        try:
            if resolved.stat().st_size > MAX_ASSIGNMENT_BYTES:
                raise AssignmentStoreError("stored assignment exceeds its size limit")
            raw = json.loads(resolved.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise AssignmentStoreError("stored assignment is malformed or unavailable")
            if raw.get("schema_version") == 1:
                assignment = LegacyAssignmentV1.model_validate(raw).into_current()
            elif raw.get("schema_version") == 2:
                assignment = LegacyAssignmentV2.model_validate(raw).into_current()
            else:
                assignment = Assignment.model_validate(raw)
                assignment.validate_dates()
        except (
            OSError,
            UnicodeDecodeError,
            json.JSONDecodeError,
            ValidationError,
            ValueError,
        ) as error:
            raise AssignmentStoreError("stored assignment is malformed or unavailable") from error
        if resolved.name != f"{assignment.assignment_id}.json":
            raise AssignmentStoreError("stored assignment ID does not match its filename")
        return assignment


def _require_course_member(principal: PrincipalContext) -> None:
    if not principal.authenticated or not ASSIGNMENT_ROLES.intersection(principal.roles):
        raise PermissionError("Course-member access is required.")


def _assignment_id(arguments: Mapping[str, JsonValue]) -> str:
    if set(arguments) != {"assignment_id"}:
        raise ToolValidationError("course.get_assignment requires only assignment_id.")
    value = arguments.get("assignment_id")
    if (
        not isinstance(value, str)
        or len(value) > 80
        or ASSIGNMENT_ID_PATTERN.fullmatch(value) is None
    ):
        raise ToolValidationError("assignment_id must be a lowercase hyphenated ID.")
    return value


class CourseListAssignmentsTool:
    id = COURSE_LIST_ASSIGNMENTS_TOOL_ID
    description = (
        "List assignments available to the current logged-in course member. Students and TAs "
        "receive released published assignments; instructors also receive drafts and scheduled "
        "assignments."
    )
    input_schema: ClassVar[dict[str, JsonValue]] = {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    }

    def __init__(self, assignments: AssignmentStore, *, clock: Callable[[], datetime] = _clock):
        self._assignments = assignments
        self._clock = clock

    async def execute(
        self,
        arguments: Mapping[str, JsonValue],
        context: ToolExecutionContext,
    ) -> ToolExecutionResult:
        if arguments:
            raise ToolValidationError("course.list_assignments does not accept arguments.")
        _require_course_member(context.principal)
        assignments = await self._assignments.list_for_principal(
            context.principal,
            now=self._clock(),
        )
        content = [
            {
                "assignment_id": assignment.assignment_id,
                "title": assignment.title,
                "summary": assignment.summary,
                "status": assignment.status,
                "release_at": assignment.release_at.isoformat(),
                "due_at": assignment.due_at.isoformat(),
                "revision": assignment.revision,
            }
            for assignment in assignments
        ]
        return ToolExecutionResult(
            content=content,
            summary=f"Listed {len(assignments)} authorized course assignments.",
            storage_policy="server_full",
        )


class CourseGetAssignmentTool:
    id = COURSE_GET_ASSIGNMENT_TOOL_ID
    description = (
        "Read one assignment by the assignment_id returned from course.list_assignments. "
        "Authorization and release state come from the current trusted login. A successful read "
        "opens the complete stored Markdown assignment in the workspace; do not restate it."
    )
    input_schema: ClassVar[dict[str, JsonValue]] = {
        "type": "object",
        "properties": {
            "assignment_id": {
                "type": "string",
                "pattern": "^[a-z0-9]+(?:-[a-z0-9]+)*$",
                "maxLength": 80,
            }
        },
        "required": ["assignment_id"],
        "additionalProperties": False,
    }

    def __init__(self, assignments: AssignmentStore, *, clock: Callable[[], datetime] = _clock):
        self._assignments = assignments
        self._clock = clock

    async def execute(
        self,
        arguments: Mapping[str, JsonValue],
        context: ToolExecutionContext,
    ) -> ToolExecutionResult:
        _require_course_member(context.principal)
        assignment_id = _assignment_id(arguments)
        assignment = await self._assignments.get_for_principal(
            assignment_id,
            context.principal,
            now=self._clock(),
        )
        if assignment is None:
            raise ToolValidationError("The assignment was not found or is not available.")
        resource_uri = f"course://assignment/{assignment.assignment_id}"
        command = OpenWorkspaceCommand(
            panel=WorkspacePanel(
                id=uuid4(),
                component_id="draft-document",
                title=assignment.title,
                resource_uri=resource_uri,
                props={
                    "title": assignment.title,
                    "description": _assignment_deadline_description(assignment.due_at),
                    "content": assignment.content_markdown,
                },
                state={
                    "document_kind": "course-assignment-view",
                    "assignment_id": assignment.assignment_id,
                },
            )
        )
        return ToolExecutionResult(
            content=assignment.model_dump(mode="json"),
            summary=f"Read authorized course assignment {assignment.assignment_id}.",
            storage_policy="server_full",
            resource_uris=[resource_uri],
            emitted_events=[
                ToolEmittedEvent(
                    type="workspace.panel.opened",
                    payload={
                        "command": command.model_dump(mode="json", exclude_none=True),
                    },
                )
            ],
        )
