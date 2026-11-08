from __future__ import annotations

import asyncio
from typing import Literal
from uuid import uuid4

import pytest
from pydantic import JsonValue

from agent_core import Memory, PrincipalContext
from course_server.agent.capabilities import (
    SAVE_MY_MEMORY_TOOL_ID,
    CapabilityCatalogError,
    CourseCapabilityPolicy,
    FileResourceProvider,
    ToolExecutionContext,
    ToolValidationError,
)
from course_server.agent.memory_tool import SaveMyMemoryTool
from course_server.agent_cli import build_runtime
from course_server.config import AgentSettings


class RecordingMemories:
    def __init__(self) -> None:
        self.saved: list[Memory] = []

    async def save(self, memory: Memory) -> None:
        self.saved.append(memory)


def _student(role: Literal["student", "ta", "instructor", "admin"] = "student") -> PrincipalContext:
    return PrincipalContext(
        authenticated=True,
        user_id=uuid4(),
        username="alice",
        roles=["public", role],
        session_id=uuid4(),
    )


def _anonymous() -> PrincipalContext:
    session_id = uuid4()
    return PrincipalContext(
        authenticated=False,
        anonymous_session_id=session_id,
        roles=["public"],
        session_id=session_id,
    )


def _save(
    memories: RecordingMemories,
    principal: PrincipalContext,
    arguments: dict[str, JsonValue],
) -> dict[str, JsonValue]:
    result = asyncio.run(
        SaveMyMemoryTool(memories).execute(
            arguments,
            ToolExecutionContext(
                principal=principal,
                conversation_id=uuid4(),
                permitted_resource_uris=frozenset(),
            ),
        )
    )
    assert isinstance(result.content, dict)
    assert result.storage_policy == "server_summary"
    assert result.summary is not None and "hints" not in result.summary
    return result.content


def test_saves_under_the_principal_and_returns_only_the_id() -> None:
    memories = RecordingMemories()
    principal = _student()

    content = _save(memories, principal, {"kind": " preference ", "content": " Prefers hints "})

    saved = memories.saved[0]
    assert saved.user_id == principal.user_id
    assert (saved.kind, saved.content) == ("preference", "Prefers hints")
    assert saved.privacy == "personal"
    assert saved.metadata == {"source": "agent"}
    assert saved.source_event_ids == []
    assert content == {"saved": True, "memory_id": str(saved.id)}


@pytest.mark.parametrize("extra", ["user_id", "owner"])
def test_model_cannot_supply_an_owner(extra: str) -> None:
    memories = RecordingMemories()

    with pytest.raises(ToolValidationError):
        _save(memories, _student(), {"kind": "goal", "content": "Ship", extra: str(uuid4())})

    assert memories.saved == []


def test_anonymous_principal_is_refused() -> None:
    memories = RecordingMemories()

    with pytest.raises(PermissionError):
        _save(memories, _anonymous(), {"kind": "goal", "content": "Ship"})

    assert memories.saved == []


@pytest.mark.parametrize(
    "arguments",
    [
        {"kind": "", "content": "Ship"},
        {"kind": "   ", "content": "Ship"},
        {"kind": "k" * 81, "content": "Ship"},
        {"kind": "goal", "content": ""},
        {"kind": "goal", "content": "   "},
        {"kind": "goal", "content": "c" * 2_001},
        {"kind": "goal", "content": 7},
        {"kind": "goal"},
    ],
)
def test_arguments_outside_the_database_bounds_are_rejected(
    arguments: dict[str, JsonValue],
) -> None:
    memories = RecordingMemories()

    with pytest.raises(ToolValidationError):
        _save(memories, _student(), arguments)

    assert memories.saved == []


def test_arguments_at_the_database_bounds_are_accepted() -> None:
    memories = RecordingMemories()

    _save(memories, _student(), {"kind": "k" * 80, "content": "c" * 2_000})

    assert (len(memories.saved[0].kind), len(memories.saved[0].content)) == (80, 2_000)


@pytest.mark.parametrize("role", ["student", "ta", "instructor", "admin"])
def test_policy_offers_the_tool_to_every_authenticated_role(
    role: Literal["student", "ta", "instructor", "admin"],
) -> None:
    policy = CourseCapabilityPolicy(memories_enabled=True)

    assert SAVE_MY_MEMORY_TOOL_ID in policy.authorize(_student(role)).tool_ids


def test_policy_hides_the_tool_from_anonymous_users_and_when_disabled() -> None:
    enabled = CourseCapabilityPolicy(memories_enabled=True)

    assert SAVE_MY_MEMORY_TOOL_ID not in enabled.authorize(_anonymous()).tool_ids
    assert SAVE_MY_MEMORY_TOOL_ID not in CourseCapabilityPolicy().authorize(_student()).tool_ids


def test_build_runtime_registers_the_tool_only_with_a_store() -> None:
    settings = AgentSettings.from_environment(
        {
            "DATABASE_URL": "postgresql://example",
            "OPENAI_API_KEY": "test-secret-value",
            "BRAVE_API_KEY": "test-brave-value",
        }
    )
    resources = FileResourceProvider.with_sample_syllabus()

    registered = build_runtime(settings, resources=resources, memories=RecordingMemories())
    unregistered = build_runtime(settings, resources=resources)

    assert [tool.id for tool in registered._tools.authorized([SAVE_MY_MEMORY_TOOL_ID])] == [
        SAVE_MY_MEMORY_TOOL_ID
    ]
    with pytest.raises(CapabilityCatalogError):
        unregistered._tools.authorized([SAVE_MY_MEMORY_TOOL_ID])
