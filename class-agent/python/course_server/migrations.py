"""Minimal checksummed PostgreSQL migration runner."""

from __future__ import annotations

import argparse
import hashlib
import os
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import psycopg

MIGRATION_FILENAME = re.compile(r"^[0-9]{4}_[a-z0-9_]+\.sql$")
DEFAULT_MIGRATIONS_PATH = Path(__file__).resolve().parents[2] / "database/migrations"


class MigrationError(RuntimeError):
    """A migration set is malformed or differs from an applied migration."""


@dataclass(frozen=True)
class Migration:
    version: str
    path: Path
    sql: str
    checksum: str


def discover_migrations(path: Path = DEFAULT_MIGRATIONS_PATH) -> list[Migration]:
    migrations: list[Migration] = []
    for migration_path in sorted(path.glob("*.sql")):
        if MIGRATION_FILENAME.fullmatch(migration_path.name) is None:
            raise MigrationError(f"invalid migration filename: {migration_path.name}")
        contents = migration_path.read_text(encoding="utf-8")
        migrations.append(
            Migration(
                version=migration_path.stem,
                path=migration_path,
                sql=contents,
                checksum=hashlib.sha256(contents.encode()).hexdigest(),
            )
        )
    if not migrations:
        raise MigrationError(f"no migrations found in {path}")
    versions = [migration.version for migration in migrations]
    if len(versions) != len(set(versions)):
        raise MigrationError("migration versions must be unique")
    return migrations


def apply_migrations(
    database_url: str,
    path: Path = DEFAULT_MIGRATIONS_PATH,
) -> list[str]:
    applied_now: list[str] = []
    migrations = discover_migrations(path)

    with psycopg.connect(database_url) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version text PRIMARY KEY,
                checksum text NOT NULL,
                applied_at timestamptz NOT NULL DEFAULT now()
            )
            """
        )
        connection.commit()
        existing_rows = connection.execute(
            "SELECT version, checksum FROM schema_migrations"
        ).fetchall()
        existing = {str(version): str(checksum) for version, checksum in existing_rows}

        for migration in migrations:
            applied_checksum = existing.get(migration.version)
            if applied_checksum is not None:
                if applied_checksum != migration.checksum:
                    raise MigrationError(
                        f"applied migration {migration.version} has a different checksum"
                    )
                continue
            with connection.transaction():
                connection.execute(migration.sql)
                connection.execute(
                    "INSERT INTO schema_migrations (version, checksum) VALUES (%s, %s)",
                    (migration.version, migration.checksum),
                )
            applied_now.append(migration.version)
    return applied_now


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage Class Agent database migrations")
    parser.add_argument(
        "command",
        choices=["apply"],
        help="migration operation to perform",
    )
    parser.add_argument(
        "--database-url",
        help="PostgreSQL URL; defaults to DATABASE_URL",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    arguments = parser.parse_args(argv)
    database_url = arguments.database_url or os.environ.get("DATABASE_URL")
    if not database_url:
        parser.error("DATABASE_URL or --database-url is required")
    applied = apply_migrations(database_url)
    if applied:
        print("Applied migrations:")
        for version in applied:
            print(f"- {version}")
    else:
        print("Database schema is current.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
