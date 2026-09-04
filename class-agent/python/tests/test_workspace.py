from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import cast
from uuid import uuid4

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import JsonValue

from agent_core import Event, PrincipalContext
from course_server.agent import ToolExecutionContext, ToolValidationError
from course_server.application_draft import (
    ApplicationDraftEditError,
    application_draft_props,
    updated_application_draft_from_user,
)
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


def execution_context(principal: PrincipalContext | None = None) -> ToolExecutionContext:
    return ToolExecutionContext(
        principal=principal or public_principal(),
        conversation_id=uuid4(),
        permitted_resource_uris=frozenset(
            {"course://syllabus", "course://schedule", "course://application"}
        ),
    )


def instructor_principal() -> PrincipalContext:
    return PrincipalContext(
        authenticated=True,
        user_id=uuid4(),
        username="test-instructor",
        display_name="Test Instructor",
        roles=["public", "instructor"],
        session_id=uuid4(),
    )


def test_workspace_schema_validates_published_component_registry() -> None:
    schema = json.loads(WORKSPACE_SCHEMA_PATH.read_text(encoding="utf-8"))
    registry = json.loads(COMPONENT_REGISTRY_PATH.read_text(encoding="utf-8"))
    validator = Draft202012Validator(
        schema,
        format_checker=FormatChecker(),
    ).evolve(schema=schema["$defs"]["ComponentRegistry"])

    assert not list(validator.iter_errors(registry))


def test_user_application_edits_persist_validation_state_without_losing_text() -> None:
    props = application_draft_props()

    invalid = updated_application_draft_from_user(
        props,
        "github_id",
        "https://github.com/ada",
    )
    invalid_fields = cast(list[dict[str, JsonValue]], invalid["fields"])
    github = next(field for field in invalid_fields if field["id"] == "github_id")
    assert github["value"] == "https://github.com/ada"
    assert github["status"] == "candidate"
    validation_error = github["validation_error"]
    assert isinstance(validation_error, str)
    assert "no @, URL" in validation_error

    corrected = updated_application_draft_from_user(props, "github_id", "ada")
    corrected_fields = cast(list[dict[str, JsonValue]], corrected["fields"])
    github = next(field for field in corrected_fields if field["id"] == "github_id")
    assert github["status"] == "confirmed"
    assert "validation_error" not in github

    with pytest.raises(ApplicationDraftEditError) as error:
        updated_application_draft_from_user(props, "interests", "x" * 4_001)
    assert error.value.code == "draft_field_too_long"
    assert error.value.field_id == "interests"


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


def test_application_draft_allows_one_atomic_update_per_user_turn() -> None:
    async def scenario() -> None:
        registry = load_component_registry()
        context = execution_context()
        opened = await WorkspaceOpenComponentTool(registry).execute(
            {
                "component_id": "draft-document",
                "title": "Course Application Draft",
                "resource_uri": "course://application",
                "props": {
                    "title": "Course Application Draft",
                    "fields": [
                        {
                            "id": "name",
                            "label": "Name",
                            "value": "",
                            "status": "missing",
                        },
                        {
                            "id": "email",
                            "label": "Email",
                            "value": "ada@example.edu",
                            "status": "candidate",
                            "source": "Public profile",
                        },
                    ],
                },
            },
            context,
        )
        assert isinstance(opened.content, dict)
        assert opened.content["next_action"] == (
            "The canonical application draft is open. Use final_answer to state the "
            "requirements and ask only for the applicant's full name, then wait."
        )
        panel_id = str(opened.content["panel_id"])
        opened_state = WorkspaceState.model_validate(context.workspace_state)
        panel = opened_state.panels[0]
        assert panel.title == "Course Application Draft"
        assert panel.state == {"document_kind": "course-application"}
        opened_fields = panel.props["fields"]
        assert isinstance(opened_fields, list)
        assert len(opened_fields) == 17
        tool = WorkspaceUpdateComponentTool(registry)

        with pytest.raises(ToolValidationError, match="initial public-web research"):
            await tool.execute(
                {
                    "panel_id": panel_id,
                    "props": {
                        "fields": [
                            {
                                "id": "name",
                                "label": "Name",
                                "value": "Ada Example",
                                "status": "confirmed",
                            }
                        ]
                    },
                },
                context,
            )
        context.transient_state["web_search_attempted"] = True

        updated = await tool.execute(
            {
                "panel_id": panel_id,
                "props": {
                    "fields": [
                        {
                            "id": "name",
                            "label": "Name",
                            "value": "Ada Example",
                            "status": "confirmed",
                        }
                    ]
                },
            },
            context,
        )

        assert isinstance(updated.content, dict)
        assert updated.content["next_action"] == (
            "End this turn with final_answer containing exactly one question, "
            "then wait for the applicant."
        )
        updated_state = WorkspaceState.model_validate(context.workspace_state)
        updated_fields = updated_state.panels[0].props["fields"]
        assert isinstance(updated_fields, list)
        assert len(updated_fields) == 17
        updated_name = updated_fields[0]
        assert isinstance(updated_name, dict)
        assert updated_name["value"] == "Ada Example"
        assert updated_fields[1] == {
            "id": "email",
            "label": "Email",
            "value": "ada@example.edu",
            "status": "candidate",
            "source": "Public profile",
            "input_type": "email",
        }
        with pytest.raises(ToolValidationError, match="already updated for this user turn"):
            await tool.execute(
                {"panel_id": panel_id, "props": {"description": "A redundant update"}},
                context,
            )

    asyncio.run(scenario())


