"""Authenticated Course MCP for ChatGPT, using existing student accounts."""

from __future__ import annotations

import asyncio
import base64
import html
import json
import os
import re
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

import uvicorn
from dotenv import load_dotenv
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions, RevocationOptions
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import CallToolResult, ImageContent, TextContent, ToolAnnotations
from psycopg_pool import AsyncConnectionPool
from pydantic import AnyHttpUrl
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, PlainTextResponse, Response
from starlette.routing import Mount

from agent_core import PrincipalContext
from course_server.agent.capabilities import CourseResourceCatalog, FileResourceProvider
from course_server.assignments import FileAssignmentStore
from course_server.auth import (
    AuthenticationService,
    InvalidCredentials,
    InvalidSession,
    LoginRateLimited,
)
from course_server.config import MailSettings, _student_project_aliases
from course_server.course_direct_messages import CourseDirectMessageService, CourseMessageError
from course_server.course_roster import CourseRoster, load_course_roster
from course_server.faq import LocalFaqKnowledgeStore, PostgresFaqStore, PublishedFaqResourceCatalog
from course_server.instructor_messages import PostgresInstructorMessageStore
from course_server.mail import PostgresTAQuestionStore
from course_server.mcp_assignments import CourseMcpAssignmentService
from course_server.mcp_form_security import same_origin_form_submission
from course_server.mcp_message_pages import register_course_message_pages
from course_server.mcp_oauth import MESSAGE_DRAFT_SCOPE, CourseOAuthProvider
from course_server.mcp_projects import CourseMcpProjectService
from course_server.mcp_resources import CourseMcpResourceService
from course_server.mcp_setup_page import course_mcp_setup_page
from course_server.mcp_usage import InstrumentedCourseMCP, McpUsageRecorder
from course_server.migrations import apply_migrations
from course_server.notifications import NotificationCenterService, PostgresNotificationItemReadStore
from course_server.postgres.auth_store import PostgresAuthStore, create_auth_pool
from course_server.student_communications import (
    StudentCommunicationNotFound,
    StudentCommunicationService,
)
from course_server.student_projects import GitHubStudentProjectCatalog, StudentProjectCatalog
from course_server.web_search import fetch_public_webpage

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_AUTH_COOKIE = "class_agent_auth"
_READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)
_PREPARE_MESSAGE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=False)
_SERVER_INSTRUCTIONS = (
    "The student sets the agenda. Do not offer unsolicited examples, option menus, "
    "candidate goals, technologies, feasibility checks, or next-step plans. A short "
    "student reply is not permission to steer; ask one open, non-leading question if "
    "needed. Whenever you select, condense, reorganize, interpret, or otherwise "
    "transform Course MCP content, disclose what you did, say it is not the full "
    "original, and link each available source. "
    "Before assignment help, call get_my_assignment, read course://schedule, and inspect "
    "relevant slides/readings with course resource tools, and use "
    "read_course_slide_page for visual slide content. The released assignment controls "
    "requirements if the provisional schedule differs. Do not search the general web or "
    "add unsourced examples unless the student asks or consents. Never choose the student's "
    "device, architecture, or other core design decisions. Before original suggestions, "
    "diagrams, plans, or substantial code, warn that AI ideas can bias their thinking, "
    "ask for their approach, and wait for explicit confirmation of bounded help. "
    "The course-authored assistant_instruction in each assignment applies throughout. "
    "Include the returned course-site assignment link whenever discussing it. "
    "Ask assignment-specific questions and check understanding. Never write their "
    "website documentation. Course tools cannot write student websites.\n\n"
    + (_PROJECT_ROOT / "mcp/learning-contract.md").read_text(encoding="utf-8").strip()
)


