"""Authorized, bounded visual pages from registered course slide decks."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass

from agent_core import PrincipalContext
from course_server.agent.capabilities import CourseResourceCatalog
from course_server.agent.document_inspection import RenderedPdfPage, render_pdf_page


@dataclass(frozen=True)
class CourseSlidePage:
    resource_uri: str
    title: str
    page: int
    page_count: int
    extracted_text: str
    png: bytes


class CourseSlidePageService:
    """Resolve only authorized registered slides; never accept a backing file path."""

    def __init__(
        self,
        resources: CourseResourceCatalog,
        *,
        render: Callable[[bytes, int], RenderedPdfPage] = render_pdf_page,
    ) -> None:
        self._resources = resources
        self._render = render

    async def read_page(
        self, principal: PrincipalContext, resource_uri: str, page: int
    ) -> CourseSlidePage:
        if not isinstance(page, int) or isinstance(page, bool) or page < 1:
            raise ValueError("page must be a positive one-based integer")
        if not resource_uri.startswith(
            "course://slides/"
        ) or resource_uri not in self._resources.authorized_resource_uris(principal):
            raise PermissionError("This slide deck is unavailable to this account.")
        resource = await self._resources.read_file(resource_uri)
        if resource.media_type != "application/pdf":
            raise ValueError("This course slide resource is not a PDF.")
        rendered = await asyncio.to_thread(self._render, resource.data, page)
        return CourseSlidePage(
            resource_uri=resource_uri,
            title=resource.title,
            page=rendered.page,
            page_count=rendered.page_count,
            extracted_text=rendered.text,
            png=rendered.png,
        )
