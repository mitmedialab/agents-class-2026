"""Authorized visual inspection of the focused PDF page in the workspace."""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from io import BytesIO
from typing import ClassVar
from uuid import UUID

import pypdfium2 as pdfium  # type: ignore[import-untyped]
from pydantic import JsonValue, ValidationError

from course_server.uploads import TemporaryUploadStore, UploadError
from course_server.workspace import WorkspacePanel, WorkspaceState

from .capabilities import (
    DOCUMENT_INSPECT_PAGE_TOOL_ID,
    CourseResourceCatalog,
    ResourceNotFound,
    ToolExecutionContext,
    ToolExecutionResult,
    ToolValidationError,
)

_MAX_PROMPT_LENGTH = 2_000
_MAX_PAGE_TEXT_LENGTH = 20_000
_MAX_RENDER_EDGE = 1_600
_MAX_RENDER_SCALE = 2.0
_MAX_RENDERED_BYTES = 10 * 1024 * 1024
_PDFIUM_LOCK = threading.Lock()

DocumentPageInspectionRunner = Callable[[bytes, str], str]


@dataclass(frozen=True)
class RenderedPdfPage:
    png: bytes
    page: int
    page_count: int
    text: str


def render_pdf_page(data: bytes, page: int) -> RenderedPdfPage:
    """Render one bounded PDF page and extract its text."""

    if not data or page < 1:
        raise ValueError("invalid PDF page request")
    try:
        with _PDFIUM_LOCK, pdfium.PdfDocument(data) as document:
            page_count = len(document)
            if page > page_count:
                raise ValueError(f"page {page} is outside this {page_count}-page document")
            pdf_page = document[page - 1]
            try:
                width, height = pdf_page.get_size()
                scale = min(_MAX_RENDER_SCALE, _MAX_RENDER_EDGE / max(width, height))
                bitmap = pdf_page.render(
                    scale=scale,
                    fill_color=(255, 255, 255, 255),
                    draw_annots=True,
                )
                try:
                    image = bitmap.to_pil()
                    output = BytesIO()
                    image.save(output, format="PNG")
                    png = output.getvalue()
                finally:
                    bitmap.close()
                text_page = pdf_page.get_textpage()
                try:
                    text = text_page.get_text_range().strip()[:_MAX_PAGE_TEXT_LENGTH]
                finally:
                    text_page.close()
            finally:
                pdf_page.close()
    except ValueError:
        raise
    except Exception as error:
        raise ValueError("the PDF page could not be rendered") from error
    if not png.startswith(b"\x89PNG\r\n\x1a\n") or len(png) > _MAX_RENDERED_BYTES:
        raise ValueError("the rendered PDF page is invalid or too large")
    return RenderedPdfPage(png=png, page=page, page_count=page_count, text=text)


