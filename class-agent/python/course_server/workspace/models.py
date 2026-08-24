"""Portable Python bindings for the versioned workspace wire contracts."""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

ComponentOperation = Literal["open", "update", "focus", "close"]


class WorkspaceModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ComponentSize(WorkspaceModel):
    width: float = Field(gt=0)
    height: float = Field(gt=0)


class ComponentManifest(WorkspaceModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9-]*$", max_length=100)
    version: str = Field(min_length=1, max_length=50)
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=1_000)
    props_schema: dict[str, JsonValue]
    supported_operations: list[ComponentOperation] = Field(min_length=1)
    default_size: ComponentSize | None = None

    @model_validator(mode="after")
    def operations_are_unique(self) -> ComponentManifest:
        if len(self.supported_operations) != len(set(self.supported_operations)):
            raise ValueError("supported operations must be unique")
        return self


class ComponentRegistryDocument(WorkspaceModel):
    schema_version: Literal[1] = 1
    components: list[ComponentManifest]


class WorkspaceLayout(WorkspaceModel):
    width: float | None = Field(default=None, gt=0)
    height: float | None = Field(default=None, gt=0)


class WorkspacePanel(WorkspaceModel):
    id: UUID
    component_id: str = Field(pattern=r"^[a-z][a-z0-9-]*$", max_length=100)
    title: str | None = Field(default=None, min_length=1, max_length=200)
    resource_uri: str | None = Field(default=None, min_length=1, max_length=500)
    props: dict[str, JsonValue] = Field(default_factory=dict)
    state: dict[str, JsonValue] = Field(default_factory=dict)
    layout: WorkspaceLayout | None = None


class WorkspaceState(WorkspaceModel):
    panels: list[WorkspacePanel] = Field(default_factory=list)
    focused_panel_id: UUID | None = None


class DocumentHighlightAnchor(WorkspaceModel):
    resource_uri: str = Field(min_length=1, max_length=500)
    page: int = Field(ge=1)
    quote: str = Field(min_length=1, max_length=2_000)
    prefix: str | None = Field(default=None, max_length=500)
    suffix: str | None = Field(default=None, max_length=500)


class OpenWorkspaceCommand(WorkspaceModel):
    type: Literal["open"] = "open"
    panel: WorkspacePanel


class UpdateWorkspaceCommand(WorkspaceModel):
    type: Literal["update"] = "update"
    panel_id: UUID
    props: dict[str, JsonValue] | None = None
    state: dict[str, JsonValue] | None = None
    title: str | None = Field(default=None, min_length=1, max_length=200)
    resource_uri: str | None = Field(default=None, min_length=1, max_length=500)

    @model_validator(mode="after")
    def contains_a_change(self) -> UpdateWorkspaceCommand:
        if not ({"props", "state", "title", "resource_uri"} & self.model_fields_set):
            raise ValueError("update command must contain at least one change")
        return self


class FocusWorkspaceCommand(WorkspaceModel):
    type: Literal["focus"] = "focus"
    panel_id: UUID


class CloseWorkspaceCommand(WorkspaceModel):
    type: Literal["close"] = "close"
    panel_id: UUID


WorkspaceCommand = Annotated[
    OpenWorkspaceCommand | UpdateWorkspaceCommand | FocusWorkspaceCommand | CloseWorkspaceCommand,
    Field(discriminator="type"),
]
