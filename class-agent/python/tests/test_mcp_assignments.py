from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from agent_core import PrincipalContext
from course_server.assignments import AssignmentDraft, FileAssignmentStore
from course_server.mcp_assignments import CourseMcpAssignmentService


def test_mcp_assignment_links_are_scoped_and_point_to_course_agent(tmp_path: Path) -> None:
    async def scenario() -> None:
        now = datetime.now(UTC)
        ids = iter(
            [
                UUID("00000000-0000-4000-8000-000000000001"),
                UUID("00000000-0000-4000-8000-000000000002"),
            ]
        )
        store = FileAssignmentStore(
            tmp_path / "assignments", clock=lambda: now, id_factory=lambda: next(ids)
        )
        published = await store.create(
            AssignmentDraft(
                title="Week 6",
                content_markdown="# Week 6\n\nExact posted requirement.",
                release_at=now - timedelta(days=1),
                due_at=now + timedelta(days=7),
                publish=True,
            ),
            created_by_user_id=uuid4(),
        )
        hidden = await store.create(
            AssignmentDraft(
                title="Hidden draft",
                content_markdown="# Hidden draft",
                release_at=now - timedelta(days=1),
                due_at=now + timedelta(days=7),
                publish=False,
            ),
            created_by_user_id=uuid4(),
        )
        student = PrincipalContext(
            authenticated=True,
            user_id=uuid4(),
            username="student",
            display_name="Student",
            roles=["public", "student"],
            session_id=uuid4(),
        )
        service = CourseMcpAssignmentService(store, public_base_url="https://course.example/")
        link = (
            f"https://course.example/?q=open_{published.assignment_id.replace('-', '_')}_assignment"
        )

        listed = await service.list_assignments(student)
        assert len(listed) == 1
        assert listed[0]["open_in_course_agent_url"] == link
        read = await service.get_assignment(student, published.assignment_id)
        assert read["content_markdown"] == "# Week 6\n\nExact posted requirement."
        assert read["open_in_course_agent_url"] == link
        instruction = " ".join(read["assistant_instruction"].split())
        assert "Do not supply unsolicited examples" in instruction
        assert "A student's short reply" in instruction
        assert "Whenever you select, shorten, paraphrase" in instruction
        assert "not the full original" in instruction
        with pytest.raises(ValueError, match="not available"):
            await service.get_assignment(student, hidden.assignment_id)

    asyncio.run(scenario())
