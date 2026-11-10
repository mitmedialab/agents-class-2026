"""HTTP ownership and validation tests against the real Course Agent app."""

import asyncio
from pathlib import Path
from typing import cast

from fastapi.testclient import TestClient

from agent_core import AgentRuntime
from course_server.agent import CourseAgentService, InMemoryConversationStore
from course_server.api import AppServices, create_app
from course_server.auth import AuthenticationService, InMemoryAuthStore, UserAdminService
from course_server.peer_discovery.service import PeerDiscovery
from course_server.peer_discovery.store import PeerStore
from course_server.student_projects import StudentProjectCatalog


def app_and_codes(tmp_path: Path) -> tuple[object, str, str]:
    store = InMemoryAuthStore()
    admin = UserAdminService(store)

    async def users() -> tuple[str, str]:
        a = await admin.create_user(
            username="alice", display_name="Alice", email="alice@example.edu", role="student"
        )
        b = await admin.create_user(
            username="bob", display_name="Bob", email="bob@example.edu", role="student"
        )
        return a.access_code, b.access_code

    alice, bob = asyncio.run(users())
    conversations = InMemoryConversationStore()
    peer = PeerDiscovery(PeerStore(tmp_path), cast(StudentProjectCatalog, object()), lambda _: "")
    app = create_app(
        services=AppServices(
            authentication=AuthenticationService(store),
            conversations=conversations,
            agent=CourseAgentService(
                runtime=cast(AgentRuntime, object()), conversations=conversations
            ),
            peer_discovery=peer,
        )
    )
    return app, alice, bob


def test_profile_routes_are_private_and_reject_model_chosen_identity(tmp_path: Path) -> None:
    app, alice_code, bob_code = app_and_codes(tmp_path)
    with TestClient(app, base_url="https://testserver") as alice:  # type: ignore[arg-type]
        assert alice.get("/api/v1/peer-discovery").status_code == 403
        assert (
            alice.post(
                "/api/v1/auth/login", json={"username": "alice", "access_code": alice_code}
            ).status_code
            == 200
        )
        profile = {"goal": "Voice agent", "challenges": [], "interests": [], "confirmed": True}
        assert (
            alice.put(
                "/api/v1/peer-discovery/profile", json={**profile, "user_id": "bob"}
            ).status_code
            == 422
        )
        assert alice.put("/api/v1/peer-discovery/profile", json=profile).status_code == 200
        with TestClient(app, base_url="https://testserver") as bob:  # type: ignore[arg-type]
            assert (
                bob.post(
                    "/api/v1/auth/login", json={"username": "bob", "access_code": bob_code}
                ).status_code
                == 200
            )
            assert bob.get("/api/v1/peer-discovery").json()["memory"]["profile"]["goal"] == ""
            bob.delete("/api/v1/peer-discovery/memory")
        assert (
            alice.get("/api/v1/peer-discovery").json()["memory"]["profile"]["goal"] == "Voice agent"
        )
        assert (
            alice.delete("/api/v1/peer-discovery/memory").json()["memory"]["profile"]["goal"] == ""
        )


def test_unconfirmed_memory_and_unknown_feedback_are_rejected(tmp_path: Path) -> None:
    app, code, _ = app_and_codes(tmp_path)
    with TestClient(app, base_url="https://testserver") as client:  # type: ignore[arg-type]
        client.post("/api/v1/auth/login", json={"username": "alice", "access_code": code})
        assert (
            client.put(
                "/api/v1/peer-discovery/profile", json={"goal": "Guess", "confirmed": False}
            ).status_code
            == 422
        )
        assert (
            client.post(
                "/api/v1/peer-discovery/feedback",
                json={"build_id": "not-mine", "rating": "helpful"},
            ).status_code
            == 400
        )
