from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Literal
from uuid import uuid4

import pytest

from agent_core import AgentContext, AgentInput, AgentResult, Event, PrincipalContext
from course_server.agent import (
    ASK_TA_TOOL_ID,
    COURSE_APPLICATION_URI,
    COURSE_FAQ_URI,
    COURSE_INSTRUCTORS_URI,
    COURSE_REPOSITORIES_URI,
    COURSE_SCHEDULE_URI,
    COURSE_SYLLABUS_URI,
    GET_APPLICATION_TOOL_ID,
    INSTRUCTOR_INSPECT_APPLICATION_IMAGES_TOOL_ID,
    INSTRUCTOR_LIST_APPLICATIONS_TOOL_ID,
    INSTRUCTOR_READ_APPLICATION_TOOL_ID,
    LIST_PRIVATE_RESOURCES_TOOL_ID,
    READ_PRIVATE_RESOURCE_TOOL_ID,
    READ_SKILL_REFERENCE_TOOL_ID,
    READ_SKILL_TOOL_ID,
    READ_UPLOAD_TOOL_ID,
    SEARCH_COURSE_TOOL_ID,
    VISIT_WEBPAGE_TOOL_ID,
    WEB_IMAGE_SEARCH_TOOL_ID,
    WEB_SEARCH_TOOL_ID,
    ConversationAccessDenied,
    CourseAgentService,
    CourseCapabilityPolicy,
    FileResourceProvider,
    InMemoryConversationStore,
    ResourceDefinition,
    SkillCatalog,
)
from course_server.agent_cli import _safe_failure_message, run_cli_turn
from course_server.auth import InMemoryAuthStore
from course_server.browser import BROWSER_TOOL_IDS
from course_server.uploads import FileTemporaryUploadStore


def public_principal() -> PrincipalContext:
    session_id = uuid4()
    return PrincipalContext(
        authenticated=False,
        anonymous_session_id=session_id,
        roles=["public"],
        session_id=session_id,
    )


def authenticated_principal(
    role: Literal["student", "ta", "instructor", "admin"],
) -> PrincipalContext:
    return PrincipalContext(
        authenticated=True,
        user_id=uuid4(),
        username=f"test-{role}",
        display_name=f"Test {role.title()}",
        roles=["public", role],
        session_id=uuid4(),
    )


class RecordingRuntime:
    def __init__(self) -> None:
        self.contexts: list[AgentContext] = []
        self.inputs: list[AgentInput] = []

    async def run(
        self,
        *,
        context: AgentContext,
        input: AgentInput,
    ) -> AgentResult:
        self.contexts.append(context)
        self.inputs.append(input)
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
    authorized = CourseCapabilityPolicy().authorize(public_principal())

    assert SEARCH_COURSE_TOOL_ID in authorized.tool_ids
    assert GET_APPLICATION_TOOL_ID in authorized.tool_ids
    assert READ_UPLOAD_TOOL_ID in authorized.tool_ids
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

    browser_authorized = CourseCapabilityPolicy(browser_enabled=True).authorize(public_principal())
    assert set(BROWSER_TOOL_IDS) <= set(browser_authorized.tool_ids)


def test_course_policy_filters_role_scoped_resources_and_instructor_tools(
    tmp_path: Path,
) -> None:
    public_file = tmp_path / "public.md"
    student_file = tmp_path / "students.md"
    instructor_file = tmp_path / "instructors.md"
    public_file.write_text("Public", encoding="utf-8")
    student_file.write_text("Students", encoding="utf-8")
    instructor_file.write_text("Instructors", encoding="utf-8")
    resources = FileResourceProvider(
        [
            ResourceDefinition(
                uri="course://public",
                title="Public",
                media_type="text/markdown",
                path=public_file,
            ),
            ResourceDefinition(
                uri="course://students/notes",
                title="Student Notes",
                media_type="text/markdown",
                path=student_file,
                visibility="students",
            ),
            ResourceDefinition(
                uri="course://instructors/notes",
                title="Instructor Notes",
                media_type="text/markdown",
                path=instructor_file,
                visibility="instructors",
            ),
        ]
    )
    policy = CourseCapabilityPolicy(resources)

    public = policy.authorize(public_principal())
    student = policy.authorize(authenticated_principal("student"))
    instructor = policy.authorize(authenticated_principal("instructor"))
    ta = policy.authorize(authenticated_principal("ta"))
    admin = policy.authorize(authenticated_principal("admin"))

    assert public.resource_uris == ("course://public",)
    assert student.resource_uris == ("course://public", "course://students/notes")
    assert instructor.resource_uris == (
        "course://public",
        "course://students/notes",
        "course://instructors/notes",
    )
    assert ta.resource_uris == admin.resource_uris == ("course://public",)
    assert LIST_PRIVATE_RESOURCES_TOOL_ID in student.tool_ids
    assert READ_PRIVATE_RESOURCE_TOOL_ID in student.tool_ids
    assert INSTRUCTOR_LIST_APPLICATIONS_TOOL_ID not in student.tool_ids
    assert INSTRUCTOR_READ_APPLICATION_TOOL_ID not in student.tool_ids
    assert INSTRUCTOR_INSPECT_APPLICATION_IMAGES_TOOL_ID not in student.tool_ids
    assert INSTRUCTOR_LIST_APPLICATIONS_TOOL_ID in instructor.tool_ids
    assert INSTRUCTOR_READ_APPLICATION_TOOL_ID in instructor.tool_ids
    assert INSTRUCTOR_INSPECT_APPLICATION_IMAGES_TOOL_ID in instructor.tool_ids
    assert LIST_PRIVATE_RESOURCES_TOOL_ID not in ta.tool_ids


