"""Deployment startup binds the accepted roster to local, immutable application IDs."""

import asyncio
import json
import stat
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import uuid4

from test_course_resources import authenticated_principal

from course_server.agent.capabilities import ApplicantStore, ApplicationSummary
from course_server.application_access import ApplicationAccessPolicy
from course_server.application_roster import (
    AcceptedRoster,
    initialize_student_application_access,
)


def write_roster(directory: Path) -> Path:
    # Entirely fictional fixture: tests must never depend on private deployment data.
    entries = [
        {"name": "Ada Example", "institution": "MIT", "department": "Example"},
        {"name": "Alex Sample", "institution": "MIT", "department": "Example"},
        {"name": "Morgan Sample", "institution": "MIT", "department": "Example"},
        {
            "name": "Robin (Rory) Example",
            "institution": "Harvard",
            "department": "Example",
            "aliases": ["Robin Example", "Rory Example"],
        },
        {"name": "Missing Example", "institution": "MIT", "department": "Example"},
        *[
            {"name": f"Fictional Applicant {number}", "institution": "MIT", "department": "Example"}
            for number in range(21)
        ],
    ]
    path = directory / "accepted-applicants.json"
    path.write_text(json.dumps({"schema_version": 1, "applicants": entries}))
    return path


def summary(name: str) -> ApplicationSummary:
    return ApplicationSummary(
        application_id=uuid4(), submitted_at=datetime.now(UTC), name=name, email="fake@example.org"
    )


def test_local_roster_resolves_once_on_server_and_never_approves_later_submissions(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        roster = AcceptedRoster.model_validate_json(write_roster(tmp_path).read_text())
        assert len(roster.applicants) == 26
        records = [summary(entry.name) for entry in roster.applicants]
        store = AsyncMock(spec=ApplicantStore)
        store.list_applications.return_value = [*records, summary("Unaccepted Person")]
        store.read_application.return_value = {"application": {}}
        await initialize_student_application_access(store, tmp_path)
        policy = ApplicationAccessPolicy(tmp_path / "student-access.json")
        ids = policy.scope(authenticated_principal("student"))
        assert ids == frozenset(record.application_id for record in records)
        assert stat.S_IMODE((tmp_path / "student-access.json").stat().st_mode) == 0o600
        report = json.loads((tmp_path / "student-access-resolution.json").read_text())
        assert all(item["status"] == "matched" for item in report["applicants"])

        # Later duplicate submissions cannot expand the frozen UUID authority.
        store.list_applications.return_value.append(summary(records[0].name))
        await initialize_student_application_access(store, tmp_path)
        store.list_applications.assert_awaited_once()
        assert policy.scope(authenticated_principal("student")) == ids

        # Explicit operator revocation persists across restart too.
        (tmp_path / "student-access.json").write_text(
            '{"schema_version": 1, "application_ids": []}'
        )
        await initialize_student_application_access(store, tmp_path)
        assert policy.scope(authenticated_principal("student")) == frozenset()

    asyncio.run(scenario())


def test_startup_blocks_ambiguous_missing_and_conflicting_records(tmp_path: Path) -> None:
    async def scenario() -> None:
        write_roster(tmp_path)
        store = AsyncMock(spec=ApplicantStore)
        robin = summary("  example ROBIN ")
        morgan = summary("Morgan Sample")
        wrong_school = summary("Ada Example")
        store.list_applications.return_value = [
            summary("Alex Sample"),
            summary("Sample Alex"),
            robin,
            morgan,
            wrong_school,
        ]

        async def read(application_id: object) -> dict[str, object]:
            school = "MIT Media Lab" if application_id == morgan.application_id else "Harvard"
            return {"application": {"school": school}}

        store.read_application.side_effect = read
        await initialize_student_application_access(store, tmp_path)
        policy = ApplicationAccessPolicy(tmp_path / "student-access.json")
        assert policy.scope(authenticated_principal("student")) == frozenset(
            {
                robin.application_id,
                morgan.application_id,
            }
        )
        report = json.loads((tmp_path / "student-access-resolution.json").read_text())
        statuses = {entry["name"]: entry["status"] for entry in report["applicants"]}
        assert statuses["Alex Sample"] == "ambiguous"
        assert statuses["Ada Example"] == "institution_mismatch"
        assert statuses["Missing Example"] == "missing"

    asyncio.run(scenario())


def test_empty_development_store_stays_closed_and_existing_registry_is_not_replaced(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        write_roster(tmp_path)
        store = AsyncMock(spec=ApplicantStore)
        store.list_applications.return_value = []
        await initialize_student_application_access(store, tmp_path)
        path = tmp_path / "student-access.json"
        assert json.loads(path.read_text())["application_ids"] == []
        path.write_text("malformed operator file")
        await initialize_student_application_access(store, tmp_path)
        assert path.read_text() == "malformed operator file"
        store.list_applications.assert_awaited_once()

    asyncio.run(scenario())


def test_bootstrap_reads_existing_file_applications_and_enables_student_tools(
    tmp_path: Path,
) -> None:
    from test_course_resources import execution_context, student_identity_policy

    from course_server.agent.capabilities import (
        FileApplicantStore,
        InstructorListApplicationsTool,
    )

    async def scenario() -> None:
        write_roster(tmp_path)
        accepted_id = uuid4()
        for application_id, name in [(accepted_id, "Ada Example"), (uuid4(), "Other Person")]:
            directory = tmp_path / f"20260901T120000Z_{application_id}"
            directory.mkdir()
            (directory / "application.json").write_text(
                json.dumps(
                    {
                        "schema_version": 2,
                        "application_id": str(application_id),
                        "submitted_at": "2026-09-01T12:00:00Z",
                        "application": {"name": name, "school": "MIT", "email": "fake@example.org"},
                    }
                )
            )
        store = FileApplicantStore(tmp_path)
        await initialize_student_application_access(store, tmp_path)
        policy = ApplicationAccessPolicy(tmp_path / "student-access.json")
        result = await InstructorListApplicationsTool(
            store, policy, student_identity_policy()
        ).execute({}, execution_context(principal=authenticated_principal("student")))
        assert isinstance(result.content, list)
        assert len(result.content) == 1
        assert isinstance(result.content[0], dict)
        assert result.content[0]["application_id"] == str(accepted_id)

    asyncio.run(scenario())


def test_absent_local_roster_does_not_initialize_or_read_applications(tmp_path: Path) -> None:
    async def scenario() -> None:
        store = AsyncMock(spec=ApplicantStore)
        await initialize_student_application_access(store, tmp_path)
        store.list_applications.assert_not_called()
        assert not (tmp_path / "student-access.json").exists()
        assert (
            ApplicationAccessPolicy(tmp_path / "student-access.json").scope(
                authenticated_principal("student")
            )
            == frozenset()
        )
        # Installing the private file later takes effect at the next startup.
        write_roster(tmp_path)
        store.list_applications.return_value = []
        await initialize_student_application_access(store, tmp_path)
        assert (tmp_path / "student-access.json").exists()

    asyncio.run(scenario())
