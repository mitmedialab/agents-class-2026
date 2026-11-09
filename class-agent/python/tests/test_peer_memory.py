"""Student-owned memories, classmate matching and confirmed introductions (fictional users)."""

from __future__ import annotations

import asyncio
import os
from uuid import UUID, uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import sql
from test_course_direct_messages import _schema_url
from test_fastapi_api import RecordingRuntime

from agent_core import AgentContext, Event, Memory, PrincipalContext
from course_server.agent import CourseAgentService, InMemoryConversationStore
from course_server.agent.capabilities import (
    PEER_MEMORY_TOOL_IDS,
    CourseCapabilityPolicy,
    ToolExecutionContext,
    ToolValidationError,
)
from course_server.api import AppServices, create_app
from course_server.auth import AuthenticationService, InMemoryAuthStore, UserAdminService
from course_server.migrations import apply_migrations
from course_server.peer_memory import (
    HELPER_OPEN_REQUEST_LIMIT,
    FindPeerHelpersTool,
    InMemoryPeerMemoryStore,
    MemoryUpdate,
    PeerIdentity,
    PeerMemoryAccessDenied,
    PeerMemoryConflict,
    PeerMemoryNotFound,
    PeerMemoryService,
    PostgresPeerMemoryStore,
    RequestPeerIntroductionTool,
    SaveMyMemoryTool,
)
from course_server.postgres.auth_store import PostgresAuthStore, create_auth_pool
from runtime_smolagents.runtime import _agent_instructions

ADA, BO, CY, ELI, STAFF = (uuid4() for _ in range(5))


def principal(user_id: UUID | None, username: str, role: str = "student") -> PrincipalContext:
    if user_id is None:
        return PrincipalContext(
            authenticated=False, anonymous_session_id=uuid4(), roles=["public"], session_id=uuid4()
        )
    return PrincipalContext(
        authenticated=True,
        user_id=user_id,
        username=username,
        display_name=username.title(),
        roles=["public", role],
        session_id=uuid4(),
    )


def _store() -> InMemoryPeerMemoryStore:
    return InMemoryPeerMemoryStore(
        {
            ADA: PeerIdentity(ADA, "ada", "Ada", "student", True),
            BO: PeerIdentity(BO, "bo", "Bo", "student", True),
            CY: PeerIdentity(CY, "cy", "Cy", "student", True),
            ELI: PeerIdentity(ELI, "eli", "Eli", "student", True),
            STAFF: PeerIdentity(STAFF, "ta", "Ta", "ta", True),
        }
    )


def _service(store: InMemoryPeerMemoryStore) -> PeerMemoryService:
    # Eli is inactive in the roster even though the account row still says active.
    return PeerMemoryService(store, student_access=lambda username: username != "eli")


def _save(
    service: PeerMemoryService, who: PrincipalContext, kind: str, text: str, shared: bool
) -> Memory:
    return asyncio.run(
        service.save_mine(
            who,
            kind=kind,  # type: ignore[arg-type]
            content=text,
            privacy="course_private" if shared else "personal",
            source_event_ids=[],
            source_excerpt=None,
        )
    )


def test_memories_are_owned_and_only_shared_items_reach_classmates() -> None:
    store = _store()
    service = _service(store)
    ada, bo, eli = principal(ADA, "ada"), principal(BO, "bo"), principal(ELI, "eli")
    _save(service, bo, "can_help", "Got MCP OAuth working with the course server.", True)
    _save(service, bo, "background", "Bo is anxious about public speaking.", False)
    _save(service, bo, "project", "Bo builds a plant-watering agent.", True)
    store.memories[uuid4()] = Memory(
        user_id=ELI, kind="can_help", content="Eli knows smolagents.", privacy="course_private"
    )
    del eli

    offers = asyncio.run(service.classmate_offers(ada))
    assert [offer["username"] for offer in offers] == ["bo"]
    flattened = repr(offers)
    assert "MCP OAuth" in flattened and "plant-watering" in flattened
    assert "public speaking" not in flattened
    assert asyncio.run(service.list_mine(ada)) == []

    bo_memory = asyncio.run(service.list_mine(bo))[0]
    with pytest.raises(PeerMemoryNotFound):
        asyncio.run(service.update_mine(ada, bo_memory.id, MemoryUpdate(content="hijack")))
    with pytest.raises(PeerMemoryNotFound):
        asyncio.run(service.forget_mine(ada, bo_memory.id))
    for denied in (principal(None, "x"), principal(STAFF, "ta", "ta"), principal(ELI, "eli")):
        with pytest.raises(PeerMemoryAccessDenied):
            asyncio.run(service.list_mine(denied))


