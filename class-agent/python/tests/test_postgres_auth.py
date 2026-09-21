from __future__ import annotations

import asyncio
import os
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql

from agent_core import Conversation, Event
from course_server.auth import AuthenticationService, UserAdminService
from course_server.auth.security import hash_session_token
from course_server.faq import PostgresFaqStore
from course_server.index_resources import index_resources
from course_server.instructor_messages import (
    PENDING_QUESTION_RECIPIENT_PREFIX,
    InstructorMessageContent,
    InstructorMessageDraft,
    InstructorMessageService,
    PostgresInstructorMessageStore,
)
from course_server.mail import InboundMail, PostgresTAQuestionStore, SentMail
from course_server.migrations import apply_migrations
from course_server.postgres.auth_store import PostgresAuthStore, create_auth_pool
from course_server.postgres.conversation_store import PostgresConversationStore

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

pytestmark = [
    pytest.mark.postgres,
    pytest.mark.skipif(
        TEST_DATABASE_URL is None,
        reason="TEST_DATABASE_URL is not configured",
    ),
]


def _database_url_for_schema(database_url: str, schema_name: str) -> str:
    parsed = urlsplit(database_url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query["options"] = f"-csearch_path={schema_name}"
    return urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, urlencode(query), parsed.fragment)
    )


