"""Grade route ownership and workspace persistence using fictional feedback."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import httpx
from test_fastapi_api import _build_client

from agent_core import PrincipalContext
from course_server.assignments import Assignment, AssignmentDraft
from course_server.grades import FileGradeBook


class OneAssignmentStore:
    def __init__(self, assignment: Assignment) -> None:
        self.assignment = assignment

    async def create(self, draft: AssignmentDraft, *, created_by_user_id: UUID) -> Assignment:
        raise NotImplementedError

    async def list_all(self) -> list[Assignment]:
        return [self.assignment]

    async def list_for_principal(
        self, principal: PrincipalContext, *, now: datetime
    ) -> list[Assignment]:
        return (
            [self.assignment]
            if principal.authenticated
            and "student" in principal.roles
            and self.assignment.release_at <= now
            else []
        )

    async def get_for_principal(
        self, assignment_id: str, principal: PrincipalContext, *, now: datetime
    ) -> Assignment | None:
        visible = await self.list_for_principal(principal, now=now)
        return visible[0] if visible and visible[0].assignment_id == assignment_id else None


def test_grade_routes_keep_feedback_owned_and_out_of_workspace_events(tmp_path: Path) -> None:
    now = datetime.now(UTC)
    assignment = Assignment(
        assignment_id="week-3",
        revision=1,
        status="published",
        title="Week 3 Build",
        summary="Fictional build instructions",
        content_markdown="# Week 3 Build\n\nBuild a fictional agent.",
        release_at=now - timedelta(days=1),
        due_at=now + timedelta(days=1),
        created_at=now,
        updated_at=now,
        created_by_user_id=uuid4(),
    )
    grade_path = tmp_path / "weekly-feedback.json"
    grade_path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "weekly_build_assignment_ids": ["week-3"],
                "students": {
                    "alice": [
                        {
                            "week": 3,
                            "date": "2026-10-17",
                            "reviewer": "Fictional TA",
                            "feedback": "Alice fictional private feedback",
                        }
                    ],
                    "bob": [
                        {
                            "week": 3,
                            "date": "2026-10-17",
                            "reviewer": "Fictional TA",
                            "feedback": "Bob fictional private feedback",
                        }
                    ],
                },
            }
        ),
        encoding="utf-8",
    )
    client, access_code, runtime = _build_client(
        assignment_store=OneAssignmentStore(assignment),
        grade_store=FileGradeBook(
            grade_path, credit_usernames=frozenset({"alice", "bob"})
        ),
    )

    async def scenario() -> None:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=client.app), base_url="https://testserver"
        ) as site:
            assert (await site.get("/grades/mine")).status_code == 404
            login = await site.post(
                "/auth/login", json={"username": "alice", "access_code": access_code}
            )
            assert login.status_code == 200
            overview = await site.get("/grades/mine")
            assert overview.status_code == 200
            assert overview.headers["cache-control"] == "private, no-store"
            assert overview.json() == {
                "assignments": [
                    {"assignment_id": "week-3", "title": "Week 3 Build", "has_feedback": True}
                ]
            }
            assert "private feedback" not in overview.text
            note = await site.get("/grades/mine/assignments/week-3")
            assert note.status_code == 200
            assert note.json()["feedback"]["feedback"] == "Alice fictional private feedback"
            assert "Bob fictional private feedback" not in note.text
            assert (await site.get("/grades/mine/assignments/week-7")).status_code == 404

            conversation_id = (
                await site.post("/conversations", json={"title": "Grading"})
            ).json()["id"]
            for payload in (
                {"target": "grading"},
                {"target": "assignment", "assignment_id": "week-3"},
            ):
                opened = await site.post(
                    f"/conversations/{conversation_id}/workspace/open-static", json=payload
                )
                assert opened.status_code == 200
                assert "private feedback" not in opened.text
            events = (await site.get(f"/conversations/{conversation_id}")).json()["events"]
            assert "private feedback" not in json.dumps(events)
            assert runtime.inputs == []

    asyncio.run(scenario())