def test_student_edit_changes_visibility_and_marks_memory() -> None:
    store = _store()
    service = _service(store)
    bo = principal(BO, "bo")
    memory = _save(service, bo, "can_help", "Knows MCP OAuth.", False)
    assert asyncio.run(service.classmate_offers(principal(ADA, "ada"))) == []
    updated = asyncio.run(
        service.update_mine(bo, memory.id, MemoryUpdate(privacy="course_private"))
    )
    assert updated.metadata["edited_by_student"] is True
    assert len(asyncio.run(service.classmate_offers(principal(ADA, "ada")))) == 1
    asyncio.run(service.forget_mine(bo, memory.id))
    assert asyncio.run(service.classmate_offers(principal(ADA, "ada"))) == []


def test_introduction_requires_sender_click_and_helper_answer() -> None:
    store = _store()
    service = _service(store)
    ada, bo, cy = principal(ADA, "ada"), principal(BO, "bo"), principal(CY, "cy")
    _save(service, bo, "can_help", "Knows MCP OAuth.", True)

    with pytest.raises(PeerMemoryNotFound):
        asyncio.run(service.draft_introduction(ada, helper_username="cy", topic="t", message="m"))
    with pytest.raises(PeerMemoryNotFound):
        asyncio.run(service.draft_introduction(bo, helper_username="bo", topic="t", message="m"))

    intro, _ = asyncio.run(
        service.draft_introduction(ada, helper_username="bo", topic="MCP auth", message="Hi Bo")
    )
    assert asyncio.run(service.introductions_view(bo)) == []  # drafts are not delivered
    for actor, action in ((bo, "send"), (cy, "send"), (ada, "accept")):
        with pytest.raises(PeerMemoryNotFound):
            asyncio.run(service.transition(actor, intro.id, action))  # type: ignore[arg-type]
    asyncio.run(service.transition(ada, intro.id, "send"))
    incoming = asyncio.run(service.introductions_view(bo))
    assert incoming[0]["direction"] == "incoming" and incoming[0]["other"] == {
        "username": "ada",
        "display_name": "Ada",
    }
    asyncio.run(service.transition(bo, intro.id, "decline"))
    assert asyncio.run(service.introductions_view(ada))[0]["status"] == "unavailable"
    with pytest.raises(PeerMemoryConflict):
        asyncio.run(service.transition(bo, intro.id, "accept"))


def test_helper_request_cap_protects_classmates() -> None:
    store = _store()
    service = _service(store)
    bo = principal(BO, "bo")
    _save(service, bo, "can_help", "Knows MCP OAuth.", True)
    for requester in (principal(ADA, "ada"), principal(CY, "cy"))[:HELPER_OPEN_REQUEST_LIMIT]:
        intro, _ = asyncio.run(
            service.draft_introduction(requester, helper_username="bo", topic="t", message="m")
        )
        asyncio.run(service.transition(requester, intro.id, "send"))
    offers = asyncio.run(service.classmate_offers(principal(ADA, "ada")))
    assert offers[0]["accepting_requests"] is False
    with pytest.raises(PeerMemoryConflict):
        asyncio.run(
            service.draft_introduction(
                principal(ADA, "ada"), helper_username="bo", topic="t", message="m"
            )
        )


def test_peer_tools_are_student_only() -> None:
    service = _service(_store())
    policy = CourseCapabilityPolicy(peer_memory_access=service.can_access)
    assert set(PEER_MEMORY_TOOL_IDS) <= set(policy.authorize(principal(ADA, "ada")).tool_ids)
    for denied in (principal(None, "x"), principal(STAFF, "ta", "ta"), principal(ELI, "eli")):
        assert not set(PEER_MEMORY_TOOL_IDS) & set(policy.authorize(denied).tool_ids)
    assert not set(PEER_MEMORY_TOOL_IDS) & set(
        CourseCapabilityPolicy().authorize(principal(ADA, "ada")).tool_ids
    )


