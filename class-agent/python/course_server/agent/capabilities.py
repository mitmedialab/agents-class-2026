"""MCP-aligned public course tools and resources.

These are application wrappers, not a competing wire protocol. Their IDs, resource
URIs, and JSON input schemas translate directly to MCP concepts when the gateway is
introduced in a later phase.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import mimetypes
import os
import re
import shutil
import socket
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import ClassVar, Literal, Protocol, cast
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    JsonValue,
    ValidationError,
    field_validator,
)
from pypdf import PdfReader
from pypdf.errors import PdfReadError

from agent_core import PrincipalContext
from course_server.browser.constants import BROWSER_TOOL_IDS
from course_server.uploads import (
    APPLICATION_PHOTO_MEDIA_TYPES,
    StoredTemporaryUpload,
    TemporaryUploadStore,
    UploadError,
)
from course_server.workspace.constants import WORKSPACE_TOOL_IDS

READ_SYLLABUS_TOOL_ID = "course.read_syllabus"
READ_PUBLIC_FILE_TOOL_ID = "course.read_public_file"
GET_SCHEDULE_TOOL_ID = "course.get_schedule"
GET_APPLICATION_TOOL_ID = "course.get_application"
SHOW_PUBLIC_FILES_TOOL_ID = "course.show_public_files"
SEARCH_FAQ_TOOL_ID = "course.search_faq"
SEARCH_COURSE_TOOL_ID = "course.search"
SUBMIT_APPLICATION_TOOL_ID = "course.submit_application"
READ_UPLOAD_TOOL_ID = "upload.read"
WEB_SEARCH_TOOL_ID = "web.search"
WEB_IMAGE_SEARCH_TOOL_ID = "web.search_images"
VISIT_WEBPAGE_TOOL_ID = "web.visit"
COURSE_SYLLABUS_URI = "course://syllabus"
COURSE_SCHEDULE_URI = "course://schedule"
COURSE_REPOSITORIES_URI = "course://repositories"
COURSE_FAQ_URI = "course://faq"
COURSE_INSTRUCTORS_URI = "course://instructors"
COURSE_APPLICATION_URI = "course://application"
PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SYLLABUS_PATH = PROJECT_ROOT / "shared/course/syllabus/syllabus.md"
DEFAULT_RESOURCE_REGISTRY_PATH = PROJECT_ROOT / "shared/registry/resources.json"
DEFAULT_APPLICANT_DATA_PATH = PROJECT_ROOT / "var/applicants"

_SEARCH_WORD = re.compile(r"[\w'-]+", re.UNICODE)
_MAX_SEARCH_QUERY_LENGTH = 300
_MAX_SEARCH_LIMIT = 10
_MAX_WEB_QUERY_LENGTH = 300
_MAX_WEB_URL_LENGTH = 2_048
_MAX_WEB_RESULT_LENGTH = 20_000
_MAX_UPLOAD_TEXT_LENGTH = 50_000

StoragePolicy = Literal["server_full", "server_summary", "local_only", "ephemeral"]
ResourceVisibility = Literal["public"]
ResourceStatus = Literal["published", "provisional"]
RegistrationStatus = Literal[
    "MAS student for credit",
    "MIT student for credit",
    "MAS student listener",
    "MIT student listener",
    "Other student for credit",
    "Other student listener",
]
REGISTRATION_STATUS_OPTIONS: tuple[RegistrationStatus, ...] = (
    "MAS student for credit",
    "MIT student for credit",
    "MAS student listener",
    "MIT student listener",
    "Other student for credit",
    "Other student listener",
)


class CapabilityCatalogError(RuntimeError):
    """The trusted authorization catalog references an unregistered capability."""


class ResourceNotFound(RuntimeError):
    """A requested resource is not registered or no longer readable."""


class ToolValidationError(ValueError):
    """A tool request failed with a safe, model-actionable validation message."""


class ToolEmittedEvent(BaseModel):
    """Trusted event draft emitted as a consequence of successful tool execution."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    type: str = Field(min_length=1, max_length=200)
    payload: dict[str, JsonValue] = Field(default_factory=dict)
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class ToolExecutionResult(BaseModel):
    """Portable tool output plus explicit history-storage behavior."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    content: JsonValue
    summary: str | None = None
    storage_policy: StoragePolicy = "server_full"
    resource_uris: list[str] = Field(default_factory=list)
    emitted_events: list[ToolEmittedEvent] = Field(default_factory=list)


@dataclass(frozen=True)
class ToolExecutionContext:
    """Trusted execution context unavailable to model-controlled arguments."""

    principal: PrincipalContext
    conversation_id: UUID
    permitted_resource_uris: frozenset[str]
    workspace_state: dict[str, JsonValue] = field(default_factory=lambda: {"panels": []})
    transient_state: dict[str, JsonValue] = field(default_factory=dict)


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


WebTextRunner = Callable[[str], str]
ImageSearchRunner = Callable[[str, int], list[dict[str, object]]]


def _required_tool_string(
    arguments: Mapping[str, JsonValue],
    field: str,
    *,
    max_length: int,
) -> str:
    if set(arguments) != {field}:
        raise ToolValidationError(f"{field} is required and no other fields are accepted")
    raw_value = arguments.get(field)
    if not isinstance(raw_value, str):
        raise ToolValidationError(f"{field} must be text")
    value = raw_value.strip()
    if not value:
        raise ToolValidationError(f"{field} must not be blank")
    if len(value) > max_length:
        raise ToolValidationError(f"{field} is too long")
    return value


def _public_web_url(raw_url: str) -> str:
    parsed = urlsplit(raw_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ToolValidationError("url must be an absolute HTTP or HTTPS URL")
    if parsed.username is not None or parsed.password is not None:
        raise ToolValidationError("url must not contain credentials")

    try:
        address_info = socket.getaddrinfo(
            parsed.hostname,
            parsed.port or (443 if parsed.scheme == "https" else 80),
            type=socket.SOCK_STREAM,
        )
    except (OSError, ValueError) as error:
        raise ToolValidationError("url hostname could not be resolved") from error
    addresses = {item[4][0] for item in address_info if isinstance(item[4][0], str)}
    if not addresses or any(
        not ipaddress.ip_address(address.split("%", 1)[0]).is_global for address in addresses
    ):
        raise ToolValidationError("url must resolve only to public internet addresses")
    return raw_url


class PublicWebSearchTool:
    """Search the public web through an injected smolagents search implementation."""

    id = WEB_SEARCH_TOOL_ID
    description = (
        "Search the public web for current information. Results are preliminary links and "
        "snippets, not verified page contents; open relevant results before relying on them. "
        "Distinguish public information from information supplied by the user."
    )
    input_schema: ClassVar[dict[str, JsonValue]] = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "A focused public-web search query.",
                "minLength": 1,
                "maxLength": _MAX_WEB_QUERY_LENGTH,
            }
        },
        "required": ["query"],
        "additionalProperties": False,
    }

    def __init__(self, search: WebTextRunner) -> None:
        self._search = search

    async def execute(
        self,
        arguments: Mapping[str, JsonValue],
        context: ToolExecutionContext,
    ) -> ToolExecutionResult:
        del context
        query = _required_tool_string(
            arguments,
            "query",
            max_length=_MAX_WEB_QUERY_LENGTH,
        )
        try:
            result = await asyncio.to_thread(self._search, query)
        except Exception as error:
            raise ToolValidationError(
                "Public web search failed. Try a shorter or more specific query."
            ) from error
        content = result.strip()
        if not content:
            raise ToolValidationError("Public web search returned no results.")
        return ToolExecutionResult(
            content=content[:_MAX_WEB_RESULT_LENGTH],
            summary="Searched the public web.",
            storage_policy="server_summary",
        )


def _https_result_url(value: object) -> str | None:
    if not isinstance(value, str) or len(value) > _MAX_WEB_URL_LENGTH:
        return None
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        return None
    hostname = parsed.hostname.casefold()
    if hostname == "localhost" or hostname.endswith((".localhost", ".local")):
        return None
    try:
        address = ipaddress.ip_address(hostname.split("%", 1)[0])
    except ValueError:
        return value
    return value if address.is_global else None


def _image_dimension(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        dimension = value
    elif isinstance(value, str) and value.isdigit():
        dimension = int(value)
    else:
        return None
    return dimension if 1 <= dimension <= 100_000 else None


def _image_layout_metadata(width: int | None, height: int | None) -> dict[str, JsonValue]:
    if width is None or height is None:
        return {
            "dimensions_known": False,
            "layout_hint": (
                "Dimensions unavailable. Do not assume this image is suitable for a banner; "
                "prefer standard or card presentation until its size is verified."
            ),
        }
    ratio = width / height
    if 0.9 <= ratio <= 1.1:
        orientation = "square"
        aspect = "square"
    elif ratio > 1.1:
        orientation = "landscape"
        aspect = "wide" if ratio >= 1.6 else "landscape"
    else:
        orientation = "portrait"
        aspect = "portrait"
    if width >= 1_600 and height >= 900:
        resolution_tier = "large"
    elif width >= 1_000 and height >= 600:
        resolution_tier = "medium"
    else:
        resolution_tier = "small"
    if resolution_tier == "small":
        presentation = "card"
    elif aspect == "wide":
        presentation = "banner"
    else:
        presentation = "feature"
    shallow_wide = ratio >= 2.0
    recommended_width = "full" if shallow_wide or presentation == "banner" else "half"
    split_layout_safe = not shallow_wide
    placement_hint = (
        "This is a shallow image: place it full-width in a stack as a banner or standard "
        "figure; do not put it in a half-width split beside taller content."
        if shallow_wide
        else "A split feature is safe when the adjacent copy is concise."
    )
    return {
        "dimensions_known": True,
        "aspect_ratio": round(ratio, 3),
        "orientation": orientation,
        "resolution_tier": resolution_tier,
        "recommended_aspect": aspect,
        "recommended_presentation": presentation,
        "recommended_width": recommended_width,
        "split_layout_safe": split_layout_safe,
        "layout_hint": (
            f"{width}x{height}px {orientation}, {resolution_tier} resolution. "
            f"Prefer presentation={presentation}, aspect={aspect}, width={recommended_width}. "
            f"{placement_hint} Use fit=contain for figures, diagrams, and screenshots, or "
            "fit=cover for photographs."
        ),
    }


def _optional_result_text(value: object, *, max_length: int) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text[:max_length] if text else None


def _simplify_image_search_query(query: str) -> str | None:
    simplified = re.sub(r"\bsite:\S+", " ", query, flags=re.IGNORECASE)
    simplified = simplified.replace('"', "").replace("'", "")
    simplified = re.sub(r"(?<=\w)-(?=\w)", " ", simplified)
    simplified = " ".join(simplified.split())
    return simplified if simplified and simplified != query else None


def _normalize_image_results(
    raw_results: Iterable[Mapping[str, object]],
    *,
    limit: int,
) -> list[dict[str, JsonValue]]:
    results: list[dict[str, JsonValue]] = []
    seen_urls: set[str] = set()
    for raw_result in raw_results:
        thumbnail_url = _https_result_url(raw_result.get("thumbnail"))
        image_url = _https_result_url(raw_result.get("image")) or thumbnail_url
        if image_url is None or image_url in seen_urls:
            continue
        seen_urls.add(image_url)
        candidate: dict[str, JsonValue] = {
            "title": _optional_result_text(raw_result.get("title"), max_length=500)
            or "Image result",
            "image_url": image_url,
        }
        optional_values: dict[str, JsonValue | None] = {
            "thumbnail_url": thumbnail_url,
            "source_page_url": _https_result_url(raw_result.get("url")),
            "source": _optional_result_text(raw_result.get("source"), max_length=200),
            "width": _image_dimension(raw_result.get("width")),
            "height": _image_dimension(raw_result.get("height")),
        }
        candidate.update(
            {name: value for name, value in optional_values.items() if value is not None}
        )
        candidate.update(
            _image_layout_metadata(
                optional_values["width"] if isinstance(optional_values["width"], int) else None,
                optional_values["height"] if isinstance(optional_values["height"], int) else None,
            )
        )
        results.append(candidate)
        if len(results) >= limit:
            break
    return results


class PublicImageSearchTool:
    """Search public images through an injected DDGS adapter."""

    id = WEB_IMAGE_SEARCH_TOOL_ID
    description = (
        "Search public images through a DuckDuckGo-first provider for use in a registered "
        "visual workspace component. Returns direct HTTPS image and thumbnail URLs, source-page "
        "metadata, pixel dimensions when available, aspect ratio, resolution tier, and a layout "
        "recommendation including whether a split layout is safe. Start with a simple descriptive "
        "query rather than site operators or quoted syntax; the tool automatically simplifies an "
        "over-constrained query once before failing. Before composing a UI about a named person, "
        "physical project or "
        "product, place, artwork, interface, device, or visual example, use a focused query when "
        "no suitable verified imagery is already available. Prefer primary-source figures, "
        "diagrams, screenshots, prototypes, and official portraits over decorative filler."
    )
    input_schema: ClassVar[dict[str, JsonValue]] = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": (
                    "A simple descriptive image query without site: or quoted search operators."
                ),
                "minLength": 1,
                "maxLength": _MAX_WEB_QUERY_LENGTH,
            },
            "limit": {
                "type": "integer",
                "description": "Maximum image candidates, from 1 through 10.",
                "minimum": 1,
                "maximum": 10,
            },
        },
        "required": ["query"],
        "additionalProperties": False,
    }

    def __init__(self, search: ImageSearchRunner) -> None:
        self._search = search

    async def execute(
        self,
        arguments: Mapping[str, JsonValue],
        context: ToolExecutionContext,
    ) -> ToolExecutionResult:
        _reject_unknown_arguments(arguments, frozenset({"query", "limit"}))
        query = _required_text_argument(
            arguments,
            "query",
            max_length=_MAX_WEB_QUERY_LENGTH,
        )
        limit = _optional_limit(arguments, default=6)
        context.transient_state["image_search_attempted"] = True
        simplified_query = _simplify_image_search_query(query)
        search_queries = [query] + ([simplified_query] if simplified_query is not None else [])
        results: list[dict[str, JsonValue]] = []
        executed_query = query
        last_error: Exception | None = None
        for candidate_query in search_queries:
            try:
                raw_results = await asyncio.to_thread(self._search, candidate_query, limit)
            except Exception as error:
                last_error = error
                continue
            normalized = _normalize_image_results(raw_results, limit=limit)
            if normalized:
                results = normalized
                executed_query = candidate_query
                break

        if not results:
            if last_error is not None:
                raise ToolValidationError(
                    "Public image search failed after one simplified retry. Try a shorter plain "
                    "description of the subject."
                ) from last_error
            raise ToolValidationError("Public image search returned no usable HTTPS images.")
        existing_candidates = context.transient_state.get("image_search_candidates", [])
        candidate_urls = (
            [value for value in existing_candidates if isinstance(value, str)]
            if isinstance(existing_candidates, list)
            else []
        )
        candidate_urls.extend(
            str(result["image_url"])
            for result in results
            if isinstance(result.get("image_url"), str)
        )
        context.transient_state["image_search_candidates"] = list(dict.fromkeys(candidate_urls))
        existing_metadata = context.transient_state.get("image_search_metadata", [])
        metadata_by_url: dict[str, JsonValue] = {}
        if isinstance(existing_metadata, list):
            metadata_by_url.update(
                {
                    str(value["image_url"]): value
                    for value in existing_metadata
                    if isinstance(value, dict) and isinstance(value.get("image_url"), str)
                }
            )
        metadata_by_url.update(
            {
                str(result["image_url"]): result
                for result in results
                if isinstance(result.get("image_url"), str)
            }
        )
        context.transient_state["image_search_metadata"] = list(metadata_by_url.values())
        content: dict[str, JsonValue] = {
            "query": query,
            "results": cast(list[JsonValue], results),
        }
        if executed_query != query:
            content["executed_query"] = executed_query
        return ToolExecutionResult(
            content=content,
            summary=f"Found {len(results)} public image candidates.",
            storage_policy="server_summary",
        )


class PublicVisitWebpageTool:
    """Read a public webpage through an injected smolagents page-view implementation."""

    id = VISIT_WEBPAGE_TOOL_ID
    description = (
        "Open and read a relevant public webpage returned by web search. Do not access local, "
        "private-network, credential-bearing, or non-HTTP URLs."
    )
    input_schema: ClassVar[dict[str, JsonValue]] = {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "An absolute public HTTP or HTTPS URL.",
                "minLength": 1,
                "maxLength": _MAX_WEB_URL_LENGTH,
            }
        },
        "required": ["url"],
        "additionalProperties": False,
    }

    def __init__(self, visit: WebTextRunner) -> None:
        self._visit = visit

    async def execute(
        self,
        arguments: Mapping[str, JsonValue],
        context: ToolExecutionContext,
    ) -> ToolExecutionResult:
        del context
        raw_url = _required_tool_string(
            arguments,
            "url",
            max_length=_MAX_WEB_URL_LENGTH,
        )
        url = await asyncio.to_thread(_public_web_url, raw_url)
        try:
            result = await asyncio.to_thread(self._visit, url)
        except Exception as error:
            raise ToolValidationError("The public webpage could not be read.") from error
        content = result.strip()
        if not content:
            raise ToolValidationError("The public webpage returned no readable content.")
        return ToolExecutionResult(
            content=content[:_MAX_WEB_RESULT_LENGTH],
            summary="Read a public webpage.",
            storage_policy="server_summary",
        )


@dataclass(frozen=True)
class ResourceDefinition:
    """Registered text resource backed by a repository-owned file."""

    uri: str
    title: str
    media_type: str
    path: Path
    description: str = ""
    visibility: ResourceVisibility = "public"
    status: ResourceStatus = "published"
    assets: dict[str, Path] = field(default_factory=dict)


class ResourceRegistryEntry(BaseModel):
    """Validated entry from the repository-owned public resource registry."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    uri: str
    title: str
    description: str = ""
    media_type: str
    path: str
    assets: dict[str, str] = Field(default_factory=dict)
    visibility: ResourceVisibility = "public"
    status: ResourceStatus = "published"


