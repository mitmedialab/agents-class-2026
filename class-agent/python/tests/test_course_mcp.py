from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import re
from datetime import UTC, date, datetime, timedelta
from html import unescape
from pathlib import Path
from urllib.parse import parse_qs, parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import uuid4

import httpx
import psycopg
import pytest
from mcp.server.transport_security import TransportSecurityMiddleware
from psycopg import sql
from pydantic import JsonValue
from starlette.requests import Request

from agent_core import PrincipalContext
from course_server.agent import FileResourceProvider, ResourceDefinition
from course_server.assignments import AssignmentDraft, FileAssignmentStore
from course_server.auth import AuthenticationService, InMemoryAuthStore, UserAdminService
from course_server.config import ConfigurationError
from course_server.course_roster import CourseMember, CourseRoster
from course_server.mcp_oauth import (
    CourseOAuthProvider,
    _chatgpt_redirect,
    _course_client_redirect,
    _google_redirect,
)
from course_server.mcp_projects import CourseMcpProjectService
from course_server.mcp_resources import CourseMcpResourceService
from course_server.mcp_server import (
    CourseMcpSettings,
    _mcp_transport_security,
    create_course_mcp_app,
)
from course_server.mcp_usage import usage_summary
from course_server.postgres.auth_store import PostgresAuthStore, create_auth_pool
from course_server.student_projects import RepositoryView, StudentProject, StudentProjectNotFound

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
BASE_URL = "http://127.0.0.1:8001"


def _assert_resource_open_link(url: str, resource_uri: str) -> None:
    parsed = urlsplit(url)
    assert parsed.scheme == "http"
    assert parsed.netloc == "127.0.0.1:8001"
    assert parsed.path == "/"
    assert parse_qs(parsed.query) == {
        "q": [f"Open the original course resource {resource_uri} in the website workspace"]
    }


def test_mcp_transport_accepts_public_proxy_host_and_rejects_others() -> None:
    security = TransportSecurityMiddleware(_mcp_transport_security("https://course.example", 8001))

    async def check(host: str, origin: str | None = None) -> int | None:
        headers = [(b"host", host.encode()), (b"content-type", b"application/json")]
        if origin is not None:
            headers.append((b"origin", origin.encode()))
        request = Request({"type": "http", "method": "POST", "headers": headers})
        response = await security.validate_request(request, is_post=True)
        return response.status_code if response is not None else None

    assert asyncio.run(check("course.example")) is None
    assert asyncio.run(check("127.0.0.1:8001")) is None
    assert asyncio.run(check("course.example", "https://course.example")) is None
    assert asyncio.run(check("attacker.example")) == 421
    assert asyncio.run(check("course.example", "https://attacker.example")) == 403


def _schema_url(database_url: str, schema_name: str) -> str:
    parsed = urlsplit(database_url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query["options"] = f"-csearch_path={schema_name}"
    return urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, urlencode(query), parsed.fragment)
    )


def _approved_callback(response: httpx.Response) -> str:
    match = re.search(r'<a id="continue-connection" href="([^"]+)"', response.text)
    assert match is not None
    return unescape(match.group(1))


def _roster_member(username: str) -> CourseMember:
    return CourseMember(
        student_id=username,
        name=username.title(),
        email=f"{username}@example.edu",
        username=username,
        github_username=f"{username}-github",
        institution="Example University",
        department="Example Department",
        enrollment_type="credit",
        course_status="active",
        participation="listener_only",
    )


