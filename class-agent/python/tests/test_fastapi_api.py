from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi.testclient import TestClient

from agent_core import AgentContext, AgentInput, AgentResult, Event
from course_server.agent import CourseAgentService, InMemoryConversationStore
from course_server.api import API_PREFIX, AppServices, create_app
from course_server.auth import AuthenticationService, InMemoryAuthStore, UserAdminService
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
        return AgentResult(
            input_id=input.id,
            conversation_id=context.conversation_id,
            output_text=output,
            events=[
                Event(
                    type="agent.message",
                    actor="course-agent",
                    principal_user_id=context.principal.user_id,
                    anonymous_session_id=context.principal.anonymous_session_id,
                    conversation_id=context.conversation_id,
                    payload={"text": output},
                )
            ],
        )

    async def run_observed(
        self,
        *,
        context: AgentContext,
        input: AgentInput,
        event_observer: Any,
        text_delta_observer: Any = None,
        progress_delta_observer: Any = None,
    ) -> AgentResult:
        result = await self.run(context=context, input=input)
        if progress_delta_observer is not None:
            progress_delta_observer("I'll prepare a concise response.")
        if text_delta_observer is not None:
            text_delta_observer("Echo: ")
            text_delta_observer(input.text)
        for event in result.events:
            event_observer(event)
        return result


def _build_client(
    upload_store: TemporaryUploadStore | None = None,
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
        agent=CourseAgentService(runtime=runtime, conversations=conversations),
        conversations=conversations,
        uploads=upload_store,
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
    assert payloads[1] == {
        "type": "agent.progress.delta",
        "text": "I'll prepare a concise response.",
    }
    assert payloads[2] == {"type": "agent.text.delta", "text": "Echo: "}
    assert payloads[3] == {"type": "agent.text.delta", "text": "hello"}
    assert payloads[4] == {"type": "agent.text.done", "text": "Echo: hello"}
    assert payloads[-1] == {"type": "agent.run.completed"}


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
