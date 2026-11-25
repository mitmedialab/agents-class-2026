from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from agent_core import PrincipalContext
from course_server.assignments import Assignment, FileAssignmentStore
from course_server.grades import FileGradeBook
from course_server.mcp_grades import CourseMcpGradeService


def _principal(username: str, role: str = "student") -> PrincipalContext:
    return PrincipalContext(
        authenticated=True,
        user_id=uuid4(),
        username=username,
        roles=["public", role],
        session_id=uuid4(),
    )


def _assignment(directory: Path, assignment_id: str, *, released: bool) -> None:
    now = datetime.now(UTC)
    assignment = Assignment(
        assignment_id=assignment_id,
        revision=1,
        status="published",
        title=f"Week {assignment_id[5:]} Build",
        summary="Build a course agent.",
        content_markdown="# Build\n\nBuild a course agent.",
        release_at=now - timedelta(days=1) if released else now + timedelta(days=1),
        due_at=now + timedelta(days=7),
        created_at=now,
        updated_at=now,
        created_by_user_id=uuid4(),
    )
    directory.mkdir(exist_ok=True)
    (directory / f"{assignment_id}.json").write_text(assignment.model_dump_json(), encoding="utf-8")


def test_mcp_feedback_is_released_and_own_credit_student_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def inline_to_thread(function: object, *args: object, **kwargs: object) -> object:
        assert callable(function)
        return function(*args, **kwargs)

    monkeypatch.setattr(asyncio, "to_thread", inline_to_thread)
    assignments_path = tmp_path / "assignments"
    _assignment(assignments_path, "week-3", released=True)
    _assignment(assignments_path, "week-4", released=False)
    grades_path = tmp_path / "feedback.json"
    grades_path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "weekly_build_assignment_ids": ["week-3", "week-4"],
                "students": {
                    "alice": [
                        {
                            "week": 3,
                            "date": "2026-10-17",
                            "reviewer": "Course TA",
                            "feedback": "Alice private checklist and comments.",
                        }
                    ],
                    "bob": [
                        {
                            "week": 3,
                            "date": "2026-10-17",
                            "reviewer": "Course TA",
                            "feedback": "Bob private feedback.",
                        }
                    ],
                },
            }
        ),
        encoding="utf-8",
    )
    service = CourseMcpGradeService(
        FileGradeBook(grades_path, credit_usernames=frozenset({"alice", "bob", "charlie"})),
        FileAssignmentStore(assignments_path),
    )

    async def scenario() -> None:
        alice = _principal("alice")
        assert await service.list_feedback(alice) == [
            {"assignment_id": "week-3", "title": "Week 3 Build", "has_feedback": True}
        ]
        own = await service.read_feedback(alice, "week-3")
        assert own["feedback"]["feedback"] == "Alice private checklist and comments."
        assert "Bob private feedback" not in str(own)
        assert (await service.read_feedback(_principal("charlie"), "week-3"))["feedback"] is None
        with pytest.raises(ValueError, match="unavailable"):
            await service.read_feedback(alice, "week-4")
        for denied in (_principal("listener"), _principal("alice", "ta")):
            with pytest.raises(PermissionError):
                await service.list_feedback(denied)
            with pytest.raises(PermissionError):
                await service.read_feedback(denied, "week-3")

    asyncio.run(scenario())
