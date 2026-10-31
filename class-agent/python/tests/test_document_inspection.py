from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import uuid4

import pytest

from agent_core import PrincipalContext
from course_server.agent import (
    CourseInspectSlidePageTool,
    DocumentInspectPageTool,
    FileResourceProvider,
    ResourceDefinition,
    ToolExecutionContext,
    ToolValidationError,
)
from course_server.agent.document_inspection import RenderedPdfPage, render_pdf_page
from course_server.slide_pages import CourseSlidePageService
from course_server.uploads import FileTemporaryUploadStore
from course_server.workspace import WorkspacePanel, WorkspaceState

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SLIDES_PATH = PROJECT_ROOT / "shared/course/slides/week-01/week-01-slides.pdf"


def public_principal() -> PrincipalContext:
    session_id = uuid4()
    return PrincipalContext(
        authenticated=False,
        anonymous_session_id=session_id,
        roles=["public"],
        session_id=session_id,
    )


def workspace_context(
    resource_uri: str,
    *,
    page: int = 1,
    principal: PrincipalContext | None = None,
    permitted: bool = True,
) -> ToolExecutionContext:
    panel_id = uuid4()
    workspace = WorkspaceState(
        panels=[
            WorkspacePanel(
                id=panel_id,
                component_id="document-viewer",
                title="Slides",
                resource_uri=resource_uri,
                props={"page": page},
            )
        ],
        focused_panel_id=panel_id,
    )
    return ToolExecutionContext(
        principal=principal or public_principal(),
        conversation_id=uuid4(),
        permitted_resource_uris=frozenset({resource_uri} if permitted else set()),
        workspace_state=workspace.model_dump(mode="json"),
    )


def test_render_pdf_page_returns_bounded_png_and_text() -> None:
    rendered = render_pdf_page(SLIDES_PATH.read_bytes(), 1)

    assert rendered.page == 1
    assert rendered.page_count == 116
    assert rendered.png.startswith(b"\x89PNG\r\n\x1a\n")
    assert len(rendered.png) < 10 * 1024 * 1024
    assert "AI Agents" in rendered.text

    with pytest.raises(ValueError, match="outside this 116-page document"):
        render_pdf_page(SLIDES_PATH.read_bytes(), 117)


def test_slide_page_service_reads_only_authorized_registered_slides(tmp_path: Path) -> None:
    slide_uri = "course://slides/week-01"
    private_uri = "course://slides/private"
    resources = FileResourceProvider(
        [
            ResourceDefinition(
                uri=slide_uri,
                title="Week 1 Slides",
                media_type="application/pdf",
                path=SLIDES_PATH,
            ),
            ResourceDefinition(
                uri=private_uri,
                title="Private Slides",
                media_type="application/pdf",
                path=SLIDES_PATH,
                visibility="students",
            ),
            ResourceDefinition(
                uri="course://readings/sample",
                title="Reading",
                media_type="text/markdown",
                path=tmp_path / "reading.md",
            ),
            ResourceDefinition(
                uri="course://slides/not-pdf",
                title="Not a PDF",
                media_type="text/markdown",
                path=PROJECT_ROOT / "shared/course/schedule/schedule.md",
            ),
        ]
    )
    service = CourseSlidePageService(resources)
    slide = asyncio.run(service.read_page(public_principal(), slide_uri, 1))
    assert slide.resource_uri == slide_uri
    assert slide.page == 1
    assert slide.page_count == 116
    assert slide.png.startswith(b"\x89PNG\r\n\x1a\n")
    with pytest.raises(PermissionError):
        asyncio.run(service.read_page(public_principal(), private_uri, 1))
    with pytest.raises(PermissionError):
        asyncio.run(service.read_page(public_principal(), "course://readings/sample", 1))
    with pytest.raises(ValueError, match="not a PDF"):
        asyncio.run(service.read_page(public_principal(), "course://slides/not-pdf", 1))
    with pytest.raises(ValueError, match="positive"):
        asyncio.run(service.read_page(public_principal(), slide_uri, 0))
    with pytest.raises(ValueError, match="outside"):
        asyncio.run(service.read_page(public_principal(), slide_uri, 117))
    with pytest.raises(ValueError, match="positive"):
        asyncio.run(service.read_page(public_principal(), slide_uri, True))


def test_course_agent_can_inspect_specific_slide_without_open_workspace(tmp_path: Path) -> None:
    uri = "course://slides/week-01"
    resources = FileResourceProvider(
        [
            ResourceDefinition(
                uri=uri,
                title="Week 1 Slides",
                media_type="application/pdf",
                path=SLIDES_PATH,
            )
        ]
    )
    calls: list[tuple[bytes, str]] = []

    def inspect(image: bytes, prompt: str) -> str:
        calls.append((image, prompt))
        return "A visible course diagram."

    tool = CourseInspectSlidePageTool(
        CourseSlidePageService(
            resources,
            render=lambda _data, page: RenderedPdfPage(
                png=b"\x89PNG\r\n\x1a\nrendered-slide",
                page=page,
                page_count=116,
                text="Extracted words",
            ),
        ),
        inspect,
    )
    context = ToolExecutionContext(
        principal=public_principal(),
        conversation_id=uuid4(),
        permitted_resource_uris=frozenset({uri}),
    )
    result = asyncio.run(
        tool.execute({"resource_uri": uri, "page": 6, "prompt": "What diagram is shown?"}, context)
    )
    assert calls == [
        (
            b"\x89PNG\r\n\x1a\nrendered-slide",
            "Course slide deck: Week 1 Slides. Page 6 of 116.\n\nWhat diagram is shown?",
        )
    ]
    assert result.storage_policy == "server_summary"
    assert result.resource_uris == [uri]
    assert isinstance(result.content, dict)
    assert result.content["visual_analysis"] == "A visible course diagram."
    assert result.content["visual_analysis_is_interpretation"] is True
    assert "rendered-slide" not in str(result.content)
    with pytest.raises(PermissionError):
        asyncio.run(
            tool.execute(
                {"resource_uri": uri, "page": 6, "prompt": "What diagram?"},
                ToolExecutionContext(
                    principal=context.principal,
                    conversation_id=uuid4(),
                    permitted_resource_uris=frozenset(),
                ),
            )
        )


