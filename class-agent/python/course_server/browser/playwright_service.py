"""Playwright adapter for isolated server-side browser sessions."""

from __future__ import annotations

import asyncio
import ipaddress
import socket
import threading
from collections.abc import Coroutine
from concurrent.futures import Future
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, TypeVar
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from playwright.async_api import (
    Browser,
    BrowserContext,
    FloatRect,
    Page,
    Playwright,
    Route,
    ViewportSize,
    async_playwright,
)
from playwright.async_api import (
    Error as PlaywrightError,
)
from playwright.async_api import (
    TimeoutError as PlaywrightTimeoutError,
)

from agent_core import PrincipalContext

from .models import (
    BrowserCapacityReached,
    BrowserNavigationError,
    BrowserPage,
    BrowserPreview,
    BrowserPreviewSnapshot,
    BrowserSecurityError,
    BrowserSessionNotFound,
    BrowserSnapshot,
    BrowserUnavailable,
)

_DEFAULT_CHROME_PATH = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
_ALLOWED_NON_NETWORK_SCHEMES = frozenset({"about", "blob", "data"})
_MAX_CAPTURE_HEIGHT = 16_000
_ResultT = TypeVar("_ResultT")


@dataclass
class _ManagedSession:
    owner_session_id: UUID
    conversation_id: UUID
    context: BrowserContext
    page: Page
    state: BrowserPage
    png: bytes
    operation_lock: asyncio.Lock


@dataclass
class _ManagedPreview:
    owner_session_id: UUID
    conversation_id: UUID
    state: BrowserPreview
    png: bytes


def _is_public_address(address: str) -> bool:
    try:
        parsed = ipaddress.ip_address(address.split("%", 1)[0])
    except ValueError:
        return False
    return parsed.is_global


async def validate_public_https_url(url: str) -> str:
    """Resolve and reject local/private destinations before Chromium receives a URL."""

    if len(url) > 2_048:
        raise BrowserSecurityError("The browser URL is too long.")
    parsed = urlsplit(url)
    if parsed.scheme.casefold() != "https" or not parsed.hostname:
        raise BrowserSecurityError("The remote browser only opens public HTTPS URLs.")
    if parsed.username is not None or parsed.password is not None:
        raise BrowserSecurityError("Credential-bearing URLs are not allowed.")
    if parsed.port not in {None, 443}:
        raise BrowserSecurityError("Only the standard HTTPS port is allowed.")
    try:
        results = await asyncio.wait_for(
            asyncio.to_thread(socket.getaddrinfo, parsed.hostname, 443, type=socket.SOCK_STREAM),
            timeout=3,
        )
    except (TimeoutError, OSError, socket.gaierror) as error:
        raise BrowserSecurityError(
            "The browser destination could not be resolved safely."
        ) from error
    addresses = {str(result[4][0]) for result in results}
    if not addresses or any(not _is_public_address(address) for address in addresses):
        raise BrowserSecurityError("Private and local network destinations are not allowed.")
    return parsed.geturl()


