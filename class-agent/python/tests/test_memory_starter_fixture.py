from __future__ import annotations

import asyncio
import importlib.util
import json
import stat
import subprocess
import sys
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import cast
from uuid import UUID

import pytest
from test_student_projects import context

from course_server.agent import ToolExecutionContext, ToolValidationError
from course_server.assignments import FileAssignmentStore
from course_server.auth import InMemoryAuthStore
from course_server.course_roster import load_course_roster, verify_roster_resources
from course_server.student_projects import (
    InspectMyStudentRepositoryTool,
    InspectStudentRepositoryTool,
    InspectStudentSiteTool,
    ListStudentProjectsTool,
    StudentProjectNotFound,
)
from course_server.student_projects.fixture import FixtureStudentProjectCatalog

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SETUP = PROJECT_ROOT / "examples/memory_starter/setup.py"
SETUP_SPEC = importlib.util.spec_from_file_location("memory_starter_setup", SETUP)
assert SETUP_SPEC is not None and SETUP_SPEC.loader is not None
SETUP_MODULE = importlib.util.module_from_spec(SETUP_SPEC)
SETUP_SPEC.loader.exec_module(SETUP_MODULE)
provision_users = cast(
    Callable[[InMemoryAuthStore], Awaitable[list[tuple[str, str]]]],
    SETUP_MODULE.provision_users,
)
require_local_database = cast(Callable[[str], None], SETUP_MODULE.require_local_database)


def test_memory_starter_installs_only_fictional_private_data(tmp_path: Path) -> None:
    command = [sys.executable, str(SETUP), "--data-only", "--output-root", str(tmp_path)]
    first = subprocess.run(command, cwd=PROJECT_ROOT, capture_output=True, text=True, check=False)

    assert first.returncode == 0, first.stderr
    roster_path = tmp_path / "var/roster/course-members.json"
    roster = load_course_roster(roster_path)
    assert roster is not None
    assert {member.username for member in roster.members} == {
        "ada-demo",
        "bo-demo",
        "cy-demo",
        "dee-demo",
        "eli-demo",
    }
    assert len(roster.active_members) == 4
    assert roster.identifies_inactive_username("eli-demo")
    assert all(str(member.email).endswith("@example.org") for member in roster.members)
    assert all(member.application_id is None for member in roster.members)
    assert stat.S_IMODE(roster_path.stat().st_mode) == 0o600
    verify_roster_resources(roster, tmp_path / "data")
    assignments = FileAssignmentStore(tmp_path / "var/assignments")._read_all()
    assert {assignment.assignment_id for assignment in assignments} == {
        *(f"week-{number}" for number in range(1, 9)),
        "final-project-team-formation",
    }
    assert all(
        assignment.created_by_user_id == UUID("00000000-0000-4000-8000-000000000001")
        for assignment in assignments
    )
    week_eight = next(a for a in assignments if a.assignment_id == "week-8")
    assert "personalization feature" in week_eight.content_markdown
    assert "Jad Bendarkawi" not in week_eight.content_markdown
    for assignment in assignments:
        authoring_copy = (
            tmp_path / f"var/assignments/{assignment.assignment_id}/{assignment.assignment_id}.md"
        )
        assert (
            authoring_copy.read_text(encoding="utf-8").strip()
            == assignment.content_markdown.strip()
        )

    original = roster_path.read_bytes()
    second = subprocess.run(command, cwd=PROJECT_ROOT, capture_output=True, text=True, check=False)
    assert second.returncode == 0, second.stderr
    assert roster_path.read_bytes() == original

    changed = json.loads(original)
    changed["members"][0]["name"] = "Existing Real Student"
    roster_path.write_text(json.dumps(changed), encoding="utf-8")
    blocked = subprocess.run(command, cwd=PROJECT_ROOT, capture_output=True, text=True, check=False)
    assert blocked.returncode != 0
    assert "Refusing to replace an existing local roster" in blocked.stderr
    assert json.loads(roster_path.read_text(encoding="utf-8")) == changed