class DocumentInspectPageTool:
    """Inspect a page chosen from trusted workspace state, never a model-supplied URI."""

    id = DOCUMENT_INSPECT_PAGE_TOOL_ID
    redact_arguments_in_events = True
    description = (
        "Visually inspect the current page of the focused PDF in the trusted workspace. Use "
        "this whenever the user asks what they are looking at, refers to 'this slide' or a "
        "visible diagram/image, or asks a question that extracted PDF text alone cannot answer. "
        "The resource URI is derived from focused workspace state and authorization is checked "
        "by the platform. Omit page to inspect the page currently open for the user; provide page "
        "only when the user explicitly asks about another page in that same PDF."
    )
    input_schema: ClassVar[dict[str, JsonValue]] = {
        "type": "object",
        "properties": {
            "prompt": {
                "type": "string",
                "minLength": 1,
                "maxLength": _MAX_PROMPT_LENGTH,
                "description": "The visual question to answer from the rendered page.",
            },
            "page": {
                "type": "integer",
                "minimum": 1,
                "description": "Optional one-based page number; defaults to the current page.",
            },
        },
        "required": ["prompt"],
        "additionalProperties": False,
    }

    def __init__(
        self,
        resources: CourseResourceCatalog,
        uploads: TemporaryUploadStore,
        inspect: DocumentPageInspectionRunner,
        *,
        render: Callable[[bytes, int], RenderedPdfPage] = render_pdf_page,
    ) -> None:
        self._resources = resources
        self._uploads = uploads
        self._inspect = inspect
        self._render = render

    async def execute(
        self,
        arguments: Mapping[str, JsonValue],
        context: ToolExecutionContext,
    ) -> ToolExecutionResult:
        unknown = set(arguments) - {"prompt", "page"}
        if unknown:
            raise ToolValidationError("prompt and optional page are the only accepted fields")
        prompt_value = arguments.get("prompt")
        if not isinstance(prompt_value, str) or not prompt_value.strip():
            raise ToolValidationError("prompt must be non-empty text")
        prompt = prompt_value.strip()
        if len(prompt) > _MAX_PROMPT_LENGTH:
            raise ToolValidationError(f"prompt must be at most {_MAX_PROMPT_LENGTH} characters")

        panel = self._focused_document_panel(context)
        resource_uri = panel.resource_uri
        assert resource_uri is not None
        if resource_uri not in context.permitted_resource_uris:
            raise PermissionError("The focused document is not authorized for this run.")

        requested_page = arguments.get("page", panel.props.get("page", 1))
        if (
            not isinstance(requested_page, int)
            or isinstance(requested_page, bool)
            or requested_page < 1
        ):
            raise ToolValidationError("page must be a positive integer")

        title, media_type, data = await self._read_pdf(resource_uri, context)
        try:
            rendered = await asyncio.to_thread(self._render, data, requested_page)
        except ValueError as error:
            raise ToolValidationError(str(error)) from error
        inspection_prompt = (
            f"Document: {title}. Page {rendered.page} of {rendered.page_count}.\n\n{prompt}"
        )
        try:
            analysis = await asyncio.to_thread(self._inspect, rendered.png, inspection_prompt)
        except Exception as error:
            raise ToolValidationError(
                "The document page could not be visually inspected."
            ) from error
        if not analysis.strip():
            raise ToolValidationError("Document page inspection returned no visual analysis.")
        return ToolExecutionResult(
            content={
                "document": {
                    "title": title,
                    "resource_uri": resource_uri,
                    "media_type": media_type,
                    "page": rendered.page,
                    "page_count": rendered.page_count,
                },
                "extracted_text": rendered.text,
                "visual_analysis": analysis.strip(),
            },
            summary=f"Inspected page {rendered.page} of {title}.",
            storage_policy="server_summary",
            resource_uris=[resource_uri],
        )

    @staticmethod
    def _focused_document_panel(context: ToolExecutionContext) -> WorkspacePanel:
        try:
            workspace = WorkspaceState.model_validate(context.workspace_state)
        except ValidationError as error:
            raise ToolValidationError("The current workspace state is invalid.") from error
        panel = next(
            (
                candidate
                for candidate in workspace.panels
                if candidate.id == workspace.focused_panel_id
            ),
            None,
        )
        if panel is None or panel.component_id != "document-viewer" or not panel.resource_uri:
            raise ToolValidationError("Open and focus a PDF in the workspace before inspecting it.")
        return panel

    async def _read_pdf(
        self,
        resource_uri: str,
        context: ToolExecutionContext,
    ) -> tuple[str, str, bytes]:
        if resource_uri.startswith("upload://"):
            try:
                upload_id = UUID(resource_uri.removeprefix("upload://"))
                upload = await self._uploads.get_for_principal(upload_id, context.principal)
            except (ValueError, UploadError) as error:
                raise ToolValidationError(
                    "The focused upload is unavailable or expired."
                ) from error
            title = upload.receipt.filename
            media_type = upload.receipt.media_type
            try:
                data = await asyncio.to_thread(upload.path.read_bytes)
            except OSError as error:
                raise ToolValidationError("The focused upload could not be read.") from error
        elif resource_uri.startswith("course://"):
            try:
                resource = await self._resources.read_file(resource_uri)
            except ResourceNotFound as error:
                raise ToolValidationError("The focused course document is unavailable.") from error
            title = resource.title
            media_type = resource.media_type
            data = resource.data
        else:
            raise ToolValidationError("Only authorized course and uploaded PDFs can be inspected.")
        if media_type != "application/pdf":
            raise ToolValidationError("The focused document is not a PDF.")
        return title, media_type, data
