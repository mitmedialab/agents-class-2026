"""Registered first-party workspace components and validated commands."""

from .models import (
    CloseWorkspaceCommand,
    ComponentManifest,
    FocusWorkspaceCommand,
    OpenWorkspaceCommand,
    UpdateWorkspaceCommand,
    WorkspaceCommand,
    WorkspacePanel,
    WorkspaceState,
)
from .registry import (
    COMPONENT_REGISTRY_PATH,
    ComponentRegistry,
    WorkspaceValidationError,
    load_component_registry,
    project_workspace_events,
)

__all__ = [
    "COMPONENT_REGISTRY_PATH",
    "CloseWorkspaceCommand",
    "ComponentManifest",
    "ComponentRegistry",
    "FocusWorkspaceCommand",
    "OpenWorkspaceCommand",
    "UpdateWorkspaceCommand",
    "WorkspaceCommand",
    "WorkspacePanel",
    "WorkspaceState",
    "WorkspaceValidationError",
    "load_component_registry",
    "project_workspace_events",
]
