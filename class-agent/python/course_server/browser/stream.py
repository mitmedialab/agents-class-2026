"""Ephemeral, bounded Chromium viewport streams; never canonical workspace history."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from typing import Any, Protocol, runtime_checkable
from uuid import UUID, uuid4

from playwright.async_api import CDPSession, Page
from playwright.async_api import Error as PlaywrightError
from pydantic import BaseModel, Field, ValidationError

from agent_core import PrincipalContext

from .models import BrowserCapacityReached, BrowserSessionNotFound


class BrowserFrame(BaseModel):
    jpeg: str = Field(max_length=8_000_000)
    width: int = Field(ge=1, le=4096)
    height: int = Field(ge=1, le=4096)
    scroll_y: int = Field(ge=0)


@runtime_checkable
class BrowserStreamService(Protocol):
    """Optional adapter capability, separate from persisted browser contracts."""

    async def subscribe(
        self, *, principal: PrincipalContext, conversation_id: UUID, session_id: UUID
    ) -> UUID: ...

    async def next_frame(
        self,
        *,
        principal: PrincipalContext,
        conversation_id: UUID,
        session_id: UUID,
        subscription_id: UUID,
    ) -> BrowserFrame | None: ...

    async def unsubscribe(
        self,
        *,
        principal: PrincipalContext,
        conversation_id: UUID,
        session_id: UUID,
        subscription_id: UUID,
    ) -> None: ...


class ViewportStream:
    """One screencast per page, at most two viewers and one pending frame per viewer."""

    def __init__(self) -> None:
        self._cdp: CDPSession | None = None
        self._queues: dict[UUID, asyncio.Queue[BrowserFrame | None]] = {}
        self._latest: BrowserFrame | None = None

    async def attach(self, page: Page) -> None:
        await self.detach()
        cdp = await page.context.new_cdp_session(page)
        self._cdp = cdp

        async def receive(event: dict[str, Any]) -> None:
            if self._cdp is not cdp:
                return
            try:
                metadata = event["metadata"]
                width, height = round(metadata["deviceWidth"]), round(metadata["deviceHeight"])
                viewport = page.viewport_size
                # Full-page PNG captures temporarily expand Chromium's viewport. Never
                # send those frames to a viewport-sized live surface.
                if viewport is None or (width, height) != (viewport["width"], viewport["height"]):
                    return
                frame = BrowserFrame(
                    jpeg=event["data"],
                    width=width,
                    height=height,
                    scroll_y=max(0, round(metadata["scrollOffsetY"])),
                )
                self._latest = frame
                for queue in self._queues.values():
                    if queue.full():
                        queue.get_nowait()
                    queue.put_nowait(frame)
            except (ValidationError, KeyError, TypeError, ValueError):
                # Malformed or oversize frames cannot break the producer's ACK loop.
                pass
            finally:
                # Acknowledgement provides producer backpressure, capped near 20 fps.
                await asyncio.sleep(0.05)
                with suppress(PlaywrightError):
                    await cdp.send("Page.screencastFrameAck", {"sessionId": event["sessionId"]})

        cdp.on("Page.screencastFrame", receive)
        await cdp.send(
            "Page.startScreencast",
            {
                "format": "jpeg",
                "quality": 80,
                "maxWidth": 4096,
                "maxHeight": 4096,
                "everyNthFrame": 1,
            },
        )

    def subscribe(self) -> UUID:
        if len(self._queues) >= 2:
            raise BrowserCapacityReached("This browser already has two live viewers.")
        subscription = uuid4()
        queue: asyncio.Queue[BrowserFrame | None] = asyncio.Queue(maxsize=1)
        if self._latest is not None:
            queue.put_nowait(self._latest)
        self._queues[subscription] = queue
        return subscription

    async def next_frame(self, subscription: UUID) -> BrowserFrame | None:
        queue = self._queues.get(subscription)
        if queue is None:
            raise BrowserSessionNotFound("Browser stream not found.")
        try:
            frame = await asyncio.wait_for(queue.get(), timeout=10)
        except TimeoutError:
            return None
        if frame is None:
            raise BrowserSessionNotFound("Browser stream closed.")
        return frame

    async def unsubscribe(self, subscription: UUID) -> None:
        self._queues.pop(subscription, None)
        if not self._queues:
            await self.detach()

    async def detach(self) -> None:
        cdp, self._cdp = self._cdp, None
        self._latest = None
        if cdp is not None:
            with suppress(PlaywrightError):
                await cdp.send("Page.stopScreencast")
                await cdp.detach()

    async def close(self) -> None:
        await self.detach()
        for queue in self._queues.values():
            if queue.full():
                queue.get_nowait()
            queue.put_nowait(None)
        self._queues.clear()

    @property
    def active(self) -> bool:
        return self._cdp is not None
