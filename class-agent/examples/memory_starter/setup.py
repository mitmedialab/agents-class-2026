"""Prepare a fork with fictional course members and local student accounts."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from course_server.auth import InMemoryAuthStore, UserAdminService
from course_server.course_roster import (
    CourseRoster,
    load_course_roster,
    publish_roster_resources,
    verify_roster_resources,
    write_course_roster,
)
from course_server.index_resources import index_resources
from course_server.migrations import apply_migrations
from course_server.postgres.auth_store import PostgresAuthStore, create_auth_pool

PROJECT_ROOT = Path(__file__).resolve().parents[2]
FIXTURE = Path(__file__).with_name("course-members.json")
STAFF = Path(__file__).with_name("course-staff.json")
ASSIGNMENTS = Path(__file__).with_name("assignments")
GRADES = Path(__file__).with_name("grades") / "weekly-feedback.json"
DEFAULT_DATABASE_URL = "postgresql://class_agent:class_agent_dev@127.0.0.1:5432/class_agent"


def install_fixture(output_root: Path) -> tuple[Path, Path]:
    """Install only into empty paths; allow reruns against the same fixture."""
    roster_path = output_root / "var/roster/course-members.json"
    data_path = output_root / "data"
    roster = CourseRoster.model_validate_json(FIXTURE.read_text(encoding="utf-8"))
    if roster_path.exists():
        if load_course_roster(roster_path) != roster:
            raise FileExistsError(f"Refusing to replace an existing local roster: {roster_path}")
        verify_roster_resources(roster, data_path)
        return roster_path, data_path

    protected_paths = (
        data_path / "students/final-project-interests/final-project-interests.md",
        data_path / "students/final-project-interests/resource.json",
        data_path / "instructors/course-roster/course-roster.md",
        data_path / "instructors/course-roster/resource.json",
    )
    existing = [path for path in protected_paths if path.exists()]
    if existing:
        raise FileExistsError(
            "Fictional setup refused to replace existing local data: "
            + ", ".join(str(path) for path in existing)
        )

    write_course_roster(roster_path, roster)
    publish_roster_resources(roster, data_path)
    return roster_path, data_path


def install_assignments(output_root: Path) -> Path:
    """Install released course assignments without replacing local records."""
    destination = output_root / "var/assignments"
    fixtures = sorted(folder for folder in ASSIGNMENTS.iterdir() if folder.is_dir())
    expected_ids = {folder.name for folder in fixtures}
    if destination.is_symlink() or (destination.exists() and not destination.is_dir()):
        raise FileExistsError(f"Refusing invalid assignment directory: {destination}")
    if destination.exists():
        for folder in destination.iterdir():
            if folder.name not in expected_ids or folder.is_symlink() or not folder.is_dir():
                raise FileExistsError(f"Refusing existing local assignment data: {folder}")
            expected_names = {f"{folder.name}.json", f"{folder.name}.md"}
            for file in folder.iterdir():
                if file.name not in expected_names or file.is_symlink() or not file.is_file():
                    raise FileExistsError(f"Refusing existing local assignment data: {file}")
    for folder in fixtures:
        target_folder = destination / folder.name
        for source in folder.iterdir():
            target = target_folder / source.name
            if target.exists() and target.read_bytes() != source.read_bytes():
                raise FileExistsError(f"Refusing to replace a local assignment: {target}")
    destination.mkdir(parents=True, exist_ok=True, mode=0o700)
    for folder in fixtures:
        target_folder = destination / folder.name
        target_folder.mkdir(mode=0o700, exist_ok=True)
        for source in folder.iterdir():
            target = target_folder / source.name
            if not target.exists():
                target.write_bytes(source.read_bytes())
                target.chmod(0o600)
    return destination


def install_grades(output_root: Path) -> Path:
    """Install fictional feedback without replacing an existing gradebook."""
    destination = output_root / "var/grades/weekly-feedback.json"
    if destination.parent.is_symlink() or destination.is_symlink():
        raise FileExistsError(f"Refusing invalid gradebook path: {destination}")
    if destination.exists():
        if not destination.is_file() or destination.read_bytes() != GRADES.read_bytes():
            raise FileExistsError(f"Refusing to replace a local gradebook: {destination}")
        return destination
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    destination.write_bytes(GRADES.read_bytes())
    destination.chmod(0o600)
    return destination


async def provision_users(store: InMemoryAuthStore | PostgresAuthStore) -> list[tuple[str, str]]:
    """Create matching demo accounts once and return newly issued access codes."""
    roster = CourseRoster.model_validate_json(FIXTURE.read_text(encoding="utf-8"))
    admin = UserAdminService(store)
    issued_codes: list[tuple[str, str]] = []
    staff = json.loads(STAFF.read_text(encoding="utf-8"))["staff"]
    accounts = [
        (member.username, member.name, str(member.email), "student") for member in roster.members
    ] + [
        (person["username"], person["display_name"], person["email"], person["role"])
        for person in staff
    ]
    for username, display_name, email, role in accounts:
        existing = await store.get_user_by_username(username)
        if existing is not None:
            if (
                existing.display_name != display_name
                or str(existing.email) != email
                or existing.role != role
                or not existing.active
            ):
                raise ValueError(f"Existing account conflicts with demo user {username}")
            continue
        issued = await admin.create_user(
            username=username,
            display_name=display_name,
            email=email,
            role=role,
        )
        issued_codes.append((username, issued.access_code))
    return issued_codes


async def provision_postgres_users(database_url: str) -> list[tuple[str, str]]:
    pool = create_auth_pool(database_url)
    await pool.open()
    try:
        return await provision_users(PostgresAuthStore(pool))
    finally:
        await pool.close()


def require_local_database(database_url: str) -> None:
    parsed = urlsplit(database_url)
    if parsed.scheme not in {"postgres", "postgresql"} or parsed.hostname not in {
        "127.0.0.1",
        "localhost",
        "::1",
    }:
        raise ValueError("Development setup requires a loopback PostgreSQL URL")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-root",
        type=Path,
        default=PROJECT_ROOT,
        help="Checkout root containing var/ and data/; defaults to class-agent/.",
    )
    parser.add_argument(
        "--data-only",
        action="store_true",
        help="Install fictional users and published assignments without a database.",
    )
    parser.add_argument(
        "--database-url",
        default=os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL),
        help="Local PostgreSQL URL; defaults to DATABASE_URL or the Compose development database.",
    )
    arguments = parser.parse_args()
    try:
        if not arguments.data_only:
            require_local_database(arguments.database_url)
            if arguments.output_root.resolve() != PROJECT_ROOT:
                raise ValueError("--output-root requires --data-only")
        roster_path, data_path = install_fixture(arguments.output_root)
        assignment_path = install_assignments(arguments.output_root)
        grade_path = install_grades(arguments.output_root)
        if arguments.data_only:
            print(f"Installed fictional roster: {roster_path}")
            print(f"Published fictional protected resources: {data_path}")
            print(f"Installed released course assignments: {assignment_path}")
            print(f"Installed fictional weekly feedback: {grade_path}")
            return

        env_path = PROJECT_ROOT / ".env"
        if not env_path.exists():
            example = (PROJECT_ROOT / ".env.example").read_text(encoding="utf-8")
            env_path.write_text(
                example.replace(
                    "STUDENT_PROJECT_FIXTURES_ENABLED=false",
                    "STUDENT_PROJECT_FIXTURES_ENABLED=true",
                ),
                encoding="utf-8",
            )
            env_path.chmod(0o600)
        apply_migrations(arguments.database_url)
        index_resources(arguments.database_url)
        issued_codes = asyncio.run(provision_postgres_users(arguments.database_url))
    except (FileExistsError, ValueError) as error:
        parser.exit(1, f"{error}\n")
    print(f"Fictional roster and protected resources are ready: {roster_path}")
    print(f"Released course assignments are ready: {assignment_path}")
    print(f"Fictional weekly feedback is ready: {grade_path}")
    if issued_codes:
        print("New local student access codes (shown only now; keep them out of Git):")
        for username, code in issued_codes:
            print(f"  {username}: {code}")
    else:
        print(
            "Demo accounts already exist; use their original codes "
            "or reset them with the admin CLI."
        )
    print("Add your own OPENAI_API_KEY and BRAVE_API_KEY to .env before starting the agent API.")
    print("Start the API with `uv run python -m course_server.api` and Vite with `pnpm dev`.")
    print("Open https://localhost:5173 and accept the local development certificate warning.")


if __name__ == "__main__":
    main()
