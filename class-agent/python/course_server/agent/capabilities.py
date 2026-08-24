"""Minimal MCP-aligned tool and resource conveniences for Phase 3.

These are application wrappers, not a competing wire protocol. Their IDs, resource
URIs, and JSON input schemas translate directly to MCP concepts when the gateway is
introduced in a later phase.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar, Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from agent_core import PrincipalContext

READ_SYLLABUS_TOOL_ID = "course.read_syllabus"
COURSE_SYLLABUS_URI = "course://syllabus"
PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SYLLABUS_PATH = PROJECT_ROOT / "shared/course/syllabus/syllabus.md"

StoragePolicy = Literal["server_full", "server_summary", "local_only", "ephemeral"]


class CapabilityCatalogError(RuntimeError):
    """The trusted authorization catalog references an unregistered capability."""


class ResourceNotFound(RuntimeError):
    """A requested resource is not registered or no longer readable."""


class ToolExecutionResult(BaseModel):
    """Portable tool output plus explicit history-storage behavior."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    content: JsonValue
    summary: str | None = None
    storage_policy: StoragePolicy = "server_full"
    resource_uris: list[str] = Field(default_factory=list)


@dataclass(frozen=True)
class ToolExecutionContext:
    """Trusted execution context unavailable to model-controlled arguments."""

    principal: PrincipalContext
    conversation_id: UUID
    permitted_resource_uris: frozenset[str]


class ExecutableTool(Protocol):
    """Internal executable wrapper that maps cleanly to an MCP tool."""

    @property
    def id(self) -> str: ...

    @property
    def description(self) -> str: ...

    @property
    def input_schema(self) -> dict[str, JsonValue]: ...

    async def execute(
        self,
        arguments: Mapping[str, JsonValue],
        context: ToolExecutionContext,
    ) -> ToolExecutionResult: ...


@dataclass(frozen=True)
class ResourceDefinition:
    """Registered text resource backed by a repository-owned file."""

    uri: str
    title: str
    media_type: str
    path: Path


class ResourceContents(BaseModel):
    """Text returned from one registered resource."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    uri: str
    title: str
    media_type: str
    text: str


class ResourceProvider(Protocol):
    async def read(self, uri: str) -> ResourceContents: ...


class FileResourceProvider:
    """Reads only explicitly registered files; model input never selects a path."""

    def __init__(self, resources: Iterable[ResourceDefinition]) -> None:
        resource_list = list(resources)
        self._resources = {resource.uri: resource for resource in resource_list}
        if len(self._resources) != len(resource_list):
            raise ValueError("resource URIs must be unique")

    async def read(self, uri: str) -> ResourceContents:
        resource = self._resources.get(uri)
        if resource is None:
            raise ResourceNotFound(uri)
        try:
            text = await asyncio.to_thread(resource.path.read_text, encoding="utf-8")
        except OSError as error:
            raise ResourceNotFound(uri) from error
        return ResourceContents(
            uri=resource.uri,
            title=resource.title,
            media_type=resource.media_type,
            text=text,
        )

    @classmethod
    def with_sample_syllabus(cls) -> FileResourceProvider:
        return cls(
            [
                ResourceDefinition(
                    uri=COURSE_SYLLABUS_URI,
                    title="Sample Class Agent Syllabus",
                    media_type="text/markdown",
                    path=DEFAULT_SYLLABUS_PATH,
                )
            ]
        )


class CourseReadSyllabusTool:
    """Public tool that reads the registered syllabus resource."""

    id = READ_SYLLABUS_TOOL_ID
    description = "Read the official course syllabus resource."
    input_schema: ClassVar[dict[str, JsonValue]] = {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    }

    def __init__(self, resources: ResourceProvider) -> None:
        self._resources = resources

    async def execute(
        self,
        arguments: Mapping[str, JsonValue],
        context: ToolExecutionContext,
    ) -> ToolExecutionResult:
        if arguments:
            raise ValueError("course.read_syllabus does not accept arguments")
        if COURSE_SYLLABUS_URI not in context.permitted_resource_uris:
            raise PermissionError("course://syllabus is not authorized for this run")
        resource = await self._resources.read(COURSE_SYLLABUS_URI)
        return ToolExecutionResult(
            content=resource.text,
            summary="Read the public course syllabus.",
            storage_policy="server_full",
            resource_uris=[resource.uri],
        )


class ToolCatalog:
    """Registry that fails closed if trusted context names an unknown tool."""

    def __init__(self, tools: Iterable[ExecutableTool]) -> None:
        tool_list = list(tools)
        self._tools = {tool.id: tool for tool in tool_list}
        if len(self._tools) != len(tool_list):
            raise ValueError("tool IDs must be unique")

    def authorized(self, tool_ids: Iterable[str]) -> list[ExecutableTool]:
        authorized: list[ExecutableTool] = []
        for tool_id in tool_ids:
            tool = self._tools.get(tool_id)
            if tool is None:
                raise CapabilityCatalogError(f"unregistered permitted tool: {tool_id}")
            authorized.append(tool)
        return authorized


@dataclass(frozen=True)
class AuthorizedCapabilities:
    tool_ids: tuple[str, ...]
    resource_uris: tuple[str, ...]


class PublicCapabilityPolicy:
    """Phase 3 policy: every principal receives only the public syllabus capability."""

    def authorize(self, principal: PrincipalContext) -> AuthorizedCapabilities:
        del principal
        return AuthorizedCapabilities(
            tool_ids=(READ_SYLLABUS_TOOL_ID,),
            resource_uris=(COURSE_SYLLABUS_URI,),
        )
