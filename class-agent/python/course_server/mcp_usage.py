"""Privacy-light, server-owned Course MCP tool-use telemetry and aggregates."""

from __future__ import annotations

import hashlib
import logging
import time
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.fastmcp import FastMCP
from mcp.types import ContentBlock
from psycopg_pool import AsyncConnectionPool

logger = logging.getLogger(__name__)
_RETENTION = timedelta(days=260)
_UNKNOWN_TOOL = "unknown_tool"


def _outcome(error: Exception, *, known_tool: bool) -> str:
    if not known_tool:
        return "invalid_tool"
    cause = error.__cause__ or error
    if isinstance(cause, PermissionError):
        return "permission_denied"
    if isinstance(cause, ValueError):
        return "invalid_input"
    if isinstance(cause, LookupError):
        return "unavailable"
    return "execution_error"


class McpUsageRecorder:
    """Persist only recognized tool names and a hash of a trusted user UUID."""

    def __init__(self, pool: AsyncConnectionPool[Any], *, server_version: str) -> None:
        self._pool = pool
        self._server_version = server_version
        self._last_pruned: date | None = None

    async def record(
        self,
        *,
        user_id: UUID,
        tool_name: str,
        outcome: str,
        duration_ms: int,
    ) -> None:
        now = datetime.now(UTC)
        principal_hash = hashlib.sha256(user_id.bytes).digest()
        async with self._pool.connection() as connection, connection.transaction():
            await connection.execute(
                """
                INSERT INTO mcp_tool_usage (
                    id, occurred_at, principal_hash, tool_name, outcome,
                    duration_ms, server_version
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    uuid4(),
                    now,
                    principal_hash,
                    tool_name,
                    outcome,
                    duration_ms,
                    self._server_version,
                ),
            )
            if self._last_pruned != now.date():
                await connection.execute(
                    "DELETE FROM mcp_tool_usage WHERE occurred_at < %s",
                    (now - _RETENTION,),
                )
                self._last_pruned = now.date()


class InstrumentedCourseMCP(FastMCP[Any]):
    """Observe actual authorized tool calls without retaining tool arguments/results."""

    usage_recorder: McpUsageRecorder | None = None

    async def call_tool(
        self, name: str, arguments: dict[str, Any]
    ) -> Sequence[ContentBlock] | dict[str, Any]:
        access = get_access_token()
        if access is None or access.subject is None:
            return await super().call_tool(name, arguments)
        try:
            user_id = UUID(access.subject)
        except ValueError:
            return await super().call_tool(name, arguments)
        known_tool = any(tool.name == name for tool in await self.list_tools())
        safe_name = name if known_tool else _UNKNOWN_TOOL
        started = time.perf_counter()
        outcome = "success"
        try:
            return await super().call_tool(name, arguments)
        except Exception as error:
            outcome = _outcome(error, known_tool=known_tool)
            raise
        finally:
            if self.usage_recorder is not None:
                duration_ms = min(3_600_000, max(0, int((time.perf_counter() - started) * 1000)))
                try:
                    await self.usage_recorder.record(
                        user_id=user_id,
                        tool_name=safe_name,
                        outcome=outcome,
                        duration_ms=duration_ms,
                    )
                except Exception as error:
                    # Telemetry must never alter the authorized tool result. Do not
                    # log arguments, outputs, exception text, or account identity.
                    logger.warning("MCP usage recording failed (%s)", type(error).__name__)


async def usage_summary(pool: AsyncConnectionPool[Any], *, days: int = 30) -> dict[str, Any]:
    """Return aggregates only; never expose per-student usage records."""
    if not 1 <= days <= 260:
        raise ValueError("Usage report range must be between 1 and 260 days.")
    since = datetime.now(UTC) - timedelta(days=days)
    async with pool.connection() as connection:
        totals = await (
            await connection.execute(
                """
                SELECT count(*) AS tool_calls,
                       count(DISTINCT principal_hash) AS active_students,
                       count(*) FILTER (WHERE outcome <> 'success') AS failed_calls
                FROM mcp_tool_usage WHERE occurred_at >= %s
                """,
                (since,),
            )
        ).fetchone()
        by_tool = await (
            await connection.execute(
                """
                SELECT tool_name, count(*) AS calls,
                       count(*) FILTER (WHERE outcome <> 'success') AS failed_calls,
                       round(avg(duration_ms))::integer AS mean_duration_ms
                FROM mcp_tool_usage WHERE occurred_at >= %s
                GROUP BY tool_name ORDER BY calls DESC, tool_name
                """,
                (since,),
            )
        ).fetchall()
        weekly = await (
            await connection.execute(
                """
                WITH weekly_people AS (
                    SELECT DISTINCT date_trunc(
                        'week', occurred_at AT TIME ZONE 'UTC'
                    ) AS week_start_utc, principal_hash
                    FROM mcp_tool_usage WHERE occurred_at >= %s
                ), first_seen AS (
                    SELECT principal_hash,
                           min(occurred_at AT TIME ZONE 'UTC') AS first_at_utc
                    FROM mcp_tool_usage GROUP BY principal_hash
                )
                SELECT w.week_start_utc,
                       count(*) AS active_students,
                       count(*) FILTER (
                           WHERE f.first_at_utc >= w.week_start_utc
                       ) AS first_seen_students,
                       count(*) FILTER (
                           WHERE f.first_at_utc < w.week_start_utc
                       ) AS returning_students
                FROM weekly_people w
                JOIN first_seen f USING (principal_hash)
                GROUP BY w.week_start_utc ORDER BY w.week_start_utc
                """,
                (since,),
            )
        ).fetchall()
        workflow = await (
            await connection.execute(
                """
                SELECT count(DISTINCT assignment.principal_hash) AS students
                FROM mcp_tool_usage assignment
                JOIN mcp_tool_usage resource
                  ON resource.principal_hash = assignment.principal_hash
                 AND resource.occurred_at >= assignment.occurred_at
                 AND resource.occurred_at < assignment.occurred_at + interval '1 day'
                WHERE assignment.occurred_at >= %s
                  AND assignment.tool_name = 'get_my_assignment'
                  AND assignment.outcome = 'success'
                  AND resource.tool_name IN (
                      'search_course_resources', 'read_course_resource',
                      'read_course_slide_page'
                  )
                  AND resource.outcome = 'success'
                """,
                (since,),
            )
        ).fetchone()
        connections = await (
            await connection.execute(
                """
                SELECT count(DISTINCT user_id) AS students
                FROM mcp_oauth_codes
                WHERE consumed_at IS NOT NULL AND created_at >= %s
                """,
                (since,),
            )
        ).fetchone()
        messages = await (
            await connection.execute(
                """
                SELECT count(*) AS drafts,
                       count(*) FILTER (WHERE status = 'sent') AS confirmed,
                       count(*) FILTER (WHERE email_sent_at IS NOT NULL) AS emailed
                FROM course_direct_messages WHERE created_at >= %s
                """,
                (since,),
            )
        ).fetchone()
    return {
        "window_days": days,
        "tool_calls": int(totals["tool_calls"]) if totals else 0,
        "active_students": int(totals["active_students"]) if totals else 0,
        "failed_calls": int(totals["failed_calls"]) if totals else 0,
        "connected_students": int(connections["students"]) if connections else 0,
        "assignment_to_resource_students": int(workflow["students"]) if workflow else 0,
        "message_funnel": {
            "drafts": int(messages["drafts"]) if messages else 0,
            "confirmed": int(messages["confirmed"]) if messages else 0,
            "emailed": int(messages["emailed"]) if messages else 0,
        },
        "by_tool": [
            {
                "tool_name": row["tool_name"],
                "calls": int(row["calls"]),
                "failed_calls": int(row["failed_calls"]),
                "mean_duration_ms": row["mean_duration_ms"],
            }
            for row in by_tool
        ],
        "weekly_active_students": [
            {
                "week_start_utc": row["week_start_utc"].isoformat() + "Z",
                "students": int(row["active_students"]),
                "first_seen_students": int(row["first_seen_students"]),
                "returning_students": int(row["returning_students"]),
            }
            for row in weekly
        ],
    }
