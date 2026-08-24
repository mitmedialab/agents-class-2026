from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from agent_core import PrincipalContext
from course_server.agent import ToolExecutionContext, ToolValidationError
from course_server.browser import (
    BrowserPage,
    BrowserPreview,
    BrowserPreviewSnapshot,
    BrowserSecurityError,
    BrowserSessionNotFound,
    BrowserSnapshot,
    validate_public_https_url,
)
from course_server.browser.tools import (
    BrowserCompareTool,
    BrowserHighlightTextTool,
    BrowserNavigateTool,
    BrowserOpenTool,
    BrowserScrollTool,
)
from course_server.workspace import WorkspaceState, load_component_registry


def public_principal() -> PrincipalContext:
    session_id = uuid4()
    return PrincipalContext(
        authenticated=False,
        anonymous_session_id=session_id,
        roles=["public"],
        session_id=session_id,
    )


class FakeBrowserSessionService:
    def __init__(self) -> None:
        self.sessions: dict[UUID, tuple[UUID, UUID, BrowserPage]] = {}
        self.previews: dict[UUID, tuple[UUID, UUID, BrowserPreview]] = {}

    async def start(self) -> None:
        return None

    async def close(self) -> None:
        self.sessions.clear()
        self.previews.clear()

    async def open(
        self,
        *,
        principal: PrincipalContext,
        conversation_id: UUID,
        url: str,
    ) -> BrowserPage:
        page = self._page(uuid4(), url, 1)
        self.sessions[page.session_id] = (principal.session_id, conversation_id, page)
        return page

    async def create_preview(
        self,
        *,
        principal: PrincipalContext,
        conversation_id: UUID,
        url: str,
    ) -> BrowserPreview:
        preview = BrowserPreview(
            preview_id=uuid4(),
            url=url,
            title="Example Domain",
            text_excerpt="Example Domain browser text",
            expires_at=datetime.now(UTC) + timedelta(minutes=15),
            viewport_width=1280,
            viewport_height=800,
            document_height=1600,
        )
        self.previews[preview.preview_id] = (
            principal.session_id,
            conversation_id,
            preview,
        )
        return preview

    async def preview_snapshot(
        self,
        *,
        principal: PrincipalContext,
        conversation_id: UUID,
        preview_id: UUID,
    ) -> BrowserPreviewSnapshot:
        stored = self.previews.get(preview_id)
        if stored is None or stored[:2] != (principal.session_id, conversation_id):
            raise BrowserSessionNotFound("Browser preview not found.")
        return BrowserPreviewSnapshot(preview=stored[2], png=b"\x89PNG\r\n\x1a\n")

    async def navigate(
        self,
        *,
        principal: PrincipalContext,
        conversation_id: UUID,
        session_id: UUID,
        url: str,
    ) -> BrowserPage:
        current = self._require(principal, conversation_id, session_id)
        return self._replace(
            principal, conversation_id, self._page(session_id, url, current.revision + 1)
        )

    async def scroll(
        self,
        *,
        principal: PrincipalContext,
        conversation_id: UUID,
        session_id: UUID,
        delta_y: int,
    ) -> BrowserPage:
        del delta_y
        current = self._require(principal, conversation_id, session_id)
        return self._replace(
            principal,
            conversation_id,
            self._page(session_id, current.url, current.revision + 1),
        )

    async def resize(
        self,
        *,
        principal: PrincipalContext,
        conversation_id: UUID,
        session_id: UUID,
        width: int,
        height: int,
    ) -> BrowserPage:
        current = self._require(principal, conversation_id, session_id)
        return self._replace(
            principal,
            conversation_id,
            current.model_copy(
                update={
                    "revision": current.revision + 1,
                    "viewport_width": width,
                    "viewport_height": height,
                }
            ),
        )

    async def highlight_text(
        self,
        *,
        principal: PrincipalContext,
        conversation_id: UUID,
        session_id: UUID,
        text: str,
    ) -> tuple[BrowserPage, int]:
        current = self._require(principal, conversation_id, session_id)
        page = self._replace(
            principal,
            conversation_id,
            self._page(session_id, current.url, current.revision + 1),
        )
        return page, int(text.casefold() in page.text_excerpt.casefold())

    async def snapshot(
        self,
        *,
        principal: PrincipalContext,
        conversation_id: UUID,
        session_id: UUID,
    ) -> BrowserSnapshot:
        return BrowserSnapshot(
            page=self._require(principal, conversation_id, session_id),
            png=b"\x89PNG\r\n\x1a\n",
        )

    async def close_session(
        self,
        *,
        principal: PrincipalContext,
        conversation_id: UUID,
        session_id: UUID,
    ) -> None:
        self._require(principal, conversation_id, session_id)
        self.sessions.pop(session_id)

    def _require(
        self,
        principal: PrincipalContext,
        conversation_id: UUID,
        session_id: UUID,
    ) -> BrowserPage:
        stored = self.sessions.get(session_id)
        if stored is None or stored[:2] != (principal.session_id, conversation_id):
            raise BrowserSessionNotFound("Browser session not found.")
        return stored[2]

    def _replace(
        self,
        principal: PrincipalContext,
        conversation_id: UUID,
        page: BrowserPage,
    ) -> BrowserPage:
        self.sessions[page.session_id] = (principal.session_id, conversation_id, page)
        return page

    @staticmethod
    def _page(session_id: UUID, url: str, revision: int) -> BrowserPage:
        return BrowserPage(
            session_id=session_id,
            url=url,
            title="Example Domain",
            revision=revision,
            text_excerpt="Example Domain browser text",
            expires_at=datetime.now(UTC) + timedelta(minutes=15),
            viewport_width=1280,
            viewport_height=800,
        )


