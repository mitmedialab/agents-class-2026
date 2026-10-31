from __future__ import annotations

import asyncio
import hashlib
import os
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql

from course_server.mcp_usage import McpUsageRecorder, usage_summary
from course_server.migrations import apply_migrations
from course_server.postgres.auth_store import create_auth_pool

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")


def _schema_url(database_url: str, schema_name: str) -> str:
    parsed = urlsplit(database_url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query["options"] = f"-csearch_path={schema_name}"
    return urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, urlencode(query), parsed.fragment)
    )


@pytest.mark.postgres
@pytest.mark.skipif(TEST_DATABASE_URL is None, reason="TEST_DATABASE_URL is not configured")
def test_mcp_usage_is_pseudonymous_aggregated_and_pruned() -> None:
    assert TEST_DATABASE_URL is not None
    schema_name = f"test_mcp_usage_{uuid4().hex}"
    with psycopg.connect(TEST_DATABASE_URL) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema_name)))
    database_url = _schema_url(TEST_DATABASE_URL, schema_name)

    async def scenario() -> None:
        apply_migrations(database_url)
        pool = create_auth_pool(database_url)
        await pool.open()
        await pool.wait()
        try:
            student_one, student_two = uuid4(), uuid4()
            old_hash = hashlib.sha256(uuid4().bytes).digest()
            async with pool.connection() as connection:
                await connection.execute(
                    """
                    INSERT INTO mcp_tool_usage (
                        id, occurred_at, principal_hash, tool_name,
                        outcome, duration_ms, server_version
                    ) VALUES (%s, %s, %s, 'get_my_assignment', 'success', 1, 'old')
                    """,
                    (uuid4(), datetime.now(UTC) - timedelta(days=261), old_hash),
                )
            recorder = McpUsageRecorder(pool, server_version="pilot-1")
            await recorder.record(
                user_id=student_one,
                tool_name="get_my_assignment",
                outcome="success",
                duration_ms=12,
            )
            await recorder.record(
                user_id=student_one,
                tool_name="read_course_resource",
                outcome="success",
                duration_ms=19,
            )
            await recorder.record(
                user_id=student_two,
                tool_name="prepare_course_message",
                outcome="invalid_input",
                duration_ms=3,
            )
            async with pool.connection() as connection:
                rows = await (
                    await connection.execute(
                        "SELECT principal_hash, server_version FROM mcp_tool_usage"
                    )
                ).fetchall()
            assert len(rows) == 3
            assert {row["principal_hash"] for row in rows} == {
                hashlib.sha256(student_one.bytes).digest(),
                hashlib.sha256(student_two.bytes).digest(),
            }
            assert {row["server_version"] for row in rows} == {"pilot-1"}
            assert str(student_one) not in str(rows)
            report = await usage_summary(pool, days=30)
            assert report["tool_calls"] == 3
            assert report["active_students"] == 2
            assert report["failed_calls"] == 1
            assert report["assignment_to_resource_students"] == 1
            assert report["connected_students"] == 0
            assert report["message_funnel"] == {"drafts": 0, "confirmed": 0, "emailed": 0}
            assert report["weekly_active_students"][0]["students"] == 2
            assert report["weekly_active_students"][0]["first_seen_students"] == 2
            assert report["weekly_active_students"][0]["returning_students"] == 0
            assert (await usage_summary(pool, days=260))["tool_calls"] == 3
            with pytest.raises(ValueError, match="between 1 and 260"):
                await usage_summary(pool, days=261)
        finally:
            await pool.close()

    try:
        asyncio.run(scenario())
    finally:
        with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as connection:
            connection.execute(
                sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema_name))
            )
