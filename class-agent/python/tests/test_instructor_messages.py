from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from agent_core import PrincipalContext
from course_server.agent import ToolExecutionContext, ToolValidationError
from course_server.auth import InMemoryAuthStore, UserAdminService
from course_server.instructor_messages import (
    PENDING_QUESTION_RECIPIENT_PREFIX,
    InMemoryInstructorMessageStore,
    InstructorMessageContent,
    InstructorMessageDraft,
    InstructorMessageService,
    InstructorMessageStateError,
    InstructorMessageStudentsTool,
)
from course_server.mail import InMemoryTAQuestionStore


async def create_principal(
    auth: InMemoryAuthStore,
    *,
    username: str,
    display_name: str,
    role: str,
) -> PrincipalContext:
    issued = await UserAdminService(auth).create_user(
        username=username,
        display_name=display_name,
        email=f"{username}@mit.edu",
        role=role,  # type: ignore[arg-type]
    )
    return PrincipalContext(
        authenticated=True,
        user_id=issued.user.id,
        username=issued.user.username,
        display_name=issued.user.display_name,
        roles=["public", issued.user.role],
        session_id=uuid4(),
    )


def test_instructor_confirms_one_fixed_all_student_recipient_snapshot() -> None:
    async def scenario() -> None:
        now = datetime(2026, 9, 14, 12, tzinfo=UTC)
        auth = InMemoryAuthStore()
        instructor = await create_principal(
            auth,
            username="prof",
            display_name="Professor Example",
            role="instructor",
        )
        alice = await create_principal(
            auth,
            username="alice",
            display_name="Alice Student",
            role="student",
        )
        bob = await create_principal(
            auth,
            username="bob",
            display_name="Bob Student",
            role="student",
        )
        await create_principal(
            auth,
            username="course-ta",
            display_name="Course TA",
            role="ta",
        )
        store = InMemoryInstructorMessageStore()
        service = InstructorMessageService(messages=store, auth=auth, clock=lambda: now)
        conversation_id = uuid4()
        prepared = await service.prepare(
            principal=instructor,
            conversation_id=conversation_id,
            draft=InstructorMessageDraft(
                audience="all_students",
                recipients=[],
                subject="Room change",
                message="Class will meet in E14-240 tomorrow.",
            ),
        )

        assert [recipient.username for recipient in prepared.recipients] == ["alice", "bob"]
        assert alice.user_id is not None
        assert await store.list_sent_for_student(alice.user_id) == []

        sent = await service.confirm(
            principal=instructor,
            conversation_id=conversation_id,
            message_id=prepared.message.id,
            content=InstructorMessageContent(
                subject="Updated room change",
                message="Class will meet in E14-250 tomorrow.",
            ),
        )

        assert sent.message.status == "sent"
        assert sent.message.sent_at == now
        assert sent.message.subject == "Updated room change"
        assert sent.message.message == "Class will meet in E14-250 tomorrow."
        assert set(sent.recipient_user_ids) == {alice.user_id, bob.user_id}
        delivered = await store.list_sent_for_student(alice.user_id)
        assert [message.subject for message in delivered] == ["Updated room change"]
        with pytest.raises(InstructorMessageStateError, match="no longer"):
            await service.confirm(
                principal=instructor,
                conversation_id=conversation_id,
                message_id=prepared.message.id,
            )

    asyncio.run(scenario())


