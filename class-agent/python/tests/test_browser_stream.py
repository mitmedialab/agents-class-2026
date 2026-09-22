from __future__ import annotations

import asyncio
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from playwright.async_api import Page

from course_server.browser.models import BrowserCapacityReached, BrowserSessionNotFound
from course_server.browser.stream import ViewportStream


def test_stream_drops_old_frames_bounds_viewers_and_detaches() -> None:
    async def run() -> None:
        cdp = MagicMock()
        cdp.send = AsyncMock()
        cdp.detach = AsyncMock()
        page = MagicMock()
        page.viewport_size = {"width": 1280, "height": 800}
        page.context.new_cdp_session = AsyncMock(return_value=cdp)
        stream = ViewportStream()
        first, second = stream.subscribe(), stream.subscribe()
        with pytest.raises(BrowserCapacityReached):
            stream.subscribe()
        await stream.attach(cast(Page, page))
        receive = cdp.on.call_args.args[1]
        for i in range(3):
            await receive(
                {
                    "data": str(i),
                    "sessionId": i,
                    "metadata": {
                        "deviceWidth": 1280,
                        "deviceHeight": 800,
                        "scrollOffsetY": 300,
                    },
                }
            )
        await receive(
            {
                "data": "bad-expanded-frame",
                "sessionId": 4,
                "metadata": {
                    "deviceWidth": 1280,
                    "deviceHeight": 5000,
                    "scrollOffsetY": 0,
                },
            }
        )
        for subscription in (first, second):
            frame = await stream.next_frame(subscription)
            assert frame is not None and frame.jpeg == "2" and frame.scroll_y == 300
        await stream.unsubscribe(first)
        assert stream.active
        await stream.unsubscribe(second)
        assert not stream.active
        cdp.detach.assert_awaited_once()
        with pytest.raises(BrowserSessionNotFound):
            await stream.next_frame(first)

    asyncio.run(run())


def test_stream_close_wakes_waiting_reader_and_rebinds_on_navigation() -> None:
    async def run() -> None:
        def page() -> Any:
            result = MagicMock()
            cdp = MagicMock(send=AsyncMock(), detach=AsyncMock())
            result.context.new_cdp_session = AsyncMock(return_value=cdp)
            return result

        stream = ViewportStream()
        subscription = stream.subscribe()
        original, replacement = page(), page()
        await stream.attach(original)
        await stream.attach(replacement)
        original.context.new_cdp_session.return_value.detach.assert_awaited_once()
        waiting = asyncio.create_task(stream.next_frame(subscription))
        await asyncio.sleep(0)
        await stream.close()
        with pytest.raises(BrowserSessionNotFound):
            await waiting

    asyncio.run(run())


def test_real_browser_stream_rejects_other_principal_and_conversation() -> None:
    from test_browser import public_principal

    from course_server.browser.playwright_service import PlaywrightBrowserSessionService

    async def run() -> None:
        service = PlaywrightBrowserSessionService()
        owner = public_principal()
        conversation, session_id = uuid4(), uuid4()
        # No live browser is needed to exercise the authorization boundary.
        session = MagicMock()
        from datetime import UTC, datetime, timedelta

        session.owner_session_id = owner.session_id
        session.conversation_id = conversation
        session.state.expires_at = datetime.now(UTC) + timedelta(minutes=1)
        service._sessions[session_id] = session
        for principal, conversation_id in ((public_principal(), conversation), (owner, uuid4())):
            with pytest.raises(BrowserSessionNotFound):
                await service.subscribe(
                    principal=principal, conversation_id=conversation_id, session_id=session_id
                )
            with pytest.raises(BrowserSessionNotFound):
                await service.next_frame(
                    principal=principal,
                    conversation_id=conversation_id,
                    session_id=session_id,
                    subscription_id=uuid4(),
                )
        session.stream.subscribe.assert_not_called()

    asyncio.run(run())
