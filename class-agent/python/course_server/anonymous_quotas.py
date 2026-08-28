"""Persistent, atomic quotas for anonymous public access."""

from __future__ import annotations

from dataclasses import dataclass
from threading import Lock
from typing import Any, Literal, Protocol
from uuid import UUID

from psycopg_pool import AsyncConnectionPool

QuotaMetric = Literal["conversations", "agent_runs", "uploads", "upload_bytes"]


@dataclass(frozen=True)
class AnonymousQuotaPolicy:
    max_conversations: int = 3
    max_agent_runs: int = 10
    max_uploads: int = 5
    max_upload_bytes: int = 20 * 1024 * 1024


@dataclass(frozen=True)
class QuotaCharge:
    metric: QuotaMetric
    amount: int
    limit: int

    def __post_init__(self) -> None:
        if self.amount < 1 or self.limit < 1 or self.amount > self.limit:
            raise ValueError("quota charge and limit must be positive and charge must fit limit")


class AnonymousQuotaExceeded(RuntimeError):
    def __init__(self, metric: QuotaMetric, limit: int) -> None:
        self.metric = metric
        self.limit = limit
        super().__init__(f"anonymous {metric} quota exceeded")


class AnonymousQuotaStore(Protocol):
    async def consume(self, session_id: UUID, charges: tuple[QuotaCharge, ...]) -> None: ...


class InMemoryAnonymousQuotaStore:
    """Process-local adapter for tests and explicitly in-memory applications."""

    def __init__(self) -> None:
        self._usage: dict[tuple[UUID, QuotaMetric], int] = {}
        self._lock = Lock()

    async def consume(self, session_id: UUID, charges: tuple[QuotaCharge, ...]) -> None:
        with self._lock:
            for charge in charges:
                used = self._usage.get((session_id, charge.metric), 0)
                if used + charge.amount > charge.limit:
                    raise AnonymousQuotaExceeded(charge.metric, charge.limit)
            for charge in charges:
                key = (session_id, charge.metric)
                self._usage[key] = self._usage.get(key, 0) + charge.amount


class PostgresAnonymousQuotaStore:
    """Atomic PostgreSQL quota accounting shared by all API processes."""

    def __init__(self, pool: AsyncConnectionPool[Any]) -> None:
        self._pool = pool

    async def consume(self, session_id: UUID, charges: tuple[QuotaCharge, ...]) -> None:
        async with self._pool.connection() as connection, connection.transaction():
            for charge in charges:
                cursor = await connection.execute(
                    """
                    INSERT INTO anonymous_quota_usage (session_id, metric, used)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (session_id, metric) DO UPDATE
                    SET used = anonymous_quota_usage.used + EXCLUDED.used
                    WHERE anonymous_quota_usage.used + EXCLUDED.used <= %s
                    RETURNING used
                    """,
                    (session_id, charge.metric, charge.amount, charge.limit),
                )
                if await cursor.fetchone() is None:
                    raise AnonymousQuotaExceeded(charge.metric, charge.limit)