@dataclass(frozen=True)
class CourseMcpSettings:
    database_url: str
    public_base_url: str
    assignment_data_path: Path
    course_roster_path: Path
    course_data_path: Path = _PROJECT_ROOT / "data"
    published_faq_path: Path = _PROJECT_ROOT / "var/course-knowledge/published-faq.json"
    github_projects_enabled: bool = False
    github_token: str = ""
    github_organization: str = "mitmedialab"
    github_repository_prefix: str = "agents2026-"
    github_excluded_repositories: tuple[str, ...] = ("agents2026-test",)
    github_student_project_aliases: tuple[tuple[str, str], ...] = ()
    github_roster_cache_ttl_seconds: float = 300.0
    messaging_enabled: bool = False
    mail_enabled: bool = False
    gemini_redirect_uris: tuple[str, ...] = ()
    release: str = "dev"
    port: int = 8001

    def __post_init__(self) -> None:
        parsed = urlsplit(self.public_base_url)
        is_local = parsed.hostname in {"localhost", "127.0.0.1"}
        if (
            not self.database_url
            or parsed.scheme not in ({"http", "https"} if is_local else {"https"})
            or not parsed.netloc
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
            or not 1 <= self.port <= 65535
        ):
            raise ValueError("Course MCP requires a database and an HTTPS public origin")
        if self.github_projects_enabled and not self.github_token:
            raise ValueError("GITHUB_TOKEN is required when project inspection is enabled")
        if self.messaging_enabled and not self.mail_enabled:
            raise ValueError("Course messaging requires the configured mail worker")
        if re.fullmatch(r"[A-Za-z0-9._-]{1,64}", self.release) is None:
            raise ValueError("MCP_RELEASE must be a short release identifier")

    @classmethod
    def from_environment(cls, values: Mapping[str, str]) -> CourseMcpSettings:
        database_url = values.get("DATABASE_URL", "").strip()
        public_base_url = values.get("MCP_PUBLIC_BASE_URL", "").strip().rstrip("/")
        github_enabled = values.get("GITHUB_STUDENT_PROJECTS_ENABLED", "false").strip().casefold()
        if github_enabled not in {"true", "false", "1", "0", "yes", "no"}:
            raise ValueError("GITHUB_STUDENT_PROJECTS_ENABLED must be true or false")
        messaging_enabled = values.get("MCP_MESSAGING_ENABLED", "false").strip().casefold()
        mail_enabled = values.get("MAIL_ENABLED", "false").strip().casefold()
        if messaging_enabled not in {"true", "false", "1", "0", "yes", "no"}:
            raise ValueError("MCP_MESSAGING_ENABLED must be true or false")
        if mail_enabled not in {"true", "false", "1", "0", "yes", "no"}:
            raise ValueError("MAIL_ENABLED must be true or false")
        if (
            messaging_enabled in {"true", "1", "yes"}
            and MailSettings.optional_from_environment(values) is None
        ):
            raise ValueError("Course messaging requires the configured mail worker")
        repository_prefix = values.get("GITHUB_REPOSITORY_PREFIX", "agents2026-").strip()
        excluded_repositories = tuple(
            name.strip()
            for name in values.get("GITHUB_EXCLUDED_REPOSITORIES", "agents2026-test").split(",")
            if name.strip()
        )
        return cls(
            database_url=database_url,
            public_base_url=public_base_url,
            assignment_data_path=Path(
                values.get("ASSIGNMENT_DATA_PATH") or _PROJECT_ROOT / "var/assignments"
            ).expanduser(),
            course_roster_path=Path(
                values.get("COURSE_ROSTER_PATH") or _PROJECT_ROOT / "var/roster/course-members.json"
            ).expanduser(),
            course_data_path=Path(
                values.get("COURSE_DATA_PATH") or _PROJECT_ROOT / "data"
            ).expanduser(),
            published_faq_path=Path(
                values.get("PUBLISHED_FAQ_PATH")
                or _PROJECT_ROOT / "var/course-knowledge/published-faq.json"
            ).expanduser(),
            github_projects_enabled=github_enabled in {"true", "1", "yes"},
            github_token=values.get("GITHUB_TOKEN", "").strip(),
            github_organization=values.get("GITHUB_ORGANIZATION", "mitmedialab").strip(),
            github_repository_prefix=repository_prefix,
            github_excluded_repositories=excluded_repositories,
            github_student_project_aliases=_student_project_aliases(
                values.get("GITHUB_STUDENT_PROJECT_ALIASES", ""),
                repository_prefix=repository_prefix,
                excluded_repositories=excluded_repositories,
            ),
            github_roster_cache_ttl_seconds=float(
                values.get("GITHUB_ROSTER_CACHE_TTL_SECONDS", "300")
            ),
            messaging_enabled=messaging_enabled in {"true", "1", "yes"},
            mail_enabled=mail_enabled in {"true", "1", "yes"},
            gemini_redirect_uris=tuple(
                uri.strip()
                for uri in values.get("MCP_GEMINI_OAUTH_REDIRECT_URIS", "").split(",")
                if uri.strip()
            ),
            release=values.get("MCP_RELEASE", "dev").strip(),
            port=int(values.get("MCP_PORT", "8001")),
        )


