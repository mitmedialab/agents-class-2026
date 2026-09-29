from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from pydantic import JsonValue

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
        self.clicks: list[tuple[int, int]] = []

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

    async def click(
        self,
        *,
        principal: PrincipalContext,
        conversation_id: UUID,
        session_id: UUID,
        x: int,
        y: int,
    ) -> BrowserPage:
        current = self._require(principal, conversation_id, session_id)
        self.clicks.append((x, y))
        return self._replace(
            principal,
            conversation_id,
            self._page(
                session_id,
                "https://example.com/clicked",
                current.revision + 1,
            ),
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
        clicked = await service.click(
            principal=principal,
            conversation_id=context.conversation_id,
            session_id=UUID(session_id),
            x=320,
            y=480,
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
        assert clicked.url == "https://example.com/clicked"
        assert service.clicks == [(320, 480)]

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


def test_thumbnail_gallery_rejects_unverified_images() -> None:
    async def scenario() -> None:
        context = ToolExecutionContext(
            principal=public_principal(),
            conversation_id=uuid4(),
            permitted_resource_uris=frozenset(),
        )
        service = FakeBrowserSessionService()
        tool = BrowserCompareTool(service, load_component_registry())
        with pytest.raises(ToolValidationError, match="image discovery"):
            await tool.execute(
                {
                    "presentation": "thumbnails",
                    "candidates": [
                        {
                            "url": "https://example.com/week2",
                            "image_url": "https://example.com/unknown.png",
                        },
                        {"url": "https://example.com/other"},
                    ],
                },
                context,
            )
        assert not service.previews

    asyncio.run(scenario())


def test_generic_open_cannot_invent_thumbnail_captures() -> None:
    from course_server.workspace.tools import WorkspaceOpenComponentTool

    async def scenario() -> None:
        context = ToolExecutionContext(
            principal=public_principal(),
            conversation_id=uuid4(),
            permitted_resource_uris=frozenset(),
        )
        with pytest.raises(ToolValidationError, match=r"browser\.compare"):
            await WorkspaceOpenComponentTool(load_component_registry()).execute(
                {
                    "component_id": "page-cards",
                    "props": {
                        "presentation": "thumbnails",
                        "items": [
                            {
                                "id": name,
                                "title": name,
                                "url": f"https://example.com/{name}",
                                "preview_id": str(uuid4()),
                                "revision": 1,
                            }
                            for name in ("one", "two")
                        ],
                    },
                },
                context,
            )
        assert context.workspace_state == {"panels": []}

    asyncio.run(scenario())


def test_screenshot_capacity_is_separate_and_bounded() -> None:
    from course_server.browser.models import BrowserCapacityReached
    from course_server.browser.playwright_service import PlaywrightBrowserSessionService

    async def scenario() -> None:
        service = PlaywrightBrowserSessionService(max_sessions=2, max_sessions_per_principal=2)
        owner = uuid4()
        # Both live-browser slots reserved by inspection; screenshots still work.
        await service._reserve(owner)
        await service._reserve(owner)
        await service._reserve_capture(owner)
        with pytest.raises(BrowserCapacityReached):
            await service._reserve_capture(owner)
        await service._reserve_capture(uuid4())
        with pytest.raises(BrowserCapacityReached):
            await service._reserve_capture(uuid4())
        with pytest.raises(BrowserCapacityReached):
            await service._reserve(owner)

    asyncio.run(scenario())


def test_showcase_gallery_survives_capture_failure_and_cannot_be_replaced() -> None:
    from course_server.browser.models import BrowserCapacityReached
    from course_server.workspace.tools import WorkspaceReviewPresentationTool

    class FailingCapture(FakeBrowserSessionService):
        async def create_preview(
            self, *, principal: PrincipalContext, conversation_id: UUID, url: str
        ) -> BrowserPreview:
            if url.endswith("/c/week2"):
                raise BrowserCapacityReached("Temporary capacity")
            return await super().create_preview(
                principal=principal, conversation_id=conversation_id, url=url
            )

    async def scenario() -> None:
        context = ToolExecutionContext(
            principal=public_principal(),
            conversation_id=uuid4(),
            permitted_resource_uris=frozenset(),
        )
        context.transient_state["showcase_selection_sites"] = [
            f"https://example.edu/{n}/" for n in "abcd"
        ]
        review = WorkspaceReviewPresentationTool()
        with pytest.raises(ToolValidationError, match="gallery is not displayed"):
            await review.execute({"decision": "no_visual"}, context)
        tool = BrowserCompareTool(FailingCapture(), load_component_registry())
        args: dict[str, JsonValue] = {
            "presentation": "thumbnails",
            "candidates": [{"url": f"https://example.edu/{n}/week2", "title": n} for n in "abcd"],
        }
        result = await tool.execute(args, context)
        assert isinstance(result.content, dict)
        assert result.content["status"] == "partial_images"
        assert result.content["capture_failures"] == [
            {"url": "https://example.edu/c/week2", "reason_code": "browser_capacityreached"}
        ]
        panel = WorkspaceState.model_validate(context.workspace_state).panels[0]
        items = panel.props["items"]
        assert isinstance(items, list) and len(items) == 4
        assert isinstance(items[2], dict) and items[2]["preview_unavailable"] is True
        context.transient_state["workspace_changed_this_turn"] = True
        await review.execute({"decision": "workspace_ready"}, context)
        with pytest.raises(ToolValidationError, match="exactly once"):
            await tool.execute(
                {**args, "candidates": [{"url": "https://example.edu/abc/week2"}] * 4}, context
            )
        context.workspace_state.clear()
        context.workspace_state.update({"panels": []})
        with pytest.raises(ToolValidationError, match="gallery is not displayed"):
            await review.execute({"decision": "no_visual"}, context)

    asyncio.run(scenario())


def test_capture_releases_reservation_when_browser_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from course_server.browser.models import BrowserUnavailable
    from course_server.browser.playwright_service import PlaywrightBrowserSessionService

    async def safe_url(url: str) -> str:
        return url

    monkeypatch.setattr(
        "course_server.browser.playwright_service.validate_public_https_url", safe_url
    )

    async def scenario() -> None:
        service = PlaywrightBrowserSessionService()
        owner = public_principal()
        for _ in range(2):
            with pytest.raises(BrowserUnavailable):
                await service.create_preview(
                    principal=owner, conversation_id=uuid4(), url="https://example.com"
                )
            assert service._captures_by_principal == {}

    asyncio.run(scenario())


def test_comparison_security_failure_does_not_become_a_placeholder() -> None:
    class UnsafeCapture(FakeBrowserSessionService):
        async def create_preview(
            self, *, principal: PrincipalContext, conversation_id: UUID, url: str
        ) -> BrowserPreview:
            raise BrowserSecurityError("Private destination blocked")

    async def scenario() -> None:
        context = ToolExecutionContext(
            principal=public_principal(),
            conversation_id=uuid4(),
            permitted_resource_uris=frozenset(),
        )
        with pytest.raises(ToolValidationError, match="Private destination") as failure:
            await BrowserCompareTool(UnsafeCapture(), load_component_registry()).execute(
                {
                    "presentation": "thumbnails",
                    "candidates": [
                        {"url": "https://example.com/a"},
                        {"url": "https://example.com/b"},
                    ],
                },
                context,
            )
        assert getattr(failure.value, "reason_code", None) == "browser_securityerror"
        assert context.workspace_state == {"panels": []}

    asyncio.run(scenario())


def test_legacy_comparison_still_fails_when_capture_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from unittest.mock import AsyncMock

    from course_server.browser.models import BrowserUnavailable

    async def scenario() -> None:
        service = FakeBrowserSessionService()
        monkeypatch.setattr(
            service, "create_preview", AsyncMock(side_effect=BrowserUnavailable("Unavailable"))
        )
        context = ToolExecutionContext(
            principal=public_principal(),
            conversation_id=uuid4(),
            permitted_resource_uris=frozenset(),
        )
        with pytest.raises(ToolValidationError, match="Unavailable"):
            await BrowserCompareTool(service, load_component_registry()).execute(
                {
                    "candidates": [
                        {"url": "https://example.com/a"},
                        {"url": "https://example.com/b"},
                    ]
                },
                context,
            )
        assert context.workspace_state == {"panels": []}

    asyncio.run(scenario())
