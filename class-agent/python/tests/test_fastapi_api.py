from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from agent_core import AgentContext, AgentInput, AgentResult, Event, PrincipalContext
from course_server.agent import CourseAgentService, InMemoryConversationStore
from course_server.anonymous_quotas import AnonymousQuotaPolicy
from course_server.api import API_PREFIX, AppServices, create_app
from course_server.auth import AuthenticationService, InMemoryAuthStore, UserAdminService
from course_server.browser import (
    BrowserPage,
    BrowserPreview,
    BrowserPreviewSnapshot,
    BrowserSessionNotFound,
    BrowserSessionService,
    BrowserSnapshot,
)
from course_server.uploads import FileTemporaryUploadStore, TemporaryUploadStore


class RecordingRuntime:
    def __init__(self) -> None:
        self.contexts: list[AgentContext] = []

    async def run(
        self,
        *,
        context: AgentContext,
        input: AgentInput,
    ) -> AgentResult:
        self.contexts.append(context)
        output = f"Echo: {input.text}"
        events = [
            Event(
                type="agent.message",
                actor="course-agent",
                principal_user_id=context.principal.user_id,
                anonymous_session_id=context.principal.anonymous_session_id,
                conversation_id=context.conversation_id,
                payload={"text": output},
            )
        ]
        if input.text == "open schedule":
            events.insert(
                0,
                Event(
                    type="workspace.panel.opened",
                    actor="course-agent",
                    principal_user_id=context.principal.user_id,
                    anonymous_session_id=context.principal.anonymous_session_id,
                    conversation_id=context.conversation_id,
                    payload={
                        "command": {
                            "type": "open",
                            "panel": {
                                "id": "40000000-0000-4000-8000-000000000001",
                                "component_id": "calendar",
                                "title": "Course schedule",
                                "resource_uri": "course://schedule",
                                "props": {"view": "agenda"},
                                "state": {},
                            },
                        }
                    },
                ),
            )
        return AgentResult(
            input_id=input.id,
            conversation_id=context.conversation_id,
            output_text=output,
            events=events,
        )

    async def run_observed(
        self,
        *,
        context: AgentContext,
        input: AgentInput,
        event_observer: Any,
        text_delta_observer: Any = None,
    ) -> AgentResult:
        result = await self.run(context=context, input=input)
        if text_delta_observer is not None:
            text_delta_observer("Echo: ")
            text_delta_observer(input.text)
        for event in result.events:
            event_observer(event)
        return result


class SnapshotBrowserService:
    def __init__(self) -> None:
        self.sessions: dict[UUID, tuple[UUID, UUID, BrowserPage]] = {}
        self.previews: dict[UUID, tuple[UUID, UUID, BrowserPreview]] = {}

    async def start(self) -> None:
        return None

    async def close(self) -> None:
        self.sessions.clear()
        self.previews.clear()

    async def open(
        self,
        *,
        principal: PrincipalContext,
        conversation_id: UUID,
        url: str,
    ) -> BrowserPage:
        session_id = uuid4()
        page = BrowserPage(
            session_id=session_id,
            url=url,
            title="Example",
            revision=1,
            text_excerpt="Example",
            expires_at=datetime.now(UTC) + timedelta(minutes=15),
            viewport_width=1280,
            viewport_height=800,
        )
        self.sessions[session_id] = (principal.session_id, conversation_id, page)
        return page

    async def create_preview(
        self,
        *,
        principal: PrincipalContext,
        conversation_id: UUID,
        url: str,
    ) -> BrowserPreview:
        preview = BrowserPreview(
            preview_id=uuid4(),
            url=url,
            title="Example preview",
            expires_at=datetime.now(UTC) + timedelta(minutes=15),
            viewport_width=1280,
            viewport_height=800,
            document_height=1600,
        )
        self.previews[preview.preview_id] = (
            principal.session_id,
            conversation_id,
            preview,
        )
        return preview

    async def preview_snapshot(
        self,
        *,
        principal: PrincipalContext,
        conversation_id: UUID,
        preview_id: UUID,
    ) -> BrowserPreviewSnapshot:
        stored = self.previews.get(preview_id)
        if stored is None or stored[:2] != (principal.session_id, conversation_id):
            raise BrowserSessionNotFound("Browser preview not found.")
        return BrowserPreviewSnapshot(preview=stored[2], png=b"\x89PNG\r\n\x1a\n")

    async def navigate(
        self,
        *,
        principal: PrincipalContext,
        conversation_id: UUID,
        session_id: UUID,
        url: str,
    ) -> BrowserPage:
        del principal, conversation_id, session_id, url
        raise NotImplementedError

    async def scroll(
        self,
        *,
        principal: PrincipalContext,
        conversation_id: UUID,
        session_id: UUID,
        delta_y: int,
    ) -> BrowserPage:
        del delta_y
        stored = self.sessions.get(session_id)
        if stored is None or stored[:2] != (principal.session_id, conversation_id):
            raise BrowserSessionNotFound("Browser session not found.")
        page = stored[2].model_copy(update={"revision": stored[2].revision + 1})
        self.sessions[session_id] = (principal.session_id, conversation_id, page)
        return page

    async def click(
        self,
        *,
        principal: PrincipalContext,
        conversation_id: UUID,
        session_id: UUID,
        x: int,
        y: int,
    ) -> BrowserPage:
        del x, y
        stored = self.sessions.get(session_id)
        if stored is None or stored[:2] != (principal.session_id, conversation_id):
            raise BrowserSessionNotFound("Browser session not found.")
        page = stored[2].model_copy(
            update={
                "url": "https://example.com/clicked",
                "title": "Clicked page",
                "revision": stored[2].revision + 1,
            }
        )
        self.sessions[session_id] = (principal.session_id, conversation_id, page)
        return page

    async def resize(
        self,
        *,
        principal: PrincipalContext,
        conversation_id: UUID,
        session_id: UUID,
        width: int,
        height: int,
    ) -> BrowserPage:
        stored = self.sessions.get(session_id)
        if stored is None or stored[:2] != (principal.session_id, conversation_id):
            raise BrowserSessionNotFound("Browser session not found.")
        page = stored[2].model_copy(
            update={
                "revision": stored[2].revision + 1,
                "viewport_width": width,
                "viewport_height": height,
            }
        )
        self.sessions[session_id] = (principal.session_id, conversation_id, page)
        return page

    async def highlight_text(
        self,
        *,
        principal: PrincipalContext,
        conversation_id: UUID,
        session_id: UUID,
        text: str,
    ) -> tuple[BrowserPage, int]:
        del principal, conversation_id, session_id, text
        raise NotImplementedError

    async def snapshot(
        self,
        *,
        principal: PrincipalContext,
        conversation_id: UUID,
        session_id: UUID,
    ) -> BrowserSnapshot:
        stored = self.sessions.get(session_id)
        if stored is None or stored[:2] != (principal.session_id, conversation_id):
            raise BrowserSessionNotFound("Browser session not found.")
        return BrowserSnapshot(page=stored[2], png=b"\x89PNG\r\n\x1a\n")

    async def close_session(
        self,
        *,
        principal: PrincipalContext,
        conversation_id: UUID,
        session_id: UUID,
    ) -> None:
        del principal, conversation_id, session_id
        raise NotImplementedError