def _mcp_transport_security(public_base_url: str, port: int) -> TransportSecuritySettings:
    """Accept the configured public proxy host without disabling Host/Origin checks."""
    public = urlsplit(public_base_url)
    local_origin = f"http://127.0.0.1:{port}"
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=[public.netloc, f"127.0.0.1:{port}"],
        allowed_origins=[f"{public.scheme}://{public.netloc}", local_origin],
    )


def _connect_page(*, request_token: str, name: str | None, error: str = "") -> HTMLResponse:
    identity = (
        f"<p>Signed in as {html.escape(name)}.</p>"
        if name
        else (
            '<label>Course username or email <input name="username" required '
            'autocomplete="username"></label>'
            '<label>Course access code <input name="access_code" type="password" '
            'required autocomplete="current-password"></label>'
        )
    )
    error_html = f'<p role="alert">{html.escape(error)}</p>' if error else ""
    body = (
        '<!doctype html><html lang="en"><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        "<title>Connect Course Agent</title>"
        '<link rel="stylesheet" href="/mcp-pages.css">'
        "<h1>Connect Course Agent to an AI app</h1>"
        "<p>Your connected AI app can read your released assignments, course materials, "
        "your own course messages and updates, and, if enabled, course project sites "
        "and your own repository. If messaging is enabled, the app can prepare course "
        "message drafts, but only you can send them after reviewing the recipient and "
        "text on this website. This connection does not save learning check-ins or "
        "write your website. The course records which tools you use, whether they "
        "succeeded, and their timing for up to 260 days to improve the service; "
        "it does not record "
        "your AI-app conversation, tool arguments, or tool results. "
        "It will not receive your course access code. "
        '<a href="/learning-contract">Read the course learning instructions</a> '
        "that accompany assignments.</p>"
        '<p><a href="/ai-connect">Setup steps and the Course MCP URL</a></p>'
        f"{error_html}<form method=post action=/connect>"
        f'<input type="hidden" name="request" value="{html.escape(request_token, quote=True)}">'
        f"{identity}<button type=submit>Connect my course account</button></form>"
        "</html>"
    )
    return HTMLResponse(
        body, headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"}
    )


def _connect_approved_page(destination: str) -> HTMLResponse:
    # A form POST's cross-origin 303 can be blocked by the site's form-action 'self'
    # CSP. End the form navigation on our origin before continuing to the client.
    callback = html.escape(destination, quote=True)
    return HTMLResponse(
        '<!doctype html><html lang="en"><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<meta http-equiv="refresh" content="0;url={callback}">'
        "<title>Continue to your AI app · Course Agent</title>"
        '<link rel="stylesheet" href="/mcp-pages.css">'
        "<main><h1>Course account approved</h1>"
        "<p>Continue to your AI app to finish connecting. If it does not open "
        "automatically, use the link below.</p>"
        f'<p><a id="continue-connection" href="{callback}" rel="noreferrer">'
        "Continue to your AI app</a></p></main></html>",
        headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
    )


