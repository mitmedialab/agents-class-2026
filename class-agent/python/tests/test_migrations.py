from __future__ import annotations

from pathlib import Path

import pytest

from course_server.migrations import MigrationError, discover_migrations

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS_PATH = PROJECT_ROOT / "database/migrations"


def test_migrations_are_discoverable_and_checksummed() -> None:
    migrations = discover_migrations(MIGRATIONS_PATH)

    assert [migration.version for migration in migrations] == [
        "0001_authentication",
        "0002_conversations_events",
    ]
    assert all(len(migration.checksum) == 64 for migration in migrations)


def test_phase_two_migration_contains_required_authentication_tables() -> None:
    sql = discover_migrations(MIGRATIONS_PATH)[0].sql.lower()

    for table in (
        "schema_migrations",
        "users",
        "auth_sessions",
        "anonymous_sessions",
        "auth_login_failures",
    ):
        assert "create table" in sql
        assert table in sql

    assert "access_code_hash" in sql
    assert "token_hash" in sql
    assert "access_code text" not in sql
    assert "session_token" not in sql


def test_phase_three_migration_contains_portable_history_tables() -> None:
    sql = discover_migrations(MIGRATIONS_PATH)[1].sql.lower()

    assert "create table conversations" in sql
    assert "create table events" in sql
    assert "payload jsonb" in sql
    assert "metadata jsonb" in sql
    assert "pickle" not in sql


def test_invalid_migration_filename_is_rejected(tmp_path: Path) -> None:
    (tmp_path / "bad-name.sql").write_text("SELECT 1;", encoding="utf-8")

    with pytest.raises(MigrationError, match="invalid migration filename"):
        discover_migrations(tmp_path)