def test_chatgpt_redirect_allowlist_and_settings() -> None:
    assert _chatgpt_redirect("https://chatgpt.com/connector_platform_oauth_redirect")
    assert _chatgpt_redirect("https://chatgpt.com/connector/oauth/abc-123")
    assert not _chatgpt_redirect("https://evil.example/connector/oauth/abc")
    assert not _chatgpt_redirect("https://chatgpt.com.evil.example/connector/oauth/abc")
    assert not _chatgpt_redirect("https://chatgpt.com/connector/oauth/abc?next=evil")
    gemini_callback = "https://oauth-redirect.googleusercontent.com/r/course-app-example"
    assert _google_redirect(gemini_callback)
    assert _course_client_redirect("https://claude.ai/api/mcp/auth_callback", frozenset())
    assert _course_client_redirect(gemini_callback, frozenset({gemini_callback}))
    assert not _course_client_redirect(gemini_callback, frozenset())
    assert not _course_client_redirect(
        "https://oauth-redirect.googleusercontent.com/r/another-app",
        frozenset({gemini_callback}),
    )
    assert not _google_redirect("https://oauth-redirect.googleusercontent.com.evil/r/app")
    assert not _google_redirect("https://oauth-redirect.googleusercontent.com/r/app?next=evil")
    assert not _course_client_redirect("https://attacker.example/callback", frozenset())
    with pytest.raises(ValueError, match="HTTPS"):
        CourseMcpSettings(
            database_url="postgresql://example",
            public_base_url="http://course.example",
            assignment_data_path=Path("/tmp/assignments"),
            course_roster_path=Path("/tmp/roster"),
        )
    with pytest.raises(ValueError, match="MCP_RELEASE"):
        CourseMcpSettings(
            database_url="postgresql://example",
            public_base_url=BASE_URL,
            assignment_data_path=Path("/tmp/assignments"),
            course_roster_path=Path("/tmp/roster"),
            release="invalid release with spaces",
        )
    provider = CourseOAuthProvider(
        create_auth_pool("postgresql://unused/unused"),
        InMemoryAuthStore(),
        public_base_url=BASE_URL,
        roster=None,
        messaging_enabled=True,
    )
    assert provider._allowed_scopes(["course:read", "course:message_drafts"])
    assert provider._allowed_scopes(["course:read"])
    assert not provider._allowed_scopes(["course:message_drafts"])
    assert not provider._allowed_scopes(["course:read", "course:read"])
    with pytest.raises(ValueError, match="exact Google callback"):
        CourseOAuthProvider(
            create_auth_pool("postgresql://unused/unused"),
            InMemoryAuthStore(),
            public_base_url=BASE_URL,
            roster=None,
            gemini_redirect_uris=("https://attacker.example/callback",),
        )
    parsed_settings = CourseMcpSettings.from_environment(
        {
            "DATABASE_URL": "postgresql://unused/unused",
            "MCP_PUBLIC_BASE_URL": BASE_URL,
            "MCP_GEMINI_OAUTH_REDIRECT_URIS": gemini_callback,
            "GITHUB_STUDENT_PROJECT_ALIASES": "test-student2=agents2026-student",
        }
    )
    assert parsed_settings.gemini_redirect_uris == (gemini_callback,)
    assert parsed_settings.github_student_project_aliases == (
        ("test-student2", "agents2026-student"),
    )
    with pytest.raises(ConfigurationError, match="GITHUB_STUDENT_PROJECT_ALIASES"):
        CourseMcpSettings.from_environment(
            {
                "DATABASE_URL": "postgresql://unused/unused",
                "MCP_PUBLIC_BASE_URL": BASE_URL,
                "GITHUB_STUDENT_PROJECT_ALIASES": "test-student2=agents2026-test",
            }
        )


def test_access_code_reset_invalidates_prior_mcp_grants() -> None:
    async def scenario() -> None:
        store = InMemoryAuthStore()
        created_at = datetime(2026, 10, 1, tzinfo=UTC)
        admin = UserAdminService(store, clock=lambda: created_at)
        student = await admin.create_user(
            username="student",
            display_name="Student",
            email="student@example.edu",
            role="student",
        )
        provider = CourseOAuthProvider(
            create_auth_pool("postgresql://unused/unused"),
            store,
            public_base_url=BASE_URL,
            roster=None,
        )
        grant_created_at = created_at + timedelta(seconds=1)
        assert (
            await provider._active_student(student.user.id, credential_created_at=grant_created_at)
            is not None
        )
        reset_admin = UserAdminService(store, clock=lambda: created_at + timedelta(seconds=2))
        await reset_admin.reset_user_code("student")
        assert (
            await provider._active_student(student.user.id, credential_created_at=grant_created_at)
            is None
        )

    asyncio.run(scenario())


def test_course_resources_follow_student_visibility(tmp_path: Path) -> None:
    async def scenario() -> None:
        definitions = []
        for name, visibility in (
            ("public", "public"),
            ("student", "students"),
            ("instructor", "instructors"),
        ):
            path = tmp_path / f"{name}.md"
            path.write_text(f"# {name}\n\n{name} access marker", encoding="utf-8")
            definitions.append(
                ResourceDefinition(
                    uri=f"course://{name}",
                    title=name,
                    media_type="text/markdown",
                    path=path,
                    visibility=visibility,  # type: ignore[arg-type]
                    assets={"pdf": tmp_path / "public.pdf"} if name == "public" else {},
                )
            )
        service = CourseMcpResourceService(
            FileResourceProvider(definitions), public_base_url=BASE_URL
        )
        student = PrincipalContext(
            authenticated=True,
            user_id=uuid4(),
            username="student",
            roles=["public", "student"],
            session_id=uuid4(),
        )
        listed = service.list_resources(student)
        assert {item["uri"] for item in listed} == {"course://public", "course://student"}
        for item in listed:
            _assert_resource_open_link(item["open_in_course_agent_url"], item["uri"])
            assert "source_url" not in item
        result = await service.read_resource(student, "course://student", max_chars=10)
        assert result["next_offset"] == 10
        assert result["total_chars"] > len(result["text"])
        assert result["text_representation"] == "course_text"
        assert result["returned_text_is_complete"] is False
        _assert_resource_open_link(result["open_in_course_agent_url"], "course://student")
        assert "source_url" not in result
        public_read = await service.read_resource(student, "course://public")
        assert public_read["returned_text_is_complete"] is True
        assert public_read["assets"] == {"pdf": "application/pdf"}
        assert "asset_urls" not in public_read
        matches = await service.search_resources(student, "marker")
        assert {item["uri"] for item in matches} == {"course://public", "course://student"}
        for item in matches:
            _assert_resource_open_link(item["open_in_course_agent_url"], item["uri"])
            assert "source_url" not in item
        with pytest.raises(ValueError, match="unavailable"):
            await service.read_resource(student, "course://instructor")
        anonymous = PrincipalContext(
            authenticated=False,
            anonymous_session_id=uuid4(),
            roles=["public"],
            session_id=uuid4(),
        )
        with pytest.raises(PermissionError):
            service.list_resources(anonymous)

    asyncio.run(scenario())


