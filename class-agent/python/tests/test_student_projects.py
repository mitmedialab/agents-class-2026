from __future__ import annotations

import asyncio
import base64
from typing import Literal
from uuid import uuid4

import httpx
import pytest
from pydantic import JsonValue

from agent_core import PrincipalContext
from course_server.agent import ToolExecutionContext, ToolValidationError
from course_server.student_projects import (
    GitHubStudentProjectCatalog,
    InspectStudentRepositoryTool,
    InspectStudentSiteTool,
    ListStudentProjectsTool,
    RepositoryView,
    StudentProject,
    StudentProjectNotFound,
)


def principal(role: Literal["student", "ta", "instructor", "admin"] | None) -> PrincipalContext:
    if role is None:
        session_id = uuid4()
        return PrincipalContext(
            authenticated=False,
            anonymous_session_id=session_id,
            roles=["public"],
            session_id=session_id,
        )
    return PrincipalContext(
        authenticated=True,
        user_id=uuid4(),
        username=f"test-{role}",
        roles=["public", role],
        session_id=uuid4(),
    )


def context(role: Literal["student", "ta", "instructor", "admin"] | None) -> ToolExecutionContext:
    return ToolExecutionContext(
        principal=principal(role),
        conversation_id=uuid4(),
        permitted_resource_uris=frozenset(),
    )


class FakeStudentProjects:
    def list_projects(self) -> list[StudentProject]:
        return [
            StudentProject("agents2026-ada", "https://ada.example.edu"),
            StudentProject("agents2026-grace", "https://grace.example.edu"),
        ]

    def inspect_repository(
        self,
        project_id: str,
        view: RepositoryView,
        *,
        path: str | None = None,
        ref: str | None = None,
    ) -> dict[str, JsonValue]:
        return {
            "project_id": project_id,
            "view": view,
            "path": path,
            "ref": ref,
            "provider": "github",
        }


def test_course_members_list_and_inspect_every_deployed_student_site() -> None:
    async def scenario() -> None:
        projects = FakeStudentProjects()
        listed = await ListStudentProjectsTool(projects).execute({}, context("instructor"))
        assert isinstance(listed.content, dict)
        listed_projects = listed.content["projects"]
        assert isinstance(listed_projects, list)
        grace = listed_projects[1]
        assert isinstance(grace, dict)
        assert listed.content["count"] == 2
        assert grace["site_url"] == "https://grace.example.edu"

        inspected = await InspectStudentSiteTool(
            projects,
            lambda url: {"url": url, "text": "Grace's deployed project", "images": []},
        ).execute({"project_id": "agents2026-grace"}, context("student"))
        assert isinstance(inspected.content, dict)
        page = inspected.content["page"]
        assert isinstance(page, dict)
        assert inspected.content["site_url"] == "https://grace.example.edu"
        assert page["text"] == "Grace's deployed project"
        assert "repository" not in inspected.content

    asyncio.run(scenario())


@pytest.mark.parametrize("role", [None])
def test_student_project_sites_reject_unauthorized_roles(
    role: None,
) -> None:
    async def scenario() -> None:
        with pytest.raises(ToolValidationError, match="course-member"):
            await ListStudentProjectsTool(FakeStudentProjects()).execute({}, context(role))

    asyncio.run(scenario())


def test_repository_inspection_requires_staff_and_validates_arguments() -> None:
    async def scenario() -> None:
        tool = InspectStudentRepositoryTool(FakeStudentProjects())
        with pytest.raises(ToolValidationError, match="TA, instructor, or admin"):
            await tool.execute(
                {"project_id": "agents2026-ada", "view": "summary"},
                context("student"),
            )
        result = await tool.execute(
            {
                "project_id": "agents2026-ada",
                "view": "file",
                "path": "src/App.tsx",
                "ref": "main",
            },
            context("instructor"),
        )
        assert isinstance(result.content, dict)
        assert result.content["path"] == "src/App.tsx"
        assert result.storage_policy == "server_summary"
        for role in ("ta", "admin"):
            staff_result = await tool.execute(
                {"project_id": "agents2026-ada", "view": "summary"},
                context(role),
            )
            assert isinstance(staff_result.content, dict)
            assert staff_result.content["view"] == "summary"

    asyncio.run(scenario())


