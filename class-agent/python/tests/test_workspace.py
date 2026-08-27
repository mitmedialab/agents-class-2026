from __future__ import annotations

import asyncio
import json
from pathlib import Path
from uuid import uuid4

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import JsonValue

from agent_core import Event, PrincipalContext
from course_server.agent import ToolExecutionContext, ToolValidationError
from course_server.workspace import (
    COMPONENT_REGISTRY_PATH,
    WorkspacePanel,
    WorkspaceState,
    WorkspaceValidationError,
    load_component_registry,
    project_workspace_events,
)
from course_server.workspace.tools import (
    WorkspaceCloseComponentTool,
    WorkspaceFocusComponentTool,
    WorkspaceListComponentsTool,
    WorkspaceOpenComponentTool,
    WorkspaceUpdateComponentTool,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
WORKSPACE_SCHEMA_PATH = PROJECT_ROOT / "shared/schemas/v1/workspace.schema.json"


def public_principal() -> PrincipalContext:
    session_id = uuid4()
    return PrincipalContext(
        authenticated=False,
        anonymous_session_id=session_id,
        roles=["public"],
        session_id=session_id,
    )


def execution_context() -> ToolExecutionContext:
    return ToolExecutionContext(
        principal=public_principal(),
        conversation_id=uuid4(),
        permitted_resource_uris=frozenset({"course://syllabus", "course://schedule"}),
    )


def test_workspace_schema_validates_published_component_registry() -> None:
    schema = json.loads(WORKSPACE_SCHEMA_PATH.read_text(encoding="utf-8"))
    registry = json.loads(COMPONENT_REGISTRY_PATH.read_text(encoding="utf-8"))
    validator = Draft202012Validator(
        schema,
        format_checker=FormatChecker(),
    ).evolve(schema=schema["$defs"]["ComponentRegistry"])

    assert not list(validator.iter_errors(registry))


def test_workspace_tools_validate_and_apply_complete_panel_lifecycle() -> None:
    async def scenario() -> None:
        registry = load_component_registry()
        context = execution_context()

        listed = await WorkspaceListComponentsTool(registry).execute({}, context)
        assert isinstance(listed.content, list)
        component_ids: list[object] = []
        for component in listed.content:
            assert isinstance(component, dict)
            component_ids.append(component["id"])
        assert component_ids == [
            "document-viewer",
            "calendar",
            "webpage-viewer",
            "browser-viewer",
            "page-cards",
            "visual-composition",
            "draft-document",
        ]

        opened = await WorkspaceOpenComponentTool(registry).execute(
            {
                "component_id": "calendar",
                "title": "Course schedule",
                "props": {"view": "agenda", "focus_date": "2026-09-20"},
            },
            context,
        )
        assert isinstance(opened.content, dict)
        panel_id = str(opened.content["panel_id"])
        assert opened.emitted_events[0].type == "workspace.panel.opened"
        opened_state = WorkspaceState.model_validate(context.workspace_state)
        assert opened_state.panels[0].resource_uri == "course://schedule"
        assert opened_state.focused_panel_id is not None

        updated = await WorkspaceUpdateComponentTool(registry).execute(
            {"panel_id": panel_id, "props": {"view": "month"}},
            context,
        )
        assert updated.emitted_events[0].type == "workspace.panel.updated"
        state = WorkspaceState.model_validate(context.workspace_state)
        assert state.panels[0].props == {
            "view": "month",
            "focus_date": "2026-09-20",
        }

        focused = await WorkspaceFocusComponentTool(registry).execute(
            {"panel_id": panel_id}, context
        )
        assert isinstance(focused.content, dict)
        assert focused.content["status"] == "focused"
        closed = await WorkspaceCloseComponentTool(registry).execute(
            {"panel_id": panel_id}, context
        )
        assert closed.emitted_events[0].type == "workspace.panel.closed"
        assert WorkspaceState.model_validate(context.workspace_state).panels == []

    asyncio.run(scenario())


def test_workspace_tools_reject_unknown_component_invalid_props_and_resource() -> None:
    async def scenario() -> None:
        registry = load_component_registry()
        tool = WorkspaceOpenComponentTool(registry)
        context = execution_context()

        with pytest.raises(ToolValidationError, match="unknown component"):
            await tool.execute({"component_id": "invented-ui"}, context)
        with pytest.raises(ToolValidationError, match="invalid props"):
            await tool.execute(
                {"component_id": "calendar", "props": {"view": "timeline"}},
                context,
            )
        with pytest.raises(PermissionError):
            await tool.execute(
                {
                    "component_id": "document-viewer",
                    "resource_uri": "course://private-grades",
                },
                context,
            )
        with pytest.raises(ToolValidationError, match="invalid props"):
            await tool.execute(
                {
                    "component_id": "webpage-viewer",
                    "props": {"url": "javascript:alert(1)"},
                },
                context,
            )

    asyncio.run(scenario())


def test_workspace_events_reconstruct_state_without_framework_objects() -> None:
    registry = load_component_registry()
    panel_id = uuid4()
    conversation_id = uuid4()
    command = {
        "type": "open",
        "panel": {
            "id": str(panel_id),
            "component_id": "document-viewer",
            "title": "Syllabus",
            "resource_uri": "course://syllabus",
            "props": {"page": 1},
            "state": {},
        },
    }
    events = [
        Event(
            type="workspace.panel.opened",
            actor="course-agent",
            conversation_id=conversation_id,
            payload={"command": command},
        )
    ]

    state = project_workspace_events(events, registry)

    assert state.focused_panel_id == panel_id
    assert state.panels[0].resource_uri == "course://syllabus"
    assert json.loads(state.model_dump_json())["panels"][0]["component_id"] == "document-viewer"


def test_opening_or_focusing_a_panel_replaces_the_prior_workspace_surface() -> None:
    registry = load_component_registry()
    first_id = uuid4()
    second_id = uuid4()
    first = WorkspacePanel(
        id=first_id,
        component_id="calendar",
        props={"view": "agenda"},
    )
    second = WorkspacePanel(
        id=second_id,
        component_id="calendar",
        props={"view": "month"},
    )

    opened = registry.apply(
        WorkspaceState(panels=[first], focused_panel_id=first_id),
        {"type": "open", "panel": second.model_dump(mode="json")},
    )
    assert [panel.id for panel in opened.panels] == [second_id]

    focused = registry.apply(
        WorkspaceState(panels=[first, second], focused_panel_id=second_id),
        {"type": "focus", "panel_id": first_id},
    )
    assert [panel.id for panel in focused.panels] == [first_id]


def test_visual_composition_requires_a_valid_bounded_component_tree() -> None:
    registry = load_component_registry()
    valid_props: dict[str, JsonValue] = {
        "root_id": "profiles",
        "elements": [
            {
                "id": "profiles",
                "type": "group",
                "layout": "grid",
                "columns": 2,
                "children": ["profile-one", "profile-two"],
            },
            {
                "id": "profile-one",
                "type": "group",
                "surface": "raised",
                "padding": "medium",
                "children": ["photo-one", "name-one"],
            },
            {
                "id": "photo-one",
                "type": "image",
                "url": "https://example.com/person.jpg",
                "alt": "Portrait",
                "radius": "round",
            },
            {"id": "name-one", "type": "heading", "text": "Ada Example"},
            {
                "id": "profile-two",
                "type": "group",
                "children": ["name-two", "bio-two"],
            },
            {"id": "name-two", "type": "heading", "text": "Grace Example"},
            {"id": "bio-two", "type": "text", "text": "Researcher"},
        ],
    }

    registry.validate_props("visual-composition", valid_props)

    cyclic: dict[str, JsonValue] = {
        "root_id": "first",
        "elements": [
            {"id": "first", "type": "group", "children": ["second"]},
            {"id": "second", "type": "group", "children": ["first"]},
        ],
    }
    with pytest.raises(WorkspaceValidationError, match="root may not have a parent"):
        registry.validate_props("visual-composition", cyclic)

    orphaned: dict[str, JsonValue] = {
        "root_id": "root",
        "elements": [
            {"id": "root", "type": "text", "text": "Visible"},
            {"id": "orphan", "type": "text", "text": "Unreachable"},
        ],
    }
    with pytest.raises(WorkspaceValidationError, match="unreachable"):
        registry.validate_props("visual-composition", orphaned)