def test_project_inspection_is_scoped_to_student_identity(tmp_path: Path) -> None:
    class FakeProjects:
        def list_projects(self) -> list[StudentProject]:
            return [
                StudentProject("agents2026-student", "https://student.example.edu"),
                StudentProject("agents2026-other", "https://other.example.edu"),
            ]

        def inspect_repository(
            self,
            project_id: str,
            view: RepositoryView,
            *,
            path: str | None = None,
            ref: str | None = None,
        ) -> dict[str, JsonValue]:
            if project_id not in {"agents2026-student", "agents2026-other"}:
                raise StudentProjectNotFound("Unknown project")
            return {"project_id": project_id, "view": view, "path": path, "ref": ref}

    async def scenario() -> None:
        service = CourseMcpProjectService(
            FakeProjects(),
            lambda url: {"url": url, "text": "Live site", "images": []},
            repository_prefix="agents2026-",
        )
        student = PrincipalContext(
            authenticated=True,
            user_id=uuid4(),
            username="student",
            roles=["public", "student"],
            session_id=uuid4(),
        )
        own = await service.inspect_my_repository(student, "file", path="src/App.tsx")
        assert own["project_id"] == "agents2026-student"
        assert own["path"] == "src/App.tsx"
        own_site = await service.inspect_my_site(student)
        assert own_site["site_url"] == "https://student.example.edu"
        other_site = await service.inspect_site(student, "agents2026-other")
        assert other_site["site_url"] == "https://other.example.edu"
        listed = await service.list_projects(student)
        assert listed["count"] == 2
        with pytest.raises(ValueError, match="view"):
            await service.inspect_my_repository(student, "secrets")
        anonymous = PrincipalContext(
            authenticated=False,
            anonymous_session_id=uuid4(),
            roles=["public"],
            session_id=uuid4(),
        )
        with pytest.raises(PermissionError):
            await service.inspect_my_repository(anonymous, "summary")

        app = create_course_mcp_app(
            CourseMcpSettings(
                database_url="postgresql://unused/unused",
                public_base_url=BASE_URL,
                assignment_data_path=tmp_path / "assignments",
                course_roster_path=tmp_path / "roster.json",
                course_data_path=tmp_path / "data",
                published_faq_path=tmp_path / "faq.json",
                github_student_project_aliases=(("test-student2", "agents2026-student"),),
            ),
            student_projects=FakeProjects(),
        )
        tools_by_name = {tool.name: tool for tool in await app.state.course_mcp.list_tools()}
        tool_names = set(tools_by_name)
        assert {
            "list_student_projects",
            "inspect_student_site",
            "inspect_my_student_site",
            "inspect_my_student_repository",
        } <= tool_names
        assert "assignment implementation code" in (
            tools_by_name["inspect_my_student_repository"].description or ""
        )
        for name in ("inspect_student_site", "inspect_my_student_site"):
            description = tools_by_name[name].description or ""
            assert "documentation website" in description
            assert "weekly" in description
            assert "final-project" in description
        test_student = student.model_copy(update={"username": "test-student2"})
        aliased = await app.state.course_projects.inspect_my_repository(test_student, "summary")
        assert aliased["project_id"] == "agents2026-student"

    asyncio.run(scenario())