def _build_client(
    upload_store: TemporaryUploadStore | None = None,
    browser: BrowserSessionService | None = None,
    anonymous_quota_policy: AnonymousQuotaPolicy | None = None,
) -> tuple[TestClient, str, RecordingRuntime]:
    auth_store = InMemoryAuthStore()
    conversations = InMemoryConversationStore()
    authentication = AuthenticationService(auth_store)
    admin = UserAdminService(auth_store)
    issued = asyncio.run(
        admin.create_user(
            username="alice",
            display_name="Alice Example",
            email="alice@mit.edu",
            role="student",
        )
    )
    runtime = RecordingRuntime()
    services = AppServices(
        authentication=authentication,
        agent=CourseAgentService(
            runtime=runtime,
            conversations=conversations,
            uploads=upload_store,
        ),
        conversations=conversations,
        uploads=upload_store,
        browser=browser,
        anonymous_quota_policy=anonymous_quota_policy or AnonymousQuotaPolicy(),
    )
    return (
        TestClient(create_app(services=services), base_url="https://testserver"),
        issued.access_code,
        runtime,
    )


def _login(client: TestClient, access_code: str, *, prefix: str = "") -> None:
    response = client.post(
        f"{prefix}/auth/login",
        json={"username": "alice", "access_code": access_code},
    )
    assert response.status_code == 200


def _create_conversation(
    client: TestClient,
    *,
    prefix: str = "",
    title: str = "Week 1",
) -> str:
    response = client.post(f"{prefix}/conversations", json={"title": title})
    assert response.status_code == 200
    return str(response.json()["id"])


def test_me_creates_isolated_anonymous_session_and_secure_cookie() -> None:
    first, _, _ = _build_client()
    second, _, _ = _build_client()

    response = first.get("/auth/me")
    second_response = second.get("/auth/me")

    assert response.status_code == 200
    assert response.json()["authenticated"] is False
    assert response.json()["roles"] == ["public"]
    assert response.json()["session_id"] != second_response.json()["session_id"]
    set_cookie = response.headers.get("set-cookie", "")
    assert "class_agent_anon=" in set_cookie
    assert "HttpOnly" in set_cookie
    assert "Secure" in set_cookie
    assert "SameSite=lax" in set_cookie
    assert first.get("/auth/me").json()["session_id"] == response.json()["session_id"]


