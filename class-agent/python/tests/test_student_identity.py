"""Self-exclusion follows the account email on every student listing, without a flag."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic import JsonValue
from test_course_resources import authenticated_principal, execution_context, public_principal
from test_student_projects import FakeStudentProjects

from agent_core import PrincipalContext
from course_server.agent.capabilities import (
    ApplicantStore,
    InstructorListApplicationsTool,
    InstructorReadApplicationTool,
    ToolValidationError,
)
from course_server.application_access import ApplicationAccessPolicy
from course_server.auth import AuthenticationService, InMemoryAuthStore, UserAdminService
from course_server.student_identity import StudentIdentityPolicy
from course_server.student_projects import InspectStudentSiteTool, ListStudentProjectsTool


async def login(auth: InMemoryAuthStore, username: str, email: str) -> PrincipalContext:
    issued = await UserAdminService(auth).create_user(
        username=username, display_name="Unrelated Display Name", email=email, role="student"
    )
    service = AuthenticationService(auth)
    session = await service.login(username=email, access_code=issued.access_code)
    return await service.resolve_authenticated(session.token)


def test_student_lists_automatically_exclude_all_own_applications_and_website(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        auth = InMemoryAuthStore()
        # Neither username nor display name identifies the applicant: use the stored email.
        ada = await login(auth, "unrelated-alias", "ada@example.org")
        grace = await login(auth, "another-alias", "grace@example.org")
        own, duplicate, peer, unshared = (uuid4() for _ in range(4))
        records: dict[object, dict[str, JsonValue]] = {
            own: {"application": {"name": "Ada Owner", "email": " ADA@EXAMPLE.ORG "}},
            duplicate: {"application": {"name": "Ada Duplicate", "email": "ada@example.org"}},
            peer: {"application": {"name": "Grace Peer", "email": "grace@example.org"}},
            unshared: {"application": {"name": "Ada Impersonator", "email": "ada@example.org"}},
        }
        for record in records.values():
            record["submitted_at"] = "2026-09-17T12:00:00Z"
        store = AsyncMock(spec=ApplicantStore)
        store.read_application.side_effect = lambda application_id: records[application_id]
        path = tmp_path / "student-access.json"
        path.write_text(
            json.dumps(
                {"schema_version": 1, "application_ids": [str(own), str(duplicate), str(peer)]}
            )
        )
        access = ApplicationAccessPolicy(path)
        identities = StudentIdentityPolicy(
            auth, applicants=store, access=access, repository_prefix="agents2026-"
        )
        listing = InstructorListApplicationsTool(store, access, identities)
        sites = ListStudentProjectsTool(FakeStudentProjects(), identities)
        ctx = execution_context(principal=ada)
        for arguments in ({}, {"accepted_only": False}, {"accepted_only": True}):
            result = await listing.execute(arguments, ctx)
            assert isinstance(result.content, list)
            assert len(result.content) == 1
            assert isinstance(result.content[0], dict)
            assert result.content[0]["application_id"] == str(peer)
        site_result = await sites.execute({}, ctx)
        assert isinstance(site_result.content, dict)
        assert site_result.content["projects"] == [
            {"project_id": "agents2026-grace", "site_url": "https://grace.example.edu"}
        ]
        assert site_result.content["count"] == 1
        # One shared provider roster is filtered separately for each authenticated account.
        grace_result = await sites.execute({}, execution_context(principal=grace))
        assert isinstance(grace_result.content, dict)
        assert grace_result.content["projects"] == [
            {"project_id": "agents2026-ada", "site_url": "https://ada.example.edu"}
        ]
        assert not (tmp_path / "student-identities.json").exists()
        store.list_applications.assert_not_called()
        assert unshared not in {call.args[0] for call in store.read_application.await_args_list}
        # There is no optional matching flag, requester ID, or email override to bypass exclusion.
        bypasses: list[dict[str, JsonValue]] = [
            {"for_matching": False},
            {"include_self": True},
            {"user_id": str(grace.user_id)},
            {"email": "grace@example.org"},
        ]
        for tool in (listing, sites):
            for bypass in bypasses:
                with pytest.raises((ToolValidationError, ValueError)):
                    await tool.execute(bypass, ctx)
        own_read = InstructorReadApplicationTool(store, access, identities)
        # Duplicate matching records are all excluded; selecting a personal profile is explicit.
        with pytest.raises(PermissionError, match="exactly one"):
            await own_read.execute({}, ctx)
        path.write_text(json.dumps({"schema_version": 1, "application_ids": [str(own), str(peer)]}))
        personal_profile = await own_read.execute({}, ctx)
        assert isinstance(personal_profile.content, dict)
        assert personal_profile.content["application"] == records[own]["application"]
        with pytest.raises(PermissionError):
            await own_read.execute(
                {}, execution_context(principal=authenticated_principal("instructor"))
            )
        # Explicit reads of one's own work remain authorized; lists are peer candidates.
        await InstructorReadApplicationTool(store, access).execute(
            {"application_id": str(own)}, ctx
        )
        own_site = await InspectStudentSiteTool(
            FakeStudentProjects(), lambda url: {"url": url, "text": "Own project"}
        ).execute({"project_id": "agents2026-ada"}, ctx)
        assert isinstance(own_site.content, dict)
        assert own_site.content["site_url"] == "https://ada.example.edu"
        # Staff browsing continues to include the full course project roster.
        staff = await sites.execute(
            {}, execution_context(principal=authenticated_principal("instructor"))
        )
        assert isinstance(staff.content, dict)
        assert staff.content["count"] == 2
        # Missing/deactivated accounts cannot fall back to an unfiltered list.
        assert ada.user_id is not None
        auth.users[ada.user_id] = auth.users[ada.user_id].model_copy(update={"active": False})
        for tool in (listing, sites):
            with pytest.raises(PermissionError, match="active student"):
                await tool.execute({}, ctx)

    asyncio.run(scenario())


def test_website_names_require_accepted_email_identity_and_omit_ambiguity(tmp_path: Path) -> None:
    async def scenario() -> None:
        auth = InMemoryAuthStore()
        principal = await login(auth, "owner", "ada@example.org")
        ids = [uuid4() for _ in range(4)]
        fields = [
            {"name": "Ada Owner", "email": "ada@example.org"},
            {"name": "Grace One", "email": "grace-one@example.org"},
            {"name": "Grace Two", "email": "grace-two@example.org"},
            {"name": "Eitan Peer", "email": "eitan@example.org"},
        ]
        records = dict(zip(ids, fields, strict=True))
        store = AsyncMock(spec=ApplicantStore)
        store.read_application.side_effect = lambda key: {"application": records[key]}
        path = tmp_path / "student-access.json"
        path.write_text(json.dumps({"schema_version": 1, "application_ids": list(map(str, ids))}))
        policy = StudentIdentityPolicy(
            auth,
            applicants=store,
            access=ApplicationAccessPolicy(path),
            repository_prefix="course-",
        )
        assert await policy.project_candidates(principal) == frozenset({"course-eitan"})
        # A first-name collision with the requester cannot bring their website back.
        records[ids[3]] = {"name": "Ada Other", "email": "different@example.org"}
        assert await policy.project_candidates(principal) == frozenset()
        records[ids[0]] = {"name": "Ada Owner", "email": "wrong@example.org"}
        with pytest.raises(PermissionError, match="login email does not match"):
            await policy.project_candidates(principal)
        path.write_text("invalid")
        with pytest.raises(PermissionError):
            await policy.project_candidates(principal)
        path.unlink()
        assert await policy.project_candidates(principal) == frozenset()
        for denied in (public_principal(), authenticated_principal("instructor")):
            with pytest.raises(PermissionError):
                await policy.email(denied)
        with pytest.raises(PermissionError):
            await StudentIdentityPolicy().email(principal)
        unknown = principal.model_copy(update={"user_id": uuid4()})
        with pytest.raises(PermissionError):
            await policy.email(unknown)

    asyncio.run(scenario())