@pytest.mark.postgres
@pytest.mark.skipif(TEST_DATABASE_URL is None, reason="TEST_DATABASE_URL is not configured")
def test_course_mcp_login_assignment_instruction_and_ownership(tmp_path: Path) -> None:
    assert TEST_DATABASE_URL is not None
    schema_name = f"test_mcp_{uuid4().hex}"
    with psycopg.connect(TEST_DATABASE_URL) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema_name)))
    database_url = _schema_url(TEST_DATABASE_URL, schema_name)

    async def scenario() -> None:
        pool = create_auth_pool(database_url)
        await pool.open()
        try:
            settings = CourseMcpSettings(
                database_url=database_url,
                public_base_url=BASE_URL,
                assignment_data_path=tmp_path / "assignments",
                course_roster_path=tmp_path / "missing-roster.json",
                course_data_path=tmp_path / "course-data",
                published_faq_path=tmp_path / "published-faq.json",
                messaging_enabled=True,
                mail_enabled=True,
                gemini_redirect_uris=(
                    "https://oauth-redirect.googleusercontent.com/r/course-app-example",
                ),
            )
            roster = CourseRoster(
                schema_version=1,
                as_of=date(2026, 10, 30),
                members=[_roster_member("student"), _roster_member("other")],
            )
            app = create_course_mcp_app(settings, pool=pool, roster=roster)
            async with app.router.lifespan_context(app):
                admin = UserAdminService(PostgresAuthStore(pool))
                student = await admin.create_user(
                    username="student",
                    display_name="Student Example",
                    email="student@example.edu",
                    role="student",
                )
                author = await admin.create_user(
                    username="author",
                    display_name="Course Author",
                    email="author@example.edu",
                    role="instructor",
                )
                other = await admin.create_user(
                    username="other",
                    display_name="Other Student",
                    email="other@example.edu",
                    role="student",
                )
                own_message_id = uuid4()
                other_message_id = uuid4()
                async with pool.connection() as connection:
                    for message_id, recipient_id, subject in (
                        (own_message_id, student.user.id, "Your private feedback"),
                        (other_message_id, other.user.id, "Other student's secret"),
                    ):
                        conversation_id = uuid4()
                        await connection.execute(
                            "INSERT INTO conversations (id, user_id, created_at, updated_at) "
                            "VALUES (%s, %s, now(), now())",
                            (conversation_id, author.user.id),
                        )
                        await connection.execute(
                            """INSERT INTO instructor_messages (
                                id, conversation_id, sender_user_id, audience, subject,
                                body, status, created_at, sent_at
                            ) VALUES (%s, %s, %s, 'specific_students', %s, %s,
                                      'sent', now(), now())""",
                            (message_id, conversation_id, author.user.id, subject, subject),
                        )
                        await connection.execute(
                            "INSERT INTO instructor_message_recipients "
                            "(message_id, student_user_id) VALUES (%s, %s)",
                            (message_id, recipient_id),
                        )
                assignments = FileAssignmentStore(tmp_path / "assignments")
                now = datetime.now(UTC)
                released = await assignments.create(
                    AssignmentDraft(
                        title="Build an agent",
                        content_markdown="# Build an agent\n\nExplain your own design.",
                        release_at=now - timedelta(days=1),
                        due_at=now + timedelta(days=7),
                        publish=True,
                    ),
                    created_by_user_id=author.user.id,
                )
                hidden = await assignments.create(
                    AssignmentDraft(
                        title="Hidden draft",
                        content_markdown="# Hidden draft",
                        release_at=now + timedelta(days=1),
                        due_at=now + timedelta(days=8),
                        publish=False,
                    ),
                    created_by_user_id=author.user.id,
                )
                transport = httpx.ASGITransport(app=app)
                async with httpx.AsyncClient(
                    transport=transport, base_url=BASE_URL, follow_redirects=False
                ) as client:
                    metadata = await client.get("/.well-known/oauth-protected-resource/mcp")
                    assert metadata.status_code == 200
                    assert metadata.json()["resource"] == f"{BASE_URL}/mcp"
                    unauthenticated = await client.post("/mcp", json={})
                    assert unauthenticated.status_code == 401
                    learning_contract = await client.get("/learning-contract")
                    assert learning_contract.status_code == 200
                    assert "Never write or rewrite" in learning_contract.text
                    source = await client.get("/learning-contract.md")
                    assert source.status_code == 200
                    assert source.headers["content-type"].startswith("text/markdown")
                    source_instruction = " ".join(source.text.split())
                    assert "Never write or rewrite" in source_instruction
                    assert "read `course://schedule`" in source_instruction
                    assert "Do not invent a replacement diagram" in source_instruction
                    assert '"just pick" for them' in source_instruction
                    setup = await client.get("/ai-connect")
                    assert setup.status_code == 200
                    assert f"{BASE_URL}/mcp" in setup.text
                    assert "https://chatgpt.com/plugins" in setup.text
                    assert "Install the Course Agent MCP" in setup.text
                    assert 'href="/learning-contract"' in setup.text
                    assert '<main id="main" class="connect-main">' in setup.text
                    assert 'src="/mit-logo.svg"' in setup.text
                    assert "{{MCP_ENDPOINT}}" not in setup.text
                    css = await client.get("/mcp-pages.css")
                    assert css.status_code == 200
                    assert css.headers["content-type"].startswith("text/css")

                    claude_registration = await client.post(
                        "/register",
                        json={
                            "redirect_uris": ["https://claude.ai/api/mcp/auth_callback"],
                            "token_endpoint_auth_method": "none",
                            "grant_types": ["authorization_code", "refresh_token"],
                            "response_types": ["code"],
                            "scope": "course:read",
                        },
                    )
                    assert claude_registration.status_code == 201, claude_registration.text
                    gemini_registration = await client.post(
                        "/register",
                        json={
                            "redirect_uris": [
                                "https://oauth-redirect.googleusercontent.com/r/course-app-example"
                            ],
                            "token_endpoint_auth_method": "none",
                            "grant_types": ["authorization_code", "refresh_token"],
                            "response_types": ["code"],
                            "scope": "course:read",
                        },
                    )
                    assert gemini_registration.status_code == 201, gemini_registration.text
                    unapproved_registration = await client.post(
                        "/register",
                        json={
                            "redirect_uris": [
                                "https://oauth-redirect.googleusercontent.com/r/another-app"
                            ],
                            "token_endpoint_auth_method": "none",
                            "grant_types": ["authorization_code", "refresh_token"],
                            "response_types": ["code"],
                            "scope": "course:read",
                        },
                    )
                    assert unapproved_registration.status_code == 400

                    registered = await client.post(
                        "/register",
                        json={
                            "redirect_uris": ["https://chatgpt.com/connector/oauth/test-123"],
                            "token_endpoint_auth_method": "client_secret_post",
                            "grant_types": ["authorization_code", "refresh_token"],
                            "response_types": ["code"],
                            "scope": "course:read",
                        },
                    )
                    assert registered.status_code == 201, registered.text
                    client_info = registered.json()
                    verifier = "course-mcp-test-verifier-01234567890123456789"
                    challenge = (
                        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
                        .decode()
                        .rstrip("=")
                    )
                    authorized = await client.get(
                        "/authorize",
                        params={
                            "client_id": client_info["client_id"],
                            "redirect_uri": "https://chatgpt.com/connector/oauth/test-123",
                            "response_type": "code",
                            "code_challenge": challenge,
                            "code_challenge_method": "S256",
                            "state": "opaque-state",
                            "scope": "course:read",
                            "resource": f"{BASE_URL}/mcp",
                        },
                    )
                    assert authorized.status_code == 302, authorized.text
                    connect_path = authorized.headers["location"]
                    page = await client.get(connect_path)
                    assert page.status_code == 200
                    assert "Course access code" in page.text
                    assert "/learning-contract" in page.text
                    request_token = parse_qs(urlsplit(connect_path).query)["request"][0]
                    wrong_role = await client.post(
                        "/connect",
                        headers={"Origin": BASE_URL},
                        data={
                            "request": request_token,
                            "username": "author",
                            "access_code": author.access_code,
                        },
                    )
                    assert wrong_role.status_code == 403
                    cross_site = await client.post(
                        "/connect",
                        headers={"Origin": "null", "Sec-Fetch-Site": "cross-site"},
                        data={
                            "request": request_token,
                            "username": "student",
                            "access_code": student.access_code,
                        },
                    )
                    assert cross_site.status_code == 400
                    approved = await client.post(
                        "/connect",
                        headers={"Origin": "null", "Sec-Fetch-Site": "same-origin"},
                        data={
                            "request": request_token,
                            "username": "student",
                            "access_code": student.access_code,
                        },
                    )
                    assert approved.status_code == 200, approved.text
                    assert 'http-equiv="refresh"' in approved.text
                    assert approved.headers["cache-control"] == "no-store"
                    callback = _approved_callback(approved)
                    assert callback.startswith("https://chatgpt.com/")
                    code = parse_qs(urlsplit(callback).query)["code"][0]
                    tokens = await client.post(
                        "/token",
                        data={
                            "grant_type": "authorization_code",
                            "client_id": client_info["client_id"],
                            "client_secret": client_info["client_secret"],
                            "code": code,
                            "code_verifier": verifier,
                            "redirect_uri": "https://chatgpt.com/connector/oauth/test-123",
                            "resource": f"{BASE_URL}/mcp",
                        },
                    )
                    assert tokens.status_code == 200, tokens.text
                    access = tokens.json()["access_token"]
                    replay = await client.post(
                        "/token",
                        data={
                            "grant_type": "authorization_code",
                            "client_id": client_info["client_id"],
                            "client_secret": client_info["client_secret"],
                            "code": code,
                            "code_verifier": verifier,
                            "redirect_uri": "https://chatgpt.com/connector/oauth/test-123",
                        },
                    )
                    assert replay.status_code == 400
                    headers = {
                        "Authorization": f"Bearer {access}",
                        "Accept": "application/json, text/event-stream",
                    }
                    initialized = await client.post(
                        "/mcp",
                        headers=headers,
                        json={
                            "jsonrpc": "2.0",
                            "id": 1,
                            "method": "initialize",
                            "params": {
                                "protocolVersion": "2025-11-25",
                                "capabilities": {},
                                "clientInfo": {"name": "test", "version": "1"},
                            },
                        },
                    )
                    assert initialized.status_code == 200, initialized.text
                    assert "Never write or rewrite the student's" in initialized.text
                    assert "read course://schedule" in initialized.text
                    assert "Never choose the student's" in initialized.text
                    tool_catalog = await client.post(
                        "/mcp",
                        headers=headers,
                        json={"jsonrpc": "2.0", "id": 12, "method": "tools/list"},
                    )
                    assert tool_catalog.status_code == 200, tool_catalog.text
                    assert "get_my_assignment" in tool_catalog.text
                    assert "record_my_self_check" not in tool_catalog.text
                    assert "list_course_resources" in tool_catalog.text
                    assert "list_my_course_updates" in tool_catalog.text
                    assert "prepare_course_message" in tool_catalog.text
                    assert "inspect_my_student_repository" not in tool_catalog.text
                    unscoped_message = await client.post(
                        "/mcp",
                        headers=headers,
                        json={
                            "jsonrpc": "2.0",
                            "id": 18,
                            "method": "tools/call",
                            "params": {
                                "name": "prepare_course_message",
                                "arguments": {
                                    "recipient_username": "other",
                                    "subject": "Question",
                                    "body": "Can we talk?",
                                },
                            },
                        },
                    )
                    assert unscoped_message.status_code == 200
                    assert unscoped_message.json()["result"]["isError"] is True
                    assert "Reconnect" in unscoped_message.text
                    message_client = await client.post(
                        "/register",
                        json={
                            "redirect_uris": ["https://chatgpt.com/connector/oauth/test-123"],
                            "token_endpoint_auth_method": "client_secret_post",
                            "grant_types": ["authorization_code", "refresh_token"],
                            "response_types": ["code"],
                            "scope": "course:read course:message_drafts",
                        },
                    )
                    assert message_client.status_code == 201, message_client.text
                    message_client_info = message_client.json()
                    message_authorized = await client.get(
                        "/authorize",
                        params={
                            "client_id": message_client_info["client_id"],
                            "redirect_uri": "https://chatgpt.com/connector/oauth/test-123",
                            "response_type": "code",
                            "code_challenge": challenge,
                            "code_challenge_method": "S256",
                            "state": "message-state",
                            "scope": "course:read course:message_drafts",
                            "resource": f"{BASE_URL}/mcp",
                        },
                    )
                    assert message_authorized.status_code == 302, message_authorized.text
                    message_request = parse_qs(
                        urlsplit(message_authorized.headers["location"]).query
                    )["request"][0]
                    message_approved = await client.post(
                        "/connect",
                        headers={"Origin": BASE_URL},
                        data={
                            "request": message_request,
                            "username": "student",
                            "access_code": student.access_code,
                        },
                    )
                    assert message_approved.status_code == 200, message_approved.text
                    message_code = parse_qs(urlsplit(_approved_callback(message_approved)).query)[
                        "code"
                    ][0]
                    message_tokens = await client.post(
                        "/token",
                        data={
                            "grant_type": "authorization_code",
                            "client_id": message_client_info["client_id"],
                            "client_secret": message_client_info["client_secret"],
                            "code": message_code,
                            "code_verifier": verifier,
                            "redirect_uri": "https://chatgpt.com/connector/oauth/test-123",
                            "resource": f"{BASE_URL}/mcp",
                        },
                    )
                    assert message_tokens.status_code == 200, message_tokens.text
                    assert set(message_tokens.json()["scope"].split()) == {
                        "course:read",
                        "course:message_drafts",
                    }
                    scoped_message = await client.post(
                        "/mcp",
                        headers={
                            **headers,
                            "Authorization": f"Bearer {message_tokens.json()['access_token']}",
                        },
                        json={
                            "jsonrpc": "2.0",
                            "id": 19,
                            "method": "tools/call",
                            "params": {
                                "name": "prepare_course_message",
                                "arguments": {
                                    "recipient_username": "other",
                                    "subject": "Question",
                                    "body": "Can we talk?",
                                },
                            },
                        },
                    )
                    assert scoped_message.status_code == 200, scoped_message.text
                    assert scoped_message.json()["result"]["isError"] is False
                    assert "confirmation_url" in scoped_message.text
                    resources = await client.post(
                        "/mcp",
                        headers=headers,
                        json={
                            "jsonrpc": "2.0",
                            "id": 13,
                            "method": "tools/call",
                            "params": {"name": "list_course_resources", "arguments": {}},
                        },
                    )
                    assert resources.status_code == 200, resources.text
                    assert "course://slides/week-01" in resources.text
                    assert "course://readings/software-agents-bradshaw" in resources.text
                    syllabus = await client.post(
                        "/mcp",
                        headers=headers,
                        json={
                            "jsonrpc": "2.0",
                            "id": 14,
                            "method": "tools/call",
                            "params": {
                                "name": "read_course_resource",
                                "arguments": {"resource_uri": "course://syllabus"},
                            },
                        },
                    )
                    assert syllabus.status_code == 200, syllabus.text
                    assert "assistant_instruction" not in syllabus.text
                    assert "Course" in syllabus.text
                    assert (
                        syllabus.json()["result"]["structuredContent"]["text_representation"]
                        == "course_text"
                    )
                    syllabus_content = syllabus.json()["result"]["structuredContent"]
                    _assert_resource_open_link(
                        syllabus_content["open_in_course_agent_url"], "course://syllabus"
                    )
                    assert "source_url" not in syllabus_content
                    assert "asset_urls" not in syllabus_content
                    slides = await client.post(
                        "/mcp",
                        headers=headers,
                        json={
                            "jsonrpc": "2.0",
                            "id": 20,
                            "method": "tools/call",
                            "params": {
                                "name": "read_course_resource",
                                "arguments": {
                                    "resource_uri": "course://slides/week-06",
                                    "max_chars": 10,
                                },
                            },
                        },
                    )
                    assert slides.status_code == 200, slides.text
                    slide_content = slides.json()["result"]["structuredContent"]
                    assert slide_content["text_representation"] == "pdf_text_extraction"
                    assert slide_content["returned_text_is_complete"] is False
                    _assert_resource_open_link(
                        slide_content["open_in_course_agent_url"], "course://slides/week-06"
                    )
                    assert "source_url" not in slide_content
                    assert "asset_urls" not in slide_content
                    slide_image = await client.post(
                        "/mcp",
                        headers=headers,
                        json={
                            "jsonrpc": "2.0",
                            "id": 21,
                            "method": "tools/call",
                            "params": {
                                "name": "read_course_slide_page",
                                "arguments": {
                                    "resource_uri": "course://slides/week-06",
                                    "page": 1,
                                },
                            },
                        },
                    )
                    assert slide_image.status_code == 200, slide_image.text[:500]
                    slide_result = slide_image.json()["result"]
                    assert slide_result.get("isError") is not True
                    assert [block["type"] for block in slide_result["content"]] == [
                        "text",
                        "image",
                    ]
                    slide_metadata = json.loads(slide_result["content"][0]["text"])
                    assert slide_metadata["resource_uri"] == "course://slides/week-06"
                    assert slide_metadata["page"] == 1
                    _assert_resource_open_link(
                        slide_metadata["open_in_course_agent_url"],
                        "course://slides/week-06",
                    )
                    assert base64.b64decode(slide_result["content"][1]["data"]).startswith(
                        b"\x89PNG\r\n\x1a\n"
                    )
                    assert slide_result["content"][1]["mimeType"] == "image/png"
                    unavailable_slide = await client.post(
                        "/mcp",
                        headers=headers,
                        json={
                            "jsonrpc": "2.0",
                            "id": 22,
                            "method": "tools/call",
                            "params": {
                                "name": "read_course_slide_page",
                                "arguments": {
                                    "resource_uri": "course://slides/unregistered",
                                    "page": 1,
                                },
                            },
                        },
                    )
                    assert unavailable_slide.status_code == 200
                    assert unavailable_slide.json()["result"]["isError"] is True
                    assert all(
                        block["type"] != "image"
                        for block in unavailable_slide.json()["result"]["content"]
                    )
                    updates = await client.post(
                        "/mcp",
                        headers=headers,
                        json={
                            "jsonrpc": "2.0",
                            "id": 15,
                            "method": "tools/call",
                            "params": {"name": "list_my_course_updates", "arguments": {}},
                        },
                    )
                    assert updates.status_code == 200, updates.text
                    assert "generated_at" in updates.text
                    update_history = await client.post(
                        "/mcp",
                        headers=headers,
                        json={
                            "jsonrpc": "2.0",
                            "id": 16,
                            "method": "tools/call",
                            "params": {
                                "name": "list_my_course_updates",
                                "arguments": {"history": True, "limit": 1},
                            },
                        },
                    )
                    assert update_history.status_code == 200, update_history.text
                    assert "next_offset" in update_history.text
                    listed = await client.post(
                        "/mcp",
                        headers=headers,
                        json={
                            "jsonrpc": "2.0",
                            "id": 2,
                            "method": "tools/call",
                            "params": {"name": "list_my_assignments", "arguments": {}},
                        },
                    )
                    assert listed.status_code == 200, listed.text
                    assert released.assignment_id in listed.text
                    assert "Hidden draft" not in listed.text
                    assignment_link = (
                        f"{BASE_URL}/?q=open_{released.assignment_id.replace('-', '_')}_assignment"
                    )
                    assert (
                        listed.json()["result"]["structuredContent"]["result"][0][
                            "open_in_course_agent_url"
                        ]
                        == assignment_link
                    )
                    hidden_read = await client.post(
                        "/mcp",
                        headers=headers,
                        json={
                            "jsonrpc": "2.0",
                            "id": 10,
                            "method": "tools/call",
                            "params": {
                                "name": "get_my_assignment",
                                "arguments": {"assignment_id": hidden.assignment_id},
                            },
                        },
                    )
                    assert hidden_read.status_code == 200
                    assert hidden_read.json()["result"]["isError"] is True
                    assert "Hidden draft" not in hidden_read.text
                    read = await client.post(
                        "/mcp",
                        headers=headers,
                        json={
                            "jsonrpc": "2.0",
                            "id": 3,
                            "method": "tools/call",
                            "params": {
                                "name": "get_my_assignment",
                                "arguments": {"assignment_id": released.assignment_id},
                            },
                        },
                    )
                    assert read.status_code == 200, read.text
                    assert "Explain your own design" in read.text
                    assert "assistant_instruction" in read.text
                    assert (
                        read.json()["result"]["structuredContent"]["open_in_course_agent_url"]
                        == assignment_link
                    )
                    instruction = " ".join(
                        read.json()["result"]["structuredContent"]["assistant_instruction"].split()
                    )
                    assert "Never take over the important cognitive labor" in instruction
                    assert "Never write or rewrite the student's" in instruction
                    assert "AI-generated ideas can anchor or bias" in instruction
                    assert "read `course://schedule`" in instruction
                    assert "Do not invent a replacement diagram" in instruction
                    assert "The student sets the agenda" in instruction
                    assert "Do not supply unsolicited examples" in instruction
                    assert "multiple-choice questions" in instruction
                    assert "A student's short reply" in instruction
                    assert "Whenever you select, shorten, paraphrase" in instruction
                    assert "not the full original" in instruction
                    assert "Include the returned `open_in_course_agent_url`" in instruction
                    assert "mcp_learning_checks" not in read.text
                    messages = await client.post(
                        "/mcp",
                        headers=headers,
                        json={
                            "jsonrpc": "2.0",
                            "id": 6,
                            "method": "tools/call",
                            "params": {"name": "list_my_course_messages", "arguments": {}},
                        },
                    )
                    assert messages.status_code == 200, messages.text
                    assert str(own_message_id) in messages.text
                    assert str(other_message_id) not in messages.text
                    assert "Other student's secret" not in messages.text
                    later_messages = await client.post(
                        "/mcp",
                        headers=headers,
                        json={
                            "jsonrpc": "2.0",
                            "id": 17,
                            "method": "tools/call",
                            "params": {
                                "name": "list_my_course_messages",
                                "arguments": {"offset": 1},
                            },
                        },
                    )
                    assert later_messages.status_code == 200, later_messages.text
                    assert str(own_message_id) not in later_messages.text
                    assert "next_offset" in later_messages.text
                    own_message = await client.post(
                        "/mcp",
                        headers=headers,
                        json={
                            "jsonrpc": "2.0",
                            "id": 11,
                            "method": "tools/call",
                            "params": {
                                "name": "read_my_course_message",
                                "arguments": {"communication_id": str(own_message_id)},
                            },
                        },
                    )
                    assert own_message.status_code == 200
                    assert "Your private feedback" in own_message.text
                    denied_message = await client.post(
                        "/mcp",
                        headers=headers,
                        json={
                            "jsonrpc": "2.0",
                            "id": 7,
                            "method": "tools/call",
                            "params": {
                                "name": "read_my_course_message",
                                "arguments": {"communication_id": str(other_message_id)},
                            },
                        },
                    )
                    assert denied_message.status_code == 200
                    assert denied_message.json()["result"]["isError"] is True
                    assert "Other student's secret" not in denied_message.text
                    unknown_tool = await client.post(
                        "/mcp",
                        headers=headers,
                        json={
                            "jsonrpc": "2.0",
                            "id": 20,
                            "method": "tools/call",
                            "params": {
                                "name": "unknown_tool_with_private_text",
                                "arguments": {"body": "private text must not enter usage"},
                            },
                        },
                    )
                    assert unknown_tool.status_code == 200
                    assert unknown_tool.json()["result"]["isError"] is True
                    async with pool.connection() as connection:
                        usage_rows = await (
                            await connection.execute(
                                "SELECT principal_hash, tool_name, outcome, server_version "
                                "FROM mcp_tool_usage ORDER BY occurred_at"
                            )
                        ).fetchall()
                    assert usage_rows
                    assert all(len(row["principal_hash"]) == 32 for row in usage_rows)
                    assert all(str(student.user.id) not in str(row) for row in usage_rows)
                    assert all("private text" not in str(row) for row in usage_rows)
                    assert any(
                        row["tool_name"] == "prepare_course_message"
                        and row["outcome"] == "permission_denied"
                        for row in usage_rows
                    )
                    assert any(
                        row["tool_name"] == "prepare_course_message" and row["outcome"] == "success"
                        for row in usage_rows
                    )
                    assert any(
                        row["tool_name"] == "unknown_tool" and row["outcome"] == "invalid_tool"
                        for row in usage_rows
                    )
                    report = await usage_summary(pool)
                    assert report["active_students"] == 1
                    assert report["connected_students"] == 1
                    assert report["tool_calls"] == len(usage_rows)
                    assert report["failed_calls"] >= 3
                    assert report["message_funnel"]["drafts"] == 1
                    assert report["message_funnel"]["confirmed"] == 0
                    refreshed = await client.post(
                        "/token",
                        data={
                            "grant_type": "refresh_token",
                            "client_id": client_info["client_id"],
                            "client_secret": client_info["client_secret"],
                            "refresh_token": tokens.json()["refresh_token"],
                            "scope": "course:read",
                            "resource": f"{BASE_URL}/mcp",
                        },
                    )
                    assert refreshed.status_code == 200, refreshed.text
                    assert refreshed.json()["access_token"] != access
                    refresh_replay = await client.post(
                        "/token",
                        data={
                            "grant_type": "refresh_token",
                            "client_id": client_info["client_id"],
                            "client_secret": client_info["client_secret"],
                            "refresh_token": tokens.json()["refresh_token"],
                            "scope": "course:read",
                            "resource": f"{BASE_URL}/mcp",
                        },
                    )
                    assert refresh_replay.status_code == 400
                    await admin.deactivate_user("student")
                    revoked_by_role = await client.post(
                        "/mcp",
                        headers={
                            **headers,
                            "Authorization": (f"Bearer {refreshed.json()['access_token']}"),
                        },
                        json={"jsonrpc": "2.0", "id": 8, "method": "tools/list"},
                    )
                    assert revoked_by_role.status_code == 401
                    await admin.activate_user("student")
                    website_session = await AuthenticationService(PostgresAuthStore(pool)).login(
                        username="student", access_code=student.access_code
                    )
                    website_cookie = {"Cookie": f"class_agent_auth={website_session.token}"}
                    connections = await client.get("/connections", headers=website_cookie)
                    assert connections.status_code == 200
                    assert "Revoke all course AI connections" in connections.text
                    revoked = await client.post(
                        "/connections",
                        headers={
                            **website_cookie,
                            "Origin": "null",
                            "Sec-Fetch-Site": "same-origin",
                        },
                    )
                    assert revoked.status_code == 200
                    after_revoke = await client.post(
                        "/mcp",
                        headers=headers,
                        json={"jsonrpc": "2.0", "id": 9, "method": "tools/list"},
                    )
                    assert after_revoke.status_code == 401
        finally:
            await pool.close()

    try:
        asyncio.run(scenario())
    finally:
        with psycopg.connect(TEST_DATABASE_URL) as connection:
            connection.execute(
                sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema_name))
            )
