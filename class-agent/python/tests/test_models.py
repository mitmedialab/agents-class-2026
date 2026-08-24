from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from pydantic import BaseModel, ValidationError

from agent_core import (
    AgentContext,
    AgentInput,
    AgentResult,
    AgentRuntime,
    Capability,
    Conversation,
    Event,
    Memory,
    ModelProvider,
    Node,
    Permission,
    PrincipalContext,
)

NOW = datetime(2026, 8, 23, 12, 0, tzinfo=UTC)


def public_principal() -> PrincipalContext:
    return PrincipalContext(
        authenticated=False,
        anonymous_session_id=uuid4(),
        roles=["public"],
        session_id=uuid4(),
    )


def student_principal() -> PrincipalContext:
    return PrincipalContext(
        authenticated=True,
        user_id=uuid4(),
        username="alice",
        display_name="Alice Example",
        roles=["public", "student"],
        session_id=uuid4(),
    )


def ta_principal() -> PrincipalContext:
    return PrincipalContext(
        authenticated=True,
        user_id=uuid4(),
        username="tom",
        display_name="Tom TA",
        roles=["public", "ta"],
        session_id=uuid4(),
    )


def roundtrip(model: BaseModel) -> BaseModel:
    return type(model).model_validate_json(model.model_dump_json())


def test_principal_context_supports_public_student_and_ta() -> None:
    public = public_principal()
    student = student_principal()
    ta = ta_principal()

    assert not public.authenticated
    assert public.roles == ["public"]
    assert student.authenticated and "student" in student.roles
    assert ta.authenticated and "ta" in ta.roles
    assert roundtrip(public) == public
    assert roundtrip(student) == student
    assert roundtrip(ta) == ta


@pytest.mark.parametrize(
    "values",
    [
        {
            "authenticated": False,
            "anonymous_session_id": None,
            "roles": ["public"],
            "session_id": uuid4(),
        },
        {
            "authenticated": False,
            "anonymous_session_id": uuid4(),
            "user_id": uuid4(),
            "roles": ["public"],
            "session_id": uuid4(),
        },
        {
            "authenticated": True,
            "user_id": uuid4(),
            "username": "alice",
            "roles": ["student"],
            "session_id": uuid4(),
        },
    ],
)
def test_principal_context_rejects_inconsistent_identity(values: object) -> None:
    with pytest.raises(ValidationError):
        PrincipalContext.model_validate(values)


def test_event_roundtrip_preserves_portable_history() -> None:
    event = Event(
        timestamp=NOW,
        type="agent.tool.completed",
        actor="course-agent",
        principal_user_id=uuid4(),
        conversation_id=uuid4(),
        payload={"tool": "course.search", "results": [1, "two", None]},
        metadata={"latency_ms": 12.5},
    )

    restored = roundtrip(event)

    assert restored == event
    assert event.schema_version == 1
    assert event.model_dump(mode="json")["timestamp"] == "2026-08-23T12:00:00Z"


def test_event_rejects_multiple_principal_references() -> None:
    with pytest.raises(ValidationError, match="both a user and an anonymous session"):
        Event(
            type="user.message",
            actor="user",
            principal_user_id=uuid4(),
            anonymous_session_id=uuid4(),
        )


def test_conversation_roundtrip_and_exact_owner() -> None:
    conversation = Conversation(
        user_id=uuid4(),
        created_at=NOW,
        updated_at=NOW,
    )

    assert roundtrip(conversation) == conversation

    with pytest.raises(ValidationError, match="exactly one"):
        Conversation(created_at=NOW, updated_at=NOW)


def test_contracts_reject_naive_timestamps() -> None:
    with pytest.raises(ValidationError, match="timezone"):
        Event(
            timestamp=datetime(2026, 8, 23, 12, 0),
            type="system.error",
            actor="system",
        )