def test_staff_email_tool_requires_enabled_mail_and_exact_student_role() -> None:
    disabled = CourseCapabilityPolicy()
    enabled = CourseCapabilityPolicy(mail_enabled=True)

    assert ASK_TA_TOOL_ID not in disabled.authorize(authenticated_principal("student")).tool_ids
    assert ASK_TA_TOOL_ID in enabled.authorize(authenticated_principal("student")).tool_ids
    assert ASK_TA_TOOL_ID not in enabled.authorize(public_principal()).tool_ids
    assert ASK_TA_TOOL_ID not in enabled.authorize(authenticated_principal("ta")).tool_ids
    assert ASK_TA_TOOL_ID not in enabled.authorize(authenticated_principal("instructor")).tool_ids
    assert ASK_TA_TOOL_ID not in enabled.authorize(authenticated_principal("admin")).tool_ids


def test_course_agent_discloses_only_login_authorized_skill_metadata() -> None:
    async def scenario() -> None:
        runtime = RecordingRuntime()
        conversations = InMemoryConversationStore()
        skills = SkillCatalog.from_registry(Path(__file__).resolve().parents[2] / "skills")
        service = CourseAgentService(
            runtime=runtime,
            conversations=conversations,
            skills=skills,
        )

        principals = [public_principal(), authenticated_principal("instructor")]
        for principal in principals:
            conversation = await service.create_conversation(principal)
            await service.run(
                principal=principal,
                conversation_id=conversation.id,
                text="Hello",
            )

        public_context, instructor_context = runtime.contexts
        public_skill_index = public_context.metadata["authorized_skill_index"]
        instructor_skill_index = instructor_context.metadata["authorized_skill_index"]
        assert isinstance(public_skill_index, list)
        assert isinstance(instructor_skill_index, list)
        assert all(isinstance(skill, dict) for skill in public_skill_index)
        assert all(isinstance(skill, dict) for skill in instructor_skill_index)
        public_skill_ids = {
            skill_id
            for skill in public_skill_index
            if isinstance(skill, dict) and isinstance((skill_id := skill.get("id")), str)
        }
        instructor_skill_ids = {
            skill_id
            for skill in instructor_skill_index
            if isinstance(skill, dict) and isinstance((skill_id := skill.get("id")), str)
        }
        assert "student-course-resources" not in public_skill_ids
        assert "instructor-application-review" not in public_skill_ids
        assert "student-course-resources" in instructor_skill_ids
        assert "instructor-application-review" in instructor_skill_ids
        assert READ_SKILL_TOOL_ID in public_context.permitted_tool_ids
        assert READ_SKILL_REFERENCE_TOOL_ID in public_context.permitted_tool_ids
        assert public_context.active_skill_ids == []

    asyncio.run(scenario())