def test_application_draft_rejects_values_outside_canonical_options() -> None:
    async def scenario() -> None:
        registry = load_component_registry()
        context = execution_context()
        opened = await WorkspaceOpenComponentTool(registry).execute(
            {
                "component_id": "draft-document",
                "resource_uri": "course://application",
            },
            context,
        )
        assert isinstance(opened.content, dict)
        panel_id = str(opened.content["panel_id"])

        with pytest.raises(
            ToolValidationError,
            match="school must be one of: MIT Media Lab, MIT, Harvard, Wellesley, Other",
        ):
            await WorkspaceUpdateComponentTool(registry).execute(
                {
                    "panel_id": panel_id,
                    "props": {
                        "fields": [
                            {
                                "id": "school",
                                "value": "Stanford",
                                "status": "confirmed",
                            }
                        ]
                    },
                },
                context,
            )

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


def test_concrete_visual_composition_requires_available_image_candidates() -> None:
    async def scenario() -> None:
        registry = load_component_registry()
        tool = WorkspaceOpenComponentTool(registry)
        context = execution_context()
        props: dict[str, JsonValue] = {
            "root_id": "root",
            "elements": [
                {
                    "id": "root",
                    "type": "group",
                    "children": ["title", "description"],
                },
                {
                    "id": "title",
                    "type": "heading",
                    "text": "SixthSense prototype",
                },
                {
                    "id": "description",
                    "type": "text",
                    "text": "A wearable gestural interface.",
                },
            ],
        }

        with pytest.raises(ToolValidationError, match=r"Call web\.search_images"):
            await tool.execute(
                {"component_id": "visual-composition", "props": props},
                context,
            )
        assert WorkspaceState.model_validate(context.workspace_state).panels == []

        context.transient_state.update(
            {
                "image_search_attempted": True,
                "image_search_candidates": ["https://example.com/sixthsense.jpg"],
            }
        )
        with pytest.raises(ToolValidationError, match="Include at least one suitable candidate"):
            await tool.execute(
                {"component_id": "visual-composition", "props": props},
                context,
            )

        elements = props["elements"]
        assert isinstance(elements, list)
        root = elements[0]
        assert isinstance(root, dict)
        children = root["children"]
        assert isinstance(children, list)
        children.insert(1, "image")
        elements.append(
            {
                "id": "image",
                "type": "image",
                "url": "https://example.com/sixthsense.jpg",
                "alt": "SixthSense wearable prototype",
                "aspect": "wide",
            }
        )
        opened = await tool.execute(
            {"component_id": "visual-composition", "props": props},
            context,
        )

        assert isinstance(opened.content, dict)
        assert opened.content["status"] == "opened"

        fallback_context = execution_context()
        fallback_context.transient_state["image_search_attempted"] = True
        fallback = await tool.execute(
            {
                "component_id": "visual-composition",
                "props": {
                    "root_id": "root",
                    "elements": [
                        {
                            "id": "root",
                            "type": "text",
                            "text": "A physical prototype with no usable public image.",
                        }
                    ],
                },
            },
            fallback_context,
        )
        assert isinstance(fallback.content, dict)
        assert fallback.content["status"] == "opened"

    asyncio.run(scenario())