def test_save_tool_records_source_message_and_draft_opens_people_panel() -> None:
    store = _store()
    service = _service(store)
    conversations = InMemoryConversationStore()
    ada = principal(ADA, "ada")
    conversation = asyncio.run(
        CourseAgentService(
            runtime=RecordingRuntime(), conversations=conversations
        ).create_conversation(ada)
    )
    message = Event(
        type="user.message",
        actor="user",
        principal_user_id=ADA,
        conversation_id=conversation.id,
        payload={"text": "I'm a mechanical engineer and I learn best from hardware analogies."},
    )
    asyncio.run(conversations.append_events(conversation.id, [message]))
    context = ToolExecutionContext(
        principal=ada, conversation_id=conversation.id, permitted_resource_uris=frozenset()
    )
    result = asyncio.run(
        SaveMyMemoryTool(service, conversations).execute(
            {"kind": "preference", "content": "Learns best from hardware analogies."}, context
        )
    )
    saved = asyncio.run(service.list_mine(ada))[0]
    assert saved.source_event_ids == [message.id] and saved.privacy == "personal"
    assert "mechanical engineer" in str(saved.metadata["source_excerpt"])
    assert result.emitted_events[0].type == "memory.created"
    with pytest.raises(ToolValidationError):
        asyncio.run(
            SaveMyMemoryTool(service, conversations).execute(
                {"kind": "preference", "content": "x", "user_id": str(BO)}, context
            )
        )

    _save(service, principal(BO, "bo"), "can_help", "Knows MCP OAuth.", True)
    found = asyncio.run(FindPeerHelpersTool(service).execute({}, context))
    assert isinstance(found.content, dict) and found.content["classmates"]
    drafted = asyncio.run(
        RequestPeerIntroductionTool(service).execute(
            {"helper_username": "bo", "topic": "MCP auth", "message": "Hi Bo"}, context
        )
    )
    assert drafted.emitted_events[0].type == "workspace.panel.opened"
    assert "people-overview" in repr(drafted.emitted_events[0].payload)


def test_agent_context_carries_only_own_memories_and_prompt_explains_them() -> None:
    store = _store()
    service = _service(store)
    _save(service, principal(ADA, "ada"), "preference", "Prefers hardware analogies.", False)
    _save(service, principal(BO, "bo"), "background", "Bo's private note.", False)
    runtime = RecordingRuntime()
    conversations = InMemoryConversationStore()
    agent = CourseAgentService(runtime=runtime, conversations=conversations, memories=service)
    ada = principal(ADA, "ada")
    conversation = asyncio.run(agent.create_conversation(ada))
    asyncio.run(agent.run(principal=ada, conversation_id=conversation.id, text="hello"))
    context: AgentContext = runtime.contexts[0]
    assert [memory.content for memory in context.selected_memories] == [
        "Prefers hardware analogies."
    ]
    prompted = _agent_instructions(
        context.model_copy(update={"permitted_tool_ids": ["memory.save_mine"]}), (), ""
    )
    assert "Prefers hardware analogies." in prompted and "Bo's private note" not in prompted
    assert "Prefers hardware analogies." not in _agent_instructions(context, (), "")


def _client() -> tuple[TestClient, PeerMemoryService, dict[str, str], dict[str, UUID]]:
    auth_store = InMemoryAuthStore()
    admin = UserAdminService(auth_store)
    codes: dict[str, str] = {}
    ids: dict[str, UUID] = {}
    store = InMemoryPeerMemoryStore()
    for name in ("ada", "bo"):
        issued = asyncio.run(
            admin.create_user(
                username=name,
                display_name=name.title(),
                email=f"{name}@example.edu",
                role="student",
            )
        )
        codes[name] = issued.access_code
        ids[name] = issued.user.id
        store.identities[issued.user.id] = PeerIdentity(
            issued.user.id, name, name.title(), "student", True
        )
    service = PeerMemoryService(store)
    conversations = InMemoryConversationStore()
    services = AppServices(
        authentication=AuthenticationService(auth_store),
        agent=CourseAgentService(runtime=RecordingRuntime(), conversations=conversations),
        conversations=conversations,
        peer_memory=service,
    )
    return (
        TestClient(create_app(services=services), base_url="https://testserver"),
        service,
        codes,
        ids,
    )


