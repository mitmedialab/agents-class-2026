from __future__ import annotations

import asyncio
import base64
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from email import policy
from email.parser import BytesParser
from pathlib import Path
from urllib.parse import parse_qs
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr

from agent_core import Conversation, PrincipalContext
from course_server.agent import (
    FileResourceProvider,
    InMemoryConversationStore,
    ToolExecutionContext,
)
from course_server.auth import InMemoryAuthStore, StoredUser
from course_server.faq import (
    CoordinatedFaqPublisher,
    FaqKnowledgeError,
    InMemoryFaqStore,
    LocalFaqKnowledgeStore,
    PublishedFaqResourceCatalog,
)
from course_server.mail import (
    CourseAskTATool,
    GoogleGmailMailAdapter,
    InboundMail,
    InMemoryTAQuestionStore,
    MailWorker,
    MicrosoftGraphMailAdapter,
    OutboundMail,
    SentMail,
    TAQuestionAccessDenied,
    TAQuestionService,
    parse_faq_review_reply,
    parse_staff_answer_reply,
)


@dataclass
class MutableClock:
    current: datetime

    def __call__(self) -> datetime:
        return self.current


@dataclass
class RecordingMailAdapter:
    incoming: list[InboundMail] = field(default_factory=list)
    sent: list[OutboundMail] = field(default_factory=list)
    replies: list[tuple[InboundMail, str, dict[str, str]]] = field(default_factory=list)

    async def send_message(self, message: OutboundMail) -> SentMail:
        self.sent.append(message)
        sequence = len(self.sent)
        return SentMail(
            provider_message_id=f"provider-{sequence}",
            internet_message_id=f"<sent-{sequence}@course.example>",
        )

    async def fetch_new_messages(self, *, since: datetime) -> list[InboundMail]:
        return [message for message in self.incoming if message.received_at >= since]

    async def reply_to_message(
        self,
        original: InboundMail,
        *,
        text: str,
        headers: dict[str, str] | None = None,
    ) -> SentMail:
        self.replies.append((original, text, headers or {}))
        sequence = len(self.replies)
        return SentMail(
            provider_message_id=f"review-provider-{sequence}",
            internet_message_id=f"<review-{sequence}@course.example>",
        )


def _user(*, role: str, email: str, now: datetime) -> StoredUser:
    return StoredUser(
        id=uuid4(),
        username=email.split("@", 1)[0],
        display_name=email.split("@", 1)[0].title(),
        email=email,
        role=role,
        active=True,
        created_at=now,
        updated_at=now,
        access_code_hash=SecretStr("not-used"),
    )


def _principal(user: StoredUser) -> PrincipalContext:
    return PrincipalContext(
        authenticated=True,
        user_id=user.id,
        username=user.username,
        display_name=user.display_name,
        roles=["public", user.role],
        session_id=uuid4(),
    )


def test_ask_ta_prepares_private_confirmation_without_sending_email() -> None:
    async def scenario() -> None:
        now = datetime(2026, 9, 4, 15, 0, tzinfo=UTC)
        auth = InMemoryAuthStore()
        student = _user(role="student", email="student@example.edu", now=now)
        await auth.create_user(student)
        questions = InMemoryTAQuestionStore()
        service = TAQuestionService(questions=questions, auth=auth, clock=lambda: now)
        tool = CourseAskTATool(service)
        conversation_id = uuid4()

        result = await tool.execute(
            {
                "subject": "Assignment model",
                "question": "May I use a local model?",
                "context": "The assignment page does not specify deployment.",
            },
            ToolExecutionContext(
                principal=_principal(student),
                conversation_id=conversation_id,
                permitted_resource_uris=frozenset(),
            ),
        )

        assert len(questions.questions) == 1
        question = next(iter(questions.questions.values()))
        assert question.status == "pending_confirmation"
        assert question.student_user_id == student.id
        assert result.storage_policy == "server_summary"
        assert result.emitted_events[0].type == "email.ta_question.confirmation_requested"
        assert result.emitted_events[0].payload["question"] == "May I use a local model?"

        anonymous_id = uuid4()
        with pytest.raises(TAQuestionAccessDenied, match="student login required"):
            await service.prepare(
                principal=PrincipalContext(
                    authenticated=False,
                    anonymous_session_id=anonymous_id,
                    roles=["public"],
                    session_id=anonymous_id,
                ),
                conversation_id=conversation_id,
                subject="No login",
                question="Can this send?",
                context=None,
            )

    asyncio.run(scenario())