class ResourceRegistry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    resources: list[ResourceRegistryEntry]


class ResourceSummary(BaseModel):
    """Safe public metadata; backing server paths are intentionally absent."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    uri: str
    title: str
    description: str
    media_type: str
    status: ResourceStatus


class CourseSearchResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    uri: str
    title: str
    excerpt: str
    score: int = Field(ge=1)
    status: ResourceStatus


class ResourceContents(BaseModel):
    """Text and safe asset metadata returned from one registered resource."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    uri: str
    title: str
    media_type: str
    text: str
    assets: dict[str, str] = Field(default_factory=dict)


@dataclass(frozen=True)
class ResourceFile:
    """Raw registered resource bytes for an authorized first-party viewer."""

    uri: str
    title: str
    media_type: str
    data: bytes


class ResourceProvider(Protocol):
    async def read(self, uri: str) -> ResourceContents: ...


class CourseResourceCatalog(ResourceProvider, Protocol):
    def list_public(self) -> list[ResourceSummary]: ...

    def asset_ids(self, uri: str) -> tuple[str, ...]: ...

    async def read_file(self, uri: str) -> ResourceFile: ...

    async def read_asset(self, uri: str, asset_id: str) -> ResourceFile: ...

    async def search(
        self,
        query: str,
        *,
        limit: int,
        resource_uris: frozenset[str],
    ) -> list[CourseSearchResult]: ...