class PlaywrightBrowserSessionService:
    """One Chromium process with isolated, principal-scoped browser contexts."""

    def __init__(
        self,
        *,
        max_sessions: int = 20,
        max_sessions_per_principal: int = 2,
        session_ttl_seconds: int = 900,
        executable_path: Path | None = None,
        viewport_width: int = 1280,
        viewport_height: int = 800,
    ) -> None:
        if max_sessions < 1 or max_sessions_per_principal < 1:
            raise ValueError("browser session limits must be positive")
        self._max_sessions = max_sessions
        self._max_sessions_per_principal = max_sessions_per_principal
        self._ttl = timedelta(seconds=session_ttl_seconds)
        self._executable_path = executable_path
        self._viewport: ViewportSize = {
            "width": viewport_width,
            "height": viewport_height,
        }
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._sessions: dict[UUID, _ManagedSession] = {}
        self._previews: dict[UUID, _ManagedPreview] = {}
        self._opening_by_principal: dict[UUID, int] = {}
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        if self._browser is not None:
            return
        try:
            playwright = await async_playwright().start()
            executable = self._executable_path
            if executable is None and _DEFAULT_CHROME_PATH.is_file():
                executable = _DEFAULT_CHROME_PATH
            self._browser = await playwright.chromium.launch(
                headless=True,
                executable_path=str(executable) if executable is not None else None,
                args=["--disable-dev-shm-usage"],
                chromium_sandbox=True,
            )
            self._playwright = playwright
        except PlaywrightError as error:
            if self._playwright is not None:
                await self._playwright.stop()
            self._playwright = None
            self._browser = None
            raise BrowserUnavailable(
                "Chromium is unavailable. Install it with `uv run playwright install chromium`."
            ) from error

    async def close(self) -> None:
        sessions = list(self._sessions.values())
        self._sessions.clear()
        self._previews.clear()
        for session in sessions:
            await session.context.close()
        if self._browser is not None:
            await self._browser.close()
            self._browser = None
        if self._playwright is not None:
            await self._playwright.stop()
            self._playwright = None

    async def open(
        self,
        *,
        principal: PrincipalContext,
        conversation_id: UUID,
        url: str,
    ) -> BrowserPage:
        safe_url = await validate_public_https_url(url)
        await self._cleanup_expired()
        await self._reserve(principal.session_id)
        context: BrowserContext | None = None
        try:
            browser = self._browser
            if browser is None:
                raise BrowserUnavailable("The remote browser is unavailable.")
            context = await browser.new_context(
                viewport=self._viewport,
                accept_downloads=False,
                ignore_https_errors=False,
                java_script_enabled=True,
                service_workers="block",
            )
            await context.route("**/*", self._route_public_request)
            page = await context.new_page()
            await self._load_page(page, safe_url)
            session_id = uuid4()
            state, png = await self._capture(
                session_id=session_id,
                page=page,
                revision=1,
            )
            self._sessions[session_id] = _ManagedSession(
                owner_session_id=principal.session_id,
                conversation_id=conversation_id,
                context=context,
                page=page,
                state=state,
                png=png,
                operation_lock=asyncio.Lock(),
            )
            return state
        except Exception:
            if context is not None:
                await context.close()
            raise
        finally:
            await self._release_reservation(principal.session_id)

    async def create_preview(
        self,
        *,
        principal: PrincipalContext,
        conversation_id: UUID,
        url: str,
    ) -> BrowserPreview:
        """Capture a page and immediately release Chromium resources."""

        safe_url = await validate_public_https_url(url)
        await self._cleanup_expired()
        await self._reserve(principal.session_id)
        context: BrowserContext | None = None
        try:
            browser = self._browser
            if browser is None:
                raise BrowserUnavailable("The remote browser is unavailable.")
            context = await browser.new_context(
                viewport=self._viewport,
                accept_downloads=False,
                ignore_https_errors=False,
                java_script_enabled=True,
                service_workers="block",
            )
            await context.route("**/*", self._route_public_request)
            page = await context.new_page()
            await self._load_page(page, safe_url)
            preview_id = uuid4()
            captured, png = await self._capture(
                session_id=preview_id,
                page=page,
                revision=1,
            )
            preview = BrowserPreview(
                preview_id=preview_id,
                url=captured.url,
                title=captured.title,
                revision=captured.revision,
                text_excerpt=captured.text_excerpt,
                expires_at=captured.expires_at,
                viewport_width=captured.viewport_width,
                viewport_height=captured.viewport_height,
                document_height=captured.document_height,
            )
            async with self._lock:
                self._previews[preview_id] = _ManagedPreview(
                    owner_session_id=principal.session_id,
                    conversation_id=conversation_id,
                    state=preview,
                    png=png,
                )
                self._prune_previews_locked(principal.session_id)
            return preview
        except Exception:
            raise
        finally:
            if context is not None:
                await context.close()
            await self._release_reservation(principal.session_id)

    async def preview_snapshot(
        self,
        *,
        principal: PrincipalContext,
        conversation_id: UUID,
        preview_id: UUID,
    ) -> BrowserPreviewSnapshot:
        await self._cleanup_expired()
        preview = self._previews.get(preview_id)
        if (
            preview is None
            or preview.owner_session_id != principal.session_id
            or preview.conversation_id != conversation_id
        ):
            raise BrowserSessionNotFound("Browser preview not found.")
        preview.state = preview.state.model_copy(
            update={"expires_at": datetime.now(UTC) + self._ttl}
        )
        return BrowserPreviewSnapshot(preview=preview.state, png=preview.png)

    async def navigate(
        self,
        *,
        principal: PrincipalContext,
        conversation_id: UUID,
        session_id: UUID,
        url: str,
    ) -> BrowserPage:
        safe_url = await validate_public_https_url(url)
        session = await self._require(principal, conversation_id, session_id)
        async with session.operation_lock:
            await self._load_page(session.page, safe_url)
            return await self._refresh(session_id, session)

    async def scroll(
        self,
        *,
        principal: PrincipalContext,
        conversation_id: UUID,
        session_id: UUID,
        delta_y: int,
    ) -> BrowserPage:
        if not -1_600 <= delta_y <= 1_600 or delta_y == 0:
            raise BrowserNavigationError("Scroll distance must be between -1600 and 1600.")
        session = await self._require(principal, conversation_id, session_id)
        async with session.operation_lock:
            await session.page.mouse.wheel(0, delta_y)
            await session.page.wait_for_timeout(150)
            return await self._refresh(session_id, session)

    async def resize(
        self,
        *,
        principal: PrincipalContext,
        conversation_id: UUID,
        session_id: UUID,
        width: int,
        height: int,
    ) -> BrowserPage:
        if not 320 <= width <= 4_096 or not 240 <= height <= 4_096:
            raise BrowserNavigationError("Browser viewport dimensions are outside safe limits.")
        session = await self._require(principal, conversation_id, session_id)
        async with session.operation_lock:
            await session.page.set_viewport_size({"width": width, "height": height})
            await session.page.wait_for_timeout(100)
            return await self._refresh(session_id, session)

    async def highlight_text(
        self,
        *,
        principal: PrincipalContext,
        conversation_id: UUID,
        session_id: UUID,
        text: str,
    ) -> tuple[BrowserPage, int]:
        query = text.strip()
        if not query or len(query) > 500:
            raise BrowserNavigationError("Highlight text must contain 1 to 500 characters.")
        session = await self._require(principal, conversation_id, session_id)
        async with session.operation_lock:
            locator = session.page.get_by_text(query, exact=False)
            count = await locator.count()
            if count:
                match = locator.first
                await match.scroll_into_view_if_needed(timeout=3_000)
                await match.evaluate(
                    """element => {
                      document.querySelectorAll('[data-class-agent-highlight]').forEach(node => {
                        node.removeAttribute('data-class-agent-highlight');
                        node.style.removeProperty('outline');
                        node.style.removeProperty('outline-offset');
                        node.style.removeProperty('background-color');
                      });
                      element.setAttribute('data-class-agent-highlight', 'true');
                      element.style.setProperty('outline', '3px solid #ff2d55', 'important');
                      element.style.setProperty('outline-offset', '4px', 'important');
                      element.style.setProperty(
                        'background-color', 'rgba(255,45,85,.16)', 'important'
                      );
                    }"""
                )
            return await self._refresh(session_id, session), count

    async def snapshot(
        self,
        *,
        principal: PrincipalContext,
        conversation_id: UUID,
        session_id: UUID,
    ) -> BrowserSnapshot:
        session = await self._require(principal, conversation_id, session_id)
        return BrowserSnapshot(page=session.state, png=session.png)

    async def close_session(
        self,
        *,
        principal: PrincipalContext,
        conversation_id: UUID,
        session_id: UUID,
    ) -> None:
        session = await self._require(principal, conversation_id, session_id)
        self._sessions.pop(session_id, None)
        async with session.operation_lock:
            await session.context.close()

    async def _route_public_request(self, route: Route) -> None:
        parsed = urlsplit(route.request.url)
        if parsed.scheme.casefold() in _ALLOWED_NON_NETWORK_SCHEMES:
            await route.continue_()
            return
        try:
            await validate_public_https_url(route.request.url)
        except BrowserSecurityError:
            await route.abort("blockedbyclient")
            return
        await route.continue_()

    async def _load_page(self, page: Page, url: str) -> None:
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=20_000)
            await validate_public_https_url(page.url)
        except BrowserSecurityError:
            raise
        except PlaywrightTimeoutError:
            if page.url in {"", "about:blank"}:
                raise BrowserNavigationError("The page did not respond in time.") from None
        except PlaywrightError as error:
            raise BrowserNavigationError("The page could not be opened.") from error

    async def _capture(
        self,
        *,
        session_id: UUID,
        page: Page,
        revision: int,
    ) -> tuple[BrowserPage, bytes]:
        try:
            viewport = page.viewport_size or self._viewport
            title = (await page.title()).strip() or urlsplit(page.url).hostname or "Web page"
            text = (await page.locator("body").inner_text(timeout=3_000))[:12_000]
            raw_metrics = await page.evaluate(
                """() => ({
                  scrollY: Math.max(0, Math.round(window.scrollY)),
                  documentHeight: Math.max(
                    document.body?.scrollHeight || 0,
                    document.documentElement?.scrollHeight || 0,
                    window.innerHeight
                  )
                })"""
            )
            scroll_y = int(raw_metrics.get("scrollY", 0)) if isinstance(raw_metrics, dict) else 0
            document_height = (
                int(raw_metrics.get("documentHeight", viewport["height"]))
                if isinstance(raw_metrics, dict)
                else viewport["height"]
            )
            if document_height <= _MAX_CAPTURE_HEIGHT:
                png = await page.screenshot(
                    type="png",
                    full_page=True,
                    animations="disabled",
                )
            else:
                clip: FloatRect = {
                    "x": 0,
                    "y": 0,
                    "width": viewport["width"],
                    "height": _MAX_CAPTURE_HEIGHT,
                }
                png = await page.screenshot(
                    type="png",
                    clip=clip,
                    animations="disabled",
                )
                document_height = _MAX_CAPTURE_HEIGHT
        except PlaywrightError as error:
            raise BrowserNavigationError("The browser view could not be captured.") from error
        return (
            BrowserPage(
                session_id=session_id,
                url=page.url,
                title=title[:500],
                revision=revision,
                text_excerpt=text,
                expires_at=datetime.now(UTC) + self._ttl,
                viewport_width=viewport["width"],
                viewport_height=viewport["height"],
                scroll_y=scroll_y,
                document_height=document_height,
            ),
            png,
        )

    async def _refresh(self, session_id: UUID, session: _ManagedSession) -> BrowserPage:
        state, png = await self._capture(
            session_id=session_id,
            page=session.page,
            revision=session.state.revision + 1,
        )
        session.state = state
        session.png = png
        return state

    async def _require(
        self,
        principal: PrincipalContext,
        conversation_id: UUID,
        session_id: UUID,
    ) -> _ManagedSession:
        await self._cleanup_expired()
        session = self._sessions.get(session_id)
        if (
            session is None
            or session.owner_session_id != principal.session_id
            or session.conversation_id != conversation_id
        ):
            raise BrowserSessionNotFound("Browser session not found.")
        session.state = session.state.model_copy(
            update={"expires_at": datetime.now(UTC) + self._ttl}
        )
        return session

    async def _reserve(self, principal_session_id: UUID) -> None:
        async with self._lock:
            active = sum(
                session.owner_session_id == principal_session_id
                for session in self._sessions.values()
            )
            opening = self._opening_by_principal.get(principal_session_id, 0)
            if len(self._sessions) + sum(self._opening_by_principal.values()) >= self._max_sessions:
                raise BrowserCapacityReached("The remote browser is currently at capacity.")
            if active + opening >= self._max_sessions_per_principal:
                raise BrowserCapacityReached(
                    "Close an existing browser panel before opening another."
                )
            self._opening_by_principal[principal_session_id] = opening + 1

    async def _release_reservation(self, principal_session_id: UUID) -> None:
        async with self._lock:
            remaining = self._opening_by_principal.get(principal_session_id, 1) - 1
            if remaining > 0:
                self._opening_by_principal[principal_session_id] = remaining
            else:
                self._opening_by_principal.pop(principal_session_id, None)

    async def _cleanup_expired(self) -> None:
        now = datetime.now(UTC)
        async with self._lock:
            expired = [
                session_id
                for session_id, session in self._sessions.items()
                if session.state.expires_at <= now
            ]
            sessions = [self._sessions.pop(session_id) for session_id in expired]
            expired_previews = [
                preview_id
                for preview_id, preview in self._previews.items()
                if preview.state.expires_at <= now
            ]
            for preview_id in expired_previews:
                self._previews.pop(preview_id, None)
        for session in sessions:
            await session.context.close()

    def _prune_previews_locked(self, principal_session_id: UUID) -> None:
        """Bound static capture memory without reducing live-session capacity."""

        owned = sorted(
            (
                (preview_id, preview)
                for preview_id, preview in self._previews.items()
                if preview.owner_session_id == principal_session_id
            ),
            key=lambda item: item[1].state.expires_at,
            reverse=True,
        )
        for preview_id, _preview in owned[12:]:
            self._previews.pop(preview_id, None)
        if len(self._previews) > 120:
            oldest = sorted(self._previews.items(), key=lambda item: item[1].state.expires_at)
            for preview_id, _preview in oldest[: len(self._previews) - 120]:
                self._previews.pop(preview_id, None)