def test_targeted_tool_resolves_students_and_requires_instructor_confirmation() -> None:
    async def scenario() -> None:
        auth = InMemoryAuthStore()
        instructor = await create_principal(
            auth,
            username="prof",
            display_name="Professor Example",
            role="instructor",
        )
        student = await create_principal(
            auth,
            username="alice",
            display_name="Alice Student",
            role="student",
        )
        store = InMemoryInstructorMessageStore()
        service = InstructorMessageService(messages=store, auth=auth)
        tool = InstructorMessageStudentsTool(service)
        context = ToolExecutionContext(
            principal=instructor,
            conversation_id=uuid4(),
            permitted_resource_uris=frozenset(),
        )

        result = await tool.execute(
            {
                "audience": "specific_students",
                "recipients": ["Alice Student"],
                "subject": "Check-in",
                "message": "Please meet with me after class.",
            },
            context,
        )

        assert result.storage_policy == "server_summary"
        assert isinstance(result.content, dict)
        assert result.content["confirmation_required"] is True
        assert result.emitted_events[0].type == "instructor.message.confirmation_requested"
        assert result.emitted_events[0].payload["recipients"] == [
            {"username": "alice", "display_name": "Alice Student"}
        ]
        assert student.user_id is not None
        assert await store.list_sent_for_student(student.user_id) == []

        student_context = ToolExecutionContext(
            principal=student,
            conversation_id=context.conversation_id,
            permitted_resource_uris=frozenset(),
        )
        with pytest.raises(ToolValidationError, match="instructor login"):
            await tool.execute(
                {
                    "audience": "all_students",
                    "recipients": [],
                    "subject": "Not allowed",
                    "message": "Students cannot send this.",
                },
                student_context,
            )
        with pytest.raises(ToolValidationError, match="No active student"):
            await tool.execute(
                {
                    "audience": "specific_students",
                    "recipients": ["missing-student"],
                    "subject": "Unknown recipient",
                    "message": "This must not be delivered.",
                },
                ToolExecutionContext(
                    principal=instructor,
                    conversation_id=uuid4(),
                    permitted_resource_uris=frozenset(),
                ),
            )

    asyncio.run(scenario())


def test_pending_question_reply_reference_resolves_owner_without_exposing_anonymous_identity() -> (
    None
):
    async def scenario() -> None:
        now = datetime(2026, 9, 15, 12, tzinfo=UTC)
        auth = InMemoryAuthStore()
        instructor = await create_principal(
            auth,
            username="prof",
            display_name="Professor Example",
            role="instructor",
        )
        student = await create_principal(
            auth,
            username="alice",
            display_name="Alice Student",
            role="student",
        )
        assert student.user_id is not None
        questions = InMemoryTAQuestionStore()
        question = await questions.create_question(
            student_user_id=student.user_id,
            conversation_id=uuid4(),
            subject="Test message",
            question_text="Can you respond?",
            context_text=None,
            created_at=now,
        )
        queued_question = await questions.transition_question(
            question.id,
            expected="pending_confirmation",
            status="queued",
            changed_at=now,
            reporter_visibility="anonymous",
        )
        assert queued_question is not None
        question = queued_question
        store = InMemoryInstructorMessageStore()
        tool = InstructorMessageStudentsTool(
            InstructorMessageService(
                messages=store,
                auth=auth,
                questions=questions,
                clock=lambda: now,
            )
        )
        context = ToolExecutionContext(
            principal=instructor,
            conversation_id=uuid4(),
            permitted_resource_uris=frozenset(),
        )

        result = await tool.execute(
            {
                "audience": "specific_students",
                "recipients": [f"{PENDING_QUESTION_RECIPIENT_PREFIX}{question.id}"],
                "subject": "Re: Test message",
                "message": "test",
            },
            context,
        )

        payload = result.emitted_events[0].payload
        assert payload["recipients"] == [
            {"username": "anonymous", "display_name": "Anonymous student"}
        ]
        assert payload["message"] == "test"
        assert payload["publication_decision"] == "private"
        assert payload["source_question_id"] == str(question.id)
        assert "alice" not in str(payload).casefold()
        stored = await store.get(UUID(str(payload["message_id"])))
        assert stored is not None
        assert stored.recipient_user_ids == (student.user_id,)

        await questions.transition_question(
            question.id,
            expected="queued",
            status="closed",
            changed_at=now,
        )
        with pytest.raises(ToolValidationError, match="no longer needs a response"):
            await tool.execute(
                {
                    "audience": "specific_students",
                    "recipients": [f"{PENDING_QUESTION_RECIPIENT_PREFIX}{question.id}"],
                    "subject": "Late reply",
                    "message": "This should not be prepared.",
                },
                ToolExecutionContext(
                    principal=instructor,
                    conversation_id=uuid4(),
                    permitted_resource_uris=frozenset(),
                ),
            )

    asyncio.run(scenario())


