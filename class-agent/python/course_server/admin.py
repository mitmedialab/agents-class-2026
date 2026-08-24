"""Instructor/admin CLI for access-code user lifecycle operations."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from collections.abc import Sequence
from typing import cast

from course_server.auth import (
    Argon2AccessCodeHasher,
    UserAdminService,
    UserAlreadyExists,
    UserNotFound,
    UserRole,
)
from course_server.postgres.auth_store import PostgresAuthStore, create_auth_pool

ROLE_CHOICES = ("student", "ta", "instructor", "admin")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage Class Agent users")
    parser.add_argument(
        "--database-url",
        help="PostgreSQL URL; defaults to DATABASE_URL",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    create = commands.add_parser("create-user", help="create a user and issue an access code")
    create.add_argument("--username", required=True)
    create.add_argument("--name", required=True)
    create.add_argument("--email", required=True)
    create.add_argument("--role", choices=ROLE_CHOICES, required=True)

    reset = commands.add_parser("reset-user-code", help="replace a user's access code")
    reset.add_argument("--username", required=True)

    deactivate = commands.add_parser("deactivate-user", help="deactivate a user")
    deactivate.add_argument("--username", required=True)

    activate = commands.add_parser("activate-user", help="activate a user")
    activate.add_argument("--username", required=True)

    commands.add_parser("list-users", help="list users without credential hashes")

    change_role = commands.add_parser("change-role", help="change a user's role")
    change_role.add_argument("--username", required=True)
    change_role.add_argument("--role", choices=ROLE_CHOICES, required=True)
    return parser


async def _run(arguments: argparse.Namespace, database_url: str) -> int:
    pool = create_auth_pool(database_url)
    await pool.open()
    try:
        service = UserAdminService(PostgresAuthStore(pool), hasher=Argon2AccessCodeHasher())
        if arguments.command == "create-user":
            issued = await service.create_user(
                username=arguments.username,
                display_name=arguments.name,
                email=arguments.email,
                role=cast(UserRole, arguments.role),
            )
            print("User created.\n")
            print(f"Username: {issued.user.username}")
            print(f"Access code: {issued.access_code}\n")
            print("This code will not be displayed again.")
            return 0

        if arguments.command == "reset-user-code":
            issued = await service.reset_user_code(arguments.username)
            print("Access code reset.\n")
            print(f"Username: {issued.user.username}")
            print(f"Access code: {issued.access_code}\n")
            print("This code will not be displayed again.")
            return 0

        if arguments.command == "deactivate-user":
            user = await service.deactivate_user(arguments.username)
            print(f"Deactivated user: {user.username}")
            return 0

        if arguments.command == "activate-user":
            user = await service.activate_user(arguments.username)
            print(f"Activated user: {user.username}")
            return 0

        if arguments.command == "change-role":
            user = await service.change_role(
                arguments.username,
                cast(UserRole, arguments.role),
            )
            print(f"Changed {user.username} role to {user.role}.")
            return 0

        users = await service.list_users()
        print("USERNAME\tROLE\tACTIVE\tNAME\tEMAIL")
        for user in users:
            print(
                f"{user.username}\t{user.role}\t{str(user.active).lower()}\t"
                f"{user.display_name}\t{user.email}"
            )
        return 0
    finally:
        await pool.close()


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    arguments = parser.parse_args(argv)
    database_url = arguments.database_url or os.environ.get("DATABASE_URL")
    if not database_url:
        parser.error("DATABASE_URL or --database-url is required")
    try:
        return asyncio.run(_run(arguments, database_url))
    except (UserAlreadyExists, UserNotFound) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