def test_anonymous_conversation_and_run_quotas_return_429() -> None:
    client, _, runtime = _build_client(
        anonymous_quota_policy=AnonymousQuotaPolicy(
            max_conversations=1,
            max_agent_runs=1,
            max_uploads=1,
            max_upload_bytes=100,
        )
    )
    conversation_id = _create_conversation(client)

    conversation_limit = client.post("/conversations", json={"title": "Second"})
    assert conversation_limit.status_code == 429
    assert conversation_limit.headers["retry-after"] == "604800"

    first_run = client.post(
        f"/conversations/{conversation_id}/run",
        json={"text": "first"},
    )
    assert first_run.status_code == 200
    second_run = client.post(
        f"/conversations/{conversation_id}/run",
        json={"text": "second"},
    )
    assert second_run.status_code == 429
    assert len(runtime.contexts) == 1


def test_authenticated_users_are_exempt_from_anonymous_quotas() -> None:
    client, access_code, _ = _build_client(
        anonymous_quota_policy=AnonymousQuotaPolicy(max_conversations=1)
    )
    _login(client, access_code)

    assert client.post("/conversations", json={"title": "First"}).status_code == 200
    assert client.post("/conversations", json={"title": "Second"}).status_code == 200


def test_disabled_anonymous_quotas_allow_local_development_usage() -> None:
    client, _, runtime = _build_client(
        anonymous_quota_policy=AnonymousQuotaPolicy(
            enabled=False,
            max_conversations=1,
            max_agent_runs=1,
        )
    )
    first_conversation_id = _create_conversation(client, title="First")

    assert client.post("/conversations", json={"title": "Second"}).status_code == 200
    assert (
        client.post(
            f"/conversations/{first_conversation_id}/run",
            json={"text": "first"},
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/conversations/{first_conversation_id}/run",
            json={"text": "second"},
        ).status_code
        == 200
    )
    assert len(runtime.contexts) == 2


def test_login_me_and_logout_flow() -> None:
    client, access_code, _ = _build_client()

    login = client.post(
        "/auth/login",
        json={"username": "alice", "access_code": access_code},
    )
    assert login.status_code == 200
    assert login.json()["authenticated"] is True
    assert "class_agent_auth=" in login.headers.get("set-cookie", "")
    assert client.get("/auth/me").json()["username"] == "alice"

    logout = client.post("/auth/logout")
    assert logout.status_code == 204
    assert client.get("/auth/me").json()["authenticated"] is False


def test_public_course_resource_catalog_marks_schedule_provisional() -> None:
    client, _, _ = _build_client()

    response = client.get(f"{API_PREFIX}/course/resources")

    assert response.status_code == 200
    assert [resource["uri"] for resource in response.json()] == [
        "course://syllabus",
        "course://schedule",
        "course://repositories",
        "course://faq",
        "course://instructors",
        "course://application",
    ]
    schedule = next(
        resource for resource in response.json() if resource["uri"] == "course://schedule"
    )
    assert schedule["status"] == "provisional"


