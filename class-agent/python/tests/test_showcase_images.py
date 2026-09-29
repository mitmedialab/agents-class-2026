import asyncio
from typing import cast

import pytest
from pydantic import JsonValue
from test_student_projects import FakeStudentProjects, context

from course_server.agent import ToolValidationError
from course_server.student_projects.images import DiscoverShowcaseImagesTool


def test_weekly_images_are_discovered_probed_and_available_for_inspection() -> None:
    calls: list[str] = []

    def visit(url: str) -> dict[str, JsonValue]:
        calls.append(url)
        if url.endswith("/week2"):
            return {
                "images": [
                    {"image_url": "https://ada.example.edu/build.png", "alt": "Week 2 demo"},
                    {"image_url": "https://ada.example.edu/missing.png"},
                ]
            }
        return {"text": "Interactive homepage", "images": []}

    async def scenario() -> None:
        tool = DiscoverShowcaseImagesTool(
            FakeStudentProjects(),
            visit,
            lambda url: url if url.endswith("/build.png") else None,
        )
        args: dict[str, JsonValue] = {
            "project_id": "agents2026-ada",
            "page_urls": ["https://ada.example.edu/week2"],
        }
        for role in (None, "student"):
            with pytest.raises(ToolValidationError):
                await tool.execute(args, context(role))
        assert not calls
        ctx = context("instructor")
        result = await tool.execute(args, ctx)
        assert isinstance(result.content, dict)
        images = cast(list[dict[str, JsonValue]], result.content["images"])
        assert len(images) == 1
        assert images[0]["source_page"] == "https://ada.example.edu/week2"
        assert images[0]["verified"] is True
        assert ctx.transient_state["page_image_candidates"] == ["https://ada.example.edu/build.png"]
        assert result.storage_policy == "server_summary"
        for override in [
            {"project_id": "agents2026-unknown"},
            {"page_urls": ["https://other.example.edu/week2"]},
            {"image_urls": ["https://token:secret@example.edu/img.png"]},
            {"image_urls": ["http://example.edu/img.png"]},
            {"page_urls": ["https://ada.example.edu/week2"] * 4},
        ]:
            with pytest.raises(ToolValidationError):
                await tool.execute({**args, **cast(dict[str, JsonValue], override)}, ctx)

    asyncio.run(scenario())


def test_failed_page_is_distinct_from_no_images() -> None:
    def visit(url: str) -> str:
        raise ValueError("private provider detail")

    async def scenario() -> None:
        result = await DiscoverShowcaseImagesTool(
            FakeStudentProjects(),
            visit,
            lambda url: None,
        ).execute({"project_id": "agents2026-ada"}, context("instructor"))
        assert isinstance(result.content, dict)
        assert result.content["images"] == []
        assert result.content["pages"] == [
            {"url": "https://ada.example.edu", "status": "fetch_failed"}
        ]

    asyncio.run(scenario())