def create_course_mcp_app(
    settings: CourseMcpSettings,
    *,
    pool: AsyncConnectionPool[Any] | None = None,
    roster: CourseRoster | None = None,
    resources: CourseResourceCatalog | None = None,
    student_projects: StudentProjectCatalog | None = None,
) -> Starlette:
    """Build the deployable ASGI app; caller controls only configuration, not identity."""
    owned_pool = pool is None
    pool = pool or create_auth_pool(settings.database_url)
    roster = roster if roster is not None else load_course_roster(settings.course_roster_path)
    auth_store = PostgresAuthStore(pool)
    authentication = AuthenticationService(
        auth_store,
        user_access_policy=(
            None
            if roster is None
            else lambda user: (
                user.role != "student" or not roster.identifies_inactive_username(user.username)
            )
        ),
    )
    oauth = CourseOAuthProvider(
        pool,
        auth_store,
        public_base_url=settings.public_base_url,
        roster=roster,
        messaging_enabled=settings.messaging_enabled,
        gemini_redirect_uris=settings.gemini_redirect_uris,
    )
    assignments = CourseMcpAssignmentService(
        FileAssignmentStore(settings.assignment_data_path),
        public_base_url=settings.public_base_url,
    )
    resource_catalog = resources or PublishedFaqResourceCatalog(
        FileResourceProvider.from_registry(protected_data_path=settings.course_data_path),
        LocalFaqKnowledgeStore(settings.published_faq_path),
    )
    course_resources = CourseMcpResourceService(
        resource_catalog, public_base_url=settings.public_base_url
    )
    question_store = PostgresTAQuestionStore(pool)
    instructor_message_store = PostgresInstructorMessageStore(pool)
    messages = StudentCommunicationService(
        auth=auth_store,
        questions=question_store,
        instructor_messages=instructor_message_store,
    )
    if settings.messaging_enabled and roster is None:
        raise ValueError("Course messaging requires the active course roster")
    direct_messages = (
        CourseDirectMessageService(pool, auth_store, roster)
        if settings.messaging_enabled and roster is not None
        else None
    )
    notifications = NotificationCenterService(
        faqs=PostgresFaqStore(pool),
        reads=PostgresNotificationItemReadStore(pool),
        auth=auth_store,
        resources=resource_catalog,
        assignments=FileAssignmentStore(settings.assignment_data_path),
        instructor_messages=instructor_message_store,
        questions=question_store,
    )
    if student_projects is None and settings.github_projects_enabled:
        if roster is None:
            raise ValueError("Project inspection requires the active course roster")
        student_projects = GitHubStudentProjectCatalog(
            settings.github_token,
            organization=settings.github_organization,
            repository_prefix=settings.github_repository_prefix,
            excluded_repositories=settings.github_excluded_repositories,
            allowed_repositories=roster.active_weekly_project_ids,
            roster_cache_ttl_seconds=settings.github_roster_cache_ttl_seconds,
        )
    projects = (
        CourseMcpProjectService(
            student_projects,
            fetch_public_webpage,
            repository_prefix=settings.github_repository_prefix,
            student_project_aliases={
                **(roster.active_student_project_aliases if roster else {}),
                **dict(settings.github_student_project_aliases),
            },
        )
        if student_projects is not None
        else None
    )
    base_url = settings.public_base_url.rstrip("/")
    mcp = InstrumentedCourseMCP(
        "MIT Course Agent",
        instructions=_SERVER_INSTRUCTIONS,
        auth_server_provider=oauth,
        auth=AuthSettings(
            issuer_url=AnyHttpUrl(base_url),
            resource_server_url=AnyHttpUrl(f"{base_url}/mcp"),
            validate_token_resource=True,
            required_scopes=["course:read"],
            client_registration_options=ClientRegistrationOptions(
                enabled=True,
                valid_scopes=(
                    ["course:read", MESSAGE_DRAFT_SCOPE]
                    if direct_messages is not None
                    else ["course:read"]
                ),
                default_scopes=(
                    ["course:read", MESSAGE_DRAFT_SCOPE]
                    if direct_messages is not None
                    else ["course:read"]
                ),
            ),
            revocation_options=RevocationOptions(enabled=True),
        ),
        host="127.0.0.1",
        port=settings.port,
        stateless_http=True,
        json_response=True,
        transport_security=_mcp_transport_security(base_url, settings.port),
    )
    mcp.usage_recorder = McpUsageRecorder(pool, server_version=settings.release)

    async def principal() -> PrincipalContext:
        access = get_access_token()
        if access is None:
            raise PermissionError("Connect a course account first.")
        user = await oauth.principal_for_access_token(access)
        if user is None:
            raise PermissionError("An active student account is required.")
        family_id = (access.claims or {}).get("family_id")
        if not isinstance(family_id, str):
            raise PermissionError("The course connection is invalid.")
        return PrincipalContext(
            authenticated=True,
            user_id=user.id,
            username=user.username,
            display_name=user.display_name,
            roles=["public", "student"],
            session_id=UUID(family_id),
        )

    async def message_draft_principal() -> PrincipalContext:
        access = get_access_token()
        if access is None or MESSAGE_DRAFT_SCOPE not in access.scopes:
            raise PermissionError("Reconnect with course message-draft access first.")
        return await principal()

    @mcp.tool(
        name="list_my_assignments",
        description=(
            "Use this to list released course assignments visible to the connected student. "
            "Returns titles, summaries, dates, IDs, and links that ask the course website "
            "agent to open each full assignment. Summaries are not complete requirements. "
            "No drafts or other students' data. "
            "Before helping with any listed assignment, call get_my_assignment to read "
            "its full requirements and course learning instruction."
        ),
        annotations=_READ_ONLY,
    )
    async def list_my_assignments() -> list[dict[str, Any]]:
        return await assignments.list_assignments(await principal())

    @mcp.tool(
        name="get_my_assignment",
        description=(
            "Read one released assignment with its attached assistant instruction. "
            "content_markdown is the original published text; open_in_course_agent_url "
            "opens a website-agent request to display it, not a static document. "
            "Do not volunteer examples, choice menus, project directions, or a plan. "
            "Disclose every selection, paraphrase, or interpretation of course content "
            "and link the original. "
            "Before substantive help, also read the schedule and relevant class slides or "
            "readings. Keep core decisions with the student; warn about idea bias and wait "
            "for explicit confirmation before original suggestions, diagrams, or substantial "
            "work. Never supply their answer or website documentation."
        ),
        annotations=_READ_ONLY,
    )
    async def get_my_assignment(assignment_id: str) -> dict[str, Any]:
        return await assignments.get_assignment(await principal(), assignment_id)

    @mcp.tool(
        name="list_course_resources",
        description=(
            "List course resources visible to this student: syllabus, schedule, readings, "
            "lecture slides, published Q&A, and authorized private course files. "
            "Use the returned course:// URI to read a resource. Results also provide "
            "an open_in_course_agent_url that asks the course website to open it."
        ),
        annotations=_READ_ONLY,
    )
    async def list_course_resources() -> list[dict[str, Any]]:
        return course_resources.list_resources(await principal())

    @mcp.tool(
        name="read_course_resource",
        description=(
            "Read an authorized course:// resource, including extracted text from PDF slides "
            "or readings. Use next_offset to continue long resources and "
            "open_in_course_agent_url to link the website viewer. "
            "returned_text_is_complete concerns only returned text; "
            "pdf_text_extraction can omit visual content. Disclose partial/extracted or "
            "interpreted content. Use read_course_slide_page to verify an existing slide "
            "diagram visually; do not invent one. Never guess a private URI or use this to answer "
            "a student's assignment for them."
        ),
        annotations=_READ_ONLY,
    )
    async def read_course_resource(
        resource_uri: str, offset: int = 0, max_chars: int = 12_000
    ) -> dict[str, Any]:
        return await course_resources.read_resource(
            await principal(), resource_uri, offset=offset, max_chars=max_chars
        )

    @mcp.tool(
        name="read_course_slide_page",
        description=(
            "Return the actual rendered PNG of one page of an authorized registered "
            "course slide PDF, plus its source URI, page number, extracted text, and a "
            "course-website opening link. Use to inspect existing diagrams/images that "
            "read_course_resource's PDF text cannot show. This is an original slide page, "
            "not a generated diagram or a project suggestion. State when your description "
            "or interpretation is not the full original and cite the source and page. "
            "Do not use slide visuals to choose the student's design for them."
        ),
        annotations=_READ_ONLY,
    )
    async def read_course_slide_page(resource_uri: str, page: int) -> CallToolResult:
        slide, open_url = await course_resources.read_slide_page(
            await principal(), resource_uri, page
        )
        metadata = {
            "resource_uri": slide.resource_uri,
            "title": slide.title,
            "page": slide.page,
            "page_count": slide.page_count,
            "media_type": "image/png",
            "extracted_text": slide.extracted_text,
            "open_in_course_agent_url": open_url,
            "note": "Image is the original rendered slide page; extracted text may omit visuals.",
        }
        return CallToolResult(
            content=[
                TextContent(type="text", text=json.dumps(metadata)),
                ImageContent(
                    type="image",
                    data=base64.b64encode(slide.png).decode("ascii"),
                    mimeType="image/png",
                ),
            ]
        )

    @mcp.tool(
        name="search_course_resources",
        description=(
            "Search text across this student's authorized course resources, including "
            "published FAQ additions. Returns source URIs, course-agent opening links, and "
            "excerpts; read the source "
            "before relying on it."
        ),
        annotations=_READ_ONLY,
    )
    async def search_course_resources(query: str, limit: int = 5) -> list[dict[str, Any]]:
        return await course_resources.search_resources(await principal(), query, limit=limit)

    @mcp.tool(
        name="list_my_course_updates",
        description=(
            "Read this student's current course updates, communications, upcoming deadlines, "
            "and lecture-slide notices. Set history=true to page through older notices. "
            "This does not mark them read or save learning progress."
        ),
        annotations=_READ_ONLY,
    )
    async def list_my_course_updates(
        history: bool = False, offset: int = 0, limit: int = 25
    ) -> dict[str, Any]:
        if not 0 <= offset <= 10_000 or not 1 <= limit <= 100:
            raise ValueError("Invalid update range.")
        center = await notifications.get(await principal())
        source = center.history_items if history else center.items
        selected = source[offset : offset + limit]
        next_offset = offset + len(selected)
        return {
            "generated_at": center.generated_at.isoformat(),
            "unread_count": center.unread_count,
            "total": len(source),
            "next_offset": next_offset if next_offset < len(source) else None,
            "items": [
                item.model_dump(
                    mode="json",
                    exclude={
                        "action_label",
                        "action_prompt",
                        "submission_check_prompt",
                        "thumbnail",
                        "dismissible",
                    },
                )
                for item in selected
            ],
        }

    if projects is not None:

        @mcp.tool(
            name="list_student_projects",
            description=(
                "List course project IDs and deployed documentation-site URLs, where weekly "
                "builds and final-project work may be posted. Never returns repository code."
            ),
            annotations=_READ_ONLY,
        )
        async def list_student_projects() -> Any:
            return await projects.list_projects(await principal())

        @mcp.tool(
            name="inspect_student_site",
            description=(
                "Read a listed student's deployed course documentation website. Look for "
                "weekly build/assignment write-ups and final-project documentation; verify "
                "what is actually posted. This does not return repository code."
            ),
            annotations=_READ_ONLY,
        )
        async def inspect_student_site(project_id: str) -> Any:
            return await projects.inspect_site(await principal(), project_id)

        @mcp.tool(
            name="inspect_my_student_site",
            description=(
                "Read the connected student's own deployed course documentation website, "
                "derived from their login. Look for weekly build/assignment write-ups and "
                "final-project documentation, but verify what is posted. Do not write or "
                "rewrite their documentation."
            ),
            annotations=_READ_ONLY,
        )
        async def inspect_my_student_site() -> Any:
            return await projects.inspect_my_site(await principal())

        @mcp.tool(
            name="inspect_my_student_repository",
            description=(
                "Read the connected student's own course GitHub repository, where weekly "
                "assignment implementation code and final-project code may be posted. Start "
                "with the tree to find actual paths; choose summary, tree, file, commits, "
                "branches, pulls, issues, or workflows. Cannot access another student's "
                "source or perform writes."
            ),
            annotations=_READ_ONLY,
        )
        async def inspect_my_student_repository(
            view: str, path: str | None = None, ref: str | None = None
        ) -> Any:
            return await projects.inspect_my_repository(await principal(), view, path=path, ref=ref)

    @mcp.tool(
        name="list_my_course_messages",
        description=(
            "List the student's existing TA question threads and instructor messages, "
            "including staff answers. These are not the newer one-to-one course-inbox "
            "messages; use list_my_direct_messages for those."
        ),
        annotations=_READ_ONLY,
    )
    async def list_my_course_messages(offset: int = 0, limit: int = 25) -> dict[str, Any]:
        if not 0 <= offset <= 10_000 or not 1 <= limit <= 25:
            raise ValueError("Invalid message range.")
        student = await principal()
        communications = await messages.list_mine(student)
        selected = communications[offset : offset + limit]
        next_offset = offset + len(selected)
        return {
            "total": len(communications),
            "next_offset": next_offset if next_offset < len(communications) else None,
            "messages": [
                {
                    "id": str(item.id),
                    "kind": item.kind,
                    "state": item.state,
                    "subject": item.subject,
                    "created_at": item.created_at.isoformat(),
                }
                for item in selected
            ],
        }

    @mcp.tool(
        name="read_my_course_message",
        description=(
            "Read one owned TA question thread or instructor message by an ID from "
            "list_my_course_messages. For one-to-one course-inbox messages use "
            "read_my_direct_message."
        ),
        annotations=_READ_ONLY,
    )
    async def read_my_course_message(communication_id: str) -> dict[str, Any]:
        try:
            item = await messages.get_mine(await principal(), UUID(communication_id))
        except (ValueError, StudentCommunicationNotFound) as error:
            raise ValueError("This course message is unavailable to this student.") from error
        return item.model_dump(mode="json", exclude_none=True)

    if direct_messages is not None:

        @mcp.tool(
            name="list_course_message_recipients",
            description=(
                "List active course members available for one-to-one messages, plus the "
                "shared course-staff inbox. Choose a returned username, not an email address."
            ),
            annotations=_READ_ONLY,
        )
        async def list_course_message_recipients() -> list[dict[str, str]]:
            return await direct_messages.list_recipients(await principal())

        @mcp.tool(
            name="list_my_direct_messages",
            description=(
                "Page through the account's sent and received one-to-one course-inbox "
                "messages. Returns summaries without body text; read a selected ID with "
                "read_my_direct_message. For older TA and instructor communications use "
                "list_my_course_messages."
            ),
            annotations=_READ_ONLY,
        )
        async def list_my_direct_messages(offset: int = 0, limit: int = 25) -> dict[str, Any]:
            return await direct_messages.list_mine(await principal(), offset=offset, limit=limit)

        @mcp.tool(
            name="read_my_direct_message",
            description="Read one owned one-to-one course-inbox message by its listed ID.",
            annotations=_READ_ONLY,
        )
        async def read_my_direct_message(message_id: str) -> dict[str, Any]:
            try:
                message = await direct_messages.read_mine(await principal(), UUID(message_id))
            except (ValueError, CourseMessageError) as error:
                raise ValueError("This course message is unavailable.") from error
            return message.public()

        @mcp.tool(
            name="prepare_course_message",
            description=(
                "Prepare a one-to-one course message or a message to @course_staff. "
                "This does not deliver it. The student must open the returned course-website "
                "link, review the resolved recipient and exact text, and press Send there. "
                "Use the student's own substantive message, not an autonomous outreach."
            ),
            annotations=_PREPARE_MESSAGE,
        )
        async def prepare_course_message(
            recipient_username: str, subject: str, body: str
        ) -> dict[str, Any]:
            draft = await direct_messages.prepare(
                await message_draft_principal(),
                recipient_username=recipient_username,
                subject=subject,
                body=body,
            )
            return {
                "draft_id": str(draft.id),
                "recipient": draft.recipient_label,
                "subject": draft.subject,
                "body": draft.body,
                "confirmation_required": True,
                "confirmation_url": f"{base_url}/messages/confirm/{draft.id}",
            }

        @mcp.tool(
            name="prepare_course_reply",
            description=(
                "Prepare a reply to one owned direct message, instructor message, or TA "
                "question thread. The server resolves the recipient from the original "
                "communication. Nothing is delivered until the student reviews and presses "
                "Send on the course website."
            ),
            annotations=_PREPARE_MESSAGE,
        )
        async def prepare_course_reply(
            communication_id: str, subject: str, body: str
        ) -> dict[str, Any]:
            try:
                reply_id = UUID(communication_id)
            except ValueError as error:
                raise ValueError("A valid communication ID is required.") from error
            draft = await direct_messages.prepare(
                await message_draft_principal(),
                recipient_username="",
                subject=subject,
                body=body,
                reply_to=reply_id,
            )
            return {
                "draft_id": str(draft.id),
                "recipient": draft.recipient_label,
                "subject": draft.subject,
                "body": draft.body,
                "confirmation_required": True,
                "confirmation_url": f"{base_url}/messages/confirm/{draft.id}",
            }

        register_course_message_pages(mcp, direct_messages, authentication, base_url)

    async def cookie_student(request: Request) -> PrincipalContext | None:
        token = request.cookies.get(_AUTH_COOKIE)
        if not token:
            return None
        try:
            result = await authentication.resolve_authenticated(token)
        except InvalidSession:
            return None
        return result if "student" in result.roles else None

    @mcp.custom_route("/ai-connect", methods=["GET"])  # type: ignore[untyped-decorator]
    async def ai_connect(_request: Request) -> Response:
        return course_mcp_setup_page(base_url)

    @mcp.custom_route("/mcp-pages.css", methods=["GET"])  # type: ignore[untyped-decorator]
    async def mcp_pages_css(_request: Request) -> Response:
        return Response(
            (_PROJECT_ROOT / "mcp/pages.css").read_text(encoding="utf-8"),
            media_type="text/css",
            headers={"Cache-Control": "no-store"},
        )

    @mcp.custom_route("/learning-contract.md", methods=["GET"])  # type: ignore[untyped-decorator]
    async def learning_contract_source(_request: Request) -> Response:
        contract = (_PROJECT_ROOT / "mcp/learning-contract.md").read_text(encoding="utf-8")
        return PlainTextResponse(
            contract,
            media_type="text/markdown; charset=utf-8",
            headers={"Cache-Control": "no-store"},
        )

    @mcp.custom_route("/learning-contract", methods=["GET"])  # type: ignore[untyped-decorator]
    async def learning_contract(_request: Request) -> Response:
        contract = (_PROJECT_ROOT / "mcp/learning-contract.md").read_text(encoding="utf-8")
        return HTMLResponse(
            '<!doctype html><html lang="en"><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            "<title>Course learning instructions</title>"
            '<link rel="stylesheet" href="/mcp-pages.css"><main>'
            "<h1>Course learning instructions</h1><p>These instructions accompany each "
            "assignment sent through the Course MCP. An outside AI model may not always "
            "follow them; students remain responsible for understanding their own work.</p>"
            '<p><a href="/learning-contract.md">View Markdown source</a></p>'
            f'<pre class="learning-contract">{html.escape(contract)}</pre>'
            "</main></html>",
            headers={"Cache-Control": "no-store"},
        )

    @mcp.custom_route("/connect", methods=["GET", "POST"])  # type: ignore[untyped-decorator]
    async def connect(request: Request) -> Response:
        if request.method == "GET":
            request_token = request.query_params.get("request", "")
        else:
            if (
                not same_origin_form_submission(request, base_url)
                or int(request.headers.get("content-length", "0")) > 4_096
            ):
                return PlainTextResponse("Invalid connection request.", status_code=400)
            form = await request.form()
            request_token = str(form.get("request", ""))
        pending = await oauth.pending_request(request_token)
        if pending is None:
            return PlainTextResponse("This connection request has expired.", status_code=400)
        student = await cookie_student(request)
        credential = None
        if request.method == "GET":
            return _connect_page(
                request_token=request_token,
                name=student.display_name if student else None,
            )
        if student is None:
            username = str(form.get("username", ""))
            access_code = str(form.get("access_code", ""))
            try:
                credential = await authentication.login(username=username, access_code=access_code)
                student = await authentication.resolve_authenticated(credential.token)
            except (InvalidCredentials, LoginRateLimited, InvalidSession):
                return _connect_page(
                    request_token=request_token,
                    name=None,
                    error="The course username or access code was not accepted.",
                )
        if "student" not in student.roles or student.user_id is None:
            return PlainTextResponse("An active student account is required.", status_code=403)
        destination = await oauth.approve(request_token, student.user_id)
        if destination is None:
            return PlainTextResponse("This connection request has expired.", status_code=400)
        response = _connect_approved_page(destination)
        if credential is not None:
            response.set_cookie(
                _AUTH_COOKIE,
                credential.token,
                path="/",
                httponly=True,
                secure=True,
                samesite="lax",
                expires=credential.expires_at,
                max_age=max(0, int((credential.expires_at - datetime.now(UTC)).total_seconds())),
            )
        return response

    @mcp.custom_route("/connections", methods=["GET", "POST"])  # type: ignore[untyped-decorator]
    async def connections(request: Request) -> Response:
        student = await cookie_student(request)
        if student is None or student.user_id is None:
            return PlainTextResponse("Sign in on the course website first.", status_code=401)
        if request.method == "POST":
            if not same_origin_form_submission(request, base_url):
                return PlainTextResponse("Invalid connection request.", status_code=400)
            await oauth.revoke_user_connections(student.user_id)
            return HTMLResponse(
                "<h1>Course MCP connection revoked</h1><p>Connected AI apps can no longer read "
                "your private course data through this connection.</p>",
                headers={"Cache-Control": "no-store"},
            )
        return HTMLResponse(
            '<!doctype html><html lang="en"><meta charset="utf-8">'
            "<title>Course MCP connections</title><h1>Course MCP connections</h1>"
            f"<p>Signed in as {html.escape(student.display_name or 'student')}.</p>"
            '<form method="post" action="/connections">'
            '<button type="submit">Revoke all course AI connections</button></form></html>',
            headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
        )

    mcp_http_app = mcp.streamable_http_app()

    @asynccontextmanager
    async def lifespan(_: Starlette) -> AsyncIterator[None]:
        await asyncio.to_thread(apply_migrations, settings.database_url)
        if owned_pool:
            await pool.open()
        await pool.wait()
        try:
            async with mcp.session_manager.run():
                yield
        finally:
            if owned_pool:
                await pool.close()

    app = Starlette(routes=[Mount("/", app=mcp_http_app)], lifespan=lifespan)
    app.state.course_mcp = mcp
    app.state.course_oauth = oauth
    app.state.course_assignments = assignments
    app.state.course_resources = course_resources
    app.state.course_projects = projects
    app.state.course_direct_messages = direct_messages
    return app


def main() -> None:
    load_dotenv(override=False)
    settings = CourseMcpSettings.from_environment(os.environ)
    uvicorn.run(create_course_mcp_app(settings), host="127.0.0.1", port=settings.port)


if __name__ == "__main__":
    main()