class FileResourceProvider:
    """Reads only explicitly registered files; model input never selects a path."""

    def __init__(self, resources: Iterable[ResourceDefinition]) -> None:
        resource_list = list(resources)
        self._resources = {resource.uri: resource for resource in resource_list}
        if len(self._resources) != len(resource_list):
            raise ValueError("resource URIs must be unique")

    async def read(self, uri: str) -> ResourceContents:
        resource_file = await self.read_file(uri)
        resource = self._resources[uri]
        try:
            text = resource_file.data.decode("utf-8")
        except UnicodeDecodeError as error:
            raise ResourceNotFound(f"{uri} is not a UTF-8 text resource") from error
        return ResourceContents(
            uri=resource_file.uri,
            title=resource_file.title,
            media_type=resource_file.media_type,
            text=text,
            assets={
                asset_id: _asset_media_type(path)
                for asset_id, path in sorted(resource.assets.items())
            },
        )

    async def read_file(self, uri: str) -> ResourceFile:
        resource = self._resources.get(uri)
        if resource is None:
            raise ResourceNotFound(uri)
        try:
            data = await asyncio.to_thread(resource.path.read_bytes)
        except OSError as error:
            raise ResourceNotFound(uri) from error
        return ResourceFile(
            uri=resource.uri,
            title=resource.title,
            media_type=resource.media_type,
            data=data,
        )

    def asset_ids(self, uri: str) -> tuple[str, ...]:
        resource = self._resources.get(uri)
        if resource is None:
            raise ResourceNotFound(uri)
        return tuple(sorted(resource.assets))

    async def read_asset(self, uri: str, asset_id: str) -> ResourceFile:
        resource = self._resources.get(uri)
        if resource is None:
            raise ResourceNotFound(uri)
        asset_path = resource.assets.get(asset_id)
        if asset_path is None:
            raise ResourceNotFound(f"{uri} asset {asset_id}")
        try:
            data = await asyncio.to_thread(asset_path.read_bytes)
        except OSError as error:
            raise ResourceNotFound(f"{uri} asset {asset_id}") from error
        return ResourceFile(
            uri=resource.uri,
            title=asset_id,
            media_type=_asset_media_type(asset_path),
            data=data,
        )

    def list_public(self) -> list[ResourceSummary]:
        return [
            ResourceSummary(
                uri=resource.uri,
                title=resource.title,
                description=resource.description,
                media_type=resource.media_type,
                status=resource.status,
            )
            for resource in self._resources.values()
            if resource.visibility == "public"
        ]

    async def search(
        self,
        query: str,
        *,
        limit: int = 5,
        resource_uris: frozenset[str] | None = None,
    ) -> list[CourseSearchResult]:
        normalized_query = query.strip()
        if not normalized_query:
            raise ValueError("search query must not be blank")
        if len(normalized_query) > _MAX_SEARCH_QUERY_LENGTH:
            raise ValueError("search query is too long")
        if not 1 <= limit <= _MAX_SEARCH_LIMIT:
            raise ValueError(f"search limit must be between 1 and {_MAX_SEARCH_LIMIT}")

        allowed = resource_uris if resource_uris is not None else frozenset(self._resources)
        terms = tuple(dict.fromkeys(_search_terms(normalized_query)))
        if not terms:
            raise ValueError("search query must contain searchable text")

        matches: list[CourseSearchResult] = []
        for resource in self._resources.values():
            if resource.uri not in allowed or resource.visibility != "public":
                continue
            contents = await self.read(resource.uri)
            for block in _search_blocks(contents.text):
                score = _search_score(block, normalized_query, terms)
                if score:
                    matches.append(
                        CourseSearchResult(
                            uri=resource.uri,
                            title=resource.title,
                            excerpt=_search_excerpt(block, terms),
                            score=score,
                            status=resource.status,
                        )
                    )
        matches.sort(key=lambda match: (-match.score, match.uri, match.excerpt))
        return matches[:limit]

    @classmethod
    def from_registry(
        cls,
        registry_path: Path = DEFAULT_RESOURCE_REGISTRY_PATH,
    ) -> FileResourceProvider:
        return cls(load_resource_definitions(registry_path))

    @classmethod
    def with_sample_syllabus(cls) -> FileResourceProvider:
        return cls(
            [
                ResourceDefinition(
                    uri=COURSE_SYLLABUS_URI,
                    title="AI Agents for Cognitive Augmentation Syllabus",
                    media_type="text/markdown",
                    path=DEFAULT_SYLLABUS_PATH,
                )
            ]
        )