def test_authorized_resource_content_is_served_by_uri_without_exposing_paths() -> None:
    client, _, _ = _build_client()

    response = client.get(
        f"{API_PREFIX}/course/resources/content",
        params={"uri": "course://schedule"},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/markdown")
    assert response.headers["x-class-agent-resource-uri"] == "course://schedule"
    assert "| Week 1 (9/15) |" in response.text
    assert "| Week 14 TBD |" in response.text
    assert "shared/course" not in response.text
    assert (
        client.get(
            f"{API_PREFIX}/course/resources/content",
            params={"uri": "course://private-grades"},
        ).status_code
        == 404
    )


def test_registered_course_asset_is_served_by_resource_and_asset_id() -> None:
    client, _, _ = _build_client()

    response = client.get(
        f"{API_PREFIX}/course/resources/asset",
        params={
            "uri": "course://instructors",
            "asset_id": "pattie_maes_portrait",
        },
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/jpeg")
    assert response.headers["x-class-agent-resource-uri"] == "course://instructors"
    assert response.headers["x-class-agent-asset-id"] == "pattie_maes_portrait"
    assert response.content.startswith(b"\xff\xd8\xff")
    assert (
        client.get(
            f"{API_PREFIX}/course/resources/asset",
            params={
                "uri": "course://instructors",
                "asset_id": "invented_portrait",
            },
        ).status_code
        == 404
    )


def test_temporary_upload_route_stores_allowed_file_for_session(tmp_path: Path) -> None:
    client, _, _ = _build_client(FileTemporaryUploadStore(tmp_path / "uploads"))

    response = client.post(
        f"{API_PREFIX}/uploads",
        params={"filename": "face photo.png"},
        content=b"\x89PNG\r\n\x1a\nphoto-data",
        headers={"Content-Type": "image/png"},
    )

    assert response.status_code == 201
    assert response.json()["filename"] == "face photo.png"
    assert response.json()["media_type"] == "image/png"
    upload_directory = tmp_path / "uploads" / response.json()["id"]
    assert (upload_directory / "content.bin").is_file()
    content = client.get(f"{API_PREFIX}/uploads/{response.json()['id']}/content")
    assert content.status_code == 200
    assert content.headers["content-type"] == "image/png"
    assert content.content == b"\x89PNG\r\n\x1a\nphoto-data"
    assert (upload_directory / "metadata.json").is_file()


def test_temporary_upload_route_rejects_unsupported_content(tmp_path: Path) -> None:
    client, _, _ = _build_client(FileTemporaryUploadStore(tmp_path / "uploads"))

    response = client.post(
        f"{API_PREFIX}/uploads",
        params={"filename": "script.js"},
        content=b"alert(1)",
        headers={"Content-Type": "application/javascript"},
    )

    assert response.status_code == 415
    assert response.json()["detail"] == "unsupported file type"


def test_invalid_credentials_are_generic_and_rate_limited() -> None:
    client, _, _ = _build_client()

    for _ in range(5):
        response = client.post(
            "/auth/login",
            json={"username": "alice", "access_code": "wrong-code"},
        )
        assert response.status_code == 401
        assert response.json()["detail"] == "invalid username or access code"

    limited = client.post(
        "/auth/login",
        json={"username": "alice", "access_code": "wrong-code"},
    )
    assert limited.status_code == 429
    assert limited.headers["retry-after"] == "900"


def test_conversation_routes_persist_events_and_enforce_ownership() -> None:
    client, access_code, runtime = _build_client()
    _login(client, access_code)
    conversation_id = _create_conversation(client)

    listed = client.get("/conversations")
    assert [item["id"] for item in listed.json()] == [conversation_id]

    run = client.post(
        f"/conversations/{conversation_id}/run",
        json={"text": "What is due this week?"},
    )
    assert run.status_code == 200
    assert run.json()["output_text"] == "Echo: What is due this week?"
    assert len(run.json()["event_ids"]) == 1
    assert runtime.contexts[0].principal.username == "alice"

    detail = client.get(f"/conversations/{conversation_id}")
    assert [event["type"] for event in detail.json()["events"]] == [
        "user.message",
        "agent.message",
    ]

    public_client = TestClient(client.app, base_url="https://testserver")
    assert public_client.get(f"/conversations/{conversation_id}").status_code == 404
    assert (
        public_client.post(
            f"/conversations/{conversation_id}/run",
            json={"text": "Show Alice's history"},
        ).status_code
        == 404
    )


def test_free_text_application_intent_is_left_to_the_agent() -> None:
    client, _, runtime = _build_client()
    conversation_id = _create_conversation(client, title="Apply")

    with client.stream(
        "POST",
        f"/conversations/{conversation_id}/run/stream",
        json={"text": "i want apply"},
    ) as response:
        assert response.status_code == 200
        body = "".join(response.iter_text())

    assert '"type":"workspace.panel.opened"' not in body
    workspace = cast(dict[str, Any], runtime.contexts[-1].metadata["workspace_state"])
    assert workspace["panels"] == []
    detail = client.get(f"/conversations/{conversation_id}").json()
    assert [event["type"] for event in detail["events"]] == [
        "user.message",
        "agent.message",
    ]


def test_application_information_question_does_not_start_an_application() -> None:
    client, _, runtime = _build_client()
    conversation_id = _create_conversation(client, title="Deadline")

    response = client.post(
        f"/conversations/{conversation_id}/run",
        json={"text": "What is the application deadline?"},
    )

    assert response.status_code == 200
    workspace = cast(dict[str, Any], runtime.contexts[-1].metadata["workspace_state"])
    assert workspace["panels"] == []


def test_stream_route_emits_typed_sse_events() -> None:
    client, access_code, _ = _build_client()
    _login(client, access_code)
    conversation_id = _create_conversation(client, title="Streaming")

    with client.stream(
        "POST",
        f"/conversations/{conversation_id}/run/stream",
        json={"text": "hello"},
    ) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        body = "".join(response.iter_text())

    assert "event: message" in body
    assert "event: done" in body
    assert "agent.progress.delta" not in body
    payloads = [
        json.loads(line.removeprefix("data: "))
        for line in body.splitlines()
        if line.startswith("data: ")
    ]
    assert payloads[0] == {
        "type": "agent.status",
        "stage": "preparing_context",
        "label": "Preparing conversation context",
    }
    assert payloads[1] == {"type": "agent.text.delta", "text": "Echo: "}
    assert payloads[2] == {"type": "agent.text.delta", "text": "hello"}
    assert payloads[3] == {"type": "agent.text.done", "text": "Echo: hello"}
    assert payloads[-1] == {"type": "agent.run.completed"}


def test_workspace_actions_validate_existing_panels_and_persist_events() -> None:
    client, _, _ = _build_client()
    conversation_id = _create_conversation(client)
    opened = client.post(
        f"/conversations/{conversation_id}/run",
        json={"text": "open schedule"},
    )
    assert opened.status_code == 200

    interaction = client.post(
        f"/conversations/{conversation_id}/workspace/interactions",
        json={
            "panel_id": "40000000-0000-4000-8000-000000000001",
            "action": "calendar.select_event",
            "value": "week-1",
        },
    )
    assert interaction.status_code == 200
    assert interaction.json()["type"] == "workspace.interaction"
    assert (
        client.post(
            f"/conversations/{conversation_id}/workspace/interactions",
            json={
                "panel_id": "40000000-0000-4000-8000-000000000001",
                "action": "document.change_page",
                "value": 2,
            },
        ).status_code
        == 400
    )

    closed = client.post(
        f"/conversations/{conversation_id}/workspace/actions",
        json={
            "action": "close",
            "panel_id": "40000000-0000-4000-8000-000000000001",
        },
    )

    assert closed.status_code == 200
    assert closed.json()["type"] == "workspace.panel.closed"
    detail = client.get(f"/conversations/{conversation_id}")
    assert [
        event["type"] for event in detail.json()["events"] if event["type"].startswith("workspace.")
    ] == [
        "workspace.panel.opened",
        "workspace.interaction",
        "workspace.panel.closed",
    ]
    assert (
        client.post(
            f"/conversations/{conversation_id}/workspace/actions",
            json={"action": "focus", "panel_id": str(uuid4())},
        ).status_code
        == 400
    )


def test_application_draft_opens_complete_and_persists_user_edits() -> None:
    client, _, _ = _build_client()
    conversation_id = _create_conversation(client, title="Apply")

    opened = client.post(f"/conversations/{conversation_id}/application-draft")
    assert opened.status_code == 200
    command = opened.json()["payload"]["command"]
    assert command["type"] == "open"
    panel = command["panel"]
    assert panel["component_id"] == "draft-document"
    assert panel["resource_uri"] == "course://application"
    assert panel["state"]["document_kind"] == "course-application"
    assert len(panel["props"]["fields"]) == 13
    assert "limited to 20 students" in panel["props"]["description"]
    assert "Apply by September 4 at midnight" in panel["props"]["description"]
    assert "notifications are sent September 9 at midnight" in panel["props"]["description"]
    assert "document each build in a GitHub repository" in panel["props"]["description"]
    assert [field["id"] for field in panel["props"]["fields"]] == [
        "name",
        "email",
        "github_id",
        "department_research_group_year_of_study_mit",
        "personal_webpage",
        "interests",
        "why_take_this_class",
        "knowledgeable_about",
        "skill_set",
        "registration_status",
        "listener_willing_to_do_weekly_builds",
        "questions_or_comments_for_instructors",
        "photo_upload_id",
    ]
    motivation = next(
        field for field in panel["props"]["fields"] if field["id"] == "why_take_this_class"
    )
    assert motivation["label"] == (
        "Motivation: why this course; what you have built and want to build; "
        "your past project roles"
    )
    photo = next(field for field in panel["props"]["fields"] if field["id"] == "photo_upload_id")
    assert photo["label"] == "Class-only picture that represents you (JPEG, PNG, or WebP)"
    assert all(field["value"] == "" for field in panel["props"]["fields"])

    malformed_github_id = client.post(
        f"/conversations/{conversation_id}/workspace/interactions",
        json={
            "panel_id": panel["id"],
            "action": "draft.change",
            "value": {"field_id": "github_id", "value": "https://github.com/ada"},
        },
    )
    assert malformed_github_id.status_code == 400

    changed = client.post(
        f"/conversations/{conversation_id}/workspace/interactions",
        json={
            "panel_id": panel["id"],
            "action": "draft.change",
            "value": {"field_id": "name", "value": "Ada Example"},
        },
    )
    assert changed.status_code == 200
    assert changed.json()["type"] == "workspace.panel.updated"

    focused = client.post(f"/conversations/{conversation_id}/application-draft")
    assert focused.status_code == 200
    assert focused.json()["payload"]["command"] == {
        "type": "focus",
        "panel_id": panel["id"],
    }

    detail = client.get(f"/conversations/{conversation_id}").json()
    updates = [
        event["payload"]["command"]
        for event in detail["events"]
        if event["type"] == "workspace.panel.updated"
        and event["payload"]["command"]["type"] == "update"
    ]
    assert updates[-1]["props"]["fields"][0] == {
        "id": "name",
        "label": "Name",
        "value": "Ada Example",
        "status": "confirmed",
        "source": "Confirmed by applicant",
    }


def test_application_draft_migrates_unmarked_legacy_field_aliases() -> None:
    client, _, _ = _build_client()
    principal = PrincipalContext.model_validate(client.get("/auth/me").json())
    conversation_id = _create_conversation(client, title="Legacy application")
    panel_id = uuid4()
    legacy = Event(
        type="workspace.panel.opened",
        actor="user",
        principal_user_id=principal.user_id,
        anonymous_session_id=principal.anonymous_session_id,
        conversation_id=UUID(conversation_id),
        payload={
            "command": {
                "type": "open",
                "panel": {
                    "id": str(panel_id),
                    "component_id": "draft-document",
                    "title": "Course application",
                    "props": {
                        "title": "Course application",
                        "status": "draft",
                        "fields": [
                            {
                                "id": "name",
                                "label": "Name",
                                "value": "Ada Example",
                                "status": "confirmed",
                            },
                            {
                                "id": "department",
                                "label": "Background",
                                "value": "MIT Media Lab",
                                "status": "inferred",
                                "source": "Public profile",
                            },
                            {
                                "id": "motivation",
                                "label": "Motivation",
                                "value": "I want to build dependable agents.",
                                "status": "confirmed",
                                "source": "Provided by applicant",
                            },
                        ],
                    },
                    "state": {},
                },
            }
        },
    )
    app = cast(Any, client.app)
    asyncio.run(
        app.state.course_state.services.conversations.append_events(
            UUID(conversation_id),
            [legacy],
        )
    )

    migrated = client.post(f"/conversations/{conversation_id}/application-draft")

    assert migrated.status_code == 200
    command = migrated.json()["payload"]["command"]
    assert command["type"] == "update"
    assert command["panel_id"] == str(panel_id)
    assert command["resource_uri"] == "course://application"
    assert command["state"] == {"document_kind": "course-application"}
    fields = command["props"]["fields"]
    assert len(fields) == 13
    assert fields[0]["value"] == "Ada Example"
    assert fields[3] == {
        "id": "department_research_group_year_of_study_mit",
        "label": "Department / Research Group / Year of Study MIT",
        "value": "MIT Media Lab",
        "status": "inferred",
        "source": "Public profile",
    }
    assert fields[6] == {
        "id": "why_take_this_class",
        "label": (
            "Motivation: why this course; what you have built and want to build; "
            "your past project roles"
        ),
        "value": "I want to build dependable agents.",
        "status": "confirmed",
        "source": "Provided by applicant",
    }


def test_agent_run_repairs_unmarked_model_created_application_draft() -> None:
    client, _, runtime = _build_client()
    principal = PrincipalContext.model_validate(client.get("/auth/me").json())
    conversation_id = UUID(_create_conversation(client, title="Course application"))
    panel_id = uuid4()
    generic_draft = Event(
        type="workspace.panel.opened",
        actor="course-agent",
        anonymous_session_id=principal.anonymous_session_id,
        conversation_id=conversation_id,
        payload={
            "command": {
                "type": "open",
                "panel": {
                    "id": str(panel_id),
                    "component_id": "draft-document",
                    "title": "Course Application — Ada Example",
                    "props": {
                        "title": "Course Application — Ada Example",
                        "fields": [
                            {
                                "id": "email",
                                "label": "Email",
                                "value": "ada@example.edu",
                                "status": "candidate",
                                "source": "Public profile",
                            },
                            {
                                "id": "photo",
                                "label": "Photo",
                                "status": "missing",
                            },
                        ],
                    },
                    "state": {},
                },
            }
        },
    )
    app = cast(Any, client.app)
    asyncio.run(
        app.state.course_state.services.conversations.append_events(
            conversation_id,
            [generic_draft],
        )
    )

    response = client.post(
        f"/conversations/{conversation_id}/run",
        json={"text": "continue"},
    )

    assert response.status_code == 200
    workspace = cast(dict[str, Any], runtime.contexts[-1].metadata["workspace_state"])
    panel = cast(list[dict[str, Any]], workspace["panels"])[0]
    assert panel["resource_uri"] == "course://application"
    assert panel["state"] == {"document_kind": "course-application"}
    fields = panel["props"]["fields"]
    assert len(fields) == 13
    assert fields[1] == {
        "id": "email",
        "label": "Email",
        "value": "ada@example.edu",
        "status": "candidate",
        "source": "Public profile",
    }
    detail = client.get(f"/conversations/{conversation_id}").json()
    assert [event["type"] for event in detail["events"]] == [
        "workspace.panel.opened",
        "workspace.panel.updated",
        "user.message",
        "agent.message",
    ]


def test_visual_composition_records_only_bounded_editable_field_changes() -> None:
    client, _, _ = _build_client()
    principal = PrincipalContext.model_validate(client.get("/auth/me").json())
    conversation_id = UUID(_create_conversation(client, title="Profile draft"))
    panel_id = uuid4()
    opened = Event(
        type="workspace.panel.opened",
        actor="course-agent",
        anonymous_session_id=principal.anonymous_session_id,
        conversation_id=conversation_id,
        payload={
            "command": {
                "type": "open",
                "panel": {
                    "id": str(panel_id),
                    "component_id": "visual-composition",
                    "props": {
                        "root_id": "profile",
                        "elements": [
                            {
                                "id": "profile",
                                "type": "group",
                                "children": ["name", "bio"],
                            },
                            {"id": "name", "type": "heading", "text": "Ada"},
                            {"id": "bio", "type": "textarea", "label": "Biography"},
                        ],
                    },
                    "state": {},
                },
            }
        },
    )
    app = cast(Any, client.app)
    asyncio.run(
        app.state.course_state.services.conversations.append_events(
            conversation_id,
            [opened],
        )
    )

    changed = client.post(
        f"/conversations/{conversation_id}/workspace/interactions",
        json={
            "panel_id": str(panel_id),
            "action": "visual.change",
            "value": {"element_id": "bio", "value": "Updated biography"},
        },
    )
    immutable = client.post(
        f"/conversations/{conversation_id}/workspace/interactions",
        json={
            "panel_id": str(panel_id),
            "action": "visual.change",
            "value": {"element_id": "name", "value": "Changed heading"},
        },
    )

    assert changed.status_code == 200
    assert changed.json()["payload"]["action"] == "visual.change"
    assert immutable.status_code == 400


def test_browser_snapshot_is_scoped_to_principal_and_conversation() -> None:
    browser = SnapshotBrowserService()
    client, _, _ = _build_client(browser=browser)
    principal = PrincipalContext.model_validate(client.get("/auth/me").json())
    conversation_id = _create_conversation(client, title="Browser")
    other_conversation_id = _create_conversation(client, title="Other")
    page = asyncio.run(
        browser.open(
            principal=principal,
            conversation_id=UUID(conversation_id),
            url="https://example.com/",
        )
    )

    snapshot = client.get(f"/conversations/{conversation_id}/browser/{page.session_id}/snapshot")
    wrong_conversation = client.get(
        f"/conversations/{other_conversation_id}/browser/{page.session_id}/snapshot"
    )
    other_principal = TestClient(client.app, base_url="https://testserver")
    wrong_principal = other_principal.get(
        f"/conversations/{conversation_id}/browser/{page.session_id}/snapshot"
    )

    assert snapshot.status_code == 200
    assert snapshot.headers["content-type"] == "image/png"
    assert snapshot.headers["cache-control"] == "private, no-store"
    assert snapshot.content.startswith(b"\x89PNG")
    assert wrong_conversation.status_code == 404
    assert wrong_principal.status_code == 404


def test_browser_preview_is_scoped_to_principal_and_conversation() -> None:
    browser = SnapshotBrowserService()
    client, _, _ = _build_client(browser=browser)
    principal = PrincipalContext.model_validate(client.get("/auth/me").json())
    conversation_id = _create_conversation(client, title="Previews")
    other_conversation_id = _create_conversation(client, title="Other")
    preview = asyncio.run(
        browser.create_preview(
            principal=principal,
            conversation_id=UUID(conversation_id),
            url="https://example.com/",
        )
    )

    snapshot = client.get(
        f"/conversations/{conversation_id}/browser/previews/{preview.preview_id}/snapshot"
    )
    wrong_conversation = client.get(
        f"/conversations/{other_conversation_id}/browser/previews/{preview.preview_id}/snapshot"
    )
    other_principal = TestClient(client.app, base_url="https://testserver")
    wrong_principal = other_principal.get(
        f"/conversations/{conversation_id}/browser/previews/{preview.preview_id}/snapshot"
    )

    assert snapshot.status_code == 200
    assert snapshot.headers["content-type"] == "image/png"
    assert snapshot.headers["cache-control"] == "private, no-store"
    assert snapshot.content.startswith(b"\x89PNG")
    assert wrong_conversation.status_code == 404
    assert wrong_principal.status_code == 404


def test_browser_scroll_recovers_a_stale_post_restart_session_in_place() -> None:
    browser = SnapshotBrowserService()
    client, _, _ = _build_client(browser=browser)
    principal = PrincipalContext.model_validate(client.get("/auth/me").json())
    conversation_id = UUID(_create_conversation(client, title="Recovered browser"))
    panel_id = uuid4()
    stale_session_id = uuid4()
    opened = Event(
        type="workspace.panel.opened",
        actor="course-agent",
        anonymous_session_id=principal.anonymous_session_id,
        conversation_id=conversation_id,
        payload={
            "command": {
                "type": "open",
                "panel": {
                    "id": str(panel_id),
                    "component_id": "browser-viewer",
                    "title": "Example",
                    "props": {
                        "session_id": str(stale_session_id),
                        "url": "https://example.com/",
                        "title": "Example",
                        "revision": 1,
                        "viewport_width": 1280,
                        "viewport_height": 800,
                    },
                    "state": {},
                },
            }
        },
    )
    app = cast(Any, client.app)
    asyncio.run(
        app.state.course_state.services.conversations.append_events(
            conversation_id,
            [opened],
        )
    )

    response = client.post(
        f"/conversations/{conversation_id}/browser/{stale_session_id}/scroll",
        json={"panel_id": str(panel_id), "delta_y": 640},
    )

    assert response.status_code == 200
    command = response.json()["payload"]["command"]
    assert command["type"] == "update"
    assert command["panel_id"] == str(panel_id)
    assert command["props"]["session_id"] != str(stale_session_id)
    assert command["props"]["revision"] == 2


def test_browser_click_navigates_and_exposes_the_current_page_to_the_next_turn() -> None:
    browser = SnapshotBrowserService()
    client, _, runtime = _build_client(browser=browser)
    principal = PrincipalContext.model_validate(client.get("/auth/me").json())
    conversation_id = UUID(_create_conversation(client, title="Clickable browser"))
    panel_id = uuid4()
    page = asyncio.run(
        browser.open(
            principal=principal,
            conversation_id=conversation_id,
            url="https://example.com/",
        )
    )
    opened = Event(
        type="workspace.panel.opened",
        actor="course-agent",
        anonymous_session_id=principal.anonymous_session_id,
        conversation_id=conversation_id,
        payload={
            "command": {
                "type": "open",
                "panel": {
                    "id": str(panel_id),
                    "component_id": "browser-viewer",
                    "title": page.title,
                    "props": {
                        "session_id": str(page.session_id),
                        "url": page.url,
                        "title": page.title,
                        "revision": page.revision,
                        "viewport_width": page.viewport_width,
                        "viewport_height": page.viewport_height,
                    },
                    "state": {},
                },
            }
        },
    )
    app = cast(Any, client.app)
    asyncio.run(
        app.state.course_state.services.conversations.append_events(
            conversation_id,
            [opened],
        )
    )

    clicked = client.post(
        f"/conversations/{conversation_id}/browser/{page.session_id}/click",
        json={"panel_id": str(panel_id), "x": 320, "y": 480},
    )
    followed_up = client.post(
        f"/conversations/{conversation_id}/run",
        json={"text": "Which page am I on?"},
    )

    assert clicked.status_code == 200
    assert clicked.json()["payload"]["command"]["props"]["url"] == ("https://example.com/clicked")
    assert followed_up.status_code == 200
    workspace = runtime.contexts[-1].metadata["workspace_state"]
    assert isinstance(workspace, dict)
    panels = workspace["panels"]
    assert isinstance(panels, list)
    panel = panels[0]
    assert isinstance(panel, dict)
    props = panel["props"]
    assert isinstance(props, dict)
    assert props["url"] == "https://example.com/clicked"


def test_versioned_agent_run_supports_json_and_streaming() -> None:
    client, access_code, _ = _build_client()
    _login(client, access_code, prefix=API_PREFIX)
    conversation_id = _create_conversation(client, prefix=API_PREFIX)

    payload = {"conversation_id": conversation_id, "text": "hello"}
    response = client.post(f"{API_PREFIX}/agent/run", json=payload)
    assert response.status_code == 200
    assert response.json()["output_text"] == "Echo: hello"

    streamed = client.post(
        f"{API_PREFIX}/agent/run",
        json=payload,
        headers={"Accept": "text/event-stream"},
    )
    assert streamed.status_code == 200
    assert "event: message" in streamed.text


def test_unknown_conversation_returns_404_before_starting_a_stream() -> None:
    client, _, runtime = _build_client()
    unknown = uuid4()

    regular = client.post(
        f"/conversations/{unknown}/run",
        json={"text": "hello"},
    )
    streamed = client.post(
        f"/conversations/{unknown}/run/stream",
        json={"text": "hello"},
    )

    assert regular.status_code == 404
    assert streamed.status_code == 404
    assert runtime.contexts == []


def test_expired_authenticated_session_falls_back_to_anonymous() -> None:
    class MutableClock:
        def __init__(self) -> None:
            self.value = datetime.now(UTC)

        def __call__(self) -> datetime:
            return self.value

    clock = MutableClock()
    auth_store = InMemoryAuthStore()
    authentication = AuthenticationService(auth_store, clock=clock)
    admin = UserAdminService(auth_store, clock=clock)
    issued = asyncio.run(
        admin.create_user(
            username="alice",
            display_name="Alice Example",
            email="alice@mit.edu",
            role="student",
        )
    )
    conversations = InMemoryConversationStore()
    app = create_app(
        services=AppServices(
            authentication=authentication,
            agent=CourseAgentService(
                runtime=RecordingRuntime(),
                conversations=conversations,
            ),
            conversations=conversations,
        )
    )
    client = TestClient(app, base_url="https://testserver")
    _login(client, issued.access_code)

    clock.value += timedelta(days=30)
    me = client.get("/auth/me")

    assert me.status_code == 200
    assert me.json()["authenticated"] is False
    cookies = me.headers.get_list("set-cookie")
    assert any(
        cookie.startswith("class_agent_auth=") and "Max-Age=0" in cookie for cookie in cookies
    )
    assert any(cookie.startswith("class_agent_anon=") for cookie in cookies)


def test_blank_messages_and_unknown_fields_are_rejected() -> None:
    client, _, _ = _build_client()
    conversation_id = _create_conversation(client)

    blank = client.post(
        f"/conversations/{conversation_id}/run",
        json={"text": "   "},
    )
    extra = client.post(
        f"/conversations/{conversation_id}/run",
        json={"text": "hello", "user_id": str(uuid4())},
    )

    assert blank.status_code == 422
    assert extra.status_code == 422


def test_openapi_documents_only_versioned_routes() -> None:
    client, _, _ = _build_client()

    paths = client.get("/openapi.json").json()["paths"]

    assert f"{API_PREFIX}/auth/login" in paths
    assert "/auth/login" not in paths