def test_postgres_auth_store_roundtrip() -> None:
    assert TEST_DATABASE_URL is not None
    schema_name = f"test_auth_{uuid4().hex}"
    with psycopg.connect(TEST_DATABASE_URL) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema_name)))

    scoped_url = _database_url_for_schema(TEST_DATABASE_URL, schema_name)
    try:
        assert apply_migrations(scoped_url) == [
            "0001_authentication",
            "0002_conversations_events",
            "0003_course_resources",
            "0004_anonymous_quotas",
            "0005_ta_email",
            "0006_email_faq_review",
            "0007_single_reply_faq_decision",
            "0008_faq_archives",
            "0009_local_faq_knowledge",
            "0010_notification_center",
            "0011_instructor_messages",
            "0012_online_question_answers",
            "0013_online_answer_retention",
            "0014_instructor_message_email",
        ]
        assert apply_migrations(scoped_url) == []
        assert index_resources(scoped_url) == [
            "course://syllabus",
            "course://schedule",
            "course://repositories",
            "course://faq",
            "course://instructors",
            "course://application",
            "course://slides/week-01",
        ]
        with psycopg.connect(scoped_url) as connection:
            assert connection.execute("SELECT count(*) FROM course_resources").fetchone() == (7,)
            assert connection.execute(
                "SELECT count(*) FROM faq_entries WHERE active"
            ).fetchone() == (6,)

        async def scenario() -> None:
            pool = create_auth_pool(scoped_url)
            await pool.open()
            await pool.wait()
            try:
                store = PostgresAuthStore(pool)
                admin = UserAdminService(store)
                auth = AuthenticationService(store)
                issued = await admin.create_user(
                    username="alice",
                    display_name="Alice Example",
                    email="alice@mit.edu",
                    role="student",
                )
                stored = await store.get_user_by_username("alice")
                assert stored is not None
                assert (await store.get_user_by_email("ALICE@MIT.EDU")) == stored
                assert stored.access_code_hash.get_secret_value().startswith("$argon2id$")
                assert issued.access_code not in stored.access_code_hash.get_secret_value()

                credential = await auth.login(
                    username="alice",
                    access_code=issued.access_code,
                )
                principal = await auth.resolve_authenticated(credential.token)
                assert principal.user_id == issued.user.id
                assert principal.roles == ["public", "student"]

                instructor = await admin.create_user(
                    username="prof",
                    display_name="Professor Example",
                    email="prof@mit.edu",
                    role="instructor",
                )
                instructor_credential = await auth.login(
                    username="prof",
                    access_code=instructor.access_code,
                )
                assert (await auth.resolve_authenticated(instructor_credential.token)).roles == [
                    "public",
                    "instructor",
                ]
                instructor_principal = await auth.resolve_authenticated(instructor_credential.token)

                conversations = PostgresConversationStore(pool)
                conversation = Conversation(user_id=principal.user_id)
                await conversations.create_conversation(conversation)
                event = Event(
                    type="user.message",
                    actor="user",
                    principal_user_id=principal.user_id,
                    conversation_id=conversation.id,
                    payload={"text": "Hello"},
                )
                await conversations.append_events(conversation.id, [event])
                assert await conversations.get_conversation(conversation.id) is not None
                assert await conversations.list_events(conversation.id) == [event]
                assert [item.id for item in await conversations.list_conversations(principal)] == [
                    conversation.id
                ]

                questions = PostgresTAQuestionStore(pool)
                question = await questions.create_question(
                    student_user_id=issued.user.id,
                    conversation_id=conversation.id,
                    subject="Assignment model",
                    question_text="May I use a local model?",
                    context_text=None,
                    created_at=conversation.created_at,
                )
                queued = await questions.transition_question(
                    question.id,
                    expected="pending_confirmation",
                    status="queued",
                    changed_at=conversation.created_at,
                )
                assert queued is not None and queued.status == "queued"
                opened = await questions.mark_question_sent(
                    question.id,
                    SentMail(
                        provider_message_id="provider-question",
                        internet_message_id="<question@example.edu>",
                    ),
                    sent_at=conversation.created_at,
                )
                assert opened is not None and opened.status == "open"
                assert [item.id for item in await questions.list_questions_pending_event()] == [
                    question.id
                ]
                await questions.mark_question_event_recorded(
                    question.id,
                    recorded_at=conversation.created_at,
                )
                answer = await questions.record_answer(
                    opened,
                    InboundMail(
                        provider_message_id="provider-answer",
                        internet_message_id="<answer@example.edu>",
                        sender=instructor.user.email,
                        subject=f"Re: {question.public_question_code}",
                        text="Yes.",
                        received_at=conversation.created_at,
                        headers={"in-reply-to": "<question@example.edu>"},
                    ),
                    answer_text="Yes.",
                    publication="publish",
                    processed_at=conversation.created_at,
                )
                assert answer is not None
                assert [item.id for item in await questions.list_answers_pending_event()] == [
                    answer.id
                ]
                await questions.mark_answer_notified(
                    answer.id,
                    SentMail(
                        provider_message_id="provider-student-notification",
                        internet_message_id="<student-notification@example.edu>",
                    ),
                    notified_at=conversation.created_at,
                )
                candidates = await questions.list_faq_candidates_pending_publication()
                assert len(candidates) == 1
                candidate = candidates[0]
                faqs = PostgresFaqStore(pool)
                published = await faqs.publish(
                    source_question_id=question.id,
                    question="Can assignments use local models?",
                    answer="Yes, with setup instructions.",
                    published_by_user_id=instructor.user.id,
                    published_at=conversation.created_at,
                )
                await questions.mark_faq_candidate_published(
                    candidate.id,
                    published_faq_entry_id=published.id,
                )
                assert await questions.list_faq_candidates_pending_publication() == []
                assert [entry.id for entry in await faqs.list_active()] == [published.id]
                notifications = await faqs.list_unread(issued.user.id)
                assert len(notifications) == 1
                assert await faqs.mark_read(
                    user_id=issued.user.id,
                    notification_id=notifications[0].id,
                    read_at=conversation.created_at,
                )
                assert await faqs.list_unread(issued.user.id) == []

                instructor_conversation = Conversation(user_id=instructor.user.id)
                await conversations.create_conversation(instructor_conversation)
                message_store = PostgresInstructorMessageStore(pool)
                messaging = InstructorMessageService(
                    messages=message_store,
                    auth=store,
                    questions=questions,
                )
                prepared = await messaging.prepare(
                    principal=instructor_principal,
                    conversation_id=instructor_conversation.id,
                    draft=InstructorMessageDraft(
                        greeting="Hello students,",
                        sign_off="Best,\nProfessor Example",
                        audience="specific_students",
                        recipients=["alice"],
                        subject="Studio reminder",
                        message="Bring your prototype to class.",
                    ),
                )
                assert await message_store.list_sent_for_student(issued.user.id) == []
                await messaging.confirm(
                    principal=instructor_principal,
                    conversation_id=instructor_conversation.id,
                    message_id=prepared.message.id,
                )
                delivered = await message_store.list_sent_for_student(issued.user.id)
                assert [message.id for message in delivered] == [prepared.message.id]

                online_question = await questions.create_question(
                    student_user_id=issued.user.id,
                    conversation_id=conversation.id,
                    subject="Online response",
                    question_text="Can this be answered online?",
                    context_text=None,
                    created_at=conversation.created_at,
                )
                queued_online_question = await questions.transition_question(
                    online_question.id,
                    expected="pending_confirmation",
                    status="queued",
                    changed_at=conversation.created_at,
                )
                assert queued_online_question is not None
                online_question = queued_online_question
                online_reply = await messaging.prepare(
                    principal=instructor_principal,
                    conversation_id=instructor_conversation.id,
                    draft=InstructorMessageDraft(
                        audience="specific_students",
                        recipients=[f"{PENDING_QUESTION_RECIPIENT_PREFIX}{online_question.id}"],
                        subject="Re: Online response",
                        message="Answer this privately.",
                    ),
                )
                await messaging.confirm(
                    principal=instructor_principal,
                    conversation_id=instructor_conversation.id,
                    message_id=online_reply.message.id,
                    content=InstructorMessageContent(
                        subject="Re: Online response",
                        message="PUBLISH\nPublish this answer.",
                    ),
                )
                online_thread = next(
                    thread
                    for thread in await questions.list_student_threads(
                        student_user_id=issued.user.id
                    )
                    if thread.question.id == online_question.id
                )
                assert online_thread.question.status == "answered"
                assert online_thread.answer is not None
                assert online_thread.answer.source == "online"
                assert online_thread.answer.publication_decision == "publish"
                assert [
                    message.id
                    for message in await message_store.list_sent_for_student(issued.user.id)
                ] == [prepared.message.id]

                anonymous = await auth.create_anonymous()
                assert (await auth.resolve_anonymous(anonymous.token)).roles == ["public"]

                await auth.logout(credential.token)
                session = await store.get_auth_session(
                    hash_session_token(credential.token, kind="authenticated")
                )
                assert session is not None and session.revoked_at is not None
            finally:
                await pool.close()

        asyncio.run(scenario())
        index_resources(scoped_url)
        with psycopg.connect(scoped_url) as connection:
            assert connection.execute(
                """
                SELECT count(*) FROM faq_entries
                WHERE source_question_id IS NOT NULL AND active
                """
            ).fetchone() == (1,)

    finally:
        with psycopg.connect(TEST_DATABASE_URL) as connection:
            connection.execute(
                sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema_name))
            )


