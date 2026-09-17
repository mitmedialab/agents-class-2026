"""Application sharing is an explicit UUID allowlist, independent of applicant claims."""

import json
from pathlib import Path
from typing import Literal
from uuid import uuid4

import pytest
from pydantic import JsonValue
from test_course_resources import authenticated_principal, public_principal, student_identity_policy

from course_server.application_access import ApplicationAccessPolicy


@pytest.mark.parametrize("role", ["ta", "admin"])
def test_nonstudent_roles_cannot_use_shared_applications(role: Literal["ta", "admin"]) -> None:
    for accepted_only in (False, True):
        with pytest.raises(PermissionError):
            ApplicationAccessPolicy().scope(
                authenticated_principal(role), accepted_only=accepted_only
            )


def test_registry_fails_closed_and_revocation_is_immediate(tmp_path: Path) -> None:
    path = tmp_path / "access.json"
    policy = ApplicationAccessPolicy(path)
    student = authenticated_principal("student")
    instructor = authenticated_principal("instructor")
    accepted = uuid4()
    assert policy.scope(student) == frozenset()
    with pytest.raises(PermissionError):
        policy.require(student, accepted)
    for accepted_only in (False, True):
        with pytest.raises(PermissionError):
            policy.scope(public_principal(), accepted_only=accepted_only)
    path.write_text(json.dumps({"schema_version": 1, "application_ids": [str(accepted)]}))
    policy.require(student, accepted)
    with pytest.raises(PermissionError):
        policy.require(student, uuid4())
    for malformed in [
        "invalid",
        "[]",
        '{"schema_version": 2, "application_ids": []}',
        '{"schema_version": 1, "application_ids": ["Ada Applicant"]}',
    ]:
        path.write_text(malformed)
        with pytest.raises(PermissionError):
            policy.require(student, accepted)
        assert policy.scope(instructor) is None
    path.unlink()
    with pytest.raises(PermissionError):
        policy.require(student, accepted)


def test_student_listing_never_enumerates_unshared_applications(tmp_path: Path) -> None:
    import asyncio
    from unittest.mock import AsyncMock

    from test_course_resources import execution_context

    from course_server.agent.capabilities import (
        ApplicantStore,
        InstructorListApplicationsTool,
        InstructorReadApplicationTool,
    )

    async def scenario() -> None:
        accepted, unshared = uuid4(), uuid4()
        path = tmp_path / "access.json"
        path.write_text(json.dumps({"schema_version": 1, "application_ids": [str(accepted)]}))
        store = AsyncMock(spec=ApplicantStore)
        # An unshared submission can claim the same name; its UUID still denies access.
        store.read_application.return_value = {
            "submitted_at": "2026-09-14T12:00:00Z",
            "application": {"name": "Same Name"},
        }
        access = ApplicationAccessPolicy(path)
        context = execution_context(principal=authenticated_principal("student"))
        result = await InstructorListApplicationsTool(
            store, access, student_identity_policy()
        ).execute({}, context)
        assert isinstance(result.content, list)
        assert len(result.content) == 1
        store.list_applications.assert_not_called()
        store.read_application.assert_awaited_once_with(accepted)
        with pytest.raises(PermissionError):
            await InstructorReadApplicationTool(store, access).execute(
                {"application_id": str(unshared)}, context
            )
        store.read_application.assert_awaited_once_with(accepted)

    asyncio.run(scenario())


