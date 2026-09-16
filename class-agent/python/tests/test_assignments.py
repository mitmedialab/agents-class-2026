from __future__ import annotations

import asyncio
import json
import stat
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from agent_core import PrincipalContext, Role
from course_server.agent import ToolExecutionContext, ToolValidationError
from course_server.assignments import (
    AssignmentDraft,
    CourseGetAssignmentTool,
    CourseListAssignmentsTool,
    FileAssignmentStore,
)

FIXED_ASSIGNMENT_IDENTITY = UUID("00000000-0000-4000-8000-000000000001")
GENERATED_ASSIGNMENT_ID = "test-assignment-00000001"


def principal(role: Role) -> PrincipalContext:
    if role == "public":
        session_id = uuid4()
        return PrincipalContext(
            authenticated=False,
            anonymous_session_id=session_id,
            roles=["public"],
            session_id=session_id,
        )
    return PrincipalContext(
        authenticated=True,
        user_id=uuid4(),
        username=f"test-{role}",
        display_name=f"Test {role.title()}",
        roles=["public", role],
        session_id=uuid4(),
    )


def context(role: Role) -> ToolExecutionContext:
    return ToolExecutionContext(
        principal=principal(role),
        conversation_id=uuid4(),
        permitted_resource_uris=frozenset(),
        workspace_state={"panels": []},
    )


def assignment_draft(now: datetime, *, publish: bool = True) -> AssignmentDraft:
    return AssignmentDraft(
        title="Test assignment",
        content_markdown=(
            "# Test assignment\n\nBuild and document one small cognitive agent.\n\n"
            "## Instructions\n\nCreate a working agent and explain the design decisions.\n\n"
            "## Submission\n\nSubmit a repository URL and a short reflection."
        ),
        release_at=now - timedelta(hours=1),
        due_at=now + timedelta(days=12),
        publish=publish,
    )


def test_stored_assignment_is_available_through_role_scoped_read_tools(tmp_path: Path) -> None:
    async def scenario() -> None:
        now = datetime(2026, 9, 6, 15, tzinfo=UTC)
        store = FileAssignmentStore(
            tmp_path / "assignments",
            clock=lambda: now,
            id_factory=lambda: FIXED_ASSIGNMENT_IDENTITY,
        )
        instructor = principal("instructor")
        assert instructor.user_id is not None
        assignment = await store.create(
            assignment_draft(now),
            created_by_user_id=instructor.user_id,
        )

        assert assignment.assignment_id == GENERATED_ASSIGNMENT_ID
        path = tmp_path / f"assignments/{GENERATED_ASSIGNMENT_ID}.json"
        record = json.loads(path.read_text(encoding="utf-8"))
        assert record["schema_version"] == 3
        assert record["summary"] == "Build and document one small cognitive agent."
        assert stat.S_IMODE(path.stat().st_mode) == 0o600

        student_context = context("student")
        listed = await CourseListAssignmentsTool(store, clock=lambda: now).execute(
            {}, student_context
        )
        assert isinstance(listed.content, list)
        assert isinstance(listed.content[0], dict)
        assert listed.content[0]["assignment_id"] == GENERATED_ASSIGNMENT_ID
        read = await CourseGetAssignmentTool(store, clock=lambda: now).execute(
            {"assignment_id": GENERATED_ASSIGNMENT_ID}, student_context
        )
        assert isinstance(read.content, dict)
        assert read.content["content_markdown"] == record["content_markdown"]
        opened = read.emitted_events[0].payload["command"]
        assert isinstance(opened, dict)
        opened_panel = opened["panel"]
        assert isinstance(opened_panel, dict)
        opened_props = opened_panel["props"]
        assert isinstance(opened_props, dict)
        assert opened_props["content"] == record["content_markdown"]
        assert opened_props["description"] == ("Due Friday, September 18, 2026 · 3:00 PM")
        assert "status" not in opened_props
        assert opened_panel["resource_uri"] == f"course://assignment/{GENERATED_ASSIGNMENT_ID}"

        with pytest.raises(PermissionError, match="Course-member"):
            await CourseListAssignmentsTool(store, clock=lambda: now).execute({}, context("public"))

    asyncio.run(scenario())