def test_instructor_email_outbox_retries_only_failed_recipients() -> None:
    from unittest.mock import AsyncMock

    from course_server.mail.instructor_delivery import InstructorEmailDelivery
    from course_server.mail.models import MailAdapter

    assert TEST_DATABASE_URL is not None
    schema_name = f"test_instructor_email_{uuid4().hex}"
    with psycopg.connect(TEST_DATABASE_URL) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema_name)))
    scoped_url = _database_url_for_schema(TEST_DATABASE_URL, schema_name)
    try:
        apply_migrations(scoped_url)

        async def scenario() -> None:
            pool = create_auth_pool(scoped_url)
            await pool.open()
            try:
                store = PostgresAuthStore(pool)
                admin = UserAdminService(store)
                instructor = await admin.create_user(
                    username="prof", display_name="Prof", email="prof@mit.edu", role="instructor"
                )
                for name in ("alice", "bob", "inactive"):
                    await admin.create_user(
                        username=name, display_name=name, email=f"{name}@mit.edu", role="student"
                    )
                auth = AuthenticationService(store)
                login = await auth.login(username="prof", access_code=instructor.access_code)
                principal = await auth.resolve_authenticated(login.token)
                conversations = PostgresConversationStore(pool)
                conversation = Conversation(user_id=instructor.user.id)
                await conversations.create_conversation(conversation)
                messages = PostgresInstructorMessageStore(pool)
                service = InstructorMessageService(
                    messages=messages, auth=store, email_enabled=True
                )
                adapter = AsyncMock(spec=MailAdapter)
                delivery = InstructorEmailDelivery(pool, adapter)
                prepared = await service.prepare(
                    principal=principal,
                    conversation_id=conversation.id,
                    draft=InstructorMessageDraft(
                        greeting="Hello students,",
                        sign_off="Best,\nProfessor Example",
                        audience="all_students",
                        subject="Draft",
                        message="Original",
                    ),
                )
                await delivery.run_once()
                adapter.send_message.assert_not_called()
                await service.confirm(
                    principal=principal,
                    conversation_id=conversation.id,
                    message_id=prepared.message.id,
                    content=InstructorMessageContent(
                        subject="Reviewed",
                        message="Hello students,\n\nFinal body.\n\nBest,\nChitra",
                        send_email=True,
                    ),
                )
                async with pool.connection() as connection:
                    await connection.execute(
                        "UPDATE users SET active = false WHERE username = 'inactive'"
                    )
                await admin.create_user(
                    username="later", display_name="Later", email="later@mit.edu", role="student"
                )
                adapter.send_message.side_effect = [
                    RuntimeError("private provider details"),
                    SentMail(provider_message_id="ok", internet_message_id="<ok>"),
                ]
                await delivery.run_once()
                assert adapter.send_message.call_count == 2
                first_calls = [call.args[0] for call in adapter.send_message.call_args_list]
                assert {str(mail.to[0]) for mail in first_calls} == {"alice@mit.edu", "bob@mit.edu"}
                assert all(
                    len(mail.to) == 1
                    and mail.subject == "Reviewed"
                    and mail.text == "Hello students,\n\nFinal body.\n\nBest,\nChitra"
                    for mail in first_calls
                )
                adapter.send_message.side_effect = None
                adapter.send_message.return_value = SentMail(
                    provider_message_id="retry", internet_message_id="<retry>"
                )
                await asyncio.gather(delivery.run_once(), delivery.run_once())
                assert adapter.send_message.call_count == 3
                assert adapter.send_message.call_args.args[0].to == first_calls[0].to
                await delivery.run_once()
                assert adapter.send_message.call_count == 3
                for action in ("cancel", "in_app"):
                    pending = await service.prepare(
                        principal=principal,
                        conversation_id=conversation.id,
                        draft=InstructorMessageDraft(
                            greeting="Hello students,",
                            sign_off="Best,\nProfessor Example",
                            audience="all_students",
                            subject="Other",
                            message="In app only",
                        ),
                    )
                    if action == "cancel":
                        await service.cancel(
                            principal=principal,
                            conversation_id=conversation.id,
                            message_id=pending.message.id,
                        )
                    else:
                        await service.confirm(
                            principal=principal,
                            conversation_id=conversation.id,
                            message_id=pending.message.id,
                        )
                    await delivery.run_once()
                    assert adapter.send_message.call_count == 3
                persisted = await messages.get(prepared.message.id)
                assert persisted is not None and persisted.message.send_email
            finally:
                await pool.close()

        asyncio.run(scenario())
    finally:
        with psycopg.connect(TEST_DATABASE_URL) as connection:
            connection.execute(
                sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema_name))
            )