def test_instructor_can_list_and_read_only_accepted_cohort(tmp_path: Path) -> None:
    import asyncio
    from unittest.mock import AsyncMock

    from test_application_roster import summary
    from test_course_resources import execution_context

    from course_server.agent.capabilities import (
        ApplicantStore,
        InstructorListApplicationsTool,
        InstructorReadApplicationTool,
    )

    async def scenario() -> None:
        records = [summary(f"Fictional Applicant {i}") for i in range(75)]
        accepted = records[:26]
        path = tmp_path / "student-access.json"
        path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "application_ids": [str(item.application_id) for item in accepted],
                }
            )
        )
        store = AsyncMock(spec=ApplicantStore)
        store.list_applications.return_value = records
        store.read_application.return_value = {
            "submitted_at": "2026-09-14T12:00:00Z",
            "application": {"name": "Fictional Applicant"},
        }
        policy = ApplicationAccessPolicy(path)
        listing = InstructorListApplicationsTool(store, policy, student_identity_policy())
        reading = InstructorReadApplicationTool(store, policy)
        instructor = execution_context(principal=authenticated_principal("instructor"))
        student = execution_context(principal=authenticated_principal("student"))
        filtered = await listing.execute({"accepted_only": True}, instructor)
        assert isinstance(filtered.content, list)
        assert len(filtered.content) == 26
        assert filtered.summary is not None
        assert "26 accepted" in filtered.summary
        assert filtered.storage_policy == "server_summary"
        store.list_applications.assert_not_called()
        assert {call.args[0] for call in store.read_application.await_args_list} == {
            item.application_id for item in accepted
        }
        assert (
            await listing.execute({"accepted_only": False}, student)
        ).content == filtered.content
        store.read_application.reset_mock()
        await reading.execute(
            {
                "application_id": str(accepted[0].application_id),
                "accepted_only": True,
            },
            instructor,
        )
        store.read_application.assert_awaited_once_with(accepted[0].application_id)
        for context in (instructor, student):
            with pytest.raises(PermissionError):
                await reading.execute(
                    {
                        "application_id": str(records[-1].application_id),
                        "accepted_only": True,
                    },
                    context,
                )
        store.read_application.assert_awaited_once_with(accepted[0].application_id)
        with pytest.raises(PermissionError):
            await reading.execute(
                {
                    "application_id": str(records[-1].application_id),
                    "accepted_only": False,
                },
                student,
            )
        await reading.execute({"application_id": str(records[-1].application_id)}, instructor)
        all_applications = await listing.execute({}, instructor)
        assert isinstance(all_applications.content, list)
        assert len(all_applications.content) == 75
        assert all_applications.summary is not None
        assert "75 private" in all_applications.summary

        # Filtered operations fail closed; instructor all-submission access remains intact.
        path.unlink()
        assert (await listing.execute({"accepted_only": True}, instructor)).content == []
        path.write_text("malformed")
        with pytest.raises(PermissionError):
            await listing.execute({"accepted_only": True}, instructor)
        with pytest.raises(PermissionError):
            await reading.execute(
                {
                    "application_id": str(accepted[0].application_id),
                    "accepted_only": True,
                },
                instructor,
            )
        assert (await listing.execute({}, instructor)).content == all_applications.content
        await reading.execute({"application_id": str(records[-1].application_id)}, instructor)

    asyncio.run(scenario())


@pytest.mark.parametrize("invalid", ["true", "false", 1, None, []])
def test_application_filter_rejects_non_boolean_arguments(invalid: JsonValue) -> None:
    import asyncio
    from unittest.mock import AsyncMock

    from test_course_resources import execution_context

    from course_server.agent.capabilities import (
        ApplicantStore,
        InstructorListApplicationsTool,
        InstructorReadApplicationTool,
        ToolValidationError,
    )

    async def scenario() -> None:
        store = AsyncMock(spec=ApplicantStore)
        context = execution_context(principal=authenticated_principal("instructor"))
        with pytest.raises(ToolValidationError, match="accepted_only must be a boolean"):
            await InstructorListApplicationsTool(store).execute(
                {"accepted_only": invalid},
                context,
            )
        with pytest.raises(ToolValidationError, match="accepted_only must be a boolean"):
            await InstructorReadApplicationTool(store).execute(
                {"accepted_only": invalid, "application_id": str(uuid4())},
                context,
            )
        store.list_applications.assert_not_called()
        store.read_application.assert_not_called()

    asyncio.run(scenario())
