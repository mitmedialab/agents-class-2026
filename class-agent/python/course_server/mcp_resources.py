"""Student-scoped reads of the existing registered course resource catalog."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

from agent_core import PrincipalContext
from course_server.agent.capabilities import CourseResourceCatalog
from course_server.slide_pages import CourseSlidePage, CourseSlidePageService

_DEFAULT_READ_CHARS = 12_000
_MAX_READ_CHARS = 20_000


class CourseMcpResourceService:
    def __init__(self, resources: CourseResourceCatalog, *, public_base_url: str) -> None:
        self._resources = resources
        self._public_base_url = public_base_url.rstrip("/")
        self._slide_pages = CourseSlidePageService(resources)

    def _open_in_course_agent_url(self, resource_uri: str) -> str:
        query = f"Open the original course resource {resource_uri} in the website workspace"
        return f"{self._public_base_url}/?{urlencode({'q': query})}"

    def _authorized_uris(self, principal: PrincipalContext) -> frozenset[str]:
        if not principal.authenticated or "student" not in principal.roles:
            raise PermissionError("Active student access is required.")
        return frozenset(self._resources.authorized_resource_uris(principal))

    def list_resources(self, principal: PrincipalContext) -> list[dict[str, Any]]:
        allowed = self._authorized_uris(principal)
        return [
            {
                **item.model_dump(mode="json"),
                "open_in_course_agent_url": self._open_in_course_agent_url(item.uri),
            }
            for item in self._resources.list_authorized(principal)
            if item.uri in allowed
        ]

    async def read_resource(
        self,
        principal: PrincipalContext,
        resource_uri: str,
        *,
        offset: int = 0,
        max_chars: int = _DEFAULT_READ_CHARS,
    ) -> dict[str, Any]:
        if resource_uri not in self._authorized_uris(principal):
            raise ValueError("This course resource is unavailable to this student.")
        if offset < 0 or not 1 <= max_chars <= _MAX_READ_CHARS:
            raise ValueError("Invalid resource read range.")
        contents = await self._resources.read(resource_uri)
        text = contents.text
        end = min(offset + max_chars, len(text))
        return {
            "uri": contents.uri,
            "title": contents.title,
            "media_type": contents.media_type,
            "open_in_course_agent_url": self._open_in_course_agent_url(contents.uri),
            "text_representation": (
                "pdf_text_extraction" if contents.media_type == "application/pdf" else "course_text"
            ),
            "returned_text_is_complete": offset == 0 and end == len(text),
            "text": text[offset:end],
            "offset": offset,
            "total_chars": len(text),
            "next_offset": end if end < len(text) else None,
            "assets": contents.assets,
        }

    async def search_resources(
        self, principal: PrincipalContext, query: str, *, limit: int = 5
    ) -> list[dict[str, Any]]:
        allowed = self._authorized_uris(principal)
        results = await self._resources.search(query, limit=limit, resource_uris=allowed)
        return [
            {
                **result.model_dump(mode="json"),
                "open_in_course_agent_url": self._open_in_course_agent_url(result.uri),
            }
            for result in results
        ]

    async def read_slide_page(
        self, principal: PrincipalContext, resource_uri: str, page: int
    ) -> tuple[CourseSlidePage, str]:
        if resource_uri not in self._authorized_uris(principal):
            raise PermissionError("This slide deck is unavailable to this student.")
        slide = await self._slide_pages.read_page(principal, resource_uri, page)
        return slide, self._open_in_course_agent_url(resource_uri)