def test_document_inspection_uses_current_page_without_persisting_image_bytes(
    tmp_path: Path,
) -> None:
    resource_uri = "course://slides/week-01"
    resources = FileResourceProvider(
        [
            ResourceDefinition(
                uri=resource_uri,
                title="Week 1 Slides",
                media_type="application/pdf",
                path=SLIDES_PATH,
            )
        ]
    )
    inspected: list[tuple[bytes, str]] = []
    rendered_pages: list[int] = []

    def render(_data: bytes, page: int) -> RenderedPdfPage:
        rendered_pages.append(page)
        return RenderedPdfPage(
            png=b"\x89PNG\r\n\x1a\nprivate-rendered-page",
            page=page,
            page_count=116,
            text="Extracted page text",
        )

    def inspect(image: bytes, prompt: str) -> str:
        inspected.append((image, prompt))
        return "A large title and a radial line illustration are visible."

    tool = DocumentInspectPageTool(
        resources,
        FileTemporaryUploadStore(tmp_path / "uploads"),
        inspect,
        render=render,
    )
    assert tool.redact_arguments_in_events is True
    result = asyncio.run(
        tool.execute(
            {"prompt": "What is on this slide?"},
            workspace_context(resource_uri, page=9),
        )
    )

    assert rendered_pages == [9]
    assert inspected == [
        (
            b"\x89PNG\r\n\x1a\nprivate-rendered-page",
            "Document: Week 1 Slides. Page 9 of 116.\n\nWhat is on this slide?",
        )
    ]
    assert result.storage_policy == "server_summary"
    assert result.resource_uris == [resource_uri]
    assert isinstance(result.content, dict)
    assert result.content["document"] == {
        "title": "Week 1 Slides",
        "resource_uri": resource_uri,
        "media_type": "application/pdf",
        "page": 9,
        "page_count": 116,
    }
    assert result.content["extracted_text"] == "Extracted page text"
    assert result.content["visual_analysis"] == (
        "A large title and a radial line illustration are visible."
    )
    assert "private-rendered-page" not in str(result.content)


def test_document_inspection_supports_principal_owned_uploaded_pdf(tmp_path: Path) -> None:
    principal = public_principal()
    uploads = FileTemporaryUploadStore(tmp_path / "uploads")
    receipt = asyncio.run(
        uploads.store(
            filename="notes.pdf",
            media_type="application/pdf",
            content=b"%PDF-test-bytes",
            principal=principal,
        )
    )
    resource_uri = f"upload://{receipt.id}"
    tool = DocumentInspectPageTool(
        FileResourceProvider([]),
        uploads,
        lambda _image, _prompt: "Visible notes.",
        render=lambda data, page: RenderedPdfPage(
            png=b"\x89PNG\r\n\x1a\nrendered",
            page=page,
            page_count=2,
            text=data.decode(),
        ),
    )

    result = asyncio.run(
        tool.execute(
            {"prompt": "Describe it", "page": 2},
            workspace_context(resource_uri, principal=principal),
        )
    )

    assert isinstance(result.content, dict)
    assert result.content["document"] == {
        "title": "notes.pdf",
        "resource_uri": resource_uri,
        "media_type": "application/pdf",
        "page": 2,
        "page_count": 2,
    }


def test_document_inspection_rejects_a_foreign_uploaded_pdf(tmp_path: Path) -> None:
    owner = public_principal()
    uploads = FileTemporaryUploadStore(tmp_path / "uploads")
    receipt = asyncio.run(
        uploads.store(
            filename="private.pdf",
            media_type="application/pdf",
            content=b"%PDF-private",
            principal=owner,
        )
    )
    resource_uri = f"upload://{receipt.id}"
    tool = DocumentInspectPageTool(
        FileResourceProvider([]),
        uploads,
        lambda _image, _prompt: "This must not run.",
    )

    with pytest.raises(ToolValidationError, match="unavailable or expired"):
        asyncio.run(
            tool.execute(
                {"prompt": "Describe it"},
                workspace_context(resource_uri, principal=public_principal()),
            )
        )


def test_document_inspection_requires_focused_authorized_pdf(tmp_path: Path) -> None:
    resource_uri = "course://slides/week-01"
    tool = DocumentInspectPageTool(
        FileResourceProvider(
            [
                ResourceDefinition(
                    uri=resource_uri,
                    title="Week 1 Slides",
                    media_type="application/pdf",
                    path=SLIDES_PATH,
                )
            ]
        ),
        FileTemporaryUploadStore(tmp_path / "uploads"),
        lambda _image, _prompt: "Visible content.",
    )

    with pytest.raises(PermissionError, match="not authorized"):
        asyncio.run(
            tool.execute(
                {"prompt": "Describe it"},
                workspace_context(resource_uri, permitted=False),
            )
        )

    context = ToolExecutionContext(
        principal=public_principal(),
        conversation_id=uuid4(),
        permitted_resource_uris=frozenset({resource_uri}),
        workspace_state={"panels": [], "focused_panel_id": None},
    )
    with pytest.raises(ToolValidationError, match="Open and focus a PDF"):
        asyncio.run(tool.execute({"prompt": "Describe it"}, context))