def test_memory_starter_refuses_to_replace_assignment(tmp_path: Path) -> None:
    command = [sys.executable, str(SETUP), "--data-only", "--output-root", str(tmp_path)]
    first = subprocess.run(command, cwd=PROJECT_ROOT, capture_output=True, text=True, check=False)
    assert first.returncode == 0, first.stderr
    assignment_path = tmp_path / "var/assignments/week-8/week-8.json"
    original = assignment_path.read_bytes()
    assignment_path.write_bytes(b'{"local": "student work"}')

    blocked = subprocess.run(command, cwd=PROJECT_ROOT, capture_output=True, text=True, check=False)
    assert blocked.returncode != 0
    assert "Refusing to replace a local assignment" in blocked.stderr
    assert assignment_path.read_bytes() != original


def test_memory_starter_provisions_matching_accounts_once() -> None:
    async def scenario() -> None:
        store = InMemoryAuthStore()
        issued = await provision_users(store)
        assert {username for username, _ in issued} == {
            "ada-demo",
            "bo-demo",
            "cy-demo",
            "dee-demo",
            "eli-demo",
            "teacher-demo",
            "ta-demo",
        }
        assert all(code for _, code in issued)
        assert await provision_users(store) == []
        assert {user.role for user in store.users.values()} == {"student", "ta", "instructor"}

    asyncio.run(scenario())


def test_memory_starter_rejects_remote_database() -> None:
    require_local_database("postgresql://class_agent:dev@localhost:5432/class_agent")
    with pytest.raises(ValueError, match="loopback"):
        require_local_database("postgresql://class_agent:dev@db.example.org:5432/class_agent")


def test_memory_starter_projects_follow_live_tool_and_roster_boundaries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Fixture and authorization behavior is covered here; the adapter has separate thread tests.
    async def direct_call(
        function: Callable[..., object], *args: object, **kwargs: object
    ) -> object:
        return function(*args, **kwargs)

    monkeypatch.setattr("course_server.student_projects.tools.asyncio.to_thread", direct_call)
    roster = load_course_roster(PROJECT_ROOT / "examples/memory_starter/course-members.json")
    assert roster is not None
    projects = FixtureStudentProjectCatalog(roster)
    assert {project.id for project in projects.list_projects()} == roster.active_weekly_project_ids
    for view in ("summary", "tree", "commits", "branches", "pulls", "issues", "workflows"):
        result = projects.inspect_repository("agents2026-ada-demo", view)
        assert result["provider"] == "fixture"
        assert result["view"] == view
    with pytest.raises(StudentProjectNotFound):
        projects.inspect_repository("agents2026-eli-demo", "summary")

    async def scenario() -> None:
        base = context("student")
        ada = ToolExecutionContext(
            principal=base.principal.model_copy(update={"username": "ada-demo"}),
            conversation_id=base.conversation_id,
            permitted_resource_uris=base.permitted_resource_uris,
        )
        listed = await ListStudentProjectsTool(projects).execute({}, ada)
        assert isinstance(listed.content, dict)
        assert listed.content["provider"] == "fixture"
        assert listed.content["count"] == 4

        own = await InspectMyStudentRepositoryTool(projects, "agents2026-").execute(
            {"view": "file", "path": "weeks/week-03.md"}, ada
        )
        assert isinstance(own.content, dict)
        assert "MCP is the interface" in str(own.content["text"])
        assert own.content["provider"] == "fixture"

        site = await InspectStudentSiteTool(projects, projects.visit_site).execute(
            {"project_id": "agents2026-bo-demo"}, ada
        )
        assert isinstance(site.content, dict)
        assert "visual timeline" in str(site.content["page"])

        with pytest.raises(ToolValidationError, match="TA, instructor, or admin"):
            await InspectStudentRepositoryTool(projects).execute(
                {"project_id": "agents2026-bo-demo", "view": "summary"}, ada
            )
        with pytest.raises(ToolValidationError, match="No course project repository"):
            unknown = context("student")
            await InspectMyStudentRepositoryTool(projects, "agents2026-").execute(
                {"view": "summary"}, unknown
            )

    asyncio.run(scenario())