def load_resource_definitions(
    registry_path: Path = DEFAULT_RESOURCE_REGISTRY_PATH,
) -> list[ResourceDefinition]:
    """Load and confine registry paths to the repository's shared data root."""

    try:
        raw_registry = json.loads(registry_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ResourceNotFound(str(registry_path)) from error
    registry = ResourceRegistry.model_validate(raw_registry)
    shared_root = registry_path.parent.parent.resolve()
    resources: list[ResourceDefinition] = []
    for entry in registry.resources:
        path = (shared_root / entry.path).resolve()
        if not path.is_relative_to(shared_root):
            raise ValueError(f"resource path leaves shared root: {entry.path}")
        if not path.is_file():
            raise ResourceNotFound(entry.uri)
        assets: dict[str, Path] = {}
        for asset_id, asset_path_string in entry.assets.items():
            asset_path = (shared_root / asset_path_string).resolve()
            if not asset_path.is_relative_to(shared_root):
                raise ValueError(f"resource asset path leaves shared root: {asset_path_string}")
            if not asset_path.is_file():
                raise ResourceNotFound(f"{entry.uri} asset {asset_id}")
            assets[asset_id] = asset_path
        resources.append(
            ResourceDefinition(
                uri=entry.uri,
                title=entry.title,
                description=entry.description,
                media_type=entry.media_type,
                path=path,
                visibility=entry.visibility,
                status=entry.status,
                assets=assets,
            )
        )
    return resources


def _search_terms(query: str) -> list[str]:
    return [match.group(0).casefold() for match in _SEARCH_WORD.finditer(query)]


def _asset_media_type(path: Path) -> str:
    media_type, _ = mimetypes.guess_type(path.name)
    return media_type or "application/octet-stream"


def _search_blocks(text: str) -> list[str]:
    blocks = [" ".join(block.split()) for block in re.split(r"\n\s*\n", text)]
    return [block for block in blocks if block]


def _search_score(block: str, query: str, terms: tuple[str, ...]) -> int:
    normalized_block = block.casefold()
    score = sum(normalized_block.count(term) for term in terms)
    if query.casefold() in normalized_block:
        score += len(terms) + 2
    return score


def _search_excerpt(
    block: str,
    terms: tuple[str, ...],
    max_length: int = 480,
) -> str:
    if len(block) <= max_length:
        return block
    normalized = block.casefold()
    positions = [normalized.find(term) for term in terms]
    first_match = min((position for position in positions if position >= 0), default=0)
    start = max(0, first_match - max_length // 3)
    end = min(len(block), start + max_length)
    if end - start < max_length:
        start = max(0, end - max_length)
    excerpt = block[start:end].strip()
    return f"{'…' if start else ''}{excerpt}{'…' if end < len(block) else ''}"


def _reject_unknown_arguments(
    arguments: Mapping[str, JsonValue],
    allowed: frozenset[str],
) -> None:
    unknown = set(arguments) - allowed
    if unknown:
        raise ValueError(f"unexpected tool arguments: {', '.join(sorted(unknown))}")


def _required_text_argument(
    arguments: Mapping[str, JsonValue],
    name: str,
    *,
    max_length: int,
    preserve_whitespace: bool = False,
) -> str:
    value = arguments.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    if len(value) > max_length:
        raise ValueError(f"{name} exceeds the maximum length")
    return value if preserve_whitespace else value.strip()


def _optional_limit(arguments: Mapping[str, JsonValue], default: int = 5) -> int:
    value = arguments.get("limit", default)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError("limit must be an integer")
    if not 1 <= value <= _MAX_SEARCH_LIMIT:
        raise ValueError(f"limit must be between 1 and {_MAX_SEARCH_LIMIT}")
    return value


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


class CourseReadPublicFileTool:
    """Read one pre-authorized registered public resource by canonical URI."""

    id = READ_PUBLIC_FILE_TOOL_ID
    description = (
        "Read a public course file and discover its registered assets by course:// URI. "
        "Use course.show_public_files first when the appropriate URI is unknown."
    )
    input_schema: ClassVar[dict[str, JsonValue]] = {
        "type": "object",
        "properties": {
            "resource_uri": {
                "type": "string",
                "description": "Canonical course:// URI returned by course.show_public_files.",
            }
        },
        "required": ["resource_uri"],
        "additionalProperties": False,
    }

    def __init__(self, resources: ResourceProvider) -> None:
        self._resources = resources

    async def execute(
        self,
        arguments: Mapping[str, JsonValue],
        context: ToolExecutionContext,
    ) -> ToolExecutionResult:
        _reject_unknown_arguments(arguments, frozenset({"resource_uri"}))
        uri = _required_text_argument(arguments, "resource_uri", max_length=200)
        if uri not in context.permitted_resource_uris:
            raise PermissionError(f"{uri} is not authorized for this run")
        resource = await self._resources.read(uri)
        content: JsonValue = resource.text
        if resource.assets:
            registered_assets: dict[str, JsonValue] = {}
            for asset_id, media_type in resource.assets.items():
                registered_assets[asset_id] = media_type
            content = {
                "text": resource.text,
                "registered_assets": registered_assets,
            }
        return ToolExecutionResult(
            content=content,
            summary=f"Read public course resource {resource.uri}.",
            storage_policy="server_full",
            resource_uris=[resource.uri],
        )


def _extract_upload_text(upload: StoredTemporaryUpload) -> str:
    if upload.receipt.media_type == "application/pdf":
        try:
            reader = PdfReader(upload.path)
            pages: list[str] = []
            length = 0
            for index, page in enumerate(reader.pages, start=1):
                text = (page.extract_text() or "").strip()
                if not text:
                    continue
                section = f"--- Page {index} ---\n{text}"
                remaining = _MAX_UPLOAD_TEXT_LENGTH - length
                if remaining <= 0:
                    break
                pages.append(section[:remaining])
                length += len(section)
            return "\n\n".join(pages)
        except (OSError, PdfReadError, ValueError) as error:
            raise ToolValidationError("The uploaded PDF could not be read.") from error
    try:
        return upload.path.read_text(encoding="utf-8")[:_MAX_UPLOAD_TEXT_LENGTH]
    except (OSError, UnicodeDecodeError) as error:
        raise ToolValidationError("The uploaded file does not contain readable text.") from error


class ReadTemporaryUploadTool:
    """Read one principal-owned temporary document without exposing its server path."""

    id = READ_UPLOAD_TOOL_ID
    description = (
        "Read text from a temporary file the user attached in chat. For PDF, Markdown, "
        "plain-text, CSV, or JSON artifacts, call this with the upload UUID, then open the "
        "returned upload:// resource in document-viewer. Never substitute a public copy when "
        "the attached artifact is available."
    )
    input_schema: ClassVar[dict[str, JsonValue]] = {
        "type": "object",
        "properties": {
            "upload_id": {
                "type": "string",
                "format": "uuid",
                "description": "Temporary upload UUID supplied with the user's attachment.",
            }
        },
        "required": ["upload_id"],
        "additionalProperties": False,
    }

    def __init__(self, uploads: TemporaryUploadStore) -> None:
        self._uploads = uploads

    async def execute(
        self,
        arguments: Mapping[str, JsonValue],
        context: ToolExecutionContext,
    ) -> ToolExecutionResult:
        _reject_unknown_arguments(arguments, frozenset({"upload_id"}))
        try:
            upload_id = UUID(_required_text_argument(arguments, "upload_id", max_length=36))
        except ValueError as error:
            raise ToolValidationError("upload_id must be a UUID.") from error
        resource_uri = f"upload://{upload_id}"
        if resource_uri not in context.permitted_resource_uris:
            raise PermissionError("The temporary upload is not authorized for this run.")
        try:
            upload = await self._uploads.get_for_principal(upload_id, context.principal)
        except UploadError as error:
            raise ToolValidationError("The temporary upload is unavailable or expired.") from error
        if upload.receipt.media_type.startswith("image/"):
            content = (
                f"Attached image: {upload.receipt.filename} "
                f"({upload.receipt.media_type}, {upload.receipt.size_bytes} bytes)."
            )
        else:
            content = await asyncio.to_thread(_extract_upload_text, upload)
            if not content.strip():
                content = "The document opened successfully but contains no extractable text."
        return ToolExecutionResult(
            content=content,
            summary=f"Read temporary upload {upload.receipt.filename}.",
            storage_policy="server_summary",
            resource_uris=[resource_uri],
        )


class CourseGetScheduleTool:
    """Read the official schedule while preserving its provisional status."""

    id = GET_SCHEDULE_TOOL_ID
    description = (
        "Read the current course schedule. Preserve its provisional status and do not "
        "supply dates or details absent from the resource."
    )
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
            raise ValueError("course.get_schedule does not accept arguments")
        if COURSE_SCHEDULE_URI not in context.permitted_resource_uris:
            raise PermissionError("course://schedule is not authorized for this run")
        resource = await self._resources.read(COURSE_SCHEDULE_URI)
        return ToolExecutionResult(
            content=resource.text,
            summary="Read the provisional public course schedule.",
            storage_policy="server_full",
            resource_uris=[resource.uri],
        )


class CourseGetApplicationTool:
    """Read the official application facts and required fields."""

    id = GET_APPLICATION_TOOL_ID
    description = (
        "Read the official application capacity, priority order, deadlines, required "
        "fields, photo requirement, and interaction instructions. Call this first when a "
        "user wants to apply or asks about applying; do not substitute general application "
        "advice."
    )
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
            raise ValueError("course.get_application does not accept arguments")
        if COURSE_APPLICATION_URI not in context.permitted_resource_uris:
            raise PermissionError("application information is not authorized for this run")
        resource = await self._resources.read(COURSE_APPLICATION_URI)
        return ToolExecutionResult(
            content=resource.text,
            summary="Read the public course application information.",
            storage_policy="server_full",
            resource_uris=[resource.uri],
        )


class CourseShowPublicFilesTool:
    """List public resource metadata without leaking server filesystem paths."""

    id = SHOW_PUBLIC_FILES_TOOL_ID
    description = "List the public course files available to the current visitor."
    input_schema: ClassVar[dict[str, JsonValue]] = {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    }

    def __init__(self, resources: CourseResourceCatalog) -> None:
        self._resources = resources

    async def execute(
        self,
        arguments: Mapping[str, JsonValue],
        context: ToolExecutionContext,
    ) -> ToolExecutionResult:
        if arguments:
            raise ValueError("course.show_public_files does not accept arguments")
        visible = [
            summary.model_dump(mode="json")
            for summary in self._resources.list_public()
            if summary.uri in context.permitted_resource_uris
        ]
        return ToolExecutionResult(
            content=visible,
            summary=f"Listed {len(visible)} public course resources.",
            storage_policy="server_full",
        )


class CourseSearchTool:
    """Search authorized public course resources using inspectable lexical matching."""

    id = SEARCH_COURSE_TOOL_ID
    description = (
        "Search the official syllabus, provisional schedule, repository overview, "
        "public FAQ, course staff profiles, and application guide."
    )
    input_schema: ClassVar[dict[str, JsonValue]] = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Words or phrase to find in official course resources.",
            },
            "limit": {
                "type": "integer",
                "description": "Maximum results, from 1 through 10.",
                "minimum": 1,
                "maximum": 10,
            },
        },
        "required": ["query"],
        "additionalProperties": False,
    }

    def __init__(self, resources: CourseResourceCatalog) -> None:
        self._resources = resources

    async def execute(
        self,
        arguments: Mapping[str, JsonValue],
        context: ToolExecutionContext,
    ) -> ToolExecutionResult:
        _reject_unknown_arguments(arguments, frozenset({"query", "limit"}))
        query = _required_text_argument(
            arguments,
            "query",
            max_length=_MAX_SEARCH_QUERY_LENGTH,
        )
        results = await self._resources.search(
            query,
            limit=_optional_limit(arguments),
            resource_uris=context.permitted_resource_uris,
        )
        searched_uris = [
            resource.uri
            for resource in self._resources.list_public()
            if resource.uri in context.permitted_resource_uris
        ]
        return ToolExecutionResult(
            content=[result.model_dump(mode="json") for result in results],
            summary=f"Found {len(results)} public course resource matches.",
            storage_policy="server_full",
            resource_uris=searched_uris,
        )


