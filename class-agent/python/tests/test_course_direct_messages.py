from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import uuid4

import httpx
import psycopg
import pytest
from psycopg import sql

from agent_core import PrincipalContext
from course_server.auth import UserAdminService
from course_server.course_direct_messages import (
    COURSE_STAFF_RECIPIENT,
    CourseDirectMessageService,
    CourseMessageError,
)
from course_server.course_roster import CourseMember, CourseRoster
from course_server.mail import InboundMail, OutboundMail, SentMail
from course_server.mail.course_message_delivery import CourseMessageEmailDelivery
from course_server.mcp_server import CourseMcpSettings, create_course_mcp_app
from course_server.migrations import apply_migrations
from course_server.postgres.auth_store import PostgresAuthStore, create_auth_pool

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")


def _schema_url(database_url: str, schema_name: str) -> str:
    parsed = urlsplit(database_url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query["options"] = f"-csearch_path={schema_name}"
    return urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, urlencode(query), parsed.fragment)
    )


def _member(username: str) -> CourseMember:
    return CourseMember(
        student_id=username,
        name=username.title(),
        email=f"{username}@example.edu",
        username=username,
        github_username=f"{username}-github",
        institution="Example University",
        department="Example Department",
        enrollment_type="credit",
        course_status="active",
        participation="listener_only",
    )


@dataclass
class RecordingMail:
    sent: list[OutboundMail] = field(default_factory=list)

    async def send_message(self, message: OutboundMail) -> SentMail:
        self.sent.append(message)
        count = len(self.sent)
        return SentMail(
            provider_message_id=f"provider-{count}",
            internet_message_id=f"<message-{count}@example.edu>",
        )

    async def reply_to_message(
        self, original: InboundMail, *, text: str, headers: dict[str, str] | None = None
    ) -> SentMail:
        raise NotImplementedError

    async def reply_to_sent_message(
        self,
        original: SentMail,
        *,
        to: tuple[str, ...],
        subject: str,
        text: str,
        headers: dict[str, str] | None = None,
    ) -> SentMail:
        raise NotImplementedError

    async def fetch_new_messages(self, *, since: object) -> list[InboundMail]:
        raise NotImplementedError