def test_people_routes_are_owner_scoped() -> None:
    client, service, codes, ids = _client()
    bo = principal(ids["bo"], "bo")
    memory = _save(service, bo, "can_help", "Knows MCP OAuth.", False)

    client.post("/api/v1/auth/login", json={"username": "ada", "access_code": codes["ada"]})
    assert client.get("/api/v1/people/mine").json() == {"memories": [], "introductions": []}
    assert (
        client.patch(f"/api/v1/people/mine/memories/{memory.id}", json={"content": "x"}).status_code
        == 404
    )
    assert client.delete(f"/api/v1/people/mine/memories/{memory.id}").status_code == 404

    client.post("/api/v1/auth/logout")
    client.cookies.clear()
    client.post("/api/v1/auth/login", json={"username": "bo", "access_code": codes["bo"]})
    response = client.patch(
        f"/api/v1/people/mine/memories/{memory.id}",
        json={"privacy": "course_private", "content": "Knows MCP OAuth and FastAPI."},
    )
    assert response.status_code == 200
    assert response.json()["memory"]["privacy"] == "course_private"
    assert response.headers["cache-control"] == "private, no-store"
    assert (
        client.patch(
            f"/api/v1/people/mine/memories/{memory.id}", json={"user_id": str(ids["ada"])}
        ).status_code
        == 422
    )
    assert client.delete(f"/api/v1/people/mine/memories/{memory.id}").status_code == 204
    assert client.get("/api/v1/people/mine").json()["memories"] == []
    assert (
        client.post(f"/api/v1/people/mine/introductions/{uuid4()}", json={"action": "send"})
    ).status_code == 404


TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")


@pytest.mark.postgres
@pytest.mark.skipif(TEST_DATABASE_URL is None, reason="TEST_DATABASE_URL is not configured")
def test_postgres_peer_memory_store_matches_in_memory_rules() -> None:
    assert TEST_DATABASE_URL is not None
    schema_name = f"test_peer_memory_{uuid4().hex}"
    with psycopg.connect(TEST_DATABASE_URL) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema_name)))
    database_url = _schema_url(TEST_DATABASE_URL, schema_name)

    async def scenario() -> None:
        assert apply_migrations(database_url)[-1] == "0019_peer_memories"
        pool = create_auth_pool(database_url)
        await pool.open()
        try:
            admin = UserAdminService(PostgresAuthStore(pool))
            users = {
                name: (
                    await admin.create_user(
                        username=name,
                        display_name=name.title(),
                        email=f"{name}@example.edu",
                        role="student",
                    )
                ).user
                for name in ("ada", "bo")
            }
            service = PeerMemoryService(PostgresPeerMemoryStore(pool))
            ada = principal(users["ada"].id, "ada")
            bo = principal(users["bo"].id, "bo")
            source = uuid4()
            shared = await service.save_mine(
                bo,
                kind="can_help",
                content="Knows  MCP OAuth.",
                privacy="course_private",
                source_event_ids=[source],
                source_excerpt="I fixed MCP OAuth last week",
            )
            await service.save_mine(
                bo,
                kind="background",
                content="Private note.",
                privacy="personal",
                source_event_ids=[],
                source_excerpt=None,
            )
            stored = await service.list_mine(bo)
            assert {item.content for item in stored} == {"Knows MCP OAuth.", "Private note."}
            assert next(i for i in stored if i.id == shared.id).source_event_ids == [source]
            offers = await service.classmate_offers(ada)
            assert offers[0]["can_help"] == ["Knows MCP OAuth."]
            assert "Private note" not in repr(offers)
            intro, _ = await service.draft_introduction(
                ada, helper_username="BO", topic="MCP", message="Hi"
            )
            await service.transition(ada, intro.id, "send")
            await service.transition(bo, intro.id, "accept")
            assert (await service.introductions_view(ada))[0]["status"] == "accepted"
            updated = await service.update_mine(bo, shared.id, MemoryUpdate(privacy="personal"))
            assert updated.metadata["edited_by_student"] is True
            assert await service.classmate_offers(ada) == []
            await service.forget_mine(bo, shared.id)
            with pytest.raises(PeerMemoryNotFound):
                await service.forget_mine(bo, shared.id)
        finally:
            await pool.close()

    try:
        asyncio.run(scenario())
    finally:
        with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as connection:
            connection.execute(
                sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema_name))
            )