class CourseSearchFaqTool:
    """Search only the published public FAQ resource."""

    id = SEARCH_FAQ_TOOL_ID
    description = "Search published answers in the public course FAQ."
    input_schema = CourseSearchTool.input_schema

    def __init__(self, resources: CourseResourceCatalog) -> None:
        self._resources = resources

    async def execute(
        self,
        arguments: Mapping[str, JsonValue],
        context: ToolExecutionContext,
    ) -> ToolExecutionResult:
        _reject_unknown_arguments(arguments, frozenset({"query", "limit"}))
        if COURSE_FAQ_URI not in context.permitted_resource_uris:
            raise PermissionError("course://faq is not authorized for this run")
        query = _required_text_argument(
            arguments,
            "query",
            max_length=_MAX_SEARCH_QUERY_LENGTH,
        )
        results = await self._resources.search(
            query,
            limit=_optional_limit(arguments),
            resource_uris=frozenset({COURSE_FAQ_URI}),
        )
        return ToolExecutionResult(
            content=[result.model_dump(mode="json") for result in results],
            summary=f"Found {len(results)} public FAQ matches.",
            storage_policy="server_full",
            resource_uris=[COURSE_FAQ_URI],
        )


class ApplicationReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    application_id: UUID
    submitted_at: datetime


