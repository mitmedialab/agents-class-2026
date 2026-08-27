"""MCP-aligned workspace tools over the registered component protocol."""

from __future__ import annotations

from collections.abc import Mapping
from typing import ClassVar
from uuid import UUID, uuid4

from pydantic import JsonValue, ValidationError

from course_server.agent.capabilities import (
    COURSE_SCHEDULE_URI,
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


def _apply_command(
    *,
    registry: ComponentRegistry,
    command: WorkspaceCommand,
    context: ToolExecutionContext,
) -> WorkspaceState:
    try:
        state = registry.apply(_current_state(context), command)
    except WorkspaceValidationError as error:
        raise ToolValidationError(str(error)) from error
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
        "to this run. Prefer this for suitable schedules, documents, profiles, composed visual "
        "layouts, and structured results instead of reproducing their full contents in chat."
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

    def __init__(self, registry: ComponentRegistry) -> None:
        self._registry = registry

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
        _apply_command(registry=self._registry, command=command, context=context)
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
        "with current props and the result must satisfy the registered schema."
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

    def __init__(self, registry: ComponentRegistry) -> None:
        self._registry = registry

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
        _apply_command(registry=self._registry, command=command, context=context)
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