def test_github_catalog_connects_to_real_api_shapes_and_excludes_test_repository() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.headers["authorization"] == "Bearer read-only-token"
        if request.url.path == "/orgs/mitmedialab/repos":
            return httpx.Response(
                200,
                json=[
                    {
                        "name": "agents2026-ada",
                        "homepage": "https://ada.example.edu",
                        "has_pages": False,
                    },
                    {
                        "name": "agents2026-grace",
                        "homepage": "",
                        "has_pages": True,
                    },
                    {"name": "agents2026-test", "homepage": "", "has_pages": False},
                    {"name": "unrelated", "homepage": "", "has_pages": False},
                ],
            )
        if request.url.path == "/repos/mitmedialab/agents2026-grace/pages":
            return httpx.Response(200, json={"html_url": "https://grace.example.edu"})
        if request.url.path == "/repos/mitmedialab/agents2026-ada":
            return httpx.Response(
                200,
                json={
                    "name": "agents2026-ada",
                    "default_branch": "main",
                    "description": "Course project",
                    "homepage": "https://ada.example.edu",
                    "language": "TypeScript",
                    "topics": ["agents"],
                    "archived": False,
                },
            )
        if request.url.path == "/repos/mitmedialab/agents2026-ada/contents/README.md":
            return httpx.Response(
                200,
                json={
                    "path": "README.md",
                    "size": 12,
                    "encoding": "base64",
                    "content": base64.b64encode(b"# Ada agent\n").decode(),
                },
            )
        raise AssertionError(f"unexpected request: {request.url}")

    catalog = GitHubStudentProjectCatalog(
        "read-only-token",
        organization="mitmedialab",
        repository_prefix="agents2026-",
        excluded_repositories=("agents2026-test",),
        transport=httpx.MockTransport(handler),
        sleep=lambda _: None,
    )

    assert catalog.list_projects() == [
        StudentProject("agents2026-ada", "https://ada.example.edu"),
        StudentProject("agents2026-grace", "https://grace.example.edu"),
    ]
    file_result = catalog.inspect_repository(
        "agents2026-ada",
        "file",
        path="README.md",
    )
    assert file_result["text"] == "# Ada agent\n"
    assert file_result["provider"] == "github"
    assert len(requests) == 4


def test_github_catalog_caches_only_the_project_roster_for_the_bounded_ttl() -> None:
    requests: list[httpx.Request] = []
    current_time = 100.0

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/orgs/mitmedialab/repos":
            return httpx.Response(
                200,
                json=[
                    {
                        "name": "agents2026-ada",
                        "homepage": "https://ada.example.edu",
                        "has_pages": False,
                    }
                ],
            )
        if request.url.path == "/repos/mitmedialab/agents2026-ada":
            return httpx.Response(
                200,
                json={"name": "agents2026-ada", "default_branch": "main"},
            )
        raise AssertionError(f"unexpected request: {request.url}")

    catalog = GitHubStudentProjectCatalog(
        "read-only-token",
        organization="mitmedialab",
        repository_prefix="agents2026-",
        roster_cache_ttl_seconds=60,
        transport=httpx.MockTransport(handler),
        sleep=lambda _: None,
        monotonic=lambda: current_time,
    )

    expected = [StudentProject("agents2026-ada", "https://ada.example.edu")]
    assert catalog.list_projects() == expected
    assert catalog.list_projects() == expected
    assert len(requests) == 1

    catalog.inspect_repository("agents2026-ada", "summary")
    catalog.inspect_repository("agents2026-ada", "summary")
    assert len(requests) == 3

    current_time += 60
    assert catalog.list_projects() == expected
    assert len(requests) == 4


def test_github_catalog_never_permits_other_org_repositories() -> None:
    catalog = GitHubStudentProjectCatalog(
        "read-only-token",
        organization="mitmedialab",
        repository_prefix="agents2026-",
        excluded_repositories=("agents2026-test",),
        transport=httpx.MockTransport(lambda _: httpx.Response(500)),
        sleep=lambda _: None,
    )

    with pytest.raises(StudentProjectNotFound, match="not found"):
        catalog.inspect_repository("agents-class-2026", "summary")
    with pytest.raises(StudentProjectNotFound, match="not found"):
        catalog.inspect_repository("agents2026-test", "summary")


def test_github_catalog_refuses_committed_credential_files_before_requesting_them() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/repos/mitmedialab/agents2026-ada":
            return httpx.Response(
                200,
                json={"name": "agents2026-ada", "default_branch": "main"},
            )
        raise AssertionError("credential path must not be requested")

    catalog = GitHubStudentProjectCatalog(
        "read-only-token",
        organization="mitmedialab",
        repository_prefix="agents2026-",
        transport=httpx.MockTransport(handler),
        sleep=lambda _: None,
    )

    with pytest.raises(StudentProjectNotFound, match="Credential"):
        catalog.inspect_repository("agents2026-ada", "file", path=".env")
