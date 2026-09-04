"""MCP-aligned public and role-scoped course tools and resources.

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
    Field,
    JsonValue,
    ValidationError,
)
from pypdf import PdfReader
from pypdf.errors import PdfReadError

from agent_core import PrincipalContext
from course_server.browser.constants import BROWSER_TOOL_IDS
from course_server.course_application import (
    LISTENER_BUILD_OPTIONS,
    REGISTRATION_STATUS_OPTIONS,
    SCHOOL_OPTIONS,
    CourseApplication,
)
from course_server.uploads import (
    APPLICATION_PHOTO_MEDIA_TYPES,
    MAX_UPLOAD_BYTES,
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
LIST_PRIVATE_RESOURCES_TOOL_ID = "course.list_private_resources"
READ_PRIVATE_RESOURCE_TOOL_ID = "course.read_private_resource"
INSTRUCTOR_LIST_APPLICATIONS_TOOL_ID = "instructor.list_applications"
INSTRUCTOR_READ_APPLICATION_TOOL_ID = "instructor.read_application"
INSTRUCTOR_INSPECT_APPLICATION_IMAGES_TOOL_ID = "instructor.inspect_application_images"
WEB_SEARCH_TOOL_ID = "web.search"
WEB_IMAGE_SEARCH_TOOL_ID = "web.search_images"
WEB_IMAGE_INSPECT_TOOL_ID = "web.inspect_images"
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
DEFAULT_COURSE_DATA_PATH = PROJECT_ROOT / "data"
DEFAULT_APPLICANT_DATA_PATH = PROJECT_ROOT / "var/applicants"

_SEARCH_WORD = re.compile(r"[\w'-]+", re.UNICODE)
_MAX_SEARCH_QUERY_LENGTH = 300
_MAX_SEARCH_LIMIT = 10
_MAX_WEB_QUERY_LENGTH = 300
_MAX_WEB_URL_LENGTH = 2_048
_MAX_WEB_RESULT_LENGTH = 20_000
_IMAGE_SEARCH_OVERSAMPLE_FACTOR = 4
_IMAGE_SEARCH_MIN_CANDIDATES = 12
_IMAGE_SEARCH_MAX_CANDIDATES = 30
_MAX_UPLOAD_TEXT_LENGTH = 50_000
_MAX_APPLICATION_RECORD_BYTES = 256 * 1024
StoragePolicy = Literal["server_full", "server_summary", "local_only", "ephemeral"]
ResourceVisibility = Literal["public", "students", "instructors"]
ResourceStatus = Literal["published", "provisional"]


class CapabilityCatalogError(RuntimeError):
    """The trusted authorization catalog references an unregistered capability."""


class ResourceNotFound(RuntimeError):
    """A requested resource is not registered or no longer readable."""


class ToolValidationError(ValueError):
    """A tool request failed with a safe, model-actionable validation message."""


class ToolProviderError(RuntimeError):
    """An external provider failed with a safe category and model-actionable message."""

    def __init__(
        self,
        message: str,
        *,
        category: Literal["invalid_request", "permission_denied", "temporary_failure"],
    ) -> None:
        super().__init__(message)
        self.category = category


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
WebVisitRunner = Callable[[str], str | Mapping[str, object]]
ImageSearchRunner = Callable[[str, int], list[dict[str, object]]]
ImageProbeRunner = Callable[[str], str | None]
ImageInspectionRunner = Callable[[list[str], str], str]


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
        query = _required_tool_string(
            arguments,
            "query",
            max_length=_MAX_WEB_QUERY_LENGTH,
        )
        context.transient_state["web_search_attempted"] = True
        try:
            result = await asyncio.to_thread(self._search, query)
        except Exception as error:
            status_code = _provider_http_status_code(error)
            if status_code in {401, 403}:
                raise ToolProviderError(
                    "Public web search credentials were rejected. Do not retry this turn.",
                    category="permission_denied",
                ) from error
            if status_code == 429:
                raise ToolProviderError(
                    "Public web search is rate limited. Do not retry this turn.",
                    category="temporary_failure",
                ) from error
            if status_code is not None and 400 <= status_code < 500:
                raise ToolProviderError(
                    "Public web search rejected the query.",
                    category="invalid_request",
                ) from error
            raise ToolProviderError(
                "Public web search is temporarily unavailable. Do not retry this turn.",
                category="temporary_failure",
            ) from error
        content = result.strip()
        if not content:
            raise ToolValidationError("Public web search returned no results.")
        return ToolExecutionResult(
            content=content[:_MAX_WEB_RESULT_LENGTH],
            summary="Searched the public web.",
            storage_policy="server_summary",
        )


def _provider_http_status_code(error: BaseException) -> int | None:
    current: BaseException | None = error
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        response = getattr(current, "response", None)
        status_code = getattr(response, "status_code", None)
        if isinstance(status_code, int):
            return status_code
        direct_status_code = getattr(current, "status_code", None)
        if isinstance(direct_status_code, int):
            return direct_status_code
        current = current.__cause__ or current.__context__
    return None


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


def _image_search_candidate_limit(result_limit: int) -> int:
    """Return a bounded overfetch pool used to fill verified result slots."""

    return min(
        _IMAGE_SEARCH_MAX_CANDIDATES,
        max(_IMAGE_SEARCH_MIN_CANDIDATES, result_limit * _IMAGE_SEARCH_OVERSAMPLE_FACTOR),
    )


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


async def _verified_image_results(
    candidates: list[dict[str, JsonValue]],
    *,
    limit: int,
    probe: ImageProbeRunner,
) -> list[dict[str, JsonValue]]:
    async def probe_candidate(candidate: dict[str, JsonValue]) -> str | None:
        image_url = str(candidate["image_url"])
        primary = await asyncio.to_thread(probe, image_url)
        if primary is not None:
            return primary
        thumbnail_url = candidate.get("thumbnail_url")
        if isinstance(thumbnail_url, str) and thumbnail_url != image_url:
            return await asyncio.to_thread(probe, thumbnail_url)
        return None

    outcomes = await asyncio.gather(
        *(probe_candidate(candidate) for candidate in candidates),
        return_exceptions=True,
    )
    verified: list[dict[str, JsonValue]] = []
    seen_urls: set[str] = set()
    for candidate, outcome in zip(candidates, outcomes, strict=True):
        final_url = _https_result_url(outcome) if isinstance(outcome, str) else None
        if final_url is None or final_url in seen_urls:
            continue
        seen_urls.add(final_url)
        result = dict(candidate)
        result["image_url"] = final_url
        if isinstance(result.get("thumbnail_url"), str) and final_url == result["thumbnail_url"]:
            result["thumbnail_url"] = final_url
        result["verified"] = True
        verified.append(result)
        if len(verified) >= limit:
            break
    return verified


class PublicImageSearchTool:
    """Search public images through an injected DDGS adapter."""

    id = WEB_IMAGE_SEARCH_TOOL_ID
    description = (
        "Search public images through a DuckDuckGo-first provider for use in a registered "
        "visual workspace component. Returns only server-fetched, verified HTTPS image URLs "
        "and automatically overfetches candidates to fill the requested verified-result slots "
        "together with thumbnail URLs, source-page "
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

    def __init__(self, search: ImageSearchRunner, probe: ImageProbeRunner) -> None:
        self._search = search
        self._probe = probe

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
        candidate_limit = _image_search_candidate_limit(limit)
        context.transient_state["image_search_attempted"] = True
        simplified_query = _simplify_image_search_query(query)
        search_queries = [query] + ([simplified_query] if simplified_query is not None else [])
        results: list[dict[str, JsonValue]] = []
        executed_query = query
        last_error: Exception | None = None
        search_succeeded = False
        for candidate_query in search_queries:
            try:
                raw_results = await asyncio.to_thread(
                    self._search,
                    candidate_query,
                    candidate_limit,
                )
            except Exception as error:
                last_error = error
                continue
            search_succeeded = True
            normalized = _normalize_image_results(raw_results, limit=candidate_limit)
            verified = await _verified_image_results(
                normalized,
                limit=limit,
                probe=self._probe,
            )
            if verified:
                results = verified
                executed_query = candidate_query
                break

        if not results:
            if last_error is not None and not search_succeeded:
                raise ToolValidationError(
                    "Public image search failed after one simplified retry. Try a shorter plain "
                    "description of the subject."
                ) from last_error
            raise ToolValidationError(
                "Public image search returned no accessible HTTPS images. Try a different "
                "source or a simpler query."
            )
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
            summary=f"Found {len(results)} verified public image candidates.",
            storage_policy="server_summary",
        )


class PublicImageInspectionTool:
    """Visually inspect a bounded batch of previously discovered public images."""

    id = WEB_IMAGE_INSPECT_TOOL_ID
    description = (
        "Inspect one to four images discovered by web.search_images or web.visit in one "
        "multimodal call. Use this to compare actual visible content and suitability before "
        "selecting images for a workspace composition. Image appearance alone does not verify "
        "identity or factual claims."
    )
    input_schema: ClassVar[dict[str, JsonValue]] = {
        "type": "object",
        "properties": {
            "urls": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 1,
                "maxItems": 4,
                "description": "One to four image URLs returned by an earlier web tool call.",
            },
            "prompt": {
                "type": "string",
                "minLength": 1,
                "maxLength": 1_000,
                "description": "What to inspect or compare across the images.",
            },
        },
        "required": ["urls", "prompt"],
        "additionalProperties": False,
    }

    def __init__(self, inspect: ImageInspectionRunner, probe: ImageProbeRunner) -> None:
        self._inspect = inspect
        self._probe = probe

    async def execute(
        self,
        arguments: Mapping[str, JsonValue],
        context: ToolExecutionContext,
    ) -> ToolExecutionResult:
        _reject_unknown_arguments(arguments, frozenset({"urls", "prompt"}))
        raw_urls = arguments.get("urls")
        if (
            not isinstance(raw_urls, list)
            or not 1 <= len(raw_urls) <= 4
            or any(not isinstance(value, str) for value in raw_urls)
        ):
            raise ToolValidationError("urls must contain one to four image URLs")
        urls = list(dict.fromkeys(cast(list[str], raw_urls)))
        prompt = _required_text_argument(arguments, "prompt", max_length=1_000)
        known_values: list[JsonValue] = []
        for key in ("image_search_candidates", "page_image_candidates"):
            values = context.transient_state.get(key, [])
            if isinstance(values, list):
                known_values.extend(values)
        known_urls = {value for value in known_values if isinstance(value, str)}
        if any(url not in known_urls for url in urls):
            raise ToolValidationError(
                "Inspect only image URLs returned by web.search_images or web.visit in this run."
            )
        outcomes: list[str | Exception | None] = []
        for url in urls:
            try:
                outcomes.append(self._probe(url))
            except Exception as error:
                outcomes.append(error)
        verified = [
            final_url
            for final_url in outcomes
            if isinstance(final_url, str) and _https_result_url(final_url) is not None
        ]
        if not verified:
            raise ToolValidationError("None of the selected images remains safely accessible.")
        try:
            analysis = self._inspect(verified, prompt)
        except Exception as error:
            raise ToolValidationError("The selected images could not be inspected.") from error
        if not analysis.strip():
            raise ToolValidationError("Image inspection returned no visual analysis.")
        existing = context.transient_state.get("image_search_candidates", [])
        candidates = (
            [value for value in existing if isinstance(value, str)]
            if isinstance(existing, list)
            else []
        )
        context.transient_state["image_search_candidates"] = list(
            dict.fromkeys([*candidates, *verified])
        )
        return ToolExecutionResult(
            content={"images": verified, "analysis": analysis.strip()},
            summary=f"Inspected {len(verified)} public images.",
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

    def __init__(self, visit: WebVisitRunner) -> None:
        self._visit = visit

    async def execute(
        self,
        arguments: Mapping[str, JsonValue],
        context: ToolExecutionContext,
    ) -> ToolExecutionResult:
        raw_url = _required_tool_string(
            arguments,
            "url",
            max_length=_MAX_WEB_URL_LENGTH,
        )
        url = _public_web_url(raw_url)
        try:
            result = self._visit(url)
        except Exception as error:
            raise ToolValidationError("The public webpage could not be read.") from error
        if isinstance(result, str):
            content: JsonValue = result.strip()
            image_urls: list[str] = []
        elif isinstance(result, Mapping):
            text = result.get("text")
            raw_images = result.get("images")
            images = (
                [dict(value) for value in raw_images if isinstance(value, Mapping)]
                if isinstance(raw_images, list)
                else []
            )
            image_urls = [
                str(image["image_url"])
                for image in images
                if _https_result_url(image.get("image_url")) is not None
            ]
            content = {
                "url": str(result.get("url", url)),
                "text": text[:_MAX_WEB_RESULT_LENGTH] if isinstance(text, str) else "",
                "images": cast(list[JsonValue], images),
            }
        else:
            raise ToolValidationError("The public webpage returned an invalid result.")
        if (isinstance(content, str) and not content) or (
            isinstance(content, dict) and not content.get("text") and not content.get("images")
        ):
            raise ToolValidationError("The public webpage returned no readable content.")
        if image_urls:
            existing = context.transient_state.get("page_image_candidates", [])
            candidates = (
                [value for value in existing if isinstance(value, str)]
                if isinstance(existing, list)
                else []
            )
            context.transient_state["page_image_candidates"] = list(
                dict.fromkeys([*candidates, *image_urls])
            )
        return ToolExecutionResult(
            content=content[:_MAX_WEB_RESULT_LENGTH] if isinstance(content, str) else content,
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
    visibility: Literal["public"] = "public"
    status: ResourceStatus = "published"


class ResourceRegistry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    resources: list[ResourceRegistryEntry]


class ProtectedResourceManifestEntry(BaseModel):
    """One role-scoped resource kept outside the public generated registry."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    uri: str
    title: str
    description: str = ""
    media_type: str
    file: str
    assets: dict[str, str] = Field(default_factory=dict)
    visibility: Literal["students", "instructors"]
    status: ResourceStatus = "published"


class ProtectedResourceManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    resource: ProtectedResourceManifestEntry


class ResourceSummary(BaseModel):
    """Safe path-free resource metadata for an authorized principal."""

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

    def list_authorized(self, principal: PrincipalContext) -> list[ResourceSummary]: ...

    def authorized_resource_uris(self, principal: PrincipalContext) -> tuple[str, ...]: ...

    def is_public(self, uri: str) -> bool: ...

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

    def list_authorized(self, principal: PrincipalContext) -> list[ResourceSummary]:
        return [
            ResourceSummary(
                uri=resource.uri,
                title=resource.title,
                description=resource.description,
                media_type=resource.media_type,
                status=resource.status,
            )
            for resource in self._resources.values()
            if _resource_visible_to_principal(resource.visibility, principal)
        ]

    def authorized_resource_uris(self, principal: PrincipalContext) -> tuple[str, ...]:
        return tuple(resource.uri for resource in self.list_authorized(principal))

    def is_public(self, uri: str) -> bool:
        resource = self._resources.get(uri)
        if resource is None:
            raise ResourceNotFound(uri)
        return resource.visibility == "public"

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

        allowed = (
            resource_uris
            if resource_uris is not None
            else frozenset(
                resource.uri
                for resource in self._resources.values()
                if resource.visibility == "public"
            )
        )
        terms = tuple(dict.fromkeys(_search_terms(normalized_query)))
        if not terms:
            raise ValueError("search query must contain searchable text")

        matches: list[CourseSearchResult] = []
        for resource in self._resources.values():
            if resource.uri not in allowed:
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
        *,
        protected_data_path: Path | None = None,
    ) -> FileResourceProvider:
        resources = load_resource_definitions(registry_path)
        if protected_data_path is not None:
            resources.extend(load_protected_resource_definitions(protected_data_path))
        return cls(resources)

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


