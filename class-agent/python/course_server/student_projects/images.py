"""Discover fetchable public build images without choosing semantic relevance for the agent."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import ClassVar
from urllib.parse import urlsplit

from pydantic import Field, JsonValue, ValidationError

from course_server.agent.capabilities import (
    ImageProbeRunner,
    ToolExecutionContext,
    ToolExecutionResult,
    ToolValidationError,
    WebVisitRunner,
    _https_result_url,
    _verified_image_results,
)
from course_server.student_project_tool_ids import SHOWCASE_IMAGES_TOOL_ID

from .client import StudentProjectCatalog, StudentProjectProviderError
from .showcase import ProjectId, StrictModel
from .tools import _require_course_staff, _translate_provider_error


class ImageRequest(StrictModel):
    project_id: ProjectId
    page_urls: list[str] = Field(default_factory=list, max_length=3)
    image_urls: list[str] = Field(default_factory=list, max_length=8)


class DiscoverShowcaseImagesTool:
    id = SHOWCASE_IMAGES_TOOL_ID
    description = (
        "Find verified, publicly fetchable images for one selected student's build. Reads the "
        "registered homepage plus up to three actual weekly-page URLs on that site, extracts "
        "image metadata and probes candidates. Optionally supply up to eight exact image URLs "
        "found in repository documentation. Use before claiming a build image is unavailable. "
        "Returned candidates are accessible images, not proof of weekly relevance: select from "
        "source context or inspect them with web.inspect_images. Choose the student's own build "
        "interface, output, prototype, or project-specific diagram. Exclude images copied directly "
        "from lecture slides, even when hosted in the student's repository or post. Accessibility "
        "does not establish authorship; check source context and inspect uncertain candidates. "
        "A homepage-only miss is not "
        "proof of absence; follow weekly routes first. Does not reroll or modify selections."
    )
    input_schema: ClassVar[dict[str, JsonValue]] = {
        "type": "object",
        "properties": {
            "project_id": {"type": "string", "pattern": "^agents2026-[A-Za-z0-9_.-]{1,80}$"},
            "page_urls": {
                "type": "array",
                "maxItems": 3,
                "items": {"type": "string", "maxLength": 2048},
            },
            "image_urls": {
                "type": "array",
                "maxItems": 8,
                "items": {"type": "string", "maxLength": 2048},
            },
        },
        "required": ["project_id"],
        "additionalProperties": False,
    }

    def __init__(
        self, projects: StudentProjectCatalog, visit: WebVisitRunner, probe: ImageProbeRunner
    ) -> None:
        self._projects, self._visit, self._probe = projects, visit, probe

    async def execute(
        self, arguments: Mapping[str, JsonValue], context: ToolExecutionContext
    ) -> ToolExecutionResult:
        _require_course_staff(context.principal)
        try:
            request = ImageRequest.model_validate(dict(arguments))
        except ValidationError as error:
            raise ToolValidationError(
                "Supply a project ID and bounded lists of source URLs."
            ) from error
        try:
            projects = await asyncio.to_thread(self._projects.list_projects)
        except StudentProjectProviderError as error:
            raise _translate_provider_error(error) from error
        project = next((p for p in projects if p.id == request.project_id), None)
        if project is None or not project.site_url:
            raise ToolValidationError("A registered project with a deployed website is required.")
        for url in [*request.page_urls, *request.image_urls]:
            if _https_result_url(url) is None:
                raise ToolValidationError("Use public credential-free HTTPS source URLs.")
        if any(
            urlsplit(url).netloc != urlsplit(project.site_url).netloc for url in request.page_urls
        ):
            raise ToolValidationError("Weekly pages must be on the registered student's site.")
        candidates: list[dict[str, JsonValue]] = [
            {"image_url": url, "source": "supplied_repository_reference"}
            for url in request.image_urls
        ]
        pages: list[JsonValue] = []
        for url in dict.fromkeys([*request.page_urls, project.site_url]):
            try:
                page = await asyncio.to_thread(self._visit, url)
            except Exception:
                pages.append({"url": url, "status": "fetch_failed"})
                continue
            raw_images = page.get("images", []) if isinstance(page, Mapping) else []
            pages.append({"url": url, "status": "read"})
            if isinstance(raw_images, list):
                # Keep the probe fanout and response bounded; preserve source/alt for relevance.
                for item in raw_images[:8]:
                    if isinstance(item, Mapping) and _https_result_url(item.get("image_url")):
                        candidates.append(
                            {
                                "image_url": str(item["image_url"]),
                                "source_page": url,
                                "alt": str(item.get("alt", ""))[:500],
                            }
                        )
        unique = {str(item["image_url"]): item for item in candidates}
        verified: list[dict[str, JsonValue]] = []
        items = list(unique.values())
        # At most four concurrent probes, using the same network safety as web image search.
        for start in range(0, len(items), 4):
            verified.extend(
                await _verified_image_results(
                    items[start : start + 4],
                    limit=4,
                    probe=self._probe,
                )
            )
        existing = context.transient_state.get("page_image_candidates", [])
        known = [v for v in existing if isinstance(v, str)] if isinstance(existing, list) else []
        context.transient_state["page_image_candidates"] = list(
            dict.fromkeys([*known, *(str(item["image_url"]) for item in verified)])
        )
        return ToolExecutionResult(
            content={
                "project_id": project.id,
                "pages": pages,
                "images": verified,
                "candidate_count": len(items),
                "note": "Verify requested-week relevance and evidence that the visual depicts the "
                "student's own creation. Exclude direct lecture-slide copies, including copies "
                "embedded in student posts or repositories. A screenshot fallback must show the "
                "student's build or results, not a lecture slide. "
                "Empty results cover only these sources; "
                "inspect weekly routes/documentation before declaring imagery unavailable.",
            },
            summary=f"Checked {len(items)} image candidates for {project.id}; "
            f"{len(verified)} publicly accessible.",
            storage_policy="server_summary",
        )