@pytest.mark.postgres
@pytest.mark.skipif(TEST_DATABASE_URL is None, reason="TEST_DATABASE_URL is not configured")
def test_course_messages_require_human_confirmation_and_scope_replies() -> None:
    assert TEST_DATABASE_URL is not None
    schema_name = f"test_direct_messages_{uuid4().hex}"
    with psycopg.connect(TEST_DATABASE_URL) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema_name)))
    database_url = _schema_url(TEST_DATABASE_URL, schema_name)

    async def scenario() -> None:
        assert apply_migrations(database_url)[-1] == "0018_mcp_usage"
        pool = create_auth_pool(database_url)
        await pool.open()
        await pool.wait()
        try:
            auth = PostgresAuthStore(pool)
            admin = UserAdminService(auth)
            people = {}
            for username, role in (
                ("alice", "student"),
                ("bob", "student"),
                ("outsider", "student"),
                ("prof", "instructor"),
                ("tauser", "ta"),
            ):
                issued = await admin.create_user(
                    username=username,
                    display_name=username.title(),
                    email=f"{username}@example.edu",
                    role=role,  # type: ignore[arg-type]
                )
                people[username] = PrincipalContext(
                    authenticated=True,
                    user_id=issued.user.id,
                    username=username,
                    roles=["public", role],
                    session_id=uuid4(),
                )
            roster = CourseRoster(
                schema_version=1,
                as_of=date(2026, 10, 30),
                members=[_member("alice"), _member("bob")],
            )
            service = CourseDirectMessageService(pool, auth, roster)
            alice, bob, prof, ta = (
                people["alice"],
                people["bob"],
                people["prof"],
                people["tauser"],
            )
            with pytest.raises(CourseMessageError, match="membership"):
                await service.list_recipients(people["outsider"])
            recipients = await service.list_recipients(alice)
            assert {item["username"] for item in recipients} == {
                "bob",
                "prof",
                "tauser",
                COURSE_STAFF_RECIPIENT,
            }
            draft = await service.prepare(
                alice, recipient_username="bob", subject="Study group", body="Can we compare ideas?"
            )
            assert (await service.list_mine(bob))["total"] == 0
            with pytest.raises(CourseMessageError, match="unavailable"):
                await service.read_mine(bob, draft.id)
            sent = await service.confirm(
                alice, draft.id, action="send", body="Let's compare ideas."
            )
            assert sent.status == "sent"
            assert sent.body == "Let's compare ideas."
            assert (await service.list_mine(bob))["total"] == 1
            assert "body" not in (await service.list_mine(bob))["messages"][0]
            assert (await service.read_mine(bob, sent.id)).body == "Let's compare ideas."
            with pytest.raises(CourseMessageError, match="no longer"):
                await service.confirm(alice, draft.id, action="send")
            with pytest.raises(CourseMessageError, match="unavailable"):
                await service.read_mine(prof, sent.id)

            reply = await service.prepare(
                bob,
                recipient_username="ignored",
                subject="Re: Study group",
                body="Yes, let's talk.",
                reply_to=sent.id,
            )
            assert reply.recipient_user_id == alice.user_id
            await service.confirm(bob, reply.id, action="send")

            staff_draft = await service.prepare(
                alice,
                recipient_username=COURSE_STAFF_RECIPIENT,
                subject="Question",
                body="Can you clarify the deadline?",
            )
            await service.confirm(alice, staff_draft.id, action="send")
            assert (await service.list_mine(prof))["total"] == 1
            assert (await service.list_mine(ta))["total"] == 1
            staff_reply = await service.prepare(
                prof,
                recipient_username="ignored",
                subject="Re: Question",
                body="Here is the deadline.",
                reply_to=staff_draft.id,
            )
            assert staff_reply.recipient_user_id == alice.user_id
            await service.confirm(prof, staff_reply.id, action="send")

            assert alice.user_id is not None and prof.user_id is not None
            async with pool.connection() as connection:
                conversation_id = uuid4()
                await connection.execute(
                    "INSERT INTO conversations (id, user_id, created_at, updated_at) "
                    "VALUES (%s, %s, now(), now())",
                    (conversation_id, prof.user_id),
                )
                instructor_id = uuid4()
                await connection.execute(
                    """
                    INSERT INTO instructor_messages (
                        id, conversation_id, sender_user_id, audience, subject,
                        body, status, created_at, sent_at
                    ) VALUES (%s, %s, %s, 'specific_students', 'Room change',
                              'Meet elsewhere', 'sent', now(), now())
                    """,
                    (instructor_id, conversation_id, prof.user_id),
                )
                await connection.execute(
                    "INSERT INTO instructor_message_recipients "
                    "(message_id, student_user_id) VALUES (%s, %s)",
                    (instructor_id, alice.user_id),
                )
                question_id = uuid4()
                await connection.execute(
                    """
                    INSERT INTO ta_questions (
                        id, public_question_code, student_user_id, conversation_id,
                        subject, question_text, status, sent_event_id, created_at
                    ) VALUES (%s, 'Q-2026-00001', %s, %s,
                              'Original question', 'How?', 'answered', %s, now())
                    """,
                    (question_id, alice.user_id, conversation_id, uuid4()),
                )
            instructor_reply = await service.prepare(
                alice,
                recipient_username="ignored",
                subject="Re: Room change",
                body="I have a question.",
                reply_to=instructor_id,
            )
            assert instructor_reply.recipient_user_id == prof.user_id
            ta_reply = await service.prepare(
                alice,
                recipient_username="ignored",
                subject="Re: Original question",
                body="A follow-up.",
                reply_to=question_id,
            )
            assert ta_reply.recipient_kind == "course_staff"
            with pytest.raises(CourseMessageError, match="cannot be replied"):
                await service.prepare(
                    bob,
                    recipient_username="ignored",
                    subject="Intrusion",
                    body="Should fail",
                    reply_to=instructor_id,
                )

            mail = RecordingMail()
            delivery = CourseMessageEmailDelivery(
                pool,
                mail,
                staff_recipient="staff@example.edu",
                public_base_url="https://course.example.edu",
                roster=roster,
            )
            await delivery.run_once()
            assert len(mail.sent) == 4
            removed_recipient = await service.prepare(
                alice,
                recipient_username="bob",
                subject="After enrollment change",
                body="This email should not be delivered.",
            )
            await service.confirm(alice, removed_recipient.id, action="send")
            changed_roster = CourseRoster(
                schema_version=1,
                as_of=date(2026, 10, 31),
                members=[_member("alice")],
            )
            changed_delivery = CourseMessageEmailDelivery(
                pool,
                mail,
                staff_recipient="staff@example.edu",
                public_base_url="https://course.example.edu",
                roster=changed_roster,
            )
            await changed_delivery.run_once()
            assert len(mail.sent) == 4
            async with pool.connection() as connection:
                email_state = await (
                    await connection.execute(
                        "SELECT email_last_error, email_abandoned_at "
                        "FROM course_direct_messages WHERE id = %s",
                        (removed_recipient.id,),
                    )
                ).fetchone()
            assert email_state is not None
            assert email_state["email_last_error"] == "recipient_unavailable"
            assert email_state["email_abandoned_at"] is not None
            assert {str(item.to[0]) for item in mail.sent} == {
                "alice@example.edu",
                "bob@example.edu",
                "staff@example.edu",
            }
            await delivery.run_once()
            assert len(mail.sent) == 4
        finally:
            await pool.close()

    try:
        asyncio.run(scenario())
    finally:
        with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as connection:
            connection.execute(
                sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema_name))
            )