def _resource_visible_to_principal(
    visibility: ResourceVisibility,
    principal: PrincipalContext,
) -> bool:
    if visibility == "public":
        return True
    if not principal.authenticated:
        return False
    if visibility == "students":
        return "student" in principal.roles or "instructor" in principal.roles
    return visibility == "instructors" and "instructor" in principal.roles


def load_protected_resource_definitions(data_path: Path) -> list[ResourceDefinition]:
    """Load explicit role-scoped manifests while keeping backing paths private."""

    data_root = data_path.resolve()
    resources: list[ResourceDefinition] = []
    seen_uris: set[str] = set()
    seen_paths: set[Path] = set()
    audience_roots: tuple[tuple[str, Literal["students", "instructors"]], ...] = (
        ("students", "students"),
        ("instructors", "instructors"),
    )
    for directory_name, expected_visibility in audience_roots:
        audience_root = (data_root / directory_name).resolve()
        if not audience_root.is_dir():
            continue
        for manifest_path in sorted(audience_root.rglob("resource.json")):
            try:
                manifest = ProtectedResourceManifest.model_validate_json(
                    manifest_path.read_text(encoding="utf-8")
                )
            except (OSError, ValidationError) as error:
                raise ResourceNotFound(str(manifest_path)) from error
            entry = manifest.resource
            if entry.visibility != expected_visibility:
                raise ValueError(
                    f"protected resource visibility does not match {directory_name} directory: "
                    f"{entry.uri}"
                )
            expected_uri_prefix = f"course://{directory_name}/"
            if not entry.uri.startswith(expected_uri_prefix):
                raise ValueError(
                    f"protected resource URI must start with {expected_uri_prefix}: {entry.uri}"
                )
            if entry.uri in seen_uris:
                raise ValueError(f"duplicate protected resource URI: {entry.uri}")
            path = (manifest_path.parent / entry.file).resolve()
            if not path.is_relative_to(audience_root) or not path.is_file():
                raise ValueError(f"invalid protected resource file for {entry.uri}")
            if path in seen_paths:
                raise ValueError(f"duplicate protected resource file for {entry.uri}")
            assets: dict[str, Path] = {}
            for asset_id, asset_path_string in sorted(entry.assets.items()):
                asset_path = (manifest_path.parent / asset_path_string).resolve()
                if not asset_path.is_relative_to(audience_root) or not asset_path.is_file():
                    raise ValueError(
                        f"invalid protected resource asset for {entry.uri}: {asset_id}"
                    )
                if asset_path == path or asset_path in seen_paths:
                    raise ValueError(
                        f"duplicate protected resource asset for {entry.uri}: {asset_id}"
                    )
                seen_paths.add(asset_path)
                assets[asset_id] = asset_path
            seen_uris.add(entry.uri)
            seen_paths.add(path)
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

    def __init__(self, resources: CourseResourceCatalog) -> None:
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
        if not self._resources.is_public(uri):
            raise PermissionError(f"{uri} is not a public course resource")
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


