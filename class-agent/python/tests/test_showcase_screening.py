from __future__ import annotations

import asyncio
import threading
import time
from pathlib import Path

import pytest
from test_student_projects import FakeStudentProjects, context

from course_server.agent import ToolValidationError
from course_server.student_projects import InspectStudentSiteTool, StudentProject
from course_server.student_projects.screening import ScreenShowcaseTool


def test_screening_bounds_cooldown_failures_and_run_cache(tmp_path: Path) -> None:
    path = tmp_path / "history.json"
    path.write_text('{"schema_version":1,"issues":[{"week":1,"project_ids":["agents2026-a"]}]}')

    class Catalog(FakeStudentProjects):
        def list_projects(self) -> list[StudentProject]:
            return [
                StudentProject(f"agents2026-{n}", f"https://{n}.example.edu") for n in "abcdefgh"
            ]

    lock = threading.Lock()
    calls: list[str] = []
    active = peak = 0

    def visit(url: str) -> str:
        nonlocal active, peak
        with lock:
            calls.append(url)
            active += 1
            peak = max(peak, active)
        try:
            time.sleep(0.02)
            if url == "https://b.example.edu":
                raise ValueError("provider detail must not leak")
            return "Week 2 build " * 500
        finally:
            with lock:
                active -= 1

    async def scenario() -> None:
        catalog = Catalog()
        tool = ScreenShowcaseTool(catalog, visit, path)
        for role in (None, "student"):
            with pytest.raises(ToolValidationError):
                await tool.execute({"week": 2}, context(role))
        assert not calls
        ctx = context("instructor")
        result = await tool.execute({"week": 2}, ctx)
        assert isinstance(result.content, dict)
        rows = result.content["projects"]
        assert isinstance(rows, list)
        assert isinstance(rows[0], dict) and rows[0]["status"] == "cooldown"
        assert isinstance(rows[1], dict) and rows[1]["status"] == "unreadable"
        assert rows[1]["repository_status"] == "read"
        assert rows[1]["eligibility_status"] == "needs_review"
        assert "repository_tree" not in rows[0]
        assert isinstance(rows[2], dict)
        assert rows[2]["repository_status"] == "read"
        assert rows[2]["eligibility_status"] == "needs_review"
        assert isinstance(rows[2], dict) and rows[2]["truncated"] is True
        assert 1 < peak <= 4
        assert len(calls) == 7
        site = InspectStudentSiteTool(catalog, visit)
        full = await site.execute({"project_id": "agents2026-c"}, ctx)
        assert isinstance(full.content, dict) and isinstance(full.content["page"], dict)
        assert len(str(full.content["page"]["text"])) > 4000
        assert len(calls) == 7
        await tool.execute({"week": 2}, ctx)
        assert len(calls) == 8  # Only failed evidence is fetched again.
        await site.execute({"project_id": "agents2026-c"}, context("instructor"))
        assert len(calls) == 9  # Another run never inherits the cache.
        with pytest.raises(ToolValidationError):
            await tool.execute({"week": True}, ctx)
        with pytest.raises(ToolValidationError):
            await tool.execute({"week": 1}, ctx)

    asyncio.run(scenario())


def test_repository_cache_requires_staff_and_is_scoped_to_run() -> None:
    from pydantic import JsonValue

    from course_server.student_projects import InspectStudentRepositoryTool, RepositoryView

    class Catalog(FakeStudentProjects):
        calls = 0

        def inspect_repository(
            self,
            project_id: str,
            view: RepositoryView,
            *,
            path: str | None = None,
            ref: str | None = None,
        ) -> dict[str, JsonValue]:
            self.calls += 1
            return super().inspect_repository(project_id, view, path=path, ref=ref)

    async def scenario() -> None:
        catalog = Catalog()
        tool = InspectStudentRepositoryTool(catalog)
        ctx = context("instructor")
        args: dict[str, JsonValue] = {"project_id": "agents2026-ada", "view": "tree"}
        await tool.execute(args, ctx)
        await tool.execute(args, ctx)
        assert catalog.calls == 1
        student = context("student")
        student.transient_state.update(ctx.transient_state)
        with pytest.raises(ToolValidationError):
            await tool.execute(args, student)
        await tool.execute({**args, "ref": "abc"}, ctx)
        assert catalog.calls == 2
        await tool.execute(args, context("instructor"))
        assert catalog.calls == 3

    asyncio.run(scenario())


def test_repository_discovery_failure_does_not_erase_site_evidence(tmp_path: Path) -> None:
    from pydantic import JsonValue

    from course_server.student_projects import RepositoryView, StudentProjectNotFound

    path = tmp_path / "history.json"
    path.write_text('{"schema_version":1,"issues":[]}')

    class Catalog(FakeStudentProjects):
        def inspect_repository(
            self,
            project_id: str,
            view: RepositoryView,
            *,
            path: str | None = None,
            ref: str | None = None,
        ) -> dict[str, JsonValue]:
            raise StudentProjectNotFound("not available")

    async def scenario() -> None:
        tool = ScreenShowcaseTool(Catalog(), lambda url: "Interactive homepage", path)
        result = await tool.execute({"week": 2}, context("instructor"))
        assert isinstance(result.content, dict)
        rows = result.content["projects"]
        assert isinstance(rows, list)
        for row in rows:
            assert isinstance(row, dict)
            assert row["status"] == "read"
            assert row["text"] == "Interactive homepage"
            assert row["repository_status"] == "unreadable"
            assert row["eligibility_status"] == "needs_review"

    asyncio.run(scenario())
