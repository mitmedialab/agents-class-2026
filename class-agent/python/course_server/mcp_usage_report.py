"""Staff-side aggregate Course MCP usage report; no student-level output."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from collections.abc import Sequence

from dotenv import load_dotenv

from course_server.mcp_usage import usage_summary
from course_server.postgres.auth_store import create_auth_pool


async def _run(database_url: str, days: int) -> None:
    pool = create_auth_pool(database_url)
    await pool.open()
    await pool.wait()
    try:
        print(json.dumps(await usage_summary(pool, days=days), indent=2))
    finally:
        await pool.close()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Aggregate Course MCP usage")
    parser.add_argument("--days", type=int, default=30, help="window from 1 to 260 days")
    arguments = parser.parse_args(argv)
    if not 1 <= arguments.days <= 90:
        parser.error("--days must be between 1 and 90")
    load_dotenv(override=False)
    database_url = os.environ.get("DATABASE_URL", "").strip()
    if not database_url:
        parser.error("DATABASE_URL is required")
    asyncio.run(_run(database_url, arguments.days))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
