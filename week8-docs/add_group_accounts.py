"""Add Group 1's local demo accounts (yuxiang, stacey, jad) to a set-up Week 8 fork.

Run after `examples/memory_starter/setup.py`, from `class-agent/`:

    uv run python ../week8-docs/add_group_accounts.py

The accounts exist only in your local roster (`var/roster/`, ignored) and your local
PostgreSQL. Each new account gets a fresh access code, printed once; nothing is written to
Git. Like the starter setup, the script refuses non-loopback databases, and it is safe to rerun:
existing accounts are kept and no code is printed for them. If a code is lost, reissue it with
`uv run python -m course_server.admin reset-user-code --username <name>`.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import shutil
from pathlib import Path
from urllib.parse import urlsplit

from course_server.auth import UserAdminService
from course_server.course_roster import (
    CourseRoster,
    load_course_roster,
    publish_roster_resources,
    write_course_roster,
)
from course_server.postgres.auth_store import PostgresAuthStore, create_auth_pool

CLASS_AGENT = Path.cwd()
DEFAULT_DATABASE_URL = "postgresql://class_agent:class_agent_dev@127.0.0.1:5432/class_agent"
# Example.org addresses keep the members' real email addresses out of local fixtures.
GROUP = (
    ("yuxiang", "Yuxiang Cheng"),
    ("stacey", "Stacey Cho"),
    ("jad", "Jad Bendarkawi"),
)


def require_local_database(database_url: str) -> None:
    parsed = urlsplit(database_url)
    if parsed.scheme not in {"postgres", "postgresql"} or parsed.hostname not in {
        "127.0.0.1",
        "localhost",
        "::1",
    }:
        raise ValueError("This script only writes to a loopback PostgreSQL database")


def add_to_roster(roster_path: Path, data_path: Path) -> list[str]:
    """Append missing group members as active credit students; back up the roster once."""
    roster = load_course_roster(roster_path)
    if roster is None or not roster.members:
        raise FileNotFoundError(
            f"No local roster at {roster_path}; run examples/memory_starter/setup.py first"
        )
    present = {member.username for member in roster.members}
    missing = [(username, name) for username, name in GROUP if username not in present]
    if not missing:
        return []
    backup = roster_path.with_name("course-members.before-group1.json")
    if not backup.exists():
        shutil.copy2(roster_path, backup)
    template = roster.members[0]
    added = [
        template.model_copy(
            update={
                "student_id": username,
                "name": name,
                "username": username,
                "aliases": [],
                "email": f"{username}@example.org",
                "github_username": f"{username}-local-demo",
                "institution": "MIT",
                "department": "Media Arts and Sciences",
                "enrollment_type": "credit",
                "course_status": "active",
                "project_id": None,
                "website": None,
                "keywords": [],
                "project_ideas": [],
                "application_id": None,
                "inactive_reason": None,
                "departure_notice_received": None,
            }
        )
        for username, name in missing
    ]
    updated = CourseRoster.model_validate(
        {
            **roster.model_dump(mode="json"),
            "members": [m.model_dump(mode="json") for m in [*roster.members, *added]],
        }
    )
    write_course_roster(roster_path, updated)
    # The API verifies that published roster resources match the roster at startup.
    publish_roster_resources(updated, data_path)
    return [username for username, _ in missing]


async def create_accounts(database_url: str) -> list[tuple[str, str]]:
    pool = create_auth_pool(database_url)
    await pool.open()
    try:
        store = PostgresAuthStore(pool)
        admin = UserAdminService(store)
        issued: list[tuple[str, str]] = []
        for username, name in GROUP:
            existing = await store.get_user_by_username(username)
            if existing is not None:
                if existing.role != "student" or not existing.active:
                    raise ValueError(f"Existing account {username} is not an active student")
                continue
            result = await admin.create_user(
                username=username,
                display_name=name,
                email=f"{username}@example.org",
                role="student",
            )
            issued.append((username, result.access_code))
        return issued
    finally:
        await pool.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--database-url",
        default=os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL),
        help="Local PostgreSQL URL; defaults to DATABASE_URL or the Compose database.",
    )
    arguments = parser.parse_args()
    if not (CLASS_AGENT / "examples/memory_starter/setup.py").exists():
        parser.exit(1, "Run this from the fork's class-agent/ directory.\n")
    try:
        require_local_database(arguments.database_url)
        added = add_to_roster(CLASS_AGENT / "var/roster/course-members.json", CLASS_AGENT / "data")
        issued = asyncio.run(create_accounts(arguments.database_url))
    except (FileNotFoundError, ValueError) as error:
        parser.exit(1, f"{error}\n")
    print(f"Roster: {'added ' + ', '.join(added) if added else 'group members already present'}")
    if issued:
        print("New local access codes (shown only now; keep them out of Git):")
        for username, code in issued:
            print(f"  {username}: {code}")
    else:
        print("Accounts already exist; use their codes or reissue with the admin CLI.")
    print("Restart the API so it reloads the roster.")


if __name__ == "__main__":
    main()