def test_private_application_images_require_instructor_and_inspector_provenance() -> None:
    async def scenario() -> None:
        registry = load_component_registry()
        tool = WorkspaceOpenComponentTool(registry)
        image_uri = "applicant://40000000-0000-4000-8000-000000000001/photo"
        props: dict[str, JsonValue] = {
            "root_id": "photo",
            "elements": [
                {
                    "id": "photo",
                    "type": "image",
                    "url": image_uri,
                    "alt": "Submitted application image",
                    "presentation": "card",
                }
            ],
        }

        public_context = execution_context()
        public_context.transient_state["private_application_image_candidates"] = [image_uri]
        with pytest.raises(PermissionError, match="Instructor access"):
            await tool.execute(
                {"component_id": "visual-composition", "props": props},
                public_context,
            )

        instructor_context = execution_context(instructor_principal())
        with pytest.raises(ToolValidationError, match=r"inspect_application_images"):
            await tool.execute(
                {"component_id": "visual-composition", "props": props},
                instructor_context,
            )

        instructor_context.transient_state["private_application_image_candidates"] = [image_uri]
        image = props["elements"]
        assert isinstance(image, list)
        photo_element = image[0]
        assert isinstance(photo_element, dict)
        photo_element["url"] = "https://placeholder.invalid/applicant-1.png"
        with pytest.raises(ToolValidationError, match="do not invent"):
            await tool.execute(
                {"component_id": "visual-composition", "props": props},
                instructor_context,
            )

        photo_element["url"] = image_uri
        opened = await tool.execute(
            {"component_id": "visual-composition", "props": props},
            instructor_context,
        )
        assert isinstance(opened.content, dict)
        assert opened.content["status"] == "opened"

    asyncio.run(scenario())


def test_chart_workspace_requires_comparable_quantitative_provenance() -> None:
    async def scenario() -> None:
        registry = load_component_registry()
        tool = WorkspaceOpenComponentTool(registry)
        base_chart: dict[str, JsonValue] = {
            "root_id": "results",
            "elements": [
                {
                    "id": "results",
                    "type": "chart",
                    "title": "Section scores",
                    "chart_type": "bar",
                    "labels": ["Section A", "Section B"],
                    "series": [{"label": "Average", "values": [72, 84]}],
                }
            ],
        }

        with pytest.raises(ToolValidationError, match="quantitative provenance"):
            await tool.execute(
                {"component_id": "visual-composition", "props": base_chart},
                execution_context(),
            )

        chart_elements = base_chart["elements"]
        assert isinstance(chart_elements, list)
        chart = chart_elements[0]
        assert isinstance(chart, dict)
        chart.update(
            {
                "data_kind": "measured",
                "data_source": "Course records, 2026",
                "comparison_basis": "Both sections use the same 0-100 score scale.",
                "unit": "percent",
            }
        )
        opened = await tool.execute(
            {"component_id": "visual-composition", "props": base_chart},
            execution_context(),
        )
        assert isinstance(opened.content, dict)
        assert opened.content["status"] == "opened"

        chart["description"] = "A qualitative 3-2-1 relative pattern, not raw measurements."
        with pytest.raises(ToolValidationError, match="actual comparable numeric values"):
            await tool.execute(
                {"component_id": "visual-composition", "props": base_chart},
                execution_context(),
            )

        chart.pop("description")
        chart["comparison_basis"] = "Distinct outcomes use different measures."
        with pytest.raises(ToolValidationError, match="do not share a comparable scale"):
            await tool.execute(
                {"component_id": "visual-composition", "props": base_chart},
                execution_context(),
            )

    asyncio.run(scenario())