def test_memory_roundtrip_and_ordering() -> None:
    event_id = uuid4()
    memory = Memory(
        user_id=uuid4(),
        created_at=NOW,
        updated_at=NOW,
        kind="preference",
        content="Prefers hints before full answers.",
        source_event_ids=[event_id],
        privacy="personal",
    )

    assert roundtrip(memory) == memory

    with pytest.raises(ValidationError, match="earlier"):
        Memory(
            user_id=uuid4(),
            created_at=NOW,
            updated_at=datetime(2026, 8, 22, tzinfo=UTC),
            kind="preference",
            content="Prefers hints.",
            privacy="personal",
        )


def test_capability_models_acquisition_state() -> None:
    available = Capability(id="course.search", status="available")
    obtainable = Capability(
        id="filesystem.read",
        status="obtainable",
        acquisition={"type": "install_bridge", "metadata": {}},
    )

    assert available.acquisition is None
    assert roundtrip(obtainable) == obtainable

    with pytest.raises(ValidationError, match="acquisition"):
        Capability(id="filesystem.read", status="obtainable")


def test_permission_requires_one_trusted_owner() -> None:
    permission = Permission(
        capability="filesystem.read",
        scope={"paths": ["/Users/alice/Downloads"]},
        status="granted",
        principal_user_id=uuid4(),
        created_at=NOW,
        updated_at=NOW,
    )

    assert roundtrip(permission) == permission

    with pytest.raises(ValidationError, match="exactly one"):
        Permission(
            capability="filesystem.read",
            scope={},
            status="requested",
            created_at=NOW,
            updated_at=NOW,
        )


def test_node_and_context_roundtrip() -> None:
    principal = student_principal()
    node = Node(
        user_id=principal.user_id,
        type="local_bridge",
        name="Alice MacBook",
        capabilities=["filesystem.read"],
        online=True,
        last_seen_at=NOW,
    )
    context = AgentContext(
        principal=principal,
        conversation_id=uuid4(),
        capabilities=[
            Capability(
                id="filesystem.read",
                status="available",
                node_id=node.id,
            )
        ],
        permitted_tool_ids=["course.search", "grades.get_mine", "filesystem.read"],
        permitted_resource_uris=["course://syllabus"],
        active_skill_ids=["course-help"],
    )

    assert roundtrip(node) == node
    assert roundtrip(context) == context
    assert "grades.get_mine" in context.permitted_tool_ids


def test_context_rejects_duplicate_authorized_tools() -> None:
    with pytest.raises(ValidationError, match="permitted_tool_ids"):
        AgentContext(
            principal=public_principal(),
            conversation_id=uuid4(),
            permitted_tool_ids=["course.search", "course.search"],
        )


def test_agent_input_and_result_roundtrip() -> None:
    conversation_id = uuid4()
    agent_input = AgentInput(
        conversation_id=conversation_id,
        text="Show me the schedule.",
    )
    result = AgentResult(
        input_id=agent_input.id,
        conversation_id=conversation_id,
        output_text="Here is the schedule.",
        events=[Event(type="agent.message", actor="course-agent")],
    )

    assert roundtrip(agent_input) == agent_input
    assert roundtrip(result) == result


def test_payloads_reject_non_json_values() -> None:
    with pytest.raises(ValidationError):
        Event(type="system.error", actor="system", payload={"not_json": UUID})


class FakeRuntime:
    async def run(
        self,
        *,
        context: AgentContext,
        input: AgentInput,
    ) -> AgentResult:
        return AgentResult(
            input_id=input.id,
            conversation_id=context.conversation_id,
            output_text=input.text,
        )


def test_agent_runtime_is_a_structural_async_protocol() -> None:
    runtime = FakeRuntime()
    context = AgentContext(principal=public_principal(), conversation_id=uuid4())
    agent_input = AgentInput(conversation_id=context.conversation_id, text="Hello")

    assert isinstance(runtime, AgentRuntime)
    result = asyncio.run(runtime.run(context=context, input=agent_input))
    assert result.output_text == "Hello"


class FakeModelProvider:
    provider_id = "fake"
    model_id = "fake-model"

    def create_model(self) -> object:
        return object()


def test_model_provider_is_a_structural_protocol() -> None:
    assert isinstance(FakeModelProvider(), ModelProvider)
