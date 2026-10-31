"""Canonical private course roster and role-filtered resource projections."""

from __future__ import annotations

import argparse
import json
import os
import re
import tempfile
import unicodedata
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import (
    AnyHttpUrl,
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

StudentId = Annotated[
    str,
    StringConstraints(strip_whitespace=True, pattern=r"^[a-z0-9][a-z0-9-]{1,99}$"),
]
Username = Annotated[
    str,
    StringConstraints(strip_whitespace=True, to_lower=True, pattern=r"^[a-z][a-z0-9._-]{1,63}$"),
]
NonEmptyText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
ProjectId = Annotated[
    str,
    StringConstraints(strip_whitespace=True, pattern=r"^agents2026-[A-Za-z0-9_.-]+$"),
]

_MARKDOWN_EMAIL = re.compile(r"\[([^]]+)]\(mailto:[^)]+\)")
_MARKDOWN_URL = re.compile(r"\[[^]]+]\((https://[^)]+)\)")
_PROJECT_FROM_URL = re.compile(r"/agents2026-([A-Za-z0-9_.-]+)/?$")


class CourseMember(BaseModel):
    """One accepted person, including current membership and project context."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    student_id: StudentId
    name: NonEmptyText
    aliases: list[NonEmptyText] = Field(default_factory=list)
    email: EmailStr
    username: Username
    github_username: Username
    institution: NonEmptyText
    department: NonEmptyText
    enrollment_type: Literal["credit", "listener"]
    course_status: Literal["active", "inactive"]
    participation: Literal["weekly_build", "listener_only"]
    project_id: ProjectId | None = None
    website: AnyHttpUrl | None = None
    keywords: list[NonEmptyText] = Field(default_factory=list)
    project_ideas: list[NonEmptyText] = Field(default_factory=list, max_length=3)
    application_id: UUID | None = None
    inactive_reason: NonEmptyText | None = None
    departure_notice_received: bool | None = None

    @field_validator(
        "name",
        "aliases",
        "institution",
        "department",
        "keywords",
        "project_ideas",
    )
    @classmethod
    def reject_multiline_text(cls, value: object) -> object:
        values = value if isinstance(value, list) else [value]
        if any(isinstance(item, str) and ("\n" in item or "\r" in item) for item in values):
            raise ValueError("roster text must be single-line")
        return value

    @model_validator(mode="after")
    def validate_membership_state(self) -> Self:
        if self.course_status == "active":
            if self.inactive_reason is not None or self.departure_notice_received is not None:
                raise ValueError("active members cannot have inactive-state fields")
        elif self.inactive_reason is None or self.departure_notice_received is None:
            raise ValueError("inactive members require a reason and departure-notice state")
        return self


class CourseRoster(BaseModel):
    """Versioned source of truth for accepted, active, and inactive course members."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1]
    as_of: date
    members: list[CourseMember] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_unique_identities(self) -> Self:
        unique_fields = {
            "student_id": [member.student_id for member in self.members],
            "email": [str(member.email).casefold() for member in self.members],
            "username": [member.username.casefold() for member in self.members],
            "github_username": [member.github_username.casefold() for member in self.members],
        }
        project_ids = [member.project_id.casefold() for member in self.members if member.project_id]
        unique_fields["project_id"] = project_ids
        for field_name, values in unique_fields.items():
            if len(values) != len(set(values)):
                raise ValueError(f"course roster contains duplicate {field_name} values")
        return self

    @property
    def active_members(self) -> tuple[CourseMember, ...]:
        return tuple(member for member in self.members if member.course_status == "active")

    @property
    def active_usernames(self) -> frozenset[str]:
        return frozenset(member.username.casefold() for member in self.active_members)

    @property
    def active_weekly_project_ids(self) -> frozenset[str]:
        return frozenset(
            member.project_id
            for member in self.active_members
            if member.participation == "weekly_build" and member.project_id is not None
        )

    def permits_student_username(self, username: str) -> bool:
        return username.strip().casefold() in self.active_usernames

    def identifies_inactive_username(self, username: str) -> bool:
        normalized = username.strip().casefold()
        return any(
            member.course_status == "inactive" and member.username.casefold() == normalized
            for member in self.members
        )

    @property
    def active_student_project_aliases(self) -> dict[str, str]:
        return {
            member.username: member.project_id
            for member in self.active_members
            if member.participation == "weekly_build"
            and member.project_id is not None
            and member.project_id != f"agents2026-{member.username}"
        }


def load_course_roster(path: Path) -> CourseRoster | None:
    """Load the configured private roster; absence leaves roster-backed features disabled."""
    if not path.is_file():
        return None
    return CourseRoster.model_validate_json(path.read_text(encoding="utf-8"))


def _atomic_private_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.parent.chmod(0o700)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}-", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        path.chmod(0o600)
    finally:
        temporary.unlink(missing_ok=True)


