from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest
from pydantic import JsonValue

from agent_core import PrincipalContext
from course_server.agent import (
    COURSE_INSTRUCTORS_URI,
    CourseReadPublicFileTool,
    FileResourceProvider,
    ToolExecutionContext,
    ToolValidationError,
)
from course_server.workspace import load_component_registry
from course_server.workspace.tools import WorkspaceOpenComponentTool


def execution_context() -> ToolExecutionContext:
    session_id = uuid4()
    return ToolExecutionContext(
        principal=PrincipalContext(
            authenticated=False,
            anonymous_session_id=session_id,
            roles=["public"],
            session_id=session_id,
        ),
        conversation_id=uuid4(),
        permitted_resource_uris=frozenset({COURSE_INSTRUCTORS_URI}),
    )


def staff_profile_props(asset_id: str) -> dict[str, JsonValue]:
    return {
        "root_id": "profile",
        "elements": [
            {
                "id": "profile",
                "type": "group",
                "children": ["portrait", "name"],
            },
            {
                "id": "portrait",
                "type": "image",
                "asset_id": asset_id,
                "alt": "Portrait of Pattie Maes",
                "presentation": "avatar",
            },
            {
                "id": "name",
                "type": "heading",
                "text": "Pattie Maes — Course Instructor",
            },
        ],
    }


def test_public_resource_read_returns_registered_asset_ids_and_bytes() -> None:
    async def scenario() -> None:
        resources = FileResourceProvider.from_registry()
        contents = await resources.read(COURSE_INSTRUCTORS_URI)

        staff_summary = next(
            summary for summary in resources.list_public() if summary.uri == COURSE_INSTRUCTORS_URI
        )
        assert "official portrait assets" in staff_summary.description
        assert contents.assets["pattie_maes_portrait"] == "image/jpeg"
        assert "shared/course" not in str(contents.assets)

        result = await CourseReadPublicFileTool(resources).execute(
            {"resource_uri": COURSE_INSTRUCTORS_URI},
            execution_context(),
        )
        assert isinstance(result.content, dict)
        registered_assets = result.content["registered_assets"]
        assert isinstance(registered_assets, dict)
        assert registered_assets["pattie_maes_portrait"] == "image/jpeg"

        portrait = await resources.read_asset(
            COURSE_INSTRUCTORS_URI,
            "pattie_maes_portrait",
        )
        assert portrait.media_type == "image/jpeg"
        assert portrait.data.startswith(b"\xff\xd8\xff")

    asyncio.run(scenario())


def test_visual_composition_accepts_only_assets_registered_to_its_resource() -> None:
    async def scenario() -> None:
        resources = FileResourceProvider.from_registry()
        tool = WorkspaceOpenComponentTool(load_component_registry(), resources)

        opened = await tool.execute(
            {
                "component_id": "visual-composition",
                "resource_uri": COURSE_INSTRUCTORS_URI,
                "props": staff_profile_props("pattie_maes_portrait"),
            },
            execution_context(),
        )
        assert isinstance(opened.content, dict)
        assert opened.content["status"] == "opened"

        with pytest.raises(ToolValidationError, match="Unknown registered asset"):
            await tool.execute(
                {
                    "component_id": "visual-composition",
                    "resource_uri": COURSE_INSTRUCTORS_URI,
                    "props": staff_profile_props("invented_portrait"),
                },
                execution_context(),
            )

        with pytest.raises(ToolValidationError, match=r"requires.*resource_uri"):
            await tool.execute(
                {
                    "component_id": "visual-composition",
                    "props": staff_profile_props("pattie_maes_portrait"),
                },
                execution_context(),
            )

    asyncio.run(scenario())