def test_local_faq_knowledge_rejects_malformed_json(tmp_path: Path) -> None:
    faq_path = tmp_path / "published-faq.json"
    faq_path.write_text('{"schema_version": 1, "entries": [}', encoding="utf-8")

    with pytest.raises(FaqKnowledgeError, match="invalid local FAQ knowledge"):
        asyncio.run(LocalFaqKnowledgeStore(faq_path).list_active())


def test_graph_adapter_uses_app_token_immutable_ids_and_unique_reply_body() -> None:
    async def scenario() -> None:
        requests: list[httpx.Request] = []

        def respond(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            path = request.url.path
            if request.url.host == "login.test":
                return httpx.Response(200, json={"access_token": "token", "expires_in": 3600})
            if request.method == "POST" and path.endswith("/messages"):
                return httpx.Response(201, json={"id": "draft-id"})
            if request.method == "POST" and path.endswith("/messages/draft-id/send"):
                return httpx.Response(202)
            if request.method == "GET" and path.endswith("/messages/draft-id"):
                return httpx.Response(
                    200,
                    json={"id": "draft-id", "internetMessageId": "<question@example.edu>"},
                )
            if request.method == "GET" and path.endswith("/mailFolders/inbox/messages"):
                return httpx.Response(200, json={"value": [{"id": "reply-id"}]})
            if request.method == "GET" and path.endswith("/messages/reply-id"):
                return httpx.Response(
                    200,
                    json={
                        "id": "reply-id",
                        "internetMessageId": "<reply@example.edu>",
                        "subject": "Re: Q-2026-00001",
                        "from": {"emailAddress": {"address": "instructor@example.edu"}},
                        "receivedDateTime": "2026-09-04T15:01:00Z",
                        "uniqueBody": {"contentType": "text", "content": "Approved."},
                        "internetMessageHeaders": [
                            {"name": "In-Reply-To", "value": "<question@example.edu>"}
                        ],
                    },
                )
            if request.method == "POST" and path.endswith("/messages/reply-id/createReply"):
                return httpx.Response(201, json={"id": "reply-draft-id"})
            if request.method == "PATCH" and path.endswith("/messages/reply-draft-id"):
                return httpx.Response(200)
            if request.method == "POST" and path.endswith("/messages/reply-draft-id/send"):
                return httpx.Response(202)
            if request.method == "GET" and path.endswith("/messages/reply-draft-id"):
                return httpx.Response(
                    200,
                    json={
                        "id": "reply-draft-id",
                        "internetMessageId": "<faq-review@example.edu>",
                    },
                )
            return httpx.Response(404)

        client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        adapter = MicrosoftGraphMailAdapter(
            tenant_id="tenant",
            client_id="client",
            client_secret="secret",
            mailbox_address="course-agent@example.edu",
            client=client,
            graph_base_url="https://graph.test/v1.0",
            login_base_url="https://login.test",
        )

        sent = await adapter.send_message(
            OutboundMail(
                to=("staff@example.edu",),
                subject="Question",
                text="May I use a local model?",
                headers={"X-Course-Agent-Question": "Q-2026-00001"},
            )
        )
        replies = await adapter.fetch_new_messages(since=datetime(2026, 9, 4, 15, 0, tzinfo=UTC))
        review = await adapter.reply_to_message(
            replies[0],
            text="Publish this answer?",
            headers={"X-Course-Agent-FAQ-Review": "candidate-id"},
        )
        await client.aclose()

        assert sent.internet_message_id == "<question@example.edu>"
        assert replies[0].text == "Approved."
        assert replies[0].headers["in-reply-to"] == "<question@example.edu>"
        assert review.internet_message_id == "<faq-review@example.edu>"
        graph_requests = [request for request in requests if request.url.host == "graph.test"]
        assert all(
            'IdType="ImmutableId"' in request.headers["Prefer"] for request in graph_requests
        )
        reply_request = next(
            request for request in graph_requests if request.url.path.endswith("/messages/reply-id")
        )
        assert 'outlook.body-content-type="text"' in reply_request.headers["Prefer"]
        update_request = next(
            request
            for request in graph_requests
            if request.method == "PATCH" and request.url.path.endswith("/messages/reply-draft-id")
        )
        update = httpx.Response(200, content=update_request.read()).json()
        assert update["body"]["content"] == "Publish this answer?"
        assert update["internetMessageHeaders"] == [
            {"name": "X-Course-Agent-FAQ-Review", "value": "candidate-id"}
        ]

    asyncio.run(scenario())


def test_gmail_adapter_refreshes_token_sends_mime_and_extracts_unique_reply() -> None:
    async def scenario() -> None:
        requests: list[httpx.Request] = []
        sent_mime: list[bytes] = []
        sent_payloads: list[dict[str, str]] = []

        def encode(value: str) -> str:
            return base64.urlsafe_b64encode(value.encode()).decode().rstrip("=")

        def respond(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            path = request.url.path
            if request.url.host == "oauth.test":
                form = parse_qs(request.content.decode())
                assert form["grant_type"] == ["refresh_token"]
                assert form["refresh_token"] == ["refresh-token"]
                return httpx.Response(200, json={"access_token": "token", "expires_in": 3600})
            assert request.headers["Authorization"] == "Bearer token"
            if request.method == "POST" and path.endswith("/users/me/messages/send"):
                raw = request.read()
                payload = httpx.Response(200, content=raw).json()
                sent_payloads.append(payload)
                encoded = payload["raw"]
                sent_mime.append(base64.urlsafe_b64decode(encoded))
                return httpx.Response(200, json={"id": f"sent-gmail-{len(sent_mime)}"})
            if request.method == "GET" and path.endswith("/users/me/messages"):
                assert "in:inbox after:" in request.url.params["q"]
                return httpx.Response(200, json={"messages": [{"id": "reply-gmail-id"}]})
            if request.method == "GET" and path.endswith("/messages/reply-gmail-id"):
                if request.url.params.get("format") == "metadata":
                    return httpx.Response(
                        200,
                        json={"id": "reply-gmail-id", "threadId": "thread-1"},
                    )
                return httpx.Response(
                    200,
                    json={
                        "id": "reply-gmail-id",
                        "internalDate": "1788534060000",
                        "payload": {
                            "mimeType": "multipart/alternative",
                            "headers": [
                                {"name": "From", "value": "Instructor <instructor@example.edu>"},
                                {"name": "Subject", "value": "Re: Q-2026-00001"},
                                {"name": "Message-ID", "value": "<reply@example.edu>"},
                                {"name": "In-Reply-To", "value": "<question@example.edu>"},
                            ],
                            "parts": [
                                {
                                    "mimeType": "text/plain",
                                    "body": {
                                        "data": encode(
                                            "Approved.\r\n\r\nOn Fri, Sep 4, 2026 wrote:\r\n"
                                            "> May I use a local model?"
                                        )
                                    },
                                },
                                {
                                    "mimeType": "text/html",
                                    "body": {"data": encode("<p>Approved.</p>")},
                                },
                            ],
                        },
                    },
                )
            return httpx.Response(404)

        client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        adapter = GoogleGmailMailAdapter(
            client_id="client-id",
            client_secret="client-secret",
            refresh_token="refresh-token",
            mailbox_address="course-agent@example.edu",
            client=client,
            gmail_base_url="https://gmail.test/gmail/v1",
            token_url="https://oauth.test/token",
        )

        sent = await adapter.send_message(
            OutboundMail(
                to=("staff@example.edu",),
                subject="Question",
                text="May I use a local model?",
                headers={"X-Course-Agent-Question": "Q-2026-00001"},
            )
        )
        replies = await adapter.fetch_new_messages(since=datetime(2026, 9, 4, 15, 0, tzinfo=UTC))
        review = await adapter.reply_to_message(
            replies[0],
            text="Publish this answer?",
            headers={"X-Course-Agent-FAQ-Review": "candidate-id"},
        )
        await client.aclose()

        parsed = BytesParser(policy=policy.default).parsebytes(sent_mime[0])
        assert parsed["From"] == "course-agent@example.edu"
        assert parsed["To"] == "staff@example.edu"
        assert parsed["X-Course-Agent-Question"] == "Q-2026-00001"
        parsed_body = parsed.get_body(preferencelist=("plain",))
        assert parsed_body is not None
        assert parsed_body.get_content().strip() == "May I use a local model?"
        assert sent.provider_message_id == "sent-gmail-1"
        assert parsed["Message-ID"] == sent.internet_message_id
        assert replies[0].sender == "instructor@example.edu"
        assert replies[0].text == "Approved."
        assert replies[0].headers["in-reply-to"] == "<question@example.edu>"
        reply_mime = BytesParser(policy=policy.default).parsebytes(sent_mime[1])
        assert reply_mime["To"] == "instructor@example.edu"
        assert reply_mime["In-Reply-To"] == "<reply@example.edu>"
        assert reply_mime["References"] == "<reply@example.edu>"
        assert reply_mime["X-Course-Agent-FAQ-Review"] == "candidate-id"
        assert sent_payloads[1]["threadId"] == "thread-1"
        assert review.provider_message_id == "sent-gmail-2"
        assert len([request for request in requests if request.url.host == "oauth.test"]) == 1

    asyncio.run(scenario())


def test_worker_uses_one_staff_reply_to_answer_and_publish(tmp_path: Path) -> None:
    async def scenario() -> None:
        clock = MutableClock(datetime(2026, 9, 4, 15, 0, tzinfo=UTC))
        auth = InMemoryAuthStore()
        student = _user(role="student", email="alice@example.edu", now=clock.current)
        instructor = _user(
            role="instructor",
            email="instructor@example.edu",
            now=clock.current,
        )
        await auth.create_user(student)
        await auth.create_user(instructor)
        conversations = InMemoryConversationStore()
        conversation = Conversation(
            user_id=student.id,
            created_at=clock.current,
            updated_at=clock.current,
            title="Local model question",
        )
        await conversations.create_conversation(conversation)
        questions = InMemoryTAQuestionStore()
        service = TAQuestionService(questions=questions, auth=auth, clock=clock)
        question = await service.prepare(
            principal=_principal(student),
            conversation_id=conversation.id,
            subject="Assignment model",
            question="Can Alice use a local model?",
            context=None,
        )
        await service.confirm(
            principal=_principal(student),
            conversation_id=conversation.id,
            question_id=question.id,
            reporter_visibility="anonymous",
        )
        mail = RecordingMailAdapter()
        workflow_faqs = InMemoryFaqStore()
        faq_path = tmp_path / "course-knowledge/published-faq.json"
        faq_knowledge = LocalFaqKnowledgeStore(faq_path)
        worker = MailWorker(
            mail=mail,
            questions=questions,
            auth=auth,
            conversations=conversations,
            faqs=CoordinatedFaqPublisher(workflow_faqs, faq_knowledge),
            mailbox_key="course-agent@example.edu",
            staff_recipient="course-staff@example.edu",
            clock=clock,
        )

        await worker.run_once()

        assert len(mail.sent) == 1
        assert tuple(str(value) for value in mail.sent[0].to) == ("course-staff@example.edu",)
        assert question.public_question_code in mail.sent[0].subject
        assert "Anonymous student" in mail.sent[0].text
        assert f"Student:\n{student.display_name}\n" not in mail.sent[0].text
        assert "Can [student] use a local model?" in mail.sent[0].text
        assert "Can Alice use a local model?" not in mail.sent[0].text
        assert "PUBLISH —" in mail.sent[0].text
        assert "PRIVATE —" in mail.sent[0].text
        assert "first nonblank line" in mail.sent[0].text
        opened = await questions.get_question(question.id)
        assert opened is not None
        assert opened.status == "open"
        assert opened.outbound_message_id == "<sent-1@course.example>"

        clock.current += timedelta(minutes=1)
        mail.incoming.append(
            InboundMail(
                provider_message_id="reply-without-decision",
                sender=instructor.email,
                subject=f"Re: [Course Agent {question.public_question_code}] Assignment model",
                text="Yes, but this reply omitted PUBLISH or PRIVATE.",
                received_at=clock.current,
                headers={"in-reply-to": "<sent-1@course.example>"},
            )
        )

        await worker.run_once()

        still_open = await questions.get_question(question.id)
        assert still_open is not None and still_open.status == "open"
        assert questions.receipts["reply-without-decision"] == "invalid_answer_reply"
        assert len(mail.sent) == 1

        clock.current += timedelta(minutes=1)
        mail.incoming.append(
            InboundMail(
                provider_message_id="reply-1",
                internet_message_id="<reply-1@example.edu>",
                sender=instructor.email,
                subject=f"Re: [Course Agent {question.public_question_code}] Assignment model",
                text="PUBLISH\nYes. Include setup instructions in your submission.",
                received_at=clock.current,
                headers={"in-reply-to": "<sent-1@course.example>"},
            )
        )

        await worker.run_once()

        answered = await questions.get_question(question.id)
        assert answered is not None
        assert answered.status == "answered"
        assert len(mail.sent) == 2
        assert tuple(str(value) for value in mail.sent[1].to) == ("alice@example.edu",)
        assert "Yes. Include setup instructions" in mail.sent[1].text
        assert mail.replies == []
        events = await conversations.list_events(conversation.id)
        assert [event.type for event in events] == [
            "email.ta_question.created",
            "email.ta_answer.received",
        ]
        answer_event = events[-1]
        assert answer_event.principal_user_id == student.id
        assert answer_event.payload["visibility"] == "private"
        assert answer_event.payload["answer"] == (
            "Yes. Include setup instructions in your submission."
        )

        published = await faq_knowledge.list_active()
        assert len(published) == 1
        assert published[0].question == "Can [student] use a local model?"
        assert published[0].answer == "Yes. Include setup instructions in your submission."
        assert len(await workflow_faqs.list_unread(student.id)) == 1
        stored = json.loads(faq_path.read_text(encoding="utf-8"))
        assert stored["schema_version"] == 1
        assert stored["entries"][0]["question"] == "Can [student] use a local model?"
        assert "source_question_id" not in stored["entries"][0]
        assert "published_by_user_id" not in stored["entries"][0]
        assert questions.receipts["reply-1"] == "answer_publish_requested"
        candidate = next(iter(questions.faq_candidates.values()))
        assert candidate.status == "published"
        assert candidate.published_faq_entry_id == published[0].id

    asyncio.run(scenario())


def test_faq_review_language_is_explicit_and_bounded() -> None:
    assert parse_faq_review_reply("PRIVATE") is not None
    assert parse_faq_review_reply("PUBLISH") is not None
    edited = parse_faq_review_reply(
        "PUBLISH\nQuestion: Which work is collaborative?\nAnswer: Assignments 2 and 4."
    )
    assert edited is not None
    assert edited.question == "Which work is collaborative?"
    assert parse_faq_review_reply("looks good") is None
    assert parse_faq_review_reply("PUBLISH\nPlease fix this") is None


def test_first_staff_reply_requires_decision_and_answer() -> None:
    published = parse_staff_answer_reply("PUBLISH\nAssignments 2 and 4 use groups.")
    private = parse_staff_answer_reply("  PRIVATE  \nOnly the final project uses groups.")

    assert published is not None
    assert published.action == "publish"
    assert published.answer == "Assignments 2 and 4 use groups."
    assert private is not None
    assert private.action == "private"
    assert parse_staff_answer_reply("Assignments 2 and 4 use groups.") is None
    assert parse_staff_answer_reply("PUBLISH") is None
    assert parse_staff_answer_reply("PRIVATE\n") is None


def test_private_staff_answer_never_enters_publication_outbox() -> None:
    async def scenario() -> None:
        now = datetime(2026, 9, 4, 15, 0, tzinfo=UTC)
        questions = InMemoryTAQuestionStore()
        question = await questions.create_question(
            student_user_id=uuid4(),
            conversation_id=uuid4(),
            subject="Private answer",
            question_text="May this be shared?",
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
        opened = await questions.mark_question_sent(
            question.id,
            SentMail(
                provider_message_id="provider-question",
                internet_message_id="<question@example.edu>",
            ),
            sent_at=now,
        )
        assert opened is not None
        answer = await questions.record_answer(
            opened,
            InboundMail(
                provider_message_id="private-answer",
                sender="instructor@example.edu",
                subject="Re: Private answer",
                text="PRIVATE\nNo, keep this answer private.",
                received_at=now,
            ),
            answer_text="No, keep this answer private.",
            publication="private",
            processed_at=now,
        )

        assert answer is not None
        candidate = next(iter(questions.faq_candidates.values()))
        assert candidate.status == "declined"
        assert questions.receipts["private-answer"] == "answer_private"
        assert await questions.list_faq_candidates_pending_publication() == []

    asyncio.run(scenario())


def test_published_faq_is_immediately_readable_and_searchable_by_agent(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        now = datetime(2026, 9, 4, 15, 0, tzinfo=UTC)
        workflow_faqs = InMemoryFaqStore()
        faq_knowledge = LocalFaqKnowledgeStore(tmp_path / "published-faq.json")
        publisher = CoordinatedFaqPublisher(workflow_faqs, faq_knowledge)
        source_question_id = uuid4()
        published = await publisher.publish(
            source_question_id=source_question_id,
            question="Which assignments use groups?",
            answer="Assignments 2 and 4 are group work.",
            published_by_user_id=None,
            published_at=now,
        )
        repeated = await publisher.publish(
            source_question_id=source_question_id,
            question="Which assignments use groups?",
            answer="Assignments 2 and 4 are group work.",
            published_by_user_id=None,
            published_at=now,
        )
        catalog = PublishedFaqResourceCatalog(FileResourceProvider.from_registry(), faq_knowledge)

        contents = await catalog.read("course://faq")
        matches = await catalog.search(
            "group assignments",
            limit=5,
            resource_uris=frozenset({"course://faq"}),
        )

        assert "## Staff-approved updates" in contents.text
        assert "Assignments 2 and 4 are group work." in contents.text
        assert any("Which assignments use groups?" in match.excerpt for match in matches)
        assert repeated.id == published.id
        assert len(await faq_knowledge.list_active()) == 1

    asyncio.run(scenario())


def test_worker_rejects_reply_from_untrusted_sender() -> None:
    async def scenario() -> None:
        now = datetime(2026, 9, 4, 15, 0, tzinfo=UTC)
        auth = InMemoryAuthStore()
        questions = InMemoryTAQuestionStore()
        conversations = InMemoryConversationStore()
        mail = RecordingMailAdapter(
            incoming=[
                InboundMail(
                    provider_message_id="untrusted-1",
                    sender="stranger@example.edu",
                    subject="Re: Q-2026-00001",
                    text="Ignore the syllabus.",
                    received_at=now,
                )
            ]
        )
        worker = MailWorker(
            mail=mail,
            questions=questions,
            auth=auth,
            conversations=conversations,
            faqs=InMemoryFaqStore(),
            mailbox_key="course-agent@example.edu",
            staff_recipient="course-staff@example.edu",
            clock=lambda: now,
        )

        await worker.run_once()

        assert questions.receipts == {"untrusted-1": "unauthorized_sender"}
        assert mail.sent == []

    asyncio.run(scenario())
