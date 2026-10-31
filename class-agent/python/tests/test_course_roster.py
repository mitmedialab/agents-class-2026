from __future__ import annotations

import stat
from datetime import date
from pathlib import Path
from typing import Literal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from agent_core import PrincipalContext
from course_server.agent import FileResourceProvider
from course_server.course_roster import (
    CourseMember,
    CourseRoster,
    load_course_roster,
    publish_roster_resources,
    verify_roster_resources,
    write_course_roster,
)


def member(
    name: str,
    username: str,
    *,
    status: Literal["active", "inactive"] = "active",
    project_id: str | None = None,
) -> CourseMember:
    return CourseMember(
        student_id=username,
        name=name,
        aliases=[],
        email=f"{username}@example.edu",
        username=username,
        github_username=f"{username}-github",
        institution="Example University",
        department="Example Department",
        enrollment_type="credit",
        course_status=status,
        participation="weekly_build",
        project_id=project_id,
        website=(f"https://example.edu/{username}" if project_id else None),
        keywords=["agents"],
        project_ideas=[f"{name}'s project idea"],
        application_id=uuid4(),
        inactive_reason=("not_in_class" if status == "inactive" else None),
        departure_notice_received=(True if status == "inactive" else None),
    )


def principal(role: str) -> PrincipalContext:
    return PrincipalContext(
        authenticated=True,
        user_id=uuid4(),
        username=f"{role}-user",
        display_name=f"{role.title()} User",
        roles=["public", role],
        session_id=uuid4(),
    )


def test_roster_validates_identity_and_membership_invariants() -> None:
    active = member("Ada Example", "ada")
    with pytest.raises(ValidationError, match="inactive-state"):
        CourseMember.model_validate(active.model_dump() | {"inactive_reason": "left"})

    duplicate_username = member("Another Ada", "another").model_copy(update={"username": "ada"})
    with pytest.raises(ValidationError, match="duplicate username"):
        CourseRoster(
            schema_version=1,
            as_of=date(2026, 10, 26),
            members=[active, duplicate_username],
        )


def test_private_roster_publishes_active_student_and_complete_instructor_views(
    tmp_path: Path,
) -> None:
    roster = CourseRoster(
        schema_version=1,
        as_of=date(2026, 10, 26),
        members=[
            member("Ada Active", "ada", project_id="agents2026-ada"),
            member(
                "Ian Inactive",
                "ian",
                status="inactive",
                project_id="agents2026-ian",
            ),
        ],
    )
    roster_path = tmp_path / "private/course-members.json"
    data_path = tmp_path / "data"
    write_course_roster(roster_path, roster)
    publish_roster_resources(roster, data_path)
    verify_roster_resources(roster, data_path)

    loaded = load_course_roster(roster_path)
    assert loaded == roster
    assert stat.S_IMODE(roster_path.stat().st_mode) == 0o600

    catalog = FileResourceProvider.from_registry(protected_data_path=data_path)
    student_uris = catalog.authorized_resource_uris(principal("student"))
    instructor_uris = catalog.authorized_resource_uris(principal("instructor"))
    assert "course://students/roster" in student_uris
    assert "course://instructors/roster" not in student_uris
    assert "course://students/roster" in instructor_uris
    assert "course://instructors/roster" in instructor_uris

    student_text = (
        data_path / "students/final-project-interests/final-project-interests.md"
    ).read_text(encoding="utf-8")
    instructor_text = (data_path / "instructors/course-roster/course-roster.md").read_text(
        encoding="utf-8"
    )
    assert "Ada Active" in student_text
    assert "Ian Inactive" not in student_text
    assert "application_id" not in student_text
    assert "Ada Active" in instructor_text
    assert "Ian Inactive" in instructor_text
    assert "Course status: inactive" in instructor_text

    (data_path / "students/final-project-interests/final-project-interests.md").write_text("stale")
    with pytest.raises(ValueError, match="stale"):
        verify_roster_resources(roster, data_path)


def test_roster_derives_membership_and_project_boundaries() -> None:
    roster = CourseRoster(
        schema_version=1,
        as_of=date(2026, 10, 26),
        members=[
            member("Ada Active", "ada-login", project_id="agents2026-ada"),
            member(
                "Ian Inactive",
                "ian-login",
                status="inactive",
                project_id="agents2026-ian",
            ),
        ],
    )

    assert roster.permits_student_username("ADA-LOGIN")
    assert not roster.permits_student_username("ian-login")
    assert roster.identifies_inactive_username("IAN-LOGIN")
    assert roster.active_weekly_project_ids == frozenset({"agents2026-ada"})
    assert roster.active_student_project_aliases == {"ada-login": "agents2026-ada"}
