from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest

from agent_core import AgentContext, AgentInput, AgentResult, Event, PrincipalContext
from course_server.agent import (
    COURSE_APPLICATION_URI,
    COURSE_FAQ_URI,
    COURSE_INSTRUCTORS_URI,
    COURSE_REPOSITORIES_URI,
    COURSE_SCHEDULE_URI,
    COURSE_SYLLABUS_URI,
    GET_APPLICATION_TOOL_ID,
    SEARCH_COURSE_TOOL_ID,
    VISIT_WEBPAGE_TOOL_ID,
    WEB_IMAGE_SEARCH_TOOL_ID,
    WEB_SEARCH_TOOL_ID,
    ConversationAccessDenied,
    CourseAgentService,
    InMemoryConversationStore,
    PublicCapabilityPolicy,
)
from course_server.agent_cli import _safe_failure_message, run_cli_turn
from course_server.auth import InMemoryAuthStore
from course_server.browser import BROWSER_TOOL_IDS


def public_principal() -> PrincipalContext:
    session_id = uuid4()
    return PrincipalContext(
        authenticated=False,
        anonymous_session_id=session_id,
        roles=["public"],
        session_id=session_id,
    )


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
        return AgentResult(
            input_id=input.id,
            conversation_id=context.conversation_id,
            output_text="Hello from Class Agent.",
            events=[
                Event(
                    type="agent.message",
                    actor="course-agent",
                    anonymous_session_id=context.principal.anonymous_session_id,
                    conversation_id=context.conversation_id,
                    payload={"text": "Hello from Class Agent."},
                )
            ],
        )


def test_public_policy_exposes_phase_six_course_capabilities() -> None:
    authorized = PublicCapabilityPolicy().authorize(public_principal())

    assert SEARCH_COURSE_TOOL_ID in authorized.tool_ids
    assert GET_APPLICATION_TOOL_ID in authorized.tool_ids
    assert WEB_SEARCH_TOOL_ID in authorized.tool_ids
    assert WEB_IMAGE_SEARCH_TOOL_ID in authorized.tool_ids
    assert VISIT_WEBPAGE_TOOL_ID in authorized.tool_ids
    assert not set(BROWSER_TOOL_IDS) & set(authorized.tool_ids)
    assert authorized.resource_uris == (
        COURSE_SYLLABUS_URI,
        COURSE_SCHEDULE_URI,
        COURSE_REPOSITORIES_URI,
        COURSE_FAQ_URI,
        COURSE_INSTRUCTORS_URI,
        COURSE_APPLICATION_URI,
    )

    browser_authorized = PublicCapabilityPolicy(browser_enabled=True).authorize(public_principal())
    assert set(BROWSER_TOOL_IDS) <= set(browser_authorized.tool_ids)


def test_course_agent_persists_portable_history_and_isolates_anonymous_users() -> None:
    async def scenario() -> None:
        runtime = RecordingRuntime()
        store = InMemoryConversationStore()
        service = CourseAgentService(runtime=runtime, conversations=store)
        alice = public_principal()
        bob = public_principal()
        conversation = await service.create_conversation(alice)

        result = await service.run(
            principal=alice,
            conversation_id=conversation.id,
            text="Hello",
        )
        assert result.output_text == "Hello from Class Agent."
        assert [event.type for event in await store.list_events(conversation.id)] == [
            "user.message",
            "agent.message",
        ]
        assert SEARCH_COURSE_TOOL_ID in runtime.contexts[0].permitted_tool_ids

        with pytest.raises(ConversationAccessDenied):
            await service.run(
                principal=bob,
                conversation_id=conversation.id,
                text="Show me Alice's history",
            )

    asyncio.run(scenario())


def test_course_agent_reports_result_events_for_unobserved_runtime_adapters() -> None:
    async def scenario() -> None:
        runtime = RecordingRuntime()
        store = InMemoryConversationStore()
        service = CourseAgentService(runtime=runtime, conversations=store)
        principal = public_principal()
        conversation = await service.create_conversation(principal)
        observed: list[Event] = []

        await service.run(
            principal=principal,
            conversation_id=conversation.id,
            text="Hello",
            event_observer=observed.append,
        )

        assert [event.type for event in observed] == ["agent.message"]

    asyncio.run(scenario())


def test_cli_flow_is_adapter_injectable_and_does_not_require_a_model_api() -> None:
    async def scenario() -> None:
        runtime = RecordingRuntime()
        conversations = InMemoryConversationStore()
        conversation, result = await run_cli_turn(
            "Hello",
            runtime=runtime,
            auth_store=InMemoryAuthStore(),
            conversation_store=conversations,
        )

        assert result.output_text == "Hello from Class Agent."
        assert conversation.anonymous_session_id is not None
        assert len(await conversations.list_events(conversation.id)) == 2

    asyncio.run(scenario())


def test_cli_failure_message_does_not_render_exception_details() -> None:
    message = _safe_failure_message(RuntimeError("Bearer test-secret-value"))

    assert "RuntimeError" in message
    assert "test-secret-value" not in message


def test_cli_failure_message_includes_safe_exception_type_chain() -> None:
    underlying = ValueError("Bearer test-secret-value")
    try:
        raise RuntimeError("provider failed") from underlying
    except RuntimeError as error:
        message = _safe_failure_message(error)

    assert "RuntimeError <- ValueError" in message
    assert "provider failed" not in message
    assert "test-secret-value" not in message


def test_cli_failure_message_includes_only_sanitized_provider_fields() -> None:
    class ProviderError(RuntimeError):
        status_code = 400
        type = "invalid_request_error"
        code = "unsupported_value"
        param = "messages[0].role"

    message = _safe_failure_message(ProviderError("Bearer test-secret-value"))

    assert (
        "[status=400, type=invalid_request_error, code=unsupported_value, "
        "param=messages[0].role]" in message
    )
    assert "test-secret-value" not in message


def test_cli_failure_message_rejects_unsafe_provider_fields() -> None:
    class ProviderError(RuntimeError):
        status_code = 400
        param = "prompt contained Bearer test-secret-value"

    message = _safe_failure_message(ProviderError("provider failed"))

    assert "[status=400]" in message
    assert "test-secret-value" not in message
