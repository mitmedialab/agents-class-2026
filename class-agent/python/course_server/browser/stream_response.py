"""Authenticated browser frame transport, without recording frame events."""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from contextlib import suppress
from uuid import UUID

from fastapi.responses import StreamingResponse

from agent_core import PrincipalContext

from .models import BrowserError
from .stream import BrowserStreamService


async def browser_stream_response(
    browser: BrowserStreamService,
    *,
    principal: PrincipalContext,
    conversation_id: UUID,
    session_id: UUID,
) -> StreamingResponse:
    subscription = await browser.subscribe(
        principal=principal,
        conversation_id=conversation_id,
        session_id=session_id,
    )

    async def frames() -> AsyncIterator[str]:
        # Reconnect at least once a minute to revalidate HTTP authentication/ownership.
        deadline = time.monotonic() + 60
        try:
            while time.monotonic() < deadline:
                frame = await browser.next_frame(
                    principal=principal,
                    conversation_id=conversation_id,
                    session_id=session_id,
                    subscription_id=subscription,
                )
                yield f"data: {frame.model_dump_json()}\n\n" if frame else ": keepalive\n\n"
        except BrowserError:
            yield "event: unavailable\ndata: {}\n\n"
        finally:
            with suppress(BrowserError):
                await asyncio.shield(
                    browser.unsubscribe(
                        principal=principal,
                        conversation_id=conversation_id,
                        session_id=session_id,
                        subscription_id=subscription,
                    )
                )

    return StreamingResponse(
        frames(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "private, no-store",
            "X-Accel-Buffering": "no",
            "X-Content-Type-Options": "nosniff",
        },
    )
