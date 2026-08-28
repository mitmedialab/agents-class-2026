from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest

from course_server.anonymous_quotas import (
    AnonymousQuotaExceeded,
    InMemoryAnonymousQuotaStore,
    QuotaCharge,
)


def test_multi_metric_charge_is_atomic_when_one_limit_would_be_exceeded() -> None:
    async def scenario() -> None:
        store = InMemoryAnonymousQuotaStore()
        session_id = uuid4()
        await store.consume(
            session_id,
            (
                QuotaCharge(metric="uploads", amount=1, limit=2),
                QuotaCharge(metric="upload_bytes", amount=5, limit=10),
            ),
        )

        with pytest.raises(AnonymousQuotaExceeded, match="upload_bytes"):
            await store.consume(
                session_id,
                (
                    QuotaCharge(metric="uploads", amount=1, limit=2),
                    QuotaCharge(metric="upload_bytes", amount=6, limit=10),
                ),
            )

        await store.consume(
            session_id,
            (QuotaCharge(metric="uploads", amount=1, limit=2),),
        )

    asyncio.run(scenario())


def test_quota_usage_is_isolated_by_anonymous_session() -> None:
    async def scenario() -> None:
        store = InMemoryAnonymousQuotaStore()
        first = uuid4()
        second = uuid4()
        charge = (QuotaCharge(metric="agent_runs", amount=1, limit=1),)
        await store.consume(first, charge)
        await store.consume(second, charge)
        with pytest.raises(AnonymousQuotaExceeded):
            await store.consume(first, charge)

    asyncio.run(scenario())