def test_named_online_reply_can_be_edited_to_publish_and_resolves_question() -> None:
    async def scenario() -> None:
        now = datetime(2026, 9, 15, 13, tzinfo=UTC)
        auth = InMemoryAuthStore()
        instructor = await create_principal(
            auth,
            username="prof",
            display_name="Professor Example",
            role="instructor",
        )
        student = await create_principal(
            auth,
            username="alice",
            display_name="Alice Student",
            role="student",
        )
        assert student.user_id is not None
        questions = InMemoryTAQuestionStore()
        question = await questions.create_question(
            student_user_id=student.user_id,
            conversation_id=uuid4(),
            subject="Test message",
            question_text="Can you respond?",
            context_text=None,
            created_at=now,
        )
        queued = await questions.transition_question(
            question.id,
            expected="pending_confirmation",
            status="queued",
            changed_at=now,
        )
        assert queued is not None
        store = InMemoryInstructorMessageStore()
        service = InstructorMessageService(
            messages=store,
            auth=auth,
            questions=questions,
            clock=lambda: now,
        )
        prepared = await service.prepare(
            principal=instructor,
            conversation_id=uuid4(),
            draft=InstructorMessageDraft(
                audience="specific_students",
                recipients=[f"{PENDING_QUESTION_RECIPIENT_PREFIX}{question.id}"],
                subject="Re: Test message",
                message="Initial response",
            ),
        )

        assert prepared.recipient_previews[0].display_name == "Alice Student"
        assert prepared.message.message == "PRIVATE\n\nInitial response"
        with pytest.raises(InstructorMessageStateError, match="non-empty response"):
            await service.confirm(
                principal=instructor,
                conversation_id=prepared.message.conversation_id,
                message_id=prepared.message.id,
                content=InstructorMessageContent(
                    subject="Re: Test message",
                    message="PUBLISH",
                ),
            )
        still_queued = await questions.get_question(question.id)
        assert still_queued is not None and still_queued.status == "queued"
        sent = await service.confirm(
            principal=instructor,
            conversation_id=prepared.message.conversation_id,
            message_id=prepared.message.id,
            content=InstructorMessageContent(
                subject="Re: Test message",
                message="Edited response",
                publication_decision="publish",
            ),
        )

        assert sent.message.message == "Edited response"
        answered = await questions.get_question(question.id)
        assert answered is not None and answered.status == "answered"
        answer = next(iter(questions.answers.values()))
        assert answer.source == "online"
        assert answer.publication_decision == "publish"
        assert answer.answer_text == "Edited response"
        assert await store.list_sent_for_student(student.user_id) == []
        candidate = next(iter(questions.faq_candidates.values()))
        assert candidate.status == "pending_publication"

    asyncio.run(scenario())


def test_cancelled_instructor_message_is_never_delivered() -> None:
    async def scenario() -> None:
        auth = InMemoryAuthStore()
        instructor = await create_principal(
            auth,
            username="prof",
            display_name="Professor Example",
            role="instructor",
        )
        student = await create_principal(
            auth,
            username="alice",
            display_name="Alice Student",
            role="student",
        )
        store = InMemoryInstructorMessageStore()
        service = InstructorMessageService(messages=store, auth=auth)
        conversation_id = uuid4()
        prepared = await service.prepare(
            principal=instructor,
            conversation_id=conversation_id,
            draft=InstructorMessageDraft(
                audience="all_students",
                recipients=[],
                subject="Draft only",
                message="Do not deliver this message.",
            ),
        )

        cancelled = await service.cancel(
            principal=instructor,
            conversation_id=conversation_id,
            message_id=prepared.message.id,
        )

        assert cancelled.message.status == "cancelled"
        assert student.user_id is not None
        assert await store.list_sent_for_student(student.user_id) == []

    asyncio.run(scenario())