def test_drafts_and_scheduled_assignments_are_instructor_only(tmp_path: Path) -> None:
    async def scenario() -> None:
        now = datetime(2026, 9, 6, 15, tzinfo=UTC)
        store = FileAssignmentStore(
            tmp_path / "assignments",
            clock=lambda: now,
            id_factory=lambda: FIXED_ASSIGNMENT_IDENTITY,
        )
        instructor = context("instructor")
        assert instructor.principal.user_id is not None
        await store.create(
            assignment_draft(now, publish=False),
            created_by_user_id=instructor.principal.user_id,
        )

        instructor_list = await CourseListAssignmentsTool(store, clock=lambda: now).execute(
            {}, instructor
        )
        student_list = await CourseListAssignmentsTool(store, clock=lambda: now).execute(
            {}, context("student")
        )

        assert isinstance(instructor_list.content, list)
        assert isinstance(instructor_list.content[0], dict)
        assert instructor_list.content[0]["status"] == "draft"
        assert student_list.content == []
        with pytest.raises(ToolValidationError, match="not found or is not available"):
            await CourseGetAssignmentTool(store, clock=lambda: now).execute(
                {"assignment_id": GENERATED_ASSIGNMENT_ID}, context("student")
            )

    asyncio.run(scenario())


def test_assignment_dates_must_define_a_positive_work_window(tmp_path: Path) -> None:
    async def scenario() -> None:
        now = datetime(2026, 9, 6, 15, tzinfo=UTC)
        store = FileAssignmentStore(tmp_path / "assignments", clock=lambda: now)
        instructor = principal("instructor")
        assert instructor.user_id is not None
        invalid = assignment_draft(now).model_copy(update={"release_at": now + timedelta(days=13)})

        with pytest.raises(ValueError, match="due_at"):
            await store.create(invalid, created_by_user_id=instructor.user_id)

    asyncio.run(scenario())


def test_schema_v2_assignment_is_projected_as_markdown(tmp_path: Path) -> None:
    async def scenario() -> None:
        now = datetime(2026, 9, 6, 15, tzinfo=UTC)
        directory = tmp_path / "assignments"
        directory.mkdir()
        path = directory / "structured-assignment.json"
        path.write_text(
            json.dumps(
                {
                    "schema_version": 2,
                    "assignment_id": "structured-assignment",
                    "revision": 2,
                    "status": "published",
                    "title": "Structured assignment",
                    "summary": "A prior grading-free assignment.",
                    "instructions": "Build one agent.",
                    "submission_requirements": "Submit the documented source.",
                    "release_at": (now - timedelta(hours=1)).isoformat(),
                    "due_at": (now + timedelta(days=2)).isoformat(),
                    "created_at": now.isoformat(),
                    "updated_at": now.isoformat(),
                    "created_by_user_id": str(uuid4()),
                }
            ),
            encoding="utf-8",
        )
        current = await FileAssignmentStore(directory).get_for_principal(
            "structured-assignment", principal("student"), now=now
        )

        assert current is not None
        assert current.schema_version == 3
        assert current.content_markdown == (
            "# Structured assignment\n\nA prior grading-free assignment.\n\n"
            "## Instructions\n\nBuild one agent.\n\n"
            "## Submission requirements\n\nSubmit the documented source."
        )
        assert json.loads(path.read_text())["schema_version"] == 2

    asyncio.run(scenario())


def test_schema_v1_assignment_remains_readable_without_rewriting_source(tmp_path: Path) -> None:
    async def scenario() -> None:
        now = datetime(2026, 9, 6, 15, tzinfo=UTC)
        directory = tmp_path / "assignments"
        directory.mkdir()
        path = directory / "legacy-assignment.json"
        path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "assignment_id": "legacy-assignment",
                    "revision": 1,
                    "status": "draft",
                    "title": "Legacy assignment",
                    "summary": "Created before grading was removed.",
                    "instructions": "Build a small agent.",
                    "submission_requirements": "Submit a repository URL.",
                    "grading_criteria": "Legacy field retained only for compatibility.",
                    "release_at": (now - timedelta(hours=1)).isoformat(),
                    "due_at": (now + timedelta(days=2)).isoformat(),
                    "created_at": now.isoformat(),
                    "updated_at": now.isoformat(),
                    "created_by_user_id": str(uuid4()),
                }
            ),
            encoding="utf-8",
        )
        current = await FileAssignmentStore(directory).get_for_principal(
            "legacy-assignment", principal("instructor"), now=now
        )

        assert current is not None
        assert current.schema_version == 3
        assert "grading_criteria" not in current.model_dump()
        assert "## Instructions" in current.content_markdown
        assert json.loads(path.read_text(encoding="utf-8"))["schema_version"] == 1

    asyncio.run(scenario())