class ThreadedPlaywrightBrowserSessionService:
    """Loop-safe facade used by HTTP handlers and synchronous agent tool threads."""

    def __init__(
        self,
        *,
        max_sessions: int = 20,
        max_sessions_per_principal: int = 2,
        session_ttl_seconds: int = 900,
        executable_path: Path | None = None,
        viewport_width: int = 1280,
        viewport_height: int = 800,
    ) -> None:
        self._max_sessions = max_sessions
        self._max_sessions_per_principal = max_sessions_per_principal
        self._session_ttl_seconds = session_ttl_seconds
        self._executable_path = executable_path
        self._viewport_width = viewport_width
        self._viewport_height = viewport_height
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._service: PlaywrightBrowserSessionService | None = None

    async def start(self) -> None:
        if self._thread is not None:
            return
        ready: Future[None] = Future()

        def run_controller() -> None:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self._loop = loop
            service = PlaywrightBrowserSessionService(
                max_sessions=self._max_sessions,
                max_sessions_per_principal=self._max_sessions_per_principal,
                session_ttl_seconds=self._session_ttl_seconds,
                executable_path=self._executable_path,
                viewport_width=self._viewport_width,
                viewport_height=self._viewport_height,
            )
            self._service = service

            async def boot() -> None:
                try:
                    await service.start()
                except BaseException as error:
                    ready.set_exception(error)
                    loop.stop()
                else:
                    ready.set_result(None)

            boot_task = loop.create_task(boot())
            loop.run_forever()
            del boot_task
            pending = asyncio.all_tasks(loop)
            for task in pending:
                task.cancel()
            if pending:
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            loop.close()

        thread = threading.Thread(
            target=run_controller,
            name="class-agent-browser-controller",
            daemon=True,
        )
        self._thread = thread
        thread.start()
        try:
            await asyncio.wrap_future(ready)
        except BaseException:
            await asyncio.to_thread(thread.join, 5)
            self._thread = None
            self._loop = None
            self._service = None
            raise

    async def close(self) -> None:
        loop = self._loop
        thread = self._thread
        service = self._service
        if loop is None or thread is None or service is None:
            return
        try:
            await self._call(service.close())
        finally:
            loop.call_soon_threadsafe(loop.stop)
            await asyncio.to_thread(thread.join, 5)
            self._thread = None
            self._loop = None
            self._service = None

    async def open(
        self,
        *,
        principal: PrincipalContext,
        conversation_id: UUID,
        url: str,
    ) -> BrowserPage:
        service = self._require_service()
        return await self._call(
            service.open(principal=principal, conversation_id=conversation_id, url=url)
        )

    async def create_preview(
        self,
        *,
        principal: PrincipalContext,
        conversation_id: UUID,
        url: str,
    ) -> BrowserPreview:
        service = self._require_service()
        return await self._call(
            service.create_preview(
                principal=principal,
                conversation_id=conversation_id,
                url=url,
            )
        )

    async def preview_snapshot(
        self,
        *,
        principal: PrincipalContext,
        conversation_id: UUID,
        preview_id: UUID,
    ) -> BrowserPreviewSnapshot:
        service = self._require_service()
        return await self._call(
            service.preview_snapshot(
                principal=principal,
                conversation_id=conversation_id,
                preview_id=preview_id,
            )
        )

    async def navigate(
        self,
        *,
        principal: PrincipalContext,
        conversation_id: UUID,
        session_id: UUID,
        url: str,
    ) -> BrowserPage:
        service = self._require_service()
        return await self._call(
            service.navigate(
                principal=principal,
                conversation_id=conversation_id,
                session_id=session_id,
                url=url,
            )
        )

    async def scroll(
        self,
        *,
        principal: PrincipalContext,
        conversation_id: UUID,
        session_id: UUID,
        delta_y: int,
    ) -> BrowserPage:
        service = self._require_service()
        return await self._call(
            service.scroll(
                principal=principal,
                conversation_id=conversation_id,
                session_id=session_id,
                delta_y=delta_y,
            )
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
        service = self._require_service()
        return await self._call(
            service.resize(
                principal=principal,
                conversation_id=conversation_id,
                session_id=session_id,
                width=width,
                height=height,
            )
        )

    async def highlight_text(
        self,
        *,
        principal: PrincipalContext,
        conversation_id: UUID,
        session_id: UUID,
        text: str,
    ) -> tuple[BrowserPage, int]:
        service = self._require_service()
        return await self._call(
            service.highlight_text(
                principal=principal,
                conversation_id=conversation_id,
                session_id=session_id,
                text=text,
            )
        )

    async def snapshot(
        self,
        *,
        principal: PrincipalContext,
        conversation_id: UUID,
        session_id: UUID,
    ) -> BrowserSnapshot:
        service = self._require_service()
        return await self._call(
            service.snapshot(
                principal=principal,
                conversation_id=conversation_id,
                session_id=session_id,
            )
        )

    async def close_session(
        self,
        *,
        principal: PrincipalContext,
        conversation_id: UUID,
        session_id: UUID,
    ) -> None:
        service = self._require_service()
        await self._call(
            service.close_session(
                principal=principal,
                conversation_id=conversation_id,
                session_id=session_id,
            )
        )

    async def _call(self, work: Coroutine[Any, Any, _ResultT]) -> _ResultT:
        loop = self._loop
        if loop is None or not loop.is_running():
            work.close()
            raise BrowserUnavailable("The remote browser is unavailable.")
        future = asyncio.run_coroutine_threadsafe(work, loop)
        return await asyncio.wrap_future(future)

    def _require_service(self) -> PlaywrightBrowserSessionService:
        if self._service is None:
            raise BrowserUnavailable("The remote browser is unavailable.")
        return self._service
