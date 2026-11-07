from __future__ import annotations

import asyncio
import json
from pathlib import Path
from uuid import uuid4

import pytest

from agent_core import PrincipalContext
from course_server.agent.capabilities import CourseCapabilityPolicy, ToolExecutionContext
from course_server.grades import FileGradeBook, GetMyGradesTool


def principal(username: str | None, role: str = "student") -> PrincipalContext:
    if username is None:
        return PrincipalContext(
            authenticated=False,
            anonymous_session_id=uuid4(),
            roles=["public"],
            session_id=uuid4(),
        )
    return PrincipalContext(
        authenticated=True,
        user_id=uuid4(),
        username=username,
        roles=["public", role],
        session_id=uuid4(),
    )


def test_gradebook_only_reads_current_student_and_does_not_persist_result(tmp_path: Path) -> None:
    path = tmp_path / "weekly-feedback.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "weekly_build_assignment_ids": ["week-2", "week-3"],
                "students": {
                    "alice": [
                        {
                            "week": 3,
                            "date": "2026-10-17",
                            "reviewer": "Course TA",
                            "feedback": (
                                "Alice private feedback.\n\nGrading Checklist:\n✓ Code link"
                            ),
                        }
                    ],
                    "bob": [
                        {
                            "week": 2,
                            "date": "2026-10-09",
                            "reviewer": "Course TA",
                            "feedback": "Bob private feedback.",
                        }
                    ],
                },
            }
        ),
        encoding="utf-8",
    )
    grades = FileGradeBook(path, credit_usernames=frozenset({"alice", "bob", "charlie"}))
    alice = principal("alice")
    own = grades.markdown_for(alice)
    assert "Alice private feedback" in own
    assert "Bob private feedback" not in own
    assert "Week 3" in own
    assert "Bob private feedback" in grades.markdown_for(principal("bob"))
    assert "No weekly feedback" in grades.markdown_for(principal("charlie"))
    for denied in (principal(None), principal("alice", "ta"), principal("alice", "instructor")):
        with pytest.raises(PermissionError):
            grades.markdown_for(denied)
    with pytest.raises(PermissionError):
        FileGradeBook(path, credit_usernames=frozenset({"alice"})).get_mine(principal("bob"))
    assert grades.feedback_for_assignment(alice, "week-3") == grades.get_mine(alice)[0]
    assert grades.feedback_for_assignment(alice, "week-2") is None
    with pytest.raises(KeyError):
        grades.feedback_for_assignment(alice, "week-7")

    tool = GetMyGradesTool(grades)
    result = asyncio.run(
        tool.execute(
            {},
            ToolExecutionContext(
                principal=alice, conversation_id=uuid4(), permitted_resource_uris=frozenset()
            ),
        )
    )
    assert isinstance(result.content, str)
    assert "Alice private feedback" in result.content
    assert result.storage_policy == "server_summary"
    assert "Alice private feedback" not in (result.summary or "")
    with pytest.raises(ValueError):
        asyncio.run(
            tool.execute(
                {"username": "bob"},
                ToolExecutionContext(
                    principal=alice, conversation_id=uuid4(), permitted_resource_uris=frozenset()
                ),
            )
        )


def test_grade_capability_is_active_credit_student_only() -> None:
    policy = CourseCapabilityPolicy(
        grades_enabled=True,
        grade_access=FileGradeBook(
            Path("unused"), credit_usernames=frozenset({"alice"})
        ).can_access,
    )
    assert "grades.get_mine" in policy.authorize(principal("alice")).tool_ids
    for denied in (principal(None), principal("alice", "ta"), principal("alice", "instructor")):
        assert "grades.get_mine" not in policy.authorize(denied).tool_ids
    assert "grades.get_mine" not in policy.authorize(principal("bob")).tool_ids


def test_gradebook_rejects_duplicate_weeks(tmp_path: Path) -> None:
    path = tmp_path / "weekly-feedback.json"
    note = {"week": 3, "date": "2026-10-17", "reviewer": "Course TA", "feedback": "Good work"}
    path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "weekly_build_assignment_ids": ["week-3"],
                "students": {"alice": [note, note]},
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="invalid"):
        FileGradeBook(path, credit_usernames=frozenset({"alice"})).get_mine(principal("alice"))


def test_preview_account_reads_only_its_sample_gradebook(tmp_path: Path) -> None:
    real_path = tmp_path / "real.json"
    preview_path = tmp_path / "preview.json"
    for path, username, text in (
        (real_path, "alice", "Alice private feedback"),
        (preview_path, "test-student2", "SAMPLE feedback"),
    ):
        path.write_text(
            json.dumps(
                {
                    "schema_version": 2,
                    "weekly_build_assignment_ids": ["week-3"],
                    "students": {
                        username: [
                            {"week": 3, "date": "2026-11-05", "reviewer": "TA", "feedback": text}
                        ]
                    },
                }
            ),
            encoding="utf-8",
        )
    grades = FileGradeBook(
        real_path,
        credit_usernames=frozenset({"alice"}),
        preview_username="test-student2",
        preview_path=preview_path,
    )
    assert "SAMPLE feedback" in grades.markdown_for(principal("test-student2"))
    assert "Alice private feedback" not in grades.markdown_for(principal("test-student2"))
    assert "Alice private feedback" in grades.markdown_for(principal("alice"))
    assert "SAMPLE feedback" not in grades.markdown_for(principal("alice"))
    assert not grades.can_access(principal("test-student2", role="ta"))
    assert not grades.can_access(principal("test-student3"))
    preview_only = FileGradeBook(
        real_path,
        credit_usernames=frozenset({"alice"}),
        preview_username="test-student2",
        preview_path=preview_path,
        preview_only=True,
    )
    assert preview_only.can_access(principal("test-student2"))
    assert not preview_only.can_access(principal("alice"))
    with pytest.raises(PermissionError):
        preview_only.get_mine(principal("alice"))
    with pytest.raises(ValueError, match="separate test account"):
        FileGradeBook(
            real_path,
            credit_usernames=frozenset({"test-student2"}),
            preview_username="test-student2",
            preview_path=preview_path,
        )
    with pytest.raises(ValueError, match="separate test account"):
        FileGradeBook(
            real_path,
            credit_usernames=frozenset(),
            preview_username="test-student2",
            preview_path=real_path,
        )
    with pytest.raises(ValueError, match="requires a test account"):
        FileGradeBook(real_path, credit_usernames=frozenset(), preview_only=True)
    preview_path.write_text(real_path.read_text(encoding="utf-8"), encoding="utf-8")
    with pytest.raises(ValueError, match="only the configured test account"):
        grades.get_mine(principal("test-student2"))