class CourseApplication(BaseModel):
    """Complete structured application; every field must contain meaningful input."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    name: str = Field(min_length=2, max_length=200)
    email: EmailStr
    department_research_group_year_of_study_mit: str = Field(min_length=1, max_length=1_000)
    personal_webpage: str = Field(min_length=1, max_length=2_000)
    interests: str = Field(min_length=1, max_length=4_000)
    why_take_this_class: str = Field(min_length=1, max_length=4_000)
    knowledgeable_about: str = Field(min_length=1, max_length=4_000)
    skill_set: str = Field(min_length=1, max_length=4_000)
    registration_status: RegistrationStatus
    listener_willing_to_do_weekly_builds: str = Field(min_length=1, max_length=500)
    questions_or_comments_for_instructors: str = Field(min_length=1, max_length=4_000)
    photo_upload_id: UUID

    @field_validator(
        "name",
        "department_research_group_year_of_study_mit",
        "personal_webpage",
        "interests",
        "why_take_this_class",
        "knowledgeable_about",
        "skill_set",
        "registration_status",
        "listener_willing_to_do_weekly_builds",
        "questions_or_comments_for_instructors",
    )
    @classmethod
    def reject_placeholders(cls, value: str) -> str:
        if value.strip().casefold() in {"-", "tbd", "unknown"}:
            raise ValueError("placeholder answers are not accepted")
        return value


class ApplicantStore(Protocol):
    async def submit(
        self,
        *,
        application: CourseApplication,
        principal: PrincipalContext,
        photo: StoredTemporaryUpload,
    ) -> ApplicationReceipt: ...


class FileApplicantStore:
    """Private server-side applicant storage with generated, non-user-controlled paths."""

    def __init__(self, directory: Path = DEFAULT_APPLICANT_DATA_PATH) -> None:
        self._directory = directory

    async def submit(
        self,
        *,
        application: CourseApplication,
        principal: PrincipalContext,
        photo: StoredTemporaryUpload,
    ) -> ApplicationReceipt:
        receipt = ApplicationReceipt(application_id=uuid4(), submitted_at=datetime.now(UTC))
        payload: dict[str, JsonValue] = {
            "schema_version": 1,
            "application_id": str(receipt.application_id),
            "submitted_at": receipt.submitted_at.isoformat(),
            "application": application.model_dump(mode="json"),
            "photo_filename": f"photo{_photo_extension(photo.receipt.media_type)}",
            "original_photo_filename": photo.receipt.filename,
            "principal": {
                "authenticated": principal.authenticated,
                "user_id": str(principal.user_id) if principal.user_id else None,
                "anonymous_session_id": (
                    str(principal.anonymous_session_id) if principal.anonymous_session_id else None
                ),
            },
        }
        await asyncio.to_thread(self._write_private_application, receipt, payload, photo)
        return receipt

    def _write_private_application(
        self,
        receipt: ApplicationReceipt,
        payload: dict[str, JsonValue],
        photo: StoredTemporaryUpload,
    ) -> None:
        self._directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._directory.chmod(0o700)
        timestamp = receipt.submitted_at.strftime("%Y%m%dT%H%M%SZ")
        final_directory = self._directory / f"{timestamp}_{receipt.application_id}"
        temporary_directory = self._directory / f".{receipt.application_id}.tmp"
        temporary_directory.mkdir(mode=0o700)
        try:
            application_path = temporary_directory / "application.json"
            descriptor = os.open(
                application_path,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
            )
            with os.fdopen(descriptor, "w", encoding="utf-8") as applicant_file:
                json.dump(payload, applicant_file, ensure_ascii=False, indent=2, sort_keys=True)
                applicant_file.write("\n")
            photo_path = temporary_directory / str(payload["photo_filename"])
            shutil.copyfile(photo.path, photo_path)
            photo_path.chmod(0o600)
            temporary_directory.rename(final_directory)
        except Exception:
            shutil.rmtree(temporary_directory, ignore_errors=True)
            raise


class CourseSubmitApplicationTool:
    """Store an explicitly requested course application outside the public catalog."""

    id = SUBMIT_APPLICATION_TOOL_ID
    redact_arguments_in_events = True
    description = (
        "Submit a course application only after the user explicitly approves the complete "
        "application. Every field must come from the user. Gather any missing field and a "
        "temporary face-photo upload before calling this tool."
    )
    input_schema: ClassVar[dict[str, JsonValue]] = {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Name field.",
            },
            "email": {
                "type": "string",
                "description": "Email field.",
            },
            "department_research_group_year_of_study_mit": {
                "type": "string",
                "description": "Department / Research Group / Year of Study MIT field.",
            },
            "personal_webpage": {
                "type": "string",
                "description": "Personal Webpage field; state explicitly if there is none.",
            },
            "interests": {
                "type": "string",
                "description": "Interests field.",
            },
            "why_take_this_class": {
                "type": "string",
                "description": "Why do you want to take this class? field.",
            },
            "knowledgeable_about": {
                "type": "string",
                "description": "Knowledgeable about field.",
            },
            "skill_set": {
                "type": "string",
                "description": "Skill-set field.",
            },
            "registration_status": {
                "type": "string",
                "enum": list(REGISTRATION_STATUS_OPTIONS),
                "description": (
                    "The applicant's combined affiliation and participation mode. Ask the "
                    "applicant to choose one option; never infer for-credit or listener status "
                    "from an MAS, MIT, or other affiliation."
                ),
            },
            "listener_willing_to_do_weekly_builds": {
                "type": "string",
                "description": (
                    "For listeners: whether the applicant is willing to complete the "
                    "weekly builds; use not applicable for non-listeners."
                ),
            },
            "questions_or_comments_for_instructors": {
                "type": "string",
                "description": (
                    "Questions or comments for instructors field; state explicitly if none."
                ),
            },
            "photo_upload_id": {
                "type": "string",
                "description": (
                    "UUID returned after the applicant uploads a recent face photo in chat."
                ),
            },
        },
        "required": [
            "name",
            "email",
            "department_research_group_year_of_study_mit",
            "personal_webpage",
            "interests",
            "why_take_this_class",
            "knowledgeable_about",
            "skill_set",
            "registration_status",
            "listener_willing_to_do_weekly_builds",
            "questions_or_comments_for_instructors",
            "photo_upload_id",
        ],
        "additionalProperties": False,
    }

    def __init__(
        self,
        applicants: ApplicantStore,
        uploads: TemporaryUploadStore,
    ) -> None:
        self._applicants = applicants
        self._uploads = uploads

    async def execute(
        self,
        arguments: Mapping[str, JsonValue],
        context: ToolExecutionContext,
    ) -> ToolExecutionResult:
        try:
            application = CourseApplication.model_validate(arguments)
        except ValidationError as error:
            invalid_fields = sorted(
                {
                    str(item["loc"][0]) if item["loc"] else "application"
                    for item in error.errors(include_url=False)
                }
            )
            raise ToolValidationError(
                "Application incomplete or invalid. Ask the user for: "
                + ", ".join(invalid_fields)
                + "."
            ) from error
        try:
            photo = await self._uploads.get_for_principal(
                application.photo_upload_id,
                context.principal,
            )
        except UploadError as error:
            raise ToolValidationError(
                "The application photo is unavailable or expired. Ask the user to upload it again."
            ) from error
        if photo.receipt.media_type not in APPLICATION_PHOTO_MEDIA_TYPES:
            raise ToolValidationError("The application photo must be a JPEG, PNG, or WebP image.")
        if not await asyncio.to_thread(_has_valid_image_signature, photo):
            raise ToolValidationError(
                "The application photo content is not a valid JPEG, PNG, or WebP image."
            )
        receipt = await self._applicants.submit(
            application=application,
            principal=context.principal,
            photo=photo,
        )
        return ToolExecutionResult(
            content={
                "application_id": str(receipt.application_id),
                "status": "received",
                "message": "The course application was stored for review.",
            },
            summary=f"Stored course application {receipt.application_id} for review.",
            storage_policy="server_summary",
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
    """Every principal receives the Phase 6 public course capabilities."""

    def __init__(
        self,
        resource_uris: Iterable[str] | None = None,
        *,
        browser_enabled: bool = False,
    ) -> None:
        resolved = tuple(
            resource_uris
            if resource_uris is not None
            else (
                COURSE_SYLLABUS_URI,
                COURSE_SCHEDULE_URI,
                COURSE_REPOSITORIES_URI,
                COURSE_FAQ_URI,
                COURSE_INSTRUCTORS_URI,
                COURSE_APPLICATION_URI,
            )
        )
        if len(resolved) != len(set(resolved)):
            raise ValueError("public resource URIs must be unique")
        if any(not uri.startswith("course://") for uri in resolved):
            raise ValueError("public resource URIs must use the course:// scheme")
        self._resource_uris = resolved
        self._browser_enabled = browser_enabled

    def authorize(self, principal: PrincipalContext) -> AuthorizedCapabilities:
        del principal
        return AuthorizedCapabilities(
            tool_ids=(
                READ_SYLLABUS_TOOL_ID,
                READ_PUBLIC_FILE_TOOL_ID,
                GET_SCHEDULE_TOOL_ID,
                GET_APPLICATION_TOOL_ID,
                SHOW_PUBLIC_FILES_TOOL_ID,
                SEARCH_FAQ_TOOL_ID,
                SEARCH_COURSE_TOOL_ID,
                READ_UPLOAD_TOOL_ID,
                SUBMIT_APPLICATION_TOOL_ID,
                WEB_SEARCH_TOOL_ID,
                WEB_IMAGE_SEARCH_TOOL_ID,
                VISIT_WEBPAGE_TOOL_ID,
                *WORKSPACE_TOOL_IDS,
                *(BROWSER_TOOL_IDS if self._browser_enabled else ()),
            ),
            resource_uris=self._resource_uris,
        )


def _photo_extension(media_type: str) -> str:
    return {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
    }[media_type]


def _has_valid_image_signature(upload: StoredTemporaryUpload) -> bool:
    header = upload.path.read_bytes()[:12]
    if upload.receipt.media_type == "image/jpeg":
        return header.startswith(b"\xff\xd8\xff")
    if upload.receipt.media_type == "image/png":
        return header.startswith(b"\x89PNG\r\n\x1a\n")
    if upload.receipt.media_type == "image/webp":
        return len(header) >= 12 and header[:4] == b"RIFF" and header[8:12] == b"WEBP"
    return False
