"""Manifest registry, prop validation, and deterministic workspace projection."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError
from pydantic import JsonValue, TypeAdapter, ValidationError

from agent_core import Event

from .models import (
    CloseWorkspaceCommand,
    ComponentManifest,
    ComponentRegistryDocument,
    FocusWorkspaceCommand,
    OpenWorkspaceCommand,
    UpdateWorkspaceCommand,
    WorkspaceCommand,
    WorkspacePanel,
    WorkspaceState,
)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
COMPONENT_REGISTRY_PATH = PROJECT_ROOT / "shared/registry/components.json"
WORKSPACE_EVENT_TYPES = frozenset(
    {
        "workspace.panel.opened",
        "workspace.panel.updated",
        "workspace.panel.closed",
    }
)
_COMMAND_ADAPTER: TypeAdapter[WorkspaceCommand] = TypeAdapter(WorkspaceCommand)


class WorkspaceValidationError(ValueError):
    """A workspace command or registered component is invalid."""


def _validate_visual_graph(props: Mapping[str, JsonValue]) -> None:
    root_id = props.get("root_id")
    raw_elements = props.get("elements")
    if not isinstance(root_id, str) or not isinstance(raw_elements, list):
        raise WorkspaceValidationError("visual composition requires a root and elements")
    by_id: dict[str, dict[str, JsonValue]] = {}
    for raw in raw_elements:
        if not isinstance(raw, dict):
            raise WorkspaceValidationError("visual composition elements must be objects")
        element_id = raw.get("id")
        if not isinstance(element_id, str) or element_id in by_id:
            raise WorkspaceValidationError("visual composition element IDs must be unique")
        by_id[element_id] = raw
    if root_id not in by_id:
        raise WorkspaceValidationError("visual composition root does not exist")

    parents: set[str] = set()
    for element in by_id.values():
        if element.get("type") != "group":
            continue
        children = element.get("children")
        if not isinstance(children, list):
            raise WorkspaceValidationError("visual composition group children are invalid")
        for child_id in children:
            if not isinstance(child_id, str) or child_id not in by_id:
                raise WorkspaceValidationError("visual composition references an unknown child")
            if child_id in parents:
                raise WorkspaceValidationError("visual elements may have only one parent")
            parents.add(child_id)
    if root_id in parents:
        raise WorkspaceValidationError("visual composition root may not have a parent")

    visited: set[str] = set()
    active: set[str] = set()

    def visit(element_id: str) -> None:
        if element_id in active:
            raise WorkspaceValidationError("visual composition contains a cycle")
        if element_id in visited:
            return
        active.add(element_id)
        element = by_id[element_id]
        children = element.get("children") if element.get("type") == "group" else None
        if isinstance(children, list):
            for child_id in children:
                if isinstance(child_id, str):
                    visit(child_id)
        active.remove(element_id)
        visited.add(element_id)

    visit(root_id)
    if len(visited) != len(by_id):
        raise WorkspaceValidationError("visual composition contains unreachable elements")


class ComponentRegistry:
    """Trusted component manifests and their compiled prop validators."""

    def __init__(self, manifests: Iterable[ComponentManifest]) -> None:
        manifest_list = list(manifests)
        self._manifests = {manifest.id: manifest for manifest in manifest_list}
        if len(self._manifests) != len(manifest_list):
            raise WorkspaceValidationError("component IDs must be unique")
        self._validators: dict[str, Draft202012Validator] = {}
        for manifest in manifest_list:
            try:
                Draft202012Validator.check_schema(manifest.props_schema)
            except SchemaError as error:
                raise WorkspaceValidationError(f"invalid props schema for {manifest.id}") from error
            self._validators[manifest.id] = Draft202012Validator(
                manifest.props_schema,
                format_checker=FormatChecker(),
            )

    def list(self) -> list[ComponentManifest]:
        return list(self._manifests.values())

    def get(self, component_id: str) -> ComponentManifest | None:
        return self._manifests.get(component_id)

    def validate_props(
        self,
        component_id: str,
        props: Mapping[str, JsonValue],
    ) -> None:
        validator = self._validators.get(component_id)
        if validator is None:
            raise WorkspaceValidationError(f"unknown component: {component_id}")
        errors = sorted(validator.iter_errors(dict(props)), key=lambda error: list(error.path))
        if errors:
            raise WorkspaceValidationError(f"invalid props for {component_id}: {errors[0].message}")
        if component_id == "visual-composition":
            _validate_visual_graph(dict(props))

    def parse_command(self, value: object) -> WorkspaceCommand:
        try:
            return _COMMAND_ADAPTER.validate_python(value)
        except ValidationError as error:
            raise WorkspaceValidationError("invalid workspace command") from error

    def apply(self, state: WorkspaceState, value: object) -> WorkspaceState:
        command = self.parse_command(value)
        if isinstance(command, OpenWorkspaceCommand):
            manifest = self._require_manifest(command.panel.component_id)
            self._require_operation(manifest, "open")
            if any(panel.id == command.panel.id for panel in state.panels):
                raise WorkspaceValidationError(f"panel already exists: {command.panel.id}")
            self.validate_props(command.panel.component_id, command.panel.props)
            return WorkspaceState(
                panels=[command.panel],
                focused_panel_id=command.panel.id,
            )

        index = next(
            (index for index, panel in enumerate(state.panels) if panel.id == command.panel_id),
            None,
        )
        if index is None:
            raise WorkspaceValidationError(f"unknown panel: {command.panel_id}")
        panel = state.panels[index]
        manifest = self._require_manifest(panel.component_id)
        self._require_operation(manifest, command.type)

        if isinstance(command, FocusWorkspaceCommand):
            return WorkspaceState(panels=[panel], focused_panel_id=command.panel_id)
        if isinstance(command, CloseWorkspaceCommand):
            panels = [candidate for candidate in state.panels if candidate.id != command.panel_id]
            focused = state.focused_panel_id
            if focused == command.panel_id:
                focused = panels[-1].id if panels else None
            return WorkspaceState(panels=panels, focused_panel_id=focused)

        return self._apply_update(state, index, panel, command)

    def _apply_update(
        self,
        state: WorkspaceState,
        index: int,
        panel: WorkspacePanel,
        command: UpdateWorkspaceCommand,
    ) -> WorkspaceState:
        props = {**panel.props, **command.props} if command.props is not None else panel.props
        self.validate_props(panel.component_id, props)
        updates: dict[str, object] = {"props": props}
        if command.state is not None:
            updates["state"] = {**panel.state, **command.state}
        if "title" in command.model_fields_set:
            updates["title"] = command.title
        if "resource_uri" in command.model_fields_set:
            updates["resource_uri"] = command.resource_uri
        panels = list(state.panels)
        panels[index] = panel.model_copy(update=updates)
        return state.model_copy(update={"panels": panels})

    def _require_manifest(self, component_id: str) -> ComponentManifest:
        manifest = self._manifests.get(component_id)
        if manifest is None:
            raise WorkspaceValidationError(f"unknown component: {component_id}")
        return manifest

    @staticmethod
    def _require_operation(manifest: ComponentManifest, operation: str) -> None:
        if operation not in manifest.supported_operations:
            raise WorkspaceValidationError(f"component {manifest.id} does not support {operation}")


def load_component_registry(
    path: Path = COMPONENT_REGISTRY_PATH,
) -> ComponentRegistry:
    try:
        document = ComponentRegistryDocument.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError, json.JSONDecodeError) as error:
        raise WorkspaceValidationError("component registry could not be loaded") from error
    return ComponentRegistry(document.components)


def project_workspace_events(
    events: Iterable[Event],
    registry: ComponentRegistry,
) -> WorkspaceState:
    state = WorkspaceState()
    for event in events:
        if event.type not in WORKSPACE_EVENT_TYPES:
            continue
        command = event.payload.get("command")
        state = registry.apply(state, command)
    return state