def test_browser_tools_open_control_and_update_one_registered_panel() -> None:
    async def scenario() -> None:
        principal = public_principal()
        context = ToolExecutionContext(
            principal=principal,
            conversation_id=uuid4(),
            permitted_resource_uris=frozenset(),
        )
        service = FakeBrowserSessionService()
        registry = load_component_registry()

        opened = await BrowserOpenTool(service, registry).execute(
            {"url": "https://example.com/"}, context
        )
        assert opened.emitted_events[0].type == "workspace.panel.opened"
        assert isinstance(opened.content, dict)
        session_id = str(opened.content["session_id"])
        state = WorkspaceState.model_validate(context.workspace_state)
        assert state.panels[0].component_id == "browser-viewer"

        navigated = await BrowserNavigateTool(service, registry).execute(
            {"url": "https://example.com/about"},
            context,
        )
        scrolled = await BrowserScrollTool(service, registry).execute({"delta_y": 640}, context)
        highlighted = await BrowserHighlightTextTool(service, registry).execute(
            {"text": "browser text"}, context
        )
        reopened = await BrowserOpenTool(service, registry).execute(
            {"url": "https://example.com/about"}, context
        )

        assert navigated.emitted_events[0].type == "workspace.panel.updated"
        assert scrolled.emitted_events[0].type == "workspace.panel.updated"
        assert isinstance(highlighted.content, dict)
        assert highlighted.content["matches"] == 1
        assert reopened.emitted_events[0].type == "workspace.panel.updated"
        assert isinstance(reopened.content, dict)
        assert reopened.content["session_id"] == session_id
        state = WorkspaceState.model_validate(context.workspace_state)
        assert len(state.panels) == 1
        assert state.panels[0].props["revision"] == 4

        service.sessions.clear()  # Simulate an API restart without durable browser state.
        recovered = await BrowserScrollTool(service, registry).execute({"delta_y": 640}, context)
        assert recovered.emitted_events[0].type == "workspace.panel.updated"
        assert isinstance(recovered.content, dict)
        assert recovered.content["session_id"] != session_id
        assert recovered.content["revision"] == 2
        assert len(WorkspaceState.model_validate(context.workspace_state).panels) == 1

    asyncio.run(scenario())


def test_browser_compare_opens_registered_page_cards_with_scoped_previews() -> None:
    async def scenario() -> None:
        principal = public_principal()
        context = ToolExecutionContext(
            principal=principal,
            conversation_id=uuid4(),
            permitted_resource_uris=frozenset(),
        )
        service = FakeBrowserSessionService()
        result = await BrowserCompareTool(service, load_component_registry()).execute(
            {
                "heading": "Research candidates",
                "candidates": [
                    {
                        "url": "https://example.com/one",
                        "title": "First project",
                        "description": "A first candidate.",
                    },
                    {
                        "url": "https://example.com/two",
                        "title": "Second project",
                    },
                    {"url": "https://example.com/three"},
                ],
            },
            context,
        )

        state = WorkspaceState.model_validate(context.workspace_state)
        assert state.panels[0].component_id == "page-cards"
        assert state.panels[0].props["heading"] == "Research candidates"
        assert isinstance(state.panels[0].props["items"], list)
        assert len(state.panels[0].props["items"]) == 3
        assert len(service.sessions) == 0
        assert len(service.previews) == 3
        assert result.emitted_events[0].type == "workspace.panel.opened"
        assert result.storage_policy == "server_summary"

    asyncio.run(scenario())


def test_browser_service_identity_is_never_a_model_argument() -> None:
    async def scenario() -> None:
        principal = public_principal()
        other = public_principal()
        conversation_id = uuid4()
        context = ToolExecutionContext(
            principal=principal,
            conversation_id=conversation_id,
            permitted_resource_uris=frozenset(),
        )
        service = FakeBrowserSessionService()
        opened = await BrowserOpenTool(service, load_component_registry()).execute(
            {"url": "https://example.com/"}, context
        )
        assert isinstance(opened.content, dict)
        session_id = UUID(str(opened.content["session_id"]))

        with pytest.raises(BrowserSessionNotFound):
            await service.snapshot(
                principal=other,
                conversation_id=conversation_id,
                session_id=session_id,
            )
        with pytest.raises(ToolValidationError, match="unexpected arguments"):
            await BrowserScrollTool(service, load_component_registry()).execute(
                {
                    "delta_y": 200,
                    "user_id": str(uuid4()),
                },
                context,
            )

    asyncio.run(scenario())


def test_public_url_policy_rejects_local_and_credential_destinations() -> None:
    async def scenario() -> None:
        with pytest.raises(BrowserSecurityError, match="Private and local"):
            await validate_public_https_url("https://127.0.0.1/")
        with pytest.raises(BrowserSecurityError, match="Credential-bearing"):
            await validate_public_https_url("https://user:secret@example.com/")
        with pytest.raises(BrowserSecurityError, match="public HTTPS"):
            await validate_public_https_url("http://example.com/")

    asyncio.run(scenario())