def write_course_roster(path: Path, roster: CourseRoster) -> None:
    payload = json.dumps(roster.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n"
    _atomic_private_write(path, payload)


def _member_markdown(member: CourseMember, *, include_status: bool) -> str:
    lines = [f"## {member.name}", ""]
    if include_status:
        lines.extend([f"- Course status: {member.course_status}"])
    lines.extend(
        [
            f"- Email: [{member.email}](mailto:{member.email})",
            f"- Course username: `{member.username}`",
            f"- GitHub username: `{member.github_username}`",
            f"- Institution: {member.institution}",
            f"- Department: {member.department}",
            f"- Enrollment: {member.enrollment_type}",
            f"- Participation: {member.participation.replace('_', ' ')}",
        ]
    )
    if member.project_id is not None:
        lines.append(f"- Project ID: `{member.project_id}`")
    if member.website is not None:
        lines.append(f"- Website: [{member.website}]({member.website})")
    lines.append(
        "- Keywords: " + ("; ".join(member.keywords) if member.keywords else "Not yet provided")
    )
    if include_status and member.course_status == "inactive":
        lines.extend(
            [
                f"- Inactive reason: {member.inactive_reason}",
                "- Departure notice received: "
                + ("yes" if member.departure_notice_received else "no"),
            ]
        )
    lines.extend(["", "### Project interests", ""])
    if member.project_ideas:
        lines.extend(f"{index}. {idea}" for index, idea in enumerate(member.project_ideas, 1))
    else:
        lines.append("Not yet provided.")
    return "\n".join(lines)


def render_student_roster(roster: CourseRoster) -> str:
    header = (
        "# Active Student Roster and Project Interests\n\n"
        f"Roster status as of {roster.as_of.isoformat()}. This resource contains active course "
        "members only. Project ideas are interests, not confirmed final-project choices.\n"
    )
    members = "\n\n".join(
        _member_markdown(member, include_status=False) for member in roster.active_members
    )
    return f"{header}\n{members}\n"


def render_instructor_roster(roster: CourseRoster) -> str:
    header = (
        "# Complete Course Roster\n\n"
        f"Roster status as of {roster.as_of.isoformat()}. This instructor-only resource includes "
        "active and inactive accepted members.\n"
    )
    members = "\n\n".join(
        _member_markdown(member, include_status=True) for member in roster.members
    )
    return f"{header}\n{members}\n"


def _roster_resource_contents(roster: CourseRoster, course_data_path: Path) -> dict[Path, str]:
    student_directory = course_data_path / "students/final-project-interests"
    instructor_directory = course_data_path / "instructors/course-roster"
    student_manifest = {
        "schema_version": 1,
        "resource": {
            "uri": "course://students/roster",
            "title": "Active Student Roster and Project Interests",
            "description": (
                "Read the complete active course roster, contact and institutional context, "
                "participation mode, project site, keywords, and proposed project ideas. "
                "Inactive former members are excluded."
            ),
            "media_type": "text/markdown",
            "file": "final-project-interests.md",
            "visibility": "students",
            "status": "published",
        },
    }
    instructor_manifest = {
        "schema_version": 1,
        "resource": {
            "uri": "course://instructors/roster",
            "title": "Complete Course Roster",
            "description": (
                "Read accepted course members with active or inactive status, enrollment, "
                "participation, project, and project-interest context."
            ),
            "media_type": "text/markdown",
            "file": "course-roster.md",
            "visibility": "instructors",
            "status": "published",
        },
    }
    return {
        student_directory / "final-project-interests.md": render_student_roster(roster),
        student_directory / "resource.json": json.dumps(student_manifest, indent=2) + "\n",
        instructor_directory / "course-roster.md": render_instructor_roster(roster),
        instructor_directory / "resource.json": json.dumps(instructor_manifest, indent=2) + "\n",
    }


def publish_roster_resources(roster: CourseRoster, course_data_path: Path) -> None:
    """Atomically publish only role-appropriate projections of the private roster."""
    for path, content in _roster_resource_contents(roster, course_data_path).items():
        _atomic_private_write(path, content)


def verify_roster_resources(roster: CourseRoster, course_data_path: Path) -> None:
    """Fail startup if role-filtered files are absent or stale."""
    for path, expected in _roster_resource_contents(roster, course_data_path).items():
        try:
            actual = path.read_text(encoding="utf-8")
        except OSError as error:
            raise ValueError(
                "Course roster projections are missing; run the roster publish command."
            ) from error
        if actual != expected:
            raise ValueError("Course roster projections are stale; run the roster publish command.")


def _name_key(name: str) -> str:
    normalized = unicodedata.normalize("NFKC", name).casefold()
    return " ".join(sorted(normalized.replace("(", " ").replace(")", " ").split()))


def _parse_legacy_interests(path: Path) -> dict[str, dict[str, object]]:
    interests: dict[str, dict[str, object]] = {}
    for line in path.read_text(encoding="utf-8").splitlines()[2:]:
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) != 7:
            raise ValueError(f"invalid project-interest row: {line[:80]}")
        name, email_cell, website_cell, keywords_cell, *idea_cells = cells
        email_match = _MARKDOWN_EMAIL.fullmatch(email_cell)
        website_match = _MARKDOWN_URL.fullmatch(website_cell)
        if not email_match:
            raise ValueError(f"invalid project-interest email for {name}")
        interests[_name_key(name)] = {
            "email": email_match.group(1),
            "website": website_match.group(1) if website_match else None,
            "keywords": (
                []
                if not keywords_cell or keywords_cell == "Not yet provided"
                else [item.strip() for item in keywords_cell.split(";") if item.strip()]
            ),
            "project_ideas": [idea for idea in idea_cells if idea],
        }
    return interests