@pytest.mark.postgres
@pytest.mark.skipif(TEST_DATABASE_URL is None, reason="TEST_DATABASE_URL is not configured")
def test_course_message_pages_require_owned_login_and_explicit_send(tmp_path: Path) -> None:
    assert TEST_DATABASE_URL is not None
    schema_name = f"test_message_pages_{uuid4().hex}"
    with psycopg.connect(TEST_DATABASE_URL) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema_name)))
    database_url = _schema_url(TEST_DATABASE_URL, schema_name)

    async def scenario() -> None:
        pool = create_auth_pool(database_url)
        await pool.open()
        await pool.wait()
        try:
            roster = CourseRoster(
                schema_version=1,
                as_of=date(2026, 10, 30),
                members=[_member("alice"), _member("bob")],
            )
            settings = CourseMcpSettings(
                database_url=database_url,
                public_base_url="https://course.example.edu",
                assignment_data_path=tmp_path / "assignments",
                course_roster_path=tmp_path / "unused-roster.json",
                course_data_path=tmp_path / "data",
                published_faq_path=tmp_path / "faq.json",
                messaging_enabled=True,
                mail_enabled=True,
            )
            app = create_course_mcp_app(settings, pool=pool, roster=roster)
            async with app.router.lifespan_context(app):
                admin = UserAdminService(PostgresAuthStore(pool))
                alice = await admin.create_user(
                    username="alice",
                    display_name="Alice",
                    email="alice@example.edu",
                    role="student",
                )
                bob = await admin.create_user(
                    username="bob",
                    display_name="Bob",
                    email="bob@example.edu",
                    role="student",
                )
                service = app.state.course_direct_messages
                assert service is not None
                principal = PrincipalContext(
                    authenticated=True,
                    user_id=alice.user.id,
                    username="alice",
                    roles=["public", "student"],
                    session_id=uuid4(),
                )
                draft = await service.prepare(
                    principal, recipient_username="bob", subject="Meet?", body="Can we talk?"
                )
                tool_names = {tool.name for tool in await app.state.course_mcp.list_tools()}
                assert {"prepare_course_message", "prepare_course_reply"} <= tool_names
                transport = httpx.ASGITransport(app=app)
                async with httpx.AsyncClient(
                    transport=transport,
                    base_url=settings.public_base_url,
                    follow_redirects=False,
                ) as browser:
                    page = await browser.get(f"/messages/confirm/{draft.id}")
                    assert page.status_code == 303
                    assert page.headers["location"].startswith("/messages/login")
                    login = await browser.post(
                        "/messages/login",
                        headers={"Origin": "null", "Sec-Fetch-Site": "same-origin"},
                        data={
                            "username": "alice",
                            "access_code": alice.access_code,
                            "next": f"/messages/confirm/{draft.id}",
                        },
                    )
                    assert login.status_code == 303
                    review = await browser.get(f"/messages/confirm/{draft.id}")
                    assert review.status_code == 200
                    assert "Bob (bob)" in review.text
                    assert "Can we talk?" in review.text
                    denied = await browser.post(
                        f"/messages/confirm/{draft.id}",
                        headers={"Origin": "https://evil.example"},
                        data={"action": "send", "subject": "Meet?", "body": "Can we talk?"},
                    )
                    assert denied.status_code == 400
                    assert (await service.list_mine(principal))["total"] == 0
                    sent = await browser.post(
                        f"/messages/confirm/{draft.id}",
                        headers={"Origin": "null", "Sec-Fetch-Site": "same-origin"},
                        data={
                            "action": "send",
                            "subject": "Meet tomorrow?",
                            "body": "Can we talk tomorrow?",
                        },
                    )
                    assert sent.status_code == 303
                    assert sent.headers["location"] == f"/messages/{draft.id}"
                    assert (await service.list_mine(principal))["total"] == 1
                async with httpx.AsyncClient(
                    transport=transport,
                    base_url=settings.public_base_url,
                    follow_redirects=False,
                ) as recipient_browser:
                    login = await recipient_browser.post(
                        "/messages/login",
                        headers={"Origin": settings.public_base_url},
                        data={"username": "bob", "access_code": bob.access_code},
                    )
                    assert login.status_code == 303
                    inbox = await recipient_browser.get("/messages")
                    assert inbox.status_code == 200
                    assert "Meet tomorrow?" in inbox.text
                    message = await recipient_browser.get(f"/messages/{draft.id}")
                    assert "Can we talk tomorrow?" in message.text
                    reply = await recipient_browser.post(
                        f"/messages/{draft.id}/reply",
                        headers={"Origin": "null", "Sec-Fetch-Site": "same-origin"},
                        data={"body": "Yes."},
                    )
                    assert reply.status_code == 303
                    assert reply.headers["location"].startswith("/messages/confirm/")
        finally:
            await pool.close()

    try:
        asyncio.run(scenario())
    finally:
        with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as connection:
            connection.execute(
                sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema_name))
            )