def test_searched_image_dimensions_control_primary_visual_placement() -> None:
    async def scenario() -> None:
        registry = load_component_registry()
        tool = WorkspaceOpenComponentTool(registry)
        image_url = "https://example.com/shallow-study-figure.png"
        context = execution_context()
        context.transient_state["image_search_metadata"] = [
            {
                "image_url": image_url,
                "dimensions_known": True,
                "width": 600,
                "height": 200,
                "resolution_tier": "small",
            }
        ]
        props: dict[str, JsonValue] = {
            "root_id": "figure",
            "elements": [
                {
                    "id": "figure",
                    "type": "image",
                    "url": image_url,
                    "alt": "Study procedure figure",
                    "presentation": "banner",
                    "fit": "contain",
                }
            ],
        }

        with pytest.raises(ToolValidationError, match="600x200px"):
            await tool.execute({"component_id": "visual-composition", "props": props}, context)

        image_elements = props["elements"]
        assert isinstance(image_elements, list)
        image = image_elements[0]
        assert isinstance(image, dict)
        image.update({"source_width": 600, "source_height": 200})
        with pytest.raises(ToolValidationError, match="too small for banner"):
            await tool.execute({"component_id": "visual-composition", "props": props}, context)

        metadata = context.transient_state["image_search_metadata"]
        assert isinstance(metadata, list)
        candidate = metadata[0]
        assert isinstance(candidate, dict)
        candidate["resolution_tier"] = "large"
        image.update({"presentation": "feature", "width": "half"})
        with pytest.raises(ToolValidationError, match="split feature would waste vertical space"):
            await tool.execute({"component_id": "visual-composition", "props": props}, context)

        image.update({"presentation": "standard", "width": "full"})
        opened = await tool.execute({"component_id": "visual-composition", "props": props}, context)
        assert isinstance(opened.content, dict)
        assert opened.content["status"] == "opened"

        unknown_context = execution_context()
        unknown_context.transient_state["image_search_metadata"] = [
            {"image_url": image_url, "dimensions_known": False}
        ]
        image.pop("source_width")
        image.pop("source_height")
        image["presentation"] = "feature"
        with pytest.raises(ToolValidationError, match="unknown dimensions"):
            await tool.execute(
                {"component_id": "visual-composition", "props": props}, unknown_context
            )

    asyncio.run(scenario())


def test_relaxed_visual_policy_skips_image_requirement_and_layout_checks() -> None:
    async def scenario() -> None:
        registry = load_component_registry()
        tool = WorkspaceOpenComponentTool(registry, strict_visual_policy=False)
        context = execution_context()
        context.transient_state["image_search_candidates"] = ["https://example.com/image.png"]

        opened = await tool.execute(
            {
                "component_id": "visual-composition",
                "props": {
                    "root_id": "root",
                    "elements": [
                        {
                            "id": "root",
                            "type": "text",
                            "text": "A physical prototype without a selected image.",
                        }
                    ],
                },
            },
            context,
        )

        assert isinstance(opened.content, dict)
        assert opened.content["status"] == "opened"

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
            "title": "Research paper",
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
                "presentation": "avatar",
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

    chart_props: dict[str, JsonValue] = {
        "root_id": "trend",
        "elements": [
            {
                "id": "trend",
                "type": "chart",
                "title": "Weekly participation",
                "chart_type": "line",
                "labels": ["Week 1", "Week 2", "Week 3"],
                "series": [
                    {
                        "label": "Students",
                        "values": [12, 18, 24],
                        "tone": "success",
                        "tones": ["coral", "secondary", "violet"],
                    }
                ],
                "value_suffix": " students",
            }
        ],
    }
    registry.validate_props("visual-composition", chart_props)

    invalid_chart: dict[str, JsonValue] = {
        **chart_props,
        "elements": [
            {
                "id": "trend",
                "type": "chart",
                "title": "Weekly participation",
                "chart_type": "line",
                "labels": ["Week 1", "Week 2", "Week 3"],
                "series": [{"label": "Students", "values": [12, 18]}],
            }
        ],
    }
    with pytest.raises(WorkspaceValidationError, match="series values must match"):
        registry.validate_props("visual-composition", invalid_chart)

    invalid_chart_tones: dict[str, JsonValue] = {
        **chart_props,
        "elements": [
            {
                "id": "trend",
                "type": "chart",
                "title": "Weekly participation",
                "chart_type": "line",
                "labels": ["Week 1", "Week 2", "Week 3"],
                "series": [
                    {
                        "label": "Students",
                        "values": [12, 18, 24],
                        "tones": ["coral", "violet"],
                    }
                ],
            }
        ],
    }
    with pytest.raises(WorkspaceValidationError, match="point tones must match"):
        registry.validate_props("visual-composition", invalid_chart_tones)

    valid_elements = valid_props["elements"]
    assert isinstance(valid_elements, list)
    invalid_presentation = {
        **valid_props,
        "elements": [
            {**element, "presentation": "billboard"}
            if isinstance(element, dict) and element.get("type") == "image"
            else element
            for element in valid_elements
        ],
    }
    with pytest.raises(WorkspaceValidationError, match="invalid props"):
        registry.validate_props("visual-composition", invalid_presentation)

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
