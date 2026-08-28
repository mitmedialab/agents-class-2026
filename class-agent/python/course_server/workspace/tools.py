"""MCP-aligned workspace tools over the registered component protocol."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import ClassVar
from uuid import UUID, uuid4

from pydantic import JsonValue, ValidationError

from course_server.agent.capabilities import (
    COURSE_SCHEDULE_URI,
    CourseResourceCatalog,
    ResourceNotFound,
    ToolEmittedEvent,
    ToolExecutionContext,
    ToolExecutionResult,
    ToolValidationError,
)

from .constants import (
    CLOSE_COMPONENT_TOOL_ID,
    FOCUS_COMPONENT_TOOL_ID,
    LIST_COMPONENTS_TOOL_ID,
    OPEN_COMPONENT_TOOL_ID,
    UPDATE_COMPONENT_TOOL_ID,
)
from .models import (
    CloseWorkspaceCommand,
    FocusWorkspaceCommand,
    OpenWorkspaceCommand,
    UpdateWorkspaceCommand,
    WorkspaceCommand,
    WorkspaceLayout,
    WorkspacePanel,
    WorkspaceState,
)
from .registry import ComponentRegistry, WorkspaceValidationError

_JSON_OBJECT_SCHEMA: dict[str, JsonValue] = {
    "type": "object",
    "additionalProperties": True,
}
_DEFAULT_COMPONENT_RESOURCES = {"calendar": COURSE_SCHEDULE_URI}
_CONCRETE_VISUAL_SUBJECT = re.compile(
    r"\b(?:people|person|staff|instructors?|researchers?|authors?|profiles?|portraits?|"
    r"projects?|prototypes?|products?|devices?|wearables?|interfaces?|robots?|artworks?|"
    r"installations?|places?|buildings?|campuses|architecture)\b",
    re.IGNORECASE,
)
_NON_QUANTITATIVE_CHART = re.compile(
    r"\b(?:qualitative|ordinal encoding|relative (?:rank|ranking|pattern|ordering)|"
    r"rank order|directional (?:claim|finding)|illustrative (?:rank|score))\b|"
    r"\bnot (?:raw|original|actual) (?:data|measurements?|scores?)\b",
    re.IGNORECASE,
)
_NONCOMPARABLE_CHART = re.compile(
    r"\b(?:not comparable|not (?:a |on a )?shared scale|different measures?|"
    r"distinct (?:measures?|outcomes?)|incompatible units?)\b",
    re.IGNORECASE,
)
_CHART_PROVENANCE_FIELDS = ("data_kind", "data_source", "comparison_basis", "unit")


def _reject_unknown(
    arguments: Mapping[str, JsonValue],
    allowed: frozenset[str],
) -> None:
    unknown = set(arguments) - allowed
    if unknown:
        raise ToolValidationError(f"unexpected arguments: {', '.join(sorted(unknown))}")


def _required_string(arguments: Mapping[str, JsonValue], name: str) -> str:
    value = arguments.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ToolValidationError(f"{name} must be non-blank text")
    return value.strip()


def _optional_string(arguments: Mapping[str, JsonValue], name: str) -> str | None:
    value = arguments.get(name)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ToolValidationError(f"{name} must be non-blank text")
    return value.strip()


def _optional_object(
    arguments: Mapping[str, JsonValue],
    name: str,
) -> dict[str, JsonValue] | None:
    value = arguments.get(name)
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ToolValidationError(f"{name} must be an object")
    return value


def _current_state(context: ToolExecutionContext) -> WorkspaceState:
    try:
        return WorkspaceState.model_validate(context.workspace_state)
    except ValidationError as error:
        raise ToolValidationError("workspace state is unavailable") from error


def _authorize_resource(resource_uri: str | None, context: ToolExecutionContext) -> None:
    if resource_uri is not None and resource_uri not in context.permitted_resource_uris:
        raise PermissionError(f"{resource_uri} is not authorized for this run")


def _visual_composition_text(panel: WorkspacePanel) -> str:
    values: list[str] = [panel.title or ""]
    for name in ("title", "description"):
        value = panel.props.get(name)
        if isinstance(value, str):
            values.append(value)
    elements = panel.props.get("elements")
    if isinstance(elements, list):
        for element in elements:
            if not isinstance(element, dict):
                continue
            for name in ("text", "label", "caption"):
                value = element.get(name)
                if isinstance(value, str):
                    values.append(value)
            items = element.get("items")
            if isinstance(items, list):
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    values.extend(
                        value
                        for name in ("label", "value")
                        if isinstance((value := item.get(name)), str)
                    )
    return "\n".join(values)


def _visual_composition_has_image(panel: WorkspacePanel) -> bool:
    elements = panel.props.get("elements")
    return isinstance(elements, list) and any(
        isinstance(element, dict)
        and element.get("type") == "image"
        and (isinstance(element.get("url"), str) or isinstance(element.get("asset_id"), str))
        for element in elements
    )


def _enforce_registered_course_assets(
    *,
    command: WorkspaceCommand,
    state: WorkspaceState,
    resources: CourseResourceCatalog | None,
) -> None:
    if isinstance(command, OpenWorkspaceCommand):
        panel_id = command.panel.id
    elif isinstance(command, UpdateWorkspaceCommand):
        panel_id = command.panel_id
    else:
        return
    panel = next((candidate for candidate in state.panels if candidate.id == panel_id), None)
    if panel is None or panel.component_id != "visual-composition":
        return
    elements = panel.props.get("elements")
    if not isinstance(elements, list):
        return
    asset_ids = [
        str(element["asset_id"])
        for element in elements
        if isinstance(element, dict)
        and element.get("type") == "image"
        and isinstance(element.get("asset_id"), str)
    ]
    if not asset_ids:
        return
    if panel.resource_uri is None or not panel.resource_uri.startswith("course://"):
        raise ToolValidationError(
            "A registered image asset requires the visual-composition resource_uri for "
            "the course resource that supplied it."
        )
    if resources is None:
        raise ToolValidationError("Registered course assets are unavailable in this runtime.")
    try:
        available = frozenset(resources.asset_ids(panel.resource_uri))
    except ResourceNotFound as error:
        raise ToolValidationError("The registered course resource is unavailable.") from error
    unknown = sorted(set(asset_ids) - available)
    if unknown:
        raise ToolValidationError(
            "Unknown registered asset for this course resource: " + ", ".join(unknown)
        )


def _enforce_chart_data_contract(
    *,
    command: WorkspaceCommand,
    state: WorkspaceState,
) -> None:
    if isinstance(command, OpenWorkspaceCommand):
        panel_id = command.panel.id
    elif isinstance(command, UpdateWorkspaceCommand):
        panel_id = command.panel_id
    else:
        return
    panel = next((candidate for candidate in state.panels if candidate.id == panel_id), None)
    if panel is None or panel.component_id != "visual-composition":
        return
    elements = panel.props.get("elements")
    if not isinstance(elements, list):
        return
    for element in elements:
        if not isinstance(element, dict) or element.get("type") != "chart":
            continue
        missing = [
            field
            for field in _CHART_PROVENANCE_FIELDS
            if not isinstance(element.get(field), str) or not str(element[field]).strip()
        ]
        if missing:
            raise ToolValidationError(
                "Chart elements require explicit quantitative provenance. Add non-blank "
                f"{', '.join(missing)} fields before opening the chart. data_kind must be "
                "measured, user-provided, or derived; comparison_basis must explain why all "
                "values share one quantitative scale."
            )
        chart_context = " ".join(
            str(element.get(field, ""))
            for field in (
                "title",
                "description",
                "value_suffix",
                "unit",
                "data_source",
                "comparison_basis",
            )
        )
        if _NON_QUANTITATIVE_CHART.search(chart_context):
            raise ToolValidationError(
                "Charts may display only actual comparable numeric values, not qualitative "
                "3-2-1 encodings, relative ranks, or directional placeholders. Use a comparison "
                "grid, process, or facts for qualitative findings."
            )
        comparison_basis = str(element.get("comparison_basis", ""))
        if _NONCOMPARABLE_CHART.search(comparison_basis):
            raise ToolValidationError(
                "The chart comparison_basis says the outcomes do not share a comparable scale. "
                "Use separate facts or sections instead of a chart."
            )


def _enforce_visual_media(
    *,
    command: WorkspaceCommand,
    state: WorkspaceState,
    context: ToolExecutionContext,
) -> None:
    if isinstance(command, OpenWorkspaceCommand):
        panel_id = command.panel.id
    elif isinstance(command, UpdateWorkspaceCommand):
        panel_id = command.panel_id
    else:
        return
    panel = next((candidate for candidate in state.panels if candidate.id == panel_id), None)
    if (
        panel is None
        or panel.component_id != "visual-composition"
        or _visual_composition_has_image(panel)
        or _CONCRETE_VISUAL_SUBJECT.search(_visual_composition_text(panel)) is None
    ):
        return
    candidates = context.transient_state.get("image_search_candidates")
    if isinstance(candidates, list) and any(isinstance(value, str) for value in candidates):
        raise ToolValidationError(
            "Relevant image candidates are available from web.search_images. Include at least "
            "one suitable candidate as a visual-composition image element using the `url` field "
            "before opening this concrete-subject UI."
        )
    if context.transient_state.get("image_search_attempted") is not True:
        raise ToolValidationError(
            "This visual composition describes a concrete person, project, prototype, device, "
            "interface, or place. Call web.search_images before opening it. If no usable image "
            "is found, retry with the schematic composition."
        )


def _enforce_image_layout_metadata(
    *,
    command: WorkspaceCommand,
    state: WorkspaceState,
    context: ToolExecutionContext,
) -> None:
    if isinstance(command, OpenWorkspaceCommand):
        panel_id = command.panel.id
    elif isinstance(command, UpdateWorkspaceCommand):
        panel_id = command.panel_id
    else:
        return
    panel = next((candidate for candidate in state.panels if candidate.id == panel_id), None)
    if panel is None or panel.component_id != "visual-composition":
        return
    elements = panel.props.get("elements")
    if not isinstance(elements, list):
        return
    raw_metadata = context.transient_state.get("image_search_metadata")
    metadata = (
        {
            str(candidate["image_url"]): candidate
            for candidate in raw_metadata
            if isinstance(candidate, dict) and isinstance(candidate.get("image_url"), str)
        }
        if isinstance(raw_metadata, list)
        else {}
    )
    parents: dict[str, dict[str, JsonValue]] = {}
    for candidate_parent in elements:
        if not isinstance(candidate_parent, dict) or candidate_parent.get("type") != "group":
            continue
        children = candidate_parent.get("children")
        if not isinstance(children, list):
            continue
        for child_id in children:
            if isinstance(child_id, str):
                parents[child_id] = candidate_parent
    for element in elements:
        if (
            not isinstance(element, dict)
            or element.get("type") != "image"
            or not isinstance(element.get("url"), str)
        ):
            continue
        candidate = metadata.get(str(element["url"]))
        presentation = element.get("presentation", "standard")
        width = element.get("source_width")
        height = element.get("source_height")
        if candidate is not None:
            dimensions_known = candidate.get("dimensions_known") is True
            if not dimensions_known:
                if presentation in {"banner", "feature"}:
                    raise ToolValidationError(
                        "This searched image has unknown dimensions, so banner or feature "
                        "placement is unsafe. Use standard/card presentation or choose a "
                        "dimensioned result."
                    )
                continue
            candidate_width = candidate.get("width")
            candidate_height = candidate.get("height")
            if not isinstance(candidate_width, int) or not isinstance(candidate_height, int):
                continue
            if width != candidate_width or height != candidate_height:
                raise ToolValidationError(
                    "Image search reported this image as "
                    f"{candidate_width}x{candidate_height}px. Copy those values to source_width "
                    "and source_height so its layout remains dimension-aware."
                )
            width = candidate_width
            height = candidate_height
            if candidate.get("resolution_tier") == "small" and presentation in {
                "banner",
                "feature",
            }:
                raise ToolValidationError(
                    f"The {width}x{height}px image is too small for {presentation} presentation. "
                    "Use card/standard or select a larger image candidate."
                )
        if not isinstance(width, int) or not isinstance(height, int):
            continue
        parent = parents.get(str(element.get("id", "")))
        parent_columns = parent.get("columns", 2) if isinstance(parent, dict) else 2
        parent_is_split = isinstance(parent, dict) and (
            parent.get("layout") == "row"
            or (
                parent.get("layout") == "grid"
                and isinstance(parent_columns, int)
                and parent_columns > 1
            )
        )
        shallow_contained = element.get("fit", "cover") == "contain" and width / height >= 2.0
        if shallow_contained and (
            parent_is_split
            or element.get("width", "auto") != "full"
            or presentation not in {"banner", "standard"}
        ):
            raise ToolValidationError(
                f"The {width}x{height}px image is shallow ({width / height:.2f}:1) and uses "
                "fit=contain. A split feature would waste vertical space. Place it in a stack "
                "with width=full and presentation=banner or standard."
            )


def _apply_command(
    *,
    registry: ComponentRegistry,
    command: WorkspaceCommand,
    context: ToolExecutionContext,
    resources: CourseResourceCatalog | None = None,
    strict_visual_policy: bool = True,
) -> WorkspaceState:
    try:
        state = registry.apply(_current_state(context), command)
    except WorkspaceValidationError as error:
        raise ToolValidationError(str(error)) from error
    _enforce_chart_data_contract(command=command, state=state)
    _enforce_registered_course_assets(command=command, state=state, resources=resources)
    if strict_visual_policy:
        _enforce_visual_media(command=command, state=state, context=context)
        _enforce_image_layout_metadata(command=command, state=state, context=context)
    context.workspace_state.clear()
    context.workspace_state.update(state.model_dump(mode="json", exclude_none=True))
    return state


def _command_result(
    *,
    command: WorkspaceCommand,
    event_type: str,
    content: dict[str, JsonValue],
    summary: str,
) -> ToolExecutionResult:
    return ToolExecutionResult(
        content=content,
        summary=summary,
        storage_policy="server_summary",
        emitted_events=[
            ToolEmittedEvent(
                type=event_type,
                payload={
                    "command": command.model_dump(mode="json", exclude_none=True),
                },
            )
        ],
    )


class WorkspaceListComponentsTool:
    id = LIST_COMPONENTS_TOOL_ID
    description = (
        "List trusted first-party workspace components and the operations and props "
        "each component supports. Use this when a resource or result could be shown "
        "visually instead of pasted at length into chat."
    )
    input_schema: ClassVar[dict[str, JsonValue]] = {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    }

    def __init__(self, registry: ComponentRegistry) -> None:
        self._registry = registry

    async def execute(
        self,
        arguments: Mapping[str, JsonValue],
        context: ToolExecutionContext,
    ) -> ToolExecutionResult:
        del context
        if arguments:
            raise ToolValidationError("workspace.list_components accepts no arguments")
        components = [
            manifest.model_dump(mode="json", exclude_none=True)
            for manifest in self._registry.list()
        ]
        return ToolExecutionResult(
            content=components,
            summary=f"Listed {len(components)} workspace components.",
            storage_policy="server_full",
        )


class WorkspaceOpenComponentTool:
    id = OPEN_COMPONENT_TOOL_ID
    description = (
        "Open a trusted first-party component in the conversation workspace. Use only a "
        "component returned by workspace.list_components and a resource URI already available "
        "to this run. Use document-viewer only for close work with a specific artifact; use "
        "webpage-viewer or the remote browser for a specific website; use specialized components "
        "for schedules and other structured resources; and use visual-composition for synthesized "
        "knowledge. Opening a component replaces the prior workspace surface when focus changes. "
        "A visual composition must be clear and presentation-ready on its first open. For a "
        "registered course image, set the panel resource_uri and use the returned asset_id. For a "
        "concrete person, project, prototype, device, interface, or place, the platform requires "
        "an image search before the first open call and requires a suitable result when one is "
        "available. Very wide contained figures belong full-width in a stack, never in a split "
        "feature beside taller content."
    )
    input_schema: ClassVar[dict[str, JsonValue]] = {
        "type": "object",
        "properties": {
            "component_id": {
                "type": "string",
                "description": "Registered component ID.",
            },
            "resource_uri": {
                "type": "string",
                "description": "Authorized resource URI displayed by the component.",
            },
            "title": {
                "type": "string",
                "description": "Optional concise panel title.",
            },
            "props": {
                **_JSON_OBJECT_SCHEMA,
                "description": "Props validated against the registered component schema.",
            },
        },
        "required": ["component_id"],
        "additionalProperties": False,
    }

    def __init__(
        self,
        registry: ComponentRegistry,
        resources: CourseResourceCatalog | None = None,
        *,
        strict_visual_policy: bool = True,
    ) -> None:
        self._registry = registry
        self._resources = resources
        self._strict_visual_policy = strict_visual_policy

    async def execute(
        self,
        arguments: Mapping[str, JsonValue],
        context: ToolExecutionContext,
    ) -> ToolExecutionResult:
        _reject_unknown(
            arguments,
            frozenset({"component_id", "resource_uri", "title", "props"}),
        )
        component_id = _required_string(arguments, "component_id")
        resource_uri = _optional_string(arguments, "resource_uri")
        if resource_uri is None:
            default_resource_uri = _DEFAULT_COMPONENT_RESOURCES.get(component_id)
            if default_resource_uri in context.permitted_resource_uris:
                resource_uri = default_resource_uri
        title = _optional_string(arguments, "title")
        props = _optional_object(arguments, "props") or {}
        _authorize_resource(resource_uri, context)
        manifest = self._registry.get(component_id)
        if manifest is None:
            raise ToolValidationError(f"unknown component: {component_id}")
        layout = None
        if manifest.default_size is not None:
            layout = WorkspaceLayout(
                width=manifest.default_size.width,
                height=manifest.default_size.height,
            )
        panel = WorkspacePanel(
            id=uuid4(),
            component_id=component_id,
            title=title or manifest.title,
            resource_uri=resource_uri,
            props=props,
            state={},
            layout=layout,
        )
        command = OpenWorkspaceCommand(panel=panel)
        _apply_command(
            registry=self._registry,
            command=command,
            context=context,
            resources=self._resources,
            strict_visual_policy=self._strict_visual_policy,
        )
        return _command_result(
            command=command,
            event_type="workspace.panel.opened",
            content={
                "status": "opened",
                "panel_id": str(panel.id),
                "component_id": panel.component_id,
                **({"resource_uri": resource_uri} if resource_uri is not None else {}),
            },
            summary=f"Opened {panel.component_id} in the workspace.",
        )


class WorkspaceUpdateComponentTool:
    id = UPDATE_COMPONENT_TOOL_ID
    description = (
        "Update validated props or state on an existing workspace panel. Props are merged "
        "with current props and the result must satisfy the registered schema. Use this only "
        "when the user is iterating on the current UI; a new question or analytical angle should "
        "open a new component, which replaces the previous surface. Concrete-subject visual "
        "compositions must also satisfy the platform's image-search requirement."
    )
    input_schema: ClassVar[dict[str, JsonValue]] = {
        "type": "object",
        "properties": {
            "panel_id": {"type": "string", "description": "Existing panel UUID."},
            "props": {**_JSON_OBJECT_SCHEMA, "description": "Validated prop changes."},
            "state": {**_JSON_OBJECT_SCHEMA, "description": "Portable state changes."},
            "title": {"type": "string", "description": "Replacement panel title."},
            "resource_uri": {
                "type": "string",
                "description": "Replacement authorized resource URI.",
            },
        },
        "required": ["panel_id"],
        "additionalProperties": False,
    }

    def __init__(
        self,
        registry: ComponentRegistry,
        resources: CourseResourceCatalog | None = None,
        *,
        strict_visual_policy: bool = True,
    ) -> None:
        self._registry = registry
        self._resources = resources
        self._strict_visual_policy = strict_visual_policy

    async def execute(
        self,
        arguments: Mapping[str, JsonValue],
        context: ToolExecutionContext,
    ) -> ToolExecutionResult:
        _reject_unknown(
            arguments,
            frozenset({"panel_id", "props", "state", "title", "resource_uri"}),
        )
        resource_uri = _optional_string(arguments, "resource_uri")
        _authorize_resource(resource_uri, context)
        changes: dict[str, object] = {
            "type": "update",
            "panel_id": _required_string(arguments, "panel_id"),
        }
        for name in ("props", "state"):
            value = _optional_object(arguments, name)
            if value is not None:
                changes[name] = value
        title = _optional_string(arguments, "title")
        if title is not None:
            changes["title"] = title
        if resource_uri is not None:
            changes["resource_uri"] = resource_uri
        try:
            command = UpdateWorkspaceCommand.model_validate(changes)
        except ValidationError as error:
            raise ToolValidationError("workspace update must contain a valid change") from error
        _apply_command(
            registry=self._registry,
            command=command,
            context=context,
            resources=self._resources,
            strict_visual_policy=self._strict_visual_policy,
        )
        return _command_result(
            command=command,
            event_type="workspace.panel.updated",
            content={"status": "updated", "panel_id": str(command.panel_id)},
            summary=f"Updated workspace panel {command.panel_id}.",
        )


class _PanelIdTool:
    input_schema: ClassVar[dict[str, JsonValue]] = {
        "type": "object",
        "properties": {
            "panel_id": {"type": "string", "description": "Existing panel UUID."},
        },
        "required": ["panel_id"],
        "additionalProperties": False,
    }

    def __init__(self, registry: ComponentRegistry) -> None:
        self._registry = registry

    @staticmethod
    def _panel_id(arguments: Mapping[str, JsonValue]) -> UUID:
        _reject_unknown(arguments, frozenset({"panel_id"}))
        try:
            return UUID(_required_string(arguments, "panel_id"))
        except ValueError as error:
            raise ToolValidationError("panel_id must be a UUID") from error


class WorkspaceFocusComponentTool(_PanelIdTool):
    id = FOCUS_COMPONENT_TOOL_ID
    description = "Focus one trusted workspace panel and discard other stale surfaces."

    async def execute(
        self,
        arguments: Mapping[str, JsonValue],
        context: ToolExecutionContext,
    ) -> ToolExecutionResult:
        command = FocusWorkspaceCommand(panel_id=self._panel_id(arguments))
        _apply_command(registry=self._registry, command=command, context=context)
        return _command_result(
            command=command,
            event_type="workspace.panel.updated",
            content={"status": "focused", "panel_id": str(command.panel_id)},
            summary=f"Focused workspace panel {command.panel_id}.",
        )


class WorkspaceCloseComponentTool(_PanelIdTool):
    id = CLOSE_COMPONENT_TOOL_ID
    description = "Close an existing trusted workspace panel."

    async def execute(
        self,
        arguments: Mapping[str, JsonValue],
        context: ToolExecutionContext,
    ) -> ToolExecutionResult:
        command = CloseWorkspaceCommand(panel_id=self._panel_id(arguments))
        _apply_command(registry=self._registry, command=command, context=context)
        return _command_result(
            command=command,
            event_type="workspace.panel.closed",
            content={"status": "closed", "panel_id": str(command.panel_id)},
            summary=f"Closed workspace panel {command.panel_id}.",
        )