def test_course_agent_authorizes_owned_uploads_for_current_and_follow_up_turns(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        runtime = RecordingRuntime()
        conversations = InMemoryConversationStore()
        uploads = FileTemporaryUploadStore(tmp_path / "uploads")
        principal = public_principal()
        receipt = await uploads.store(
            filename="paper.pdf",
            media_type="application/pdf",
            content=b"%PDF-1.4\n%%EOF",
            principal=principal,
        )
        service = CourseAgentService(
            runtime=runtime,
            conversations=conversations,
            uploads=uploads,
        )
        conversation = await service.create_conversation(principal)

        await service.run(
            principal=principal,
            conversation_id=conversation.id,
            text=f"Read this paper. [Temporary upload; upload_id: {receipt.id}]",
        )
        await service.run(
            principal=principal,
            conversation_id=conversation.id,
            text="How was the study conducted?",
        )

        resource_uri = f"upload://{receipt.id}"
        assert resource_uri in runtime.contexts[0].permitted_resource_uris
        assert resource_uri in runtime.contexts[1].permitted_resource_uris

    asyncio.run(scenario())


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


def test_course_agent_context_prioritizes_dialogue_over_run_bookkeeping() -> None:
    async def scenario() -> None:
        runtime = RecordingRuntime()
        store = InMemoryConversationStore()
        principal = public_principal()
        service = CourseAgentService(runtime=runtime, conversations=store)
        conversation = await service.create_conversation(principal)
        events: list[Event] = []
        for index in range(30):
            common = {
                "actor": "course-agent",
                "anonymous_session_id": principal.anonymous_session_id,
                "conversation_id": conversation.id,
            }
            events.extend(
                [
                    Event(
                        type="user.message",
                        payload={"text": f"User turn {index}"},
                        **common,
                    ),
                    Event(type="agent.run.started", payload={"turn": index}, **common),
                    Event(
                        type="agent.tool.requested",
                        payload={"tool_id": "test.tool"},
                        **common,
                    ),
                    Event(
                        type="agent.tool.completed",
                        payload={"tool_id": "test.tool"},
                        **common,
                    ),
                    Event(
                        type="agent.message",
                        payload={"text": f"Agent turn {index}"},
                        **common,
                    ),
                    Event(type="agent.run.completed", payload={"turn": index}, **common),
                ]
            )
        await store.append_events(conversation.id, events)

        await service.run(
            principal=principal,
            conversation_id=conversation.id,
            text="Continue",
        )

        recent = runtime.contexts[0].recent_events
        dialogue = [event for event in recent if event.type in {"user.message", "agent.message"}]
        supporting = [event for event in recent if event.type == "agent.tool.completed"]
        assert len(dialogue) == 24
        assert dialogue[0].payload["text"] == "User turn 18"
        assert dialogue[-1].payload["text"] == "Agent turn 29"
        assert len(supporting) == 16
        assert all(
            event.type in {"user.message", "agent.message", "agent.tool.completed"}
            for event in recent
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


def test_course_agent_continues_from_a_trusted_action_without_a_fake_user_message() -> None:
    async def scenario() -> None:
        runtime = RecordingRuntime()
        store = InMemoryConversationStore()
        service = CourseAgentService(runtime=runtime, conversations=store)
        principal = authenticated_principal("student")
        conversation = await service.create_conversation(principal)
        question_id = uuid4()
        prepared = Event(
            type="email.ta_question.confirmation_requested",
            actor="course-agent",
            principal_user_id=principal.user_id,
            conversation_id=conversation.id,
            payload={
                "question_id": str(question_id),
                "question_code": "Q-2026-00001",
                "question": "Which assignments are group work?",
                "status": "pending_confirmation",
            },
            metadata={"visibility": "private"},
        )
        trigger = Event(
            type="email.ta_question.queued",
            actor="user",
            principal_user_id=principal.user_id,
            conversation_id=conversation.id,
            payload={
                "question_id": str(question_id),
                "question_code": "Q-2026-00001",
                "status": "queued",
            },
            metadata={"visibility": "private"},
        )
        await store.append_events(conversation.id, [prepared, trigger])

        first = await service.continue_after_event(
            principal=principal,
            conversation_id=conversation.id,
            trigger_event_id=trigger.id,
        )
        second = await service.continue_after_event(
            principal=principal,
            conversation_id=conversation.id,
            trigger_event_id=trigger.id,
        )

        assert first.output_text == second.output_text == "Hello from Class Agent."
        assert len(runtime.inputs) == 1
        assert runtime.inputs[0].text == (
            "The student approved sending the prepared question to course staff."
        )
        assert "Which assignments are group work?" not in runtime.inputs[0].text
        assert runtime.contexts[0].recent_events == [prepared, trigger]
        assert ASK_TA_TOOL_ID not in runtime.contexts[0].permitted_tool_ids
        events = await store.list_events(conversation.id)
        assert all(event.type != "user.message" for event in events)
        continuation = next(event for event in events if event.type == "agent.message")
        assert continuation.metadata["trigger_event_id"] == str(trigger.id)

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
