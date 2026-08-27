"""Application-owned contracts for remote, read-only browser sessions."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from agent_core import PrincipalContext


class BrowserError(RuntimeError):
    """Base class for safe remote-browser failures."""


class BrowserUnavailable(BrowserError):
    """The browser process is not available."""


class BrowserCapacityReached(BrowserError):
    """The configured isolated-session capacity has been reached."""


class BrowserSessionNotFound(BrowserError):
    """The session is absent, expired, or not owned by this principal."""


class BrowserNavigationError(BrowserError):
    """The requested page could not be loaded."""


class BrowserSecurityError(BrowserError):
    """The requested URL is outside the public HTTPS browser policy."""


class BrowserPage(BaseModel):
    """Portable page state exposed to tools and the trusted workspace host."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    session_id: UUID
    url: str = Field(min_length=1, max_length=2_048)
    title: str = Field(min_length=1, max_length=500)
    revision: int = Field(ge=1)
    text_excerpt: str = Field(default="", max_length=12_000)
    expires_at: datetime
    viewport_width: int = Field(ge=320, le=4_096)
    viewport_height: int = Field(ge=240, le=4_096)
    scroll_y: int = Field(default=0, ge=0)
    document_height: int = Field(default=0, ge=0)


class BrowserSnapshot(BaseModel):
    """Current screenshot bytes plus the page revision they represent."""

    model_config = ConfigDict(extra="forbid", frozen=True, arbitrary_types_allowed=True)

    page: BrowserPage
    png: bytes


class BrowserPreview(BaseModel):
    """Short-lived static page capture used by trusted comparison UIs."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    preview_id: UUID
    url: str = Field(min_length=1, max_length=2_048)
    title: str = Field(min_length=1, max_length=500)
    revision: int = Field(default=1, ge=1)
    text_excerpt: str = Field(default="", max_length=12_000)
    expires_at: datetime
    viewport_width: int = Field(ge=320, le=4_096)
    viewport_height: int = Field(ge=240, le=4_096)
    document_height: int = Field(default=0, ge=0)


class BrowserPreviewSnapshot(BaseModel):
    """A principal-scoped preview image without a retained browser context."""

    model_config = ConfigDict(extra="forbid", frozen=True, arbitrary_types_allowed=True)

    preview: BrowserPreview
    png: bytes


class BrowserSessionService(Protocol):
    """Replaceable browser controller; Playwright is only one adapter."""

    async def start(self) -> None: ...

    async def close(self) -> None: ...

    async def open(
        self,
        *,
        principal: PrincipalContext,
        conversation_id: UUID,
        url: str,
    ) -> BrowserPage: ...

    async def create_preview(
        self,
        *,
        principal: PrincipalContext,
        conversation_id: UUID,
        url: str,
    ) -> BrowserPreview: ...

    async def preview_snapshot(
        self,
        *,
        principal: PrincipalContext,
        conversation_id: UUID,
        preview_id: UUID,
    ) -> BrowserPreviewSnapshot: ...

    async def navigate(
        self,
        *,
        principal: PrincipalContext,
        conversation_id: UUID,
        session_id: UUID,
        url: str,
    ) -> BrowserPage: ...

    async def scroll(
        self,
        *,
        principal: PrincipalContext,
        conversation_id: UUID,
        session_id: UUID,
        delta_y: int,
    ) -> BrowserPage: ...

    async def click(
        self,
        *,
        principal: PrincipalContext,
        conversation_id: UUID,
        session_id: UUID,
        x: int,
        y: int,
    ) -> BrowserPage: ...

    async def resize(
        self,
        *,
        principal: PrincipalContext,
        conversation_id: UUID,
        session_id: UUID,
        width: int,
        height: int,
    ) -> BrowserPage: ...

    async def highlight_text(
        self,
        *,
        principal: PrincipalContext,
        conversation_id: UUID,
        session_id: UUID,
        text: str,
    ) -> tuple[BrowserPage, int]: ...

    async def snapshot(
        self,
        *,
        principal: PrincipalContext,
        conversation_id: UUID,
        session_id: UUID,
    ) -> BrowserSnapshot: ...

    async def close_session(
        self,
        *,
        principal: PrincipalContext,
        conversation_id: UUID,
        session_id: UUID,
    ) -> None: ...