def _read_application_records(directory: Path) -> dict[str, list[dict[str, object]]]:
    records: dict[str, list[dict[str, object]]] = defaultdict(list)
    for path in sorted(directory.glob("*/application.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        application = payload.get("application")
        if not isinstance(application, dict) or not isinstance(application.get("name"), str):
            continue
        records[_name_key(application["name"])].append(payload)
    return records


def migrate_legacy_roster(
    *,
    accepted_path: Path,
    status_path: Path,
    interests_path: Path,
    applicant_directory: Path,
) -> CourseRoster:
    """One-time deterministic import of the three former hand-maintained sources."""
    accepted_payload = json.loads(accepted_path.read_text(encoding="utf-8"))
    status_payload = json.loads(status_path.read_text(encoding="utf-8"))
    accepted = accepted_payload.get("applicants")
    if not isinstance(accepted, list):
        raise ValueError("legacy accepted roster is invalid")
    active = {_name_key(item["name"]): item for item in status_payload.get("active_members", [])}
    inactive = {
        _name_key(item["name"]): item for item in status_payload.get("inactive_members", [])
    }
    interests = _parse_legacy_interests(interests_path)
    applications = _read_application_records(applicant_directory)
    resolution_path = applicant_directory / "student-access-resolution.json"
    resolutions: dict[str, str] = {}
    if resolution_path.is_file():
        resolution_payload = json.loads(resolution_path.read_text(encoding="utf-8"))
        for item in resolution_payload.get("applicants", []):
            ids = item.get("application_ids", [])
            if item.get("status") == "matched" and len(ids) == 1:
                resolutions[_name_key(item["name"])] = ids[0]

    members: list[CourseMember] = []
    for applicant in accepted:
        name = applicant["name"]
        key = _name_key(name)
        status = active.get(key) or inactive.get(key)
        if status is None:
            raise ValueError(f"accepted member lacks course status: {name}")
        is_active = key in active
        project_interest = interests.get(key, {})
        candidate_records = applications.get(key, [])
        resolved_id = resolutions.get(key)
        record = next(
            (
                item
                for item in candidate_records
                if resolved_id is not None and item.get("application_id") == resolved_id
            ),
            None,
        )
        if record is None and len(candidate_records) == 1:
            record = candidate_records[0]
        if record is None:
            raise ValueError(f"accepted member lacks one resolved application: {name}")
        application = record["application"]
        assert isinstance(application, dict)
        project_id = status.get("project_id") if is_active else status.get("former_project_id")
        website = status.get("website") if is_active else None
        if project_interest.get("website"):
            website = project_interest["website"]
            if project_id is None:
                project_match = _PROJECT_FROM_URL.search(str(website))
                if project_match:
                    project_id = f"agents2026-{project_match.group(1)}"
        enrollment_type = applicant.get("type")
        if enrollment_type not in {"credit", "listener"}:
            raise ValueError(f"accepted member lacks enrollment type: {name}")
        participation = status.get("participation") if is_active else None
        if participation is None:
            participation = (
                "weekly_build"
                if enrollment_type == "credit" or project_id is not None
                else "listener_only"
            )
        github_id = application.get("github_id")
        if not isinstance(github_id, str) or not github_id.strip():
            if isinstance(project_id, str):
                github_id = project_id.removeprefix("agents2026-")
            else:
                raise ValueError(f"accepted member lacks a username: {name}")
        github_id = github_id.strip().casefold()
        email = project_interest.get("email") or application.get("email")
        if not isinstance(email, str) or not email.strip():
            raise ValueError(f"accepted member lacks an email: {name}")
        account_username = email.split("@", 1)[0].casefold()
        student_id = (
            str(project_id).removeprefix("agents2026-")
            if project_id is not None
            else re.sub(r"[^a-z0-9]+", "-", name.casefold()).strip("-")
        )
        members.append(
            CourseMember(
                student_id=student_id,
                name=name,
                aliases=applicant.get("aliases", []),
                email=email,
                username=account_username,
                github_username=github_id,
                institution=applicant["institution"],
                department=applicant["department"],
                enrollment_type=enrollment_type,
                course_status="active" if is_active else "inactive",
                participation=participation,
                project_id=project_id,
                website=website,
                keywords=project_interest.get("keywords", []),
                project_ideas=project_interest.get("project_ideas", []),
                application_id=record.get("application_id"),
                inactive_reason=None if is_active else status.get("status"),
                departure_notice_received=(
                    None if is_active else status.get("departure_notice_received")
                ),
            )
        )
    return CourseRoster(
        schema_version=1,
        as_of=status_payload["as_of"],
        members=members,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate, migrate, and publish the course roster")
    subparsers = parser.add_subparsers(dest="command", required=True)
    migrate = subparsers.add_parser("migrate-legacy")
    migrate.add_argument("--accepted", type=Path, required=True)
    migrate.add_argument("--status", type=Path, required=True)
    migrate.add_argument("--interests", type=Path, required=True)
    migrate.add_argument("--applicants", type=Path, required=True)
    migrate.add_argument("--output", type=Path, required=True)
    migrate.add_argument("--course-data", type=Path, required=True)
    publish = subparsers.add_parser("publish")
    publish.add_argument("--roster", type=Path, required=True)
    publish.add_argument("--course-data", type=Path, required=True)
    arguments = parser.parse_args()

    if arguments.command == "migrate-legacy":
        roster = migrate_legacy_roster(
            accepted_path=arguments.accepted,
            status_path=arguments.status,
            interests_path=arguments.interests,
            applicant_directory=arguments.applicants,
        )
        write_course_roster(arguments.output, roster)
    else:
        loaded_roster = load_course_roster(arguments.roster)
        if loaded_roster is None:
            raise SystemExit("configured course roster does not exist")
        roster = loaded_roster
    publish_roster_resources(roster, arguments.course_data)


if __name__ == "__main__":
    main()