class CourseReadPrivateResourceTool:
    """Read one pre-authorized role-scoped resource without persisting its contents."""

    id = READ_PRIVATE_RESOURCE_TOOL_ID
    redact_arguments_in_events = True
    description = (
        "Read a private course resource available to the current logged-in account. "
        "Use course.list_private_resources when the canonical URI is unknown."
    )
    input_schema: ClassVar[dict[str, JsonValue]] = {
        "type": "object",
        "properties": {
            "resource_uri": {
                "type": "string",
                "description": "Canonical course:// URI returned by the private resource list.",
            }
        },
        "required": ["resource_uri"],
        "additionalProperties": False,
    }

    def __init__(self, resources: CourseResourceCatalog) -> None:
        self._resources = resources

    async def execute(
        self,
        arguments: Mapping[str, JsonValue],
        context: ToolExecutionContext,
    ) -> ToolExecutionResult:
        _reject_unknown_arguments(arguments, frozenset({"resource_uri"}))
        uri = _required_text_argument(arguments, "resource_uri", max_length=200)
        if (
            uri not in context.permitted_resource_uris
            or uri not in self._resources.authorized_resource_uris(context.principal)
        ):
            raise PermissionError("The private course resource is not authorized for this run.")
        if self._resources.is_public(uri):
            raise ToolValidationError("Use the public course resource reader for this URI.")
        resource = await self._resources.read(uri)
        content: JsonValue = resource.text
        if resource.assets:
            content = {
                "text": resource.text,
                "registered_assets": {
                    asset_id: media_type for asset_id, media_type in resource.assets.items()
                },
            }
        return ToolExecutionResult(
            content=content,
            summary=f"Read authorized private course resource {resource.uri}.",
            storage_policy="server_summary",
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
        "fields, photo requirement, and interaction instructions. When the user asks a factual "
        "application question, read this without opening a form. When the user intends to "
        "apply, call this exactly once, then immediately open draft-document with "
        "resource_uri course://application. Never call this tool repeatedly in one run; its "
        "returned guide remains available to you."
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


class CourseListPrivateResourcesTool:
    """List only role-scoped resources already authorized for this principal."""

    id = LIST_PRIVATE_RESOURCES_TOOL_ID
    description = (
        "List private course resources available to the current logged-in account. "
        "The result contains opaque course:// identifiers, never server paths."
    )
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
            raise ValueError("course.list_private_resources does not accept arguments")
        public_uris = {summary.uri for summary in self._resources.list_public()}
        visible = [
            summary.model_dump(mode="json")
            for summary in self._resources.list_authorized(context.principal)
            if summary.uri in context.permitted_resource_uris and summary.uri not in public_uris
        ]
        return ToolExecutionResult(
            content=visible,
            summary=f"Listed {len(visible)} authorized private course resources.",
            storage_policy="server_summary",
        )


class CourseSearchTool:
    """Search authorized course resources using inspectable lexical matching."""

    id = SEARCH_COURSE_TOOL_ID
    description = (
        "Search the official course resources authorized for the current account, including "
        "role-scoped resources after login."
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
        authorized_uris = frozenset(
            uri
            for uri in self._resources.authorized_resource_uris(context.principal)
            if uri in context.permitted_resource_uris
        )
        results = await self._resources.search(
            query,
            limit=_optional_limit(arguments),
            resource_uris=authorized_uris,
        )
        authorized_resources = [
            resource
            for resource in self._resources.list_authorized(context.principal)
            if resource.uri in authorized_uris
        ]
        searched_uris = [resource.uri for resource in authorized_resources]
        includes_private = any(
            not self._resources.is_public(resource.uri) for resource in authorized_resources
        )
        return ToolExecutionResult(
            content=[result.model_dump(mode="json") for result in results],
            summary=f"Found {len(results)} authorized course resource matches.",
            storage_policy="server_summary" if includes_private else "server_full",
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


class ApplicationSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    application_id: UUID
    submitted_at: datetime
    name: str
    email: str
    registration_status: str | None = None


@dataclass(frozen=True)
class ApplicationPhoto:
    """Private applicant photo bytes loaded only by an authorized server-side tool."""

    application_id: UUID
    filename: str
    media_type: str
    data: bytes

    @property
    def resource_uri(self) -> str:
        return f"applicant://{self.application_id}/photo"


ApplicantImageInspectionRunner = Callable[[list[ApplicationPhoto], str], str]


class ApplicantStore(Protocol):
    async def submit(
        self,
        *,
        application: CourseApplication,
        principal: PrincipalContext,
        photo: StoredTemporaryUpload,
    ) -> ApplicationReceipt: ...

    async def list_applications(self) -> list[ApplicationSummary]: ...

    async def read_application(self, application_id: UUID) -> dict[str, JsonValue]: ...

    async def read_application_photo(self, application_id: UUID) -> ApplicationPhoto: ...


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
            "schema_version": 2,
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

    async def list_applications(self) -> list[ApplicationSummary]:
        return await asyncio.to_thread(self._list_private_applications)

    async def read_application(self, application_id: UUID) -> dict[str, JsonValue]:
        return await asyncio.to_thread(self._read_private_application, application_id)

    async def read_application_photo(self, application_id: UUID) -> ApplicationPhoto:
        return await asyncio.to_thread(self._read_private_application_photo, application_id)

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

    def _list_private_applications(self) -> list[ApplicationSummary]:
        if not self._directory.is_dir():
            return []
        summaries: list[ApplicationSummary] = []
        for directory in sorted(self._directory.iterdir(), reverse=True):
            if not directory.is_dir() or directory.name.startswith("."):
                continue
            try:
                application_id = UUID(directory.name.rsplit("_", 1)[1])
                record = self._read_private_application(application_id)
                application = record.get("application")
                if not isinstance(application, dict):
                    raise ValueError("application payload is unavailable")
                summaries.append(
                    ApplicationSummary(
                        application_id=application_id,
                        submitted_at=str(record.get("submitted_at", "")),
                        name=str(application.get("name", "")),
                        email=str(application.get("email", "")),
                        registration_status=(
                            str(application["registration_status"])
                            if application.get("registration_status") is not None
                            else None
                        ),
                    )
                )
            except (IndexError, OSError, ValueError, ValidationError) as error:
                raise ToolValidationError(
                    "A stored course application is malformed or unavailable."
                ) from error
        return summaries

    def _read_private_application(self, application_id: UUID) -> dict[str, JsonValue]:
        directory = self._application_directory(application_id)
        application_path = (directory / "application.json").resolve()
        if not application_path.is_relative_to(directory) or not application_path.is_file():
            raise ResourceNotFound("course application not found")
        try:
            if application_path.stat().st_size > _MAX_APPLICATION_RECORD_BYTES:
                raise ToolValidationError("The stored course application is too large to read.")
            raw_record = json.loads(application_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ToolValidationError("The stored course application could not be read.") from error
        if not isinstance(raw_record, dict):
            raise ToolValidationError("The stored course application has an invalid format.")
        try:
            stored_id = UUID(str(raw_record.get("application_id", "")))
        except ValueError as error:
            raise ToolValidationError("The stored course application has an invalid ID.") from error
        if stored_id != application_id:
            raise ToolValidationError("The stored course application ID does not match its record.")
        record = cast(dict[str, JsonValue], raw_record)
        photo_filename = record.get("photo_filename")
        if isinstance(photo_filename, str) and Path(photo_filename).name == photo_filename:
            photo_path = (directory / photo_filename).resolve()
            if photo_path.is_relative_to(directory) and photo_path.is_file():
                record = {
                    **record,
                    "photo": {
                        "filename": photo_filename,
                        "media_type": _asset_media_type(photo_path),
                        "size_bytes": photo_path.stat().st_size,
                    },
                }
        return record

    def _application_directory(self, application_id: UUID) -> Path:
        root = self._directory.resolve()
        candidates = sorted(self._directory.glob(f"*_{application_id}"))
        if len(candidates) != 1:
            raise ResourceNotFound("course application not found")
        directory = candidates[0].resolve()
        if not directory.is_relative_to(root) or not directory.is_dir():
            raise ResourceNotFound("course application not found")
        return directory

    def _read_private_application_photo(self, application_id: UUID) -> ApplicationPhoto:
        directory = self._application_directory(application_id)
        record = self._read_private_application(application_id)
        photo_filename = record.get("photo_filename")
        if not isinstance(photo_filename, str) or Path(photo_filename).name != photo_filename:
            raise ToolValidationError("The stored application photo has an invalid filename.")
        photo_path = (directory / photo_filename).resolve()
        if not photo_path.is_relative_to(directory) or not photo_path.is_file():
            raise ResourceNotFound("course application photo not found")
        media_type = _asset_media_type(photo_path)
        if media_type not in APPLICATION_PHOTO_MEDIA_TYPES:
            raise ToolValidationError("The stored application photo has an unsupported type.")
        try:
            size_bytes = photo_path.stat().st_size
            if size_bytes > MAX_UPLOAD_BYTES:
                raise ToolValidationError("The stored application photo is too large to inspect.")
            data = photo_path.read_bytes()
        except OSError as error:
            raise ToolValidationError("The stored application photo could not be read.") from error
        if not _has_valid_image_header(media_type, data[:12]):
            raise ToolValidationError("The stored application photo is not a valid image.")
        return ApplicationPhoto(
            application_id=application_id,
            filename=photo_filename,
            media_type=media_type,
            data=data,
        )


def _application_validation_details(error: ValidationError) -> list[str]:
    """Return safe, field-specific reasons suitable for model correction."""

    option_fields = {
        "school": SCHOOL_OPTIONS,
        "registration_status": REGISTRATION_STATUS_OPTIONS,
        "listener_willing_to_do_weekly_builds": LISTENER_BUILD_OPTIONS,
    }
    details: list[str] = []
    for item in error.errors(include_url=False, include_input=False):
        location = item["loc"]
        field_name = str(location[0]) if location else "application"
        error_type = item["type"]
        context = item.get("ctx") or {}
        if error_type == "missing":
            reason = "is required"
        elif field_name in option_fields and error_type == "literal_error":
            reason = "must be one of: " + ", ".join(option_fields[field_name])
        elif field_name == "email":
            reason = "must be a valid email address"
        elif field_name == "github_id":
            reason = (
                "must be a GitHub username with 1-39 letters, numbers, or single hyphens; "
                "if the applicant has no GitHub account, they must create one first"
            )
        elif field_name == "degree_start_year":
            reason = "must be the four-digit year when the applicant started the degree"
        elif field_name == "photo_upload_id":
            reason = "must be a valid upload UUID"
        elif error_type == "string_too_short":
            reason = f"must contain at least {context.get('min_length')} characters"
        elif error_type == "string_too_long":
            reason = f"must contain at most {context.get('max_length')} characters"
        elif error_type == "extra_forbidden":
            reason = "is not an accepted application field"
        else:
            message = str(item["msg"])
            reason = (
                message.removeprefix("Value error, ").removeprefix("String should ").rstrip(".")
            )
        detail = f"{field_name} {reason}"
        if detail not in details:
            details.append(detail)
    return details


class CourseSubmitApplicationTool:
    """Store an explicitly requested course application outside the public catalog."""

    id = SUBMIT_APPLICATION_TOOL_ID
    redact_arguments_in_events = True
    description = (
        "Submit a course application only after the user explicitly approves the complete "
        "application. Every field must be supplied or individually confirmed by the user. "
        "Gather any missing field and a temporary class-only representative-picture upload "
        "before calling this tool."
    )
    input_schema: ClassVar[dict[str, JsonValue]] = {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "minLength": 2,
                "maxLength": 200,
                "description": "Name field.",
            },
            "email": {
                "type": "string",
                "format": "email",
                "description": "Email field.",
            },
            "github_id": {
                "type": "string",
                "minLength": 1,
                "maxLength": 39,
                "pattern": "^[A-Za-z0-9](?:[A-Za-z0-9]|-(?=[A-Za-z0-9])){0,38}$",
                "description": (
                    "Required GitHub username only, without @ or a profile URL. It may contain "
                    "letters, numbers, and single hyphens, and cannot begin or end with a hyphen. "
                    "If the applicant has no GitHub account, ask them to create one before "
                    "continuing."
                ),
            },
            "school": {
                "type": "string",
                "enum": list(SCHOOL_OPTIONS),
                "description": "School; choose exactly one listed option.",
            },
            "department": {
                "type": "string",
                "minLength": 1,
                "maxLength": 1_000,
                "description": "Department field.",
            },
            "research_group": {
                "type": "string",
                "minLength": 1,
                "maxLength": 1_000,
                "description": (
                    "Research group field; state 'Not applicable' when the applicant does not "
                    "belong to one."
                ),
            },
            "degree": {
                "type": "string",
                "minLength": 1,
                "maxLength": 500,
                "description": "Degree field.",
            },
            "degree_start_year": {
                "type": "string",
                "pattern": "^\\d{4}$",
                "description": "Four-digit year when the applicant started the degree.",
            },
            "personal_webpage": {
                "type": "string",
                "minLength": 1,
                "maxLength": 2_000,
                "description": "Personal Webpage field; state explicitly if there is none.",
            },
            "interests": {
                "type": "string",
                "minLength": 1,
                "maxLength": 4_000,
                "description": "Interests field.",
            },
            "why_take_this_class": {
                "type": "string",
                "minLength": 1,
                "maxLength": 4_000,
                "description": (
                    "Application motivation: why the course interests the applicant, what "
                    "they have built, what they want to build and why, and their roles in "
                    "past projects. Ask a follow-up for any part they have not addressed."
                ),
            },
            "knowledgeable_about": {
                "type": "string",
                "minLength": 1,
                "maxLength": 4_000,
                "description": "Knowledgeable about field.",
            },
            "skill_set": {
                "type": "string",
                "minLength": 1,
                "maxLength": 4_000,
                "description": "Skill-set field.",
            },
            "registration_status": {
                "type": "string",
                "enum": list(REGISTRATION_STATUS_OPTIONS),
                "description": (
                    "Choose exactly 'for credit' or 'listener'; never infer the choice from "
                    "school, department, degree, or affiliation."
                ),
            },
            "listener_willing_to_do_weekly_builds": {
                "type": "string",
                "enum": list(LISTENER_BUILD_OPTIONS),
                "description": (
                    "Use 'yes' or 'no' for listeners. Use 'not applicable' for applicants "
                    "registering for credit."
                ),
            },
            "questions_or_comments_for_instructors": {
                "type": "string",
                "minLength": 1,
                "maxLength": 4_000,
                "description": (
                    "Questions or comments for instructors field; state explicitly if none."
                ),
            },
            "photo_upload_id": {
                "type": "string",
                "format": "uuid",
                "description": (
                    "UUID returned after the applicant uploads a class-only representative "
                    "picture in chat. It may be any JPG/JPEG, PNG, or WebP image they want to "
                    "represent them and does not need to be a formal headshot."
                ),
            },
        },
        "required": [
            "name",
            "email",
            "github_id",
            "school",
            "department",
            "research_group",
            "degree",
            "degree_start_year",
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
            raise ToolValidationError(
                "Application validation failed: "
                + "; ".join(_application_validation_details(error))
                + "."
            ) from error
        try:
            photo = await self._uploads.get_for_principal(
                application.photo_upload_id,
                context.principal,
            )
        except UploadError as error:
            raise ToolValidationError(
                "Application validation failed: photo_upload_id refers to an upload that is "
                "expired or unavailable to this session; upload the JPG/JPEG, PNG, or WebP "
                "picture again."
            ) from error
        if photo.receipt.media_type not in APPLICATION_PHOTO_MEDIA_TYPES:
            raise ToolValidationError(
                "Application validation failed: photo_upload_id must refer to a JPG/JPEG, PNG, "
                "or WebP image."
            )
        if not await asyncio.to_thread(_has_valid_image_signature, photo):
            raise ToolValidationError(
                "Application validation failed: the uploaded picture's content is not a valid "
                "JPG/JPEG, PNG, or WebP image."
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


def _require_instructor(principal: PrincipalContext) -> None:
    if not principal.authenticated or "instructor" not in principal.roles:
        raise PermissionError("Instructor access is required.")


class InstructorListApplicationsTool:
    """List private applicant records for an authenticated instructor."""

    id = INSTRUCTOR_LIST_APPLICATIONS_TOOL_ID
    description = (
        "List submitted course applications available for instructor review. "
        "Returns application IDs and concise applicant metadata, never filesystem paths."
    )
    input_schema: ClassVar[dict[str, JsonValue]] = {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    }

    def __init__(self, applicants: ApplicantStore) -> None:
        self._applicants = applicants

    async def execute(
        self,
        arguments: Mapping[str, JsonValue],
        context: ToolExecutionContext,
    ) -> ToolExecutionResult:
        if arguments:
            raise ValueError("instructor.list_applications does not accept arguments")
        _require_instructor(context.principal)
        applications = await self._applicants.list_applications()
        return ToolExecutionResult(
            content=[application.model_dump(mode="json") for application in applications],
            summary=f"Listed {len(applications)} private course applications.",
            storage_policy="server_summary",
        )


class InstructorReadApplicationTool:
    """Read one private applicant record by its server-issued UUID."""

    id = INSTRUCTOR_READ_APPLICATION_TOOL_ID
    redact_arguments_in_events = True
    description = (
        "Read the complete structured contents of one submitted course application by the "
        "application ID returned from instructor.list_applications. The representative photo "
        "is reported as protected metadata. If the instructor explicitly asks about visible "
        "image content, use instructor.inspect_application_images with the application ID."
    )
    input_schema: ClassVar[dict[str, JsonValue]] = {
        "type": "object",
        "properties": {
            "application_id": {
                "type": "string",
                "format": "uuid",
                "description": "Server-issued application UUID.",
            }
        },
        "required": ["application_id"],
        "additionalProperties": False,
    }

    def __init__(self, applicants: ApplicantStore) -> None:
        self._applicants = applicants

    async def execute(
        self,
        arguments: Mapping[str, JsonValue],
        context: ToolExecutionContext,
    ) -> ToolExecutionResult:
        _require_instructor(context.principal)
        _reject_unknown_arguments(arguments, frozenset({"application_id"}))
        try:
            application_id = UUID(
                _required_text_argument(arguments, "application_id", max_length=36)
            )
        except ValueError as error:
            raise ToolValidationError("application_id must be a UUID.") from error
        try:
            application = await self._applicants.read_application(application_id)
        except ResourceNotFound as error:
            raise ToolValidationError("The course application was not found.") from error
        return ToolExecutionResult(
            content=application,
            summary=f"Read private course application {application_id}.",
            storage_policy="server_summary",
        )


class InstructorInspectApplicationImagesTool:
    """Inspect selected private applicant images for an authenticated instructor."""

    id = INSTRUCTOR_INSPECT_APPLICATION_IMAGES_TOOL_ID
    redact_arguments_in_events = True
    description = (
        "Visually inspect one to four submitted application images only when the authenticated "
        "instructor explicitly asks about their visible content. Use application IDs returned "
        "by instructor.list_applications. This sends the selected private images and inspection "
        "request to the configured multimodal model without provider-side storage. Each result "
        "includes an exact protected applicant:// image_uri that may be used as the url of a "
        "visual-composition image in the same turn; never invent, replace, or web-search for an "
        "application image URL. Never use appearance to identify someone, infer sensitive traits, "
        "or assess admission suitability."
    )
    input_schema: ClassVar[dict[str, JsonValue]] = {
        "type": "object",
        "properties": {
            "application_ids": {
                "type": "array",
                "items": {"type": "string", "format": "uuid"},
                "minItems": 1,
                "maxItems": 4,
                "description": "One to four server-issued application UUIDs.",
            },
            "prompt": {
                "type": "string",
                "minLength": 1,
                "maxLength": 1_000,
                "description": "Neutral visual question requested by the instructor.",
            },
        },
        "required": ["application_ids", "prompt"],
        "additionalProperties": False,
    }

    def __init__(
        self,
        applicants: ApplicantStore,
        inspect: ApplicantImageInspectionRunner,
    ) -> None:
        self._applicants = applicants
        self._inspect = inspect

    async def execute(
        self,
        arguments: Mapping[str, JsonValue],
        context: ToolExecutionContext,
    ) -> ToolExecutionResult:
        _require_instructor(context.principal)
        _reject_unknown_arguments(arguments, frozenset({"application_ids", "prompt"}))
        raw_application_ids = arguments.get("application_ids")
        if (
            not isinstance(raw_application_ids, list)
            or not 1 <= len(raw_application_ids) <= 4
            or any(not isinstance(value, str) for value in raw_application_ids)
        ):
            raise ToolValidationError("application_ids must contain one to four UUIDs.")
        try:
            application_ids = list(
                dict.fromkeys(UUID(value) for value in cast(list[str], raw_application_ids))
            )
        except ValueError as error:
            raise ToolValidationError("application_ids must contain valid UUIDs.") from error
        prompt = _required_text_argument(arguments, "prompt", max_length=1_000)
        photos: list[ApplicationPhoto] = []
        try:
            for application_id in application_ids:
                photos.append(await self._applicants.read_application_photo(application_id))
        except ResourceNotFound as error:
            raise ToolValidationError("An application image was not found.") from error
        try:
            analysis = await asyncio.to_thread(self._inspect, photos, prompt)
        except Exception as error:
            raise ToolValidationError("The application images could not be inspected.") from error
        if not analysis.strip():
            raise ToolValidationError("Image inspection returned no visual analysis.")
        image_uris = [photo.resource_uri for photo in photos]
        context.transient_state["private_application_image_candidates"] = cast(
            JsonValue, image_uris
        )
        return ToolExecutionResult(
            content={
                "images": [
                    {
                        "application_id": str(photo.application_id),
                        "image_uri": photo.resource_uri,
                        "media_type": photo.media_type,
                        "size_bytes": len(photo.data),
                    }
                    for photo in photos
                ],
                "analysis": analysis.strip(),
            },
            summary=f"Inspected {len(photos)} private application images.",
            storage_policy="server_summary",
            resource_uris=image_uris,
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
    resource_index: tuple[str, ...] = ()


class CourseCapabilityPolicy:
    """Authorize public and role-scoped course capabilities from trusted identity."""

    def __init__(
        self,
        resources: CourseResourceCatalog | None = None,
        *,
        browser_enabled: bool = False,
    ) -> None:
        self._resources = resources
        self._browser_enabled = browser_enabled

    def authorize(self, principal: PrincipalContext) -> AuthorizedCapabilities:
        if self._resources is None:
            visible_resources = [
                ResourceSummary(
                    uri=uri,
                    title=title,
                    description="",
                    media_type="text/markdown",
                    status="published",
                )
                for uri, title in (
                    (COURSE_SYLLABUS_URI, "Course Syllabus"),
                    (COURSE_SCHEDULE_URI, "Course Schedule"),
                    (COURSE_REPOSITORIES_URI, "Student Repository Overview"),
                    (COURSE_FAQ_URI, "Course FAQ"),
                    (COURSE_INSTRUCTORS_URI, "Course Staff"),
                    (COURSE_APPLICATION_URI, "Course Application Guide"),
                )
            ]
            public_uris = {resource.uri for resource in visible_resources}
        else:
            visible_resources = self._resources.list_authorized(principal)
            public_uris = {resource.uri for resource in self._resources.list_public()}
        resource_uris = tuple(resource.uri for resource in visible_resources)
        has_private_resources = any(uri not in public_uris for uri in resource_uris)
        instructor_tools = (
            (
                INSTRUCTOR_LIST_APPLICATIONS_TOOL_ID,
                INSTRUCTOR_READ_APPLICATION_TOOL_ID,
                INSTRUCTOR_INSPECT_APPLICATION_IMAGES_TOOL_ID,
            )
            if principal.authenticated and "instructor" in principal.roles
            else ()
        )
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
                WEB_IMAGE_INSPECT_TOOL_ID,
                VISIT_WEBPAGE_TOOL_ID,
                *WORKSPACE_TOOL_IDS,
                *(
                    (LIST_PRIVATE_RESOURCES_TOOL_ID, READ_PRIVATE_RESOURCE_TOOL_ID)
                    if has_private_resources
                    else ()
                ),
                *instructor_tools,
                *(BROWSER_TOOL_IDS if self._browser_enabled else ()),
            ),
            resource_uris=resource_uris,
            resource_index=tuple(
                resource.title + (f" — {resource.description}" if resource.description else "")
                for resource in visible_resources
            ),
        )


def _photo_extension(media_type: str) -> str:
    return {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
    }[media_type]


def _has_valid_image_signature(upload: StoredTemporaryUpload) -> bool:
    header = upload.path.read_bytes()[:12]
    return _has_valid_image_header(upload.receipt.media_type, header)


def _has_valid_image_header(media_type: str, header: bytes) -> bool:
    if media_type == "image/jpeg":
        return header.startswith(b"\xff\xd8\xff")
    if media_type == "image/png":
        return header.startswith(b"\x89PNG\r\n\x1a\n")
    if media_type == "image/webp":
        return len(header) >= 12 and header[:4] == b"RIFF" and header[8:12] == b"WEBP"
    return False
