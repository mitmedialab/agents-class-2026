from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from pydantic import JsonValue

from agent_core import PrincipalContext
from course_server.agent import ToolExecutionContext, ToolValidationError
from course_server.auth import InMemoryAuthStore, UserAdminService
from course_server.instructor_messages import (
    PENDING_QUESTION_RECIPIENT_PREFIX,
    InMemoryInstructorMessageStore,
    InstructorMessageAccessDenied,
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
                greeting="Hello students,",
                sign_off="Best,\nProfessor Example",
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
                "greeting": "Hi Alice,",
                "sign_off": "Best,\nProfessor Example",
            },
            context,
        )

        assert result.storage_policy == "server_summary"
        assert isinstance(result.content, dict)
        assert result.content["confirmation_required"] is True
        assert result.emitted_events[0].type == "instructor.message.confirmation_requested"
        assert result.emitted_events[0].payload["message"] == (
            "Hi Alice,\n\nPlease meet with me after class.\n\nBest,\nProfessor Example"
        )
        assert result.emitted_events[0].payload["recipients"] == [
            {"username": "alice", "display_name": "Alice Student", "email": "alice@mit.edu"}
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


def test_online_reply_can_request_silent_faq_publication() -> None:
    async def scenario() -> None:
        now = datetime(2026, 9, 15, 14, tzinfo=UTC)
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
        service = InstructorMessageService(
            messages=InMemoryInstructorMessageStore(),
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

        await service.confirm(
            principal=instructor,
            conversation_id=prepared.message.conversation_id,
            message_id=prepared.message.id,
            content=InstructorMessageContent(
                subject="Re: Test message",
                message="Useful FAQ answer.",
                publication_decision="silent_publish",
            ),
        )

        answer = next(iter(questions.answers.values()))
        candidate = next(iter(questions.faq_candidates.values()))
        assert answer.publication_decision == "silent_publish"
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
                greeting="Hello students,",
                sign_off="Best,\nProfessor Example",
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


@pytest.mark.parametrize("audience", ["all_students", "specific_students"])
@pytest.mark.parametrize("send_email", [False, True])
def test_email_choice_is_confirmed_with_fixed_recipients(audience: str, send_email: bool) -> None:
    async def scenario() -> None:
        auth = InMemoryAuthStore()
        instructor = await create_principal(
            auth, username="prof", display_name="Prof", role="instructor"
        )
        student = await create_principal(
            auth, username="alice", display_name="Alice", role="student"
        )
        store = InMemoryInstructorMessageStore()
        service = InstructorMessageService(messages=store, auth=auth, email_enabled=True)
        conversation_id = uuid4()
        prepared = await service.prepare(
            principal=instructor,
            conversation_id=conversation_id,
            draft=InstructorMessageDraft(
                greeting="Hello students,",
                sign_off="Best,\nProfessor Example",
                audience=audience,
                recipients=[] if audience == "all_students" else ["alice"],
                subject="Reminder",
                message="Original",
            ),
        )
        assert not prepared.message.send_email
        assert prepared.message.message == "Hello students,\n\nOriginal\n\nBest,\nProfessor Example"
        await create_principal(auth, username="later", display_name="Later", role="student")
        sent = await service.confirm(
            principal=instructor,
            conversation_id=conversation_id,
            message_id=prepared.message.id,
            content=InstructorMessageContent(
                subject="Edited", message="Reviewed", send_email=send_email
            ),
        )
        assert sent.message.send_email is send_email
        assert sent.message.message == "Reviewed"
        assert sent.recipient_user_ids == (student.user_id,)

    asyncio.run(scenario())


def test_email_unavailable_keeps_message_pending() -> None:
    async def scenario() -> None:
        auth = InMemoryAuthStore()
        instructor = await create_principal(
            auth, username="prof", display_name="Prof", role="instructor"
        )
        await create_principal(auth, username="alice", display_name="Alice", role="student")
        store = InMemoryInstructorMessageStore()
        service = InstructorMessageService(messages=store, auth=auth)
        conversation_id = uuid4()
        prepared = await service.prepare(
            principal=instructor,
            conversation_id=conversation_id,
            draft=InstructorMessageDraft(
                greeting="Hello students,",
                sign_off="Best,\nProfessor Example",
                audience="all_students",
                subject="Reminder",
                message="Hello",
            ),
        )
        with pytest.raises(InstructorMessageStateError, match="Email delivery is unavailable"):
            await service.confirm(
                principal=instructor,
                conversation_id=conversation_id,
                message_id=prepared.message.id,
                content=InstructorMessageContent(
                    subject="Reminder", message="Hello", send_email=True
                ),
            )
        stored = await store.get(prepared.message.id)
        assert stored is not None and stored.message.status == "pending_confirmation"
        assert not stored.message.send_email

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "payload",
    [
        {"action": "cancel", "send_email": True},
        {"action": "send", "send_email": True},
        {"action": "send", "subject": "Hi", "message": "Hello", "send_email": "true"},
        {
            "action": "send",
            "subject": "Hi",
            "message": "Hello",
            "send_email": True,
            "recipients": ["intruder"],
        },
    ],
)
def test_email_request_rejects_unreviewed_or_untrusted_fields(payload: dict[str, object]) -> None:
    from pydantic import ValidationError

    from course_server.api import InstructorMessageConfirmationRequest

    with pytest.raises(ValidationError):
        InstructorMessageConfirmationRequest.model_validate(payload)


@pytest.mark.parametrize("missing", ["greeting", "sign_off"])
def test_incomplete_ordinary_draft_cannot_create_a_confirmation(missing: str) -> None:
    async def scenario() -> None:
        auth = InMemoryAuthStore()
        instructor = await create_principal(
            auth, username="prof", display_name="Professor Example", role="instructor"
        )
        await create_principal(auth, username="alice", display_name="Alice", role="student")
        store = InMemoryInstructorMessageStore()
        tool = InstructorMessageStudentsTool(InstructorMessageService(messages=store, auth=auth))
        arguments: dict[str, JsonValue] = {
            "audience": "all_students",
            "recipients": [],
            "subject": "Invitation",
            "message": "Please accept your GitHub invitation.",
            "greeting": "Hello everyone,",
            "sign_off": "Best,\nProfessor Example",
        }
        del arguments[missing]
        with pytest.raises(ToolValidationError, match="require greeting and sign_off"):
            await tool.execute(
                arguments,
                ToolExecutionContext(
                    principal=instructor,
                    conversation_id=uuid4(),
                    permitted_resource_uris=frozenset(),
                ),
            )
        assert store.messages == {}

    asyncio.run(scenario())


@pytest.mark.parametrize("field", ["greeting", "sign_off"])
def test_blank_composition_parts_are_rejected(field: str) -> None:
    from pydantic import ValidationError

    arguments = {
        "audience": "all_students",
        "subject": "Invitation",
        "message": "Accept the invitation.",
        "greeting": "Hello everyone,",
        "sign_off": "Best,\nProfessor Example",
        field: "   ",
    }
    with pytest.raises(ValidationError):
        InstructorMessageDraft.model_validate(arguments)


@pytest.mark.parametrize("role", ["student", "ta", "admin", "instructor"])
def test_student_email_directory_is_instructor_only_and_checks_current_account(role: str) -> None:
    from course_server.instructor_contacts import InstructorListStudentsTool

    async def scenario() -> None:
        auth = InMemoryAuthStore()
        principal = await create_principal(
            auth, username="viewer", display_name="Viewer", role=role
        )
        alice = await create_principal(auth, username="alice", display_name="Alice", role="student")
        bob = await create_principal(auth, username="bob", display_name="Bob", role="student")
        assert bob.user_id is not None
        await auth.set_user_active(bob.user_id, False, datetime.now(UTC))
        service = InstructorMessageService(messages=InMemoryInstructorMessageStore(), auth=auth)
        tool = InstructorListStudentsTool(service)
        context = ToolExecutionContext(
            principal=principal, conversation_id=uuid4(), permitted_resource_uris=frozenset()
        )
        if role != "instructor":
            with pytest.raises(ToolValidationError, match="instructor login"):
                await tool.execute({}, context)
            # A stale or forged role claim must not override the stored role.
            with pytest.raises(InstructorMessageAccessDenied, match="instructor login"):
                await service.list_students(
                    principal.model_copy(update={"roles": ["public", "instructor"]})
                )
        else:
            result = await tool.execute({"limit": 1}, context)
            assert result.content == {
                "students": [
                    {"username": "alice", "display_name": "Alice", "email": "alice@mit.edu"}
                ],
                "total": 1,
                "next_offset": None,
            }
            assert result.storage_policy == "server_summary"
            assert result.summary is not None
            assert "alice@mit.edu" not in result.summary
            assert principal.user_id is not None
            await auth.set_user_active(principal.user_id, False, datetime.now(UTC))
            with pytest.raises(ToolValidationError, match="instructor login"):
                await tool.execute({}, context)
        assert alice.user_id is not None

    asyncio.run(scenario())
