"""First-party visual inspection of a specified authorized course slide page."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import ClassVar

from pydantic import JsonValue

from course_server.slide_pages import CourseSlidePageService

from .capabilities import (
    COURSE_INSPECT_SLIDE_PAGE_TOOL_ID,
    ResourceNotFound,
    ToolExecutionContext,
    ToolExecutionResult,
    ToolValidationError,
)
from .document_inspection import DocumentPageInspectionRunner

_MAX_PROMPT_LENGTH = 2_000


class CourseInspectSlidePageTool:
    """Use the existing multimodal inspection boundary without persisting page images."""

    id = COURSE_INSPECT_SLIDE_PAGE_TOOL_ID
    redact_arguments_in_events = True
    description = (
        "Visually inspect one numbered page of a registered, authorized course slide deck "
        "by its course://slides/ URI. Use when the question concerns a diagram, image, layout, "
        "or other visual detail that PDF text extraction cannot verify, even if the deck is "
        "not open in the workspace. This reads an existing slide, not permission to invent "
        "a diagram or suggest a student's design. Identify the source and page, and label "
        "the returned visual analysis as an interpretation, not the full original."
    )
    input_schema: ClassVar[dict[str, JsonValue]] = {
        "type": "object",
        "properties": {
            "resource_uri": {
                "type": "string",
                "description": "Authorized canonical course://slides/ URI from the course catalog.",
            },
            "page": {
                "type": "integer",
                "minimum": 1,
                "description": "One-based PDF page number to inspect.",
            },
            "prompt": {
                "type": "string",
                "minLength": 1,
                "maxLength": _MAX_PROMPT_LENGTH,
                "description": "A specific visual question about this existing slide page.",
            },
        },
        "required": ["resource_uri", "page", "prompt"],
        "additionalProperties": False,
    }

    def __init__(
        self, pages: CourseSlidePageService, inspect: DocumentPageInspectionRunner
    ) -> None:
        self._pages = pages
        self._inspect = inspect

    async def execute(
        self, arguments: Mapping[str, JsonValue], context: ToolExecutionContext
    ) -> ToolExecutionResult:
        if set(arguments) != {"resource_uri", "page", "prompt"}:
            raise ToolValidationError("resource_uri, page, and prompt are required")
        uri = arguments["resource_uri"]
        page = arguments["page"]
        prompt = arguments["prompt"]
        if not isinstance(uri, str) or len(uri) > 200 or uri not in context.permitted_resource_uris:
            raise PermissionError("This slide deck is not authorized for this run.")
        if not isinstance(page, int) or isinstance(page, bool) or page < 1:
            raise ToolValidationError("page must be a positive integer")
        if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > _MAX_PROMPT_LENGTH:
            raise ToolValidationError("prompt must be non-empty text of at most 2000 characters")
        try:
            slide = await self._pages.read_page(context.principal, uri, page)
        except (ResourceNotFound, ValueError) as error:
            raise ToolValidationError(str(error)) from error
        try:
            analysis = await asyncio.to_thread(
                self._inspect,
                slide.png,
                f"Course slide deck: {slide.title}. Page {slide.page} of "
                f"{slide.page_count}.\n\n{prompt.strip()}",
            )
        except Exception as error:
            raise ToolValidationError("The slide page could not be visually inspected.") from error
        if not analysis.strip():
            raise ToolValidationError("Slide page inspection returned no visual analysis.")
        return ToolExecutionResult(
            content={
                "slide": {
                    "resource_uri": slide.resource_uri,
                    "title": slide.title,
                    "page": slide.page,
                    "page_count": slide.page_count,
                },
                "extracted_text": slide.extracted_text,
                "visual_analysis": analysis.strip(),
                "visual_analysis_is_interpretation": True,
            },
            summary=f"Inspected page {slide.page} of {slide.title}.",
            storage_policy="server_summary",
            resource_uris=[slide.resource_uri],
        )
