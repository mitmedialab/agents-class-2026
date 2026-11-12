from __future__ import annotations

import asyncio
import json
import stat
import subprocess
import sys
from pathlib import Path

import pytest
from examples.memory_starter.setup import provision_users, require_local_database

from course_server.auth import InMemoryAuthStore
from course_server.course_roster import load_course_roster, verify_roster_resources

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SETUP = PROJECT_ROOT / "examples/memory_starter/setup.py"


def test_memory_starter_installs_only_fictional_private_data(tmp_path: Path) -> None:
    command = [sys.executable, str(SETUP), "--data-only", "--output-root", str(tmp_path)]
    first = subprocess.run(command, cwd=PROJECT_ROOT, capture_output=True, text=True, check=False)

    assert first.returncode == 0, first.stderr
    roster_path = tmp_path / "var/roster/course-members.json"
    roster = load_course_roster(roster_path)
    assert roster is not None
    assert {member.username for member in roster.members} == {"ada-demo", "bo-demo"}
    assert all(str(member.email).endswith("@example.org") for member in roster.members)
    assert all(member.application_id is None for member in roster.members)
    assert stat.S_IMODE(roster_path.stat().st_mode) == 0o600
    verify_roster_resources(roster, tmp_path / "data")

    original = roster_path.read_bytes()
    second = subprocess.run(command, cwd=PROJECT_ROOT, capture_output=True, text=True, check=False)
    assert second.returncode == 0, second.stderr
    assert roster_path.read_bytes() == original

    changed = json.loads(original)
    changed["members"][0]["name"] = "Existing Real Student"
    roster_path.write_text(json.dumps(changed), encoding="utf-8")
    blocked = subprocess.run(command, cwd=PROJECT_ROOT, capture_output=True, text=True, check=False)
    assert blocked.returncode != 0
    assert "Refusing to replace an existing local roster" in blocked.stderr
    assert json.loads(roster_path.read_text(encoding="utf-8")) == changed


def test_memory_starter_provisions_matching_accounts_once() -> None:
    async def scenario() -> None:
        store = InMemoryAuthStore()
        issued = await provision_users(store)
        assert {username for username, _ in issued} == {"ada-demo", "bo-demo"}
        assert all(code for _, code in issued)
        assert await provision_users(store) == []
        assert all(user.role == "student" for user in store.users.values())

    asyncio.run(scenario())


def test_memory_starter_rejects_remote_database() -> None:
    require_local_database("postgresql://class_agent:dev@localhost:5432/class_agent")
    with pytest.raises(ValueError, match="loopback"):
        require_local_database("postgresql://class_agent:dev@db.example.org:5432/class_agent")
