"""Authorization-aware question preparation and durable mailbox worker."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID

from agent_core import Event, PrincipalContext
from course_server.agent.store import ConversationStore, EventAlreadyExists
from course_server.auth.store import AuthStore
from course_server.faq import FaqPublisher

from .models import (
    FaqReviewCandidate,
    InboundMail,
    MailAdapter,
    OutboundMail,
    PublicationDecision,
    ReporterVisibility,
    TAAnswer,
    TAQuestion,
)
from .store import TAQuestionStore

Clock = Callable[[], datetime]
QUESTION_CODE = re.compile(r"\bQ-[0-9]{4}-[0-9]{5}\b", re.IGNORECASE)
MESSAGE_ID = re.compile(r"<[^<>\s]+>")
REPLY_OVERLAP = timedelta(minutes=2)
INITIAL_LOOKBACK = timedelta(days=1)
FAQ_EDIT = re.compile(
    r"^Question:\s*(?P<question>.+?)\n+Answer:\s*(?P<answer>.+)$",
    re.IGNORECASE | re.DOTALL,
)


def _clock() -> datetime:
    return datetime.now(UTC)


class TAQuestionAccessDenied(RuntimeError):
    """The principal may not read or mutate this private question."""


class TAQuestionStateError(RuntimeError):
    """The question is no longer in the expected confirmation state."""


@dataclass(frozen=True)
class FaqReviewDecision:
    action: Literal["publish", "private"]
    question: str | None = None
    answer: str | None = None


@dataclass(frozen=True)
class StaffAnswerDecision:
    action: PublicationDecision
    answer: str


class TAQuestionService:
    """Prepares questions; sending remains a separate confirmed worker action."""

    def __init__(
        self,
        *,
        questions: TAQuestionStore,
        auth: AuthStore,
        clock: Clock = _clock,
    ) -> None:
        self._questions = questions
        self._auth = auth
        self._clock = clock

    async def prepare(
        self,
        *,
        principal: PrincipalContext,
        conversation_id: UUID,
        subject: str,
        question: str,
        context: str | None,
    ) -> TAQuestion:
        user_id = self._student_user_id(principal)
        user = await self._auth.get_user_by_id(user_id)
        if user is None or not user.active or user.role != "student":
            raise TAQuestionAccessDenied("student login required")
        if await self._questions.get_pending_question(
            student_user_id=user.id,
            conversation_id=conversation_id,
        ):
            raise TAQuestionStateError("a question is already awaiting confirmation")
        return await self._questions.create_question(
            student_user_id=user.id,
            conversation_id=conversation_id,
            subject=subject,
            question_text=question,
            context_text=context,
            created_at=self._clock(),
        )

    async def confirm(
        self,
        *,
        principal: PrincipalContext,
        conversation_id: UUID,
        question_id: UUID,
        reporter_visibility: ReporterVisibility = "named",
    ) -> TAQuestion:
        question = await self._owned_question(
            principal=principal,
            conversation_id=conversation_id,
            question_id=question_id,
        )
        if question.status in {"queued", "open", "answered"}:
            return question
        if question.status != "pending_confirmation":
            raise TAQuestionStateError("question is no longer awaiting confirmation")
        updated = await self._questions.transition_question(
            question.id,
            expected="pending_confirmation",
            status="queued",
            changed_at=self._clock(),
            reporter_visibility=reporter_visibility,
        )
        if updated is None:
            raise TAQuestionStateError("question is no longer awaiting confirmation")
        return updated

    async def cancel(
        self,
        *,
        principal: PrincipalContext,
        conversation_id: UUID,
        question_id: UUID,
    ) -> TAQuestion:
        question = await self._owned_question(
            principal=principal,
            conversation_id=conversation_id,
            question_id=question_id,
        )
        if question.status == "closed":
            return question
        if question.status != "pending_confirmation":
            raise TAQuestionStateError("question is no longer awaiting confirmation")
        updated = await self._questions.transition_question(
            question.id,
            expected="pending_confirmation",
            status="closed",
            changed_at=self._clock(),
        )
        if updated is None:
            raise TAQuestionStateError("question is no longer awaiting confirmation")
        return updated

    async def _owned_question(
        self,
        *,
        principal: PrincipalContext,
        conversation_id: UUID,
        question_id: UUID,
    ) -> TAQuestion:
        user_id = self._student_user_id(principal)
        question = await self._questions.get_question(question_id)
        if (
            question is None
            or question.student_user_id != user_id
            or question.conversation_id != conversation_id
        ):
            raise TAQuestionAccessDenied("question not found")
        return question

    @staticmethod
    def _student_user_id(principal: PrincipalContext) -> UUID:
        if (
            not principal.authenticated
            or principal.user_id is None
            or "student" not in principal.roles
        ):
            raise TAQuestionAccessDenied("student login required")
        return principal.user_id


class MailWorker:
    """Polls one mailbox and advances the durable question/answer outbox."""

    def __init__(
        self,
        *,
        mail: MailAdapter,
        questions: TAQuestionStore,
        auth: AuthStore,
        conversations: ConversationStore,
        faqs: FaqPublisher,
        mailbox_key: str,
        staff_recipient: str,
        authorized_reply_senders: Iterable[str] = (),
        clock: Clock = _clock,
    ) -> None:
        self._mail = mail
        self._questions = questions
        self._auth = auth
        self._conversations = conversations
        self._faqs = faqs
        self._mailbox_key = mailbox_key.casefold()
        self._staff_recipient = staff_recipient
        self._authorized_reply_senders = {
            sender.strip().casefold() for sender in authorized_reply_senders if sender.strip()
        }
        self._clock = clock

    async def run_once(self) -> None:
        await self._send_queued_questions()
        await self._record_question_events()
        await self._receive_replies()
        await self._record_answer_events()
        await self._notify_students()
        await self._publish_requested_faqs()
        await self._send_faq_reviews()

    async def _send_queued_questions(self) -> None:
        for question in await self._questions.list_queued_questions():
            user = await self._auth.get_user_by_id(question.student_user_id)
            if user is None or not user.active or user.role != "student":
                await self._questions.transition_question(
                    question.id,
                    expected="queued",
                    status="closed",
                    changed_at=self._clock(),
                )
                continue
            sent = await self._mail.send_message(
                OutboundMail(
                    to=(self._staff_recipient,),
                    subject=f"[Course Agent {question.public_question_code}] {question.subject}",
                    text=_staff_question_body(
                        question,
                        display_name=user.display_name,
                        email=str(user.email),
                    ),
                    headers={"X-Course-Agent-Question": question.public_question_code},
                )
            )
            sent_at = self._clock()
            await self._questions.mark_question_sent(
                question.id,
                sent,
                sent_at=sent_at,
            )

    async def _record_question_events(self) -> None:
        for question in await self._questions.list_questions_pending_event():
            event = Event(
                id=question.sent_event_id,
                timestamp=question.sent_at or self._clock(),
                type="email.ta_question.created",
                actor="mail-worker",
                principal_user_id=question.student_user_id,
                conversation_id=question.conversation_id,
                payload={
                    "question_id": str(question.id),
                    "question_code": question.public_question_code,
                    "subject": question.subject,
                    "status": "open",
                },
            )
            with suppress(EventAlreadyExists):
                await self._conversations.append_events(question.conversation_id, [event])
            await self._questions.mark_question_event_recorded(
                question.id,
                recorded_at=self._clock(),
            )

    async def _receive_replies(self) -> None:
        now = self._clock()
        checkpoint = await self._questions.get_sync_checkpoint(self._mailbox_key)
        since = (checkpoint - REPLY_OVERLAP) if checkpoint else (now - INITIAL_LOOKBACK)
        messages = await self._mail.fetch_new_messages(since=since)
        for message in messages:
            await self._process_message(message)
        latest = max((message.received_at for message in messages), default=now)
        await self._questions.set_sync_checkpoint(
            self._mailbox_key,
            last_received_at=latest,
            updated_at=self._clock(),
        )

    async def _process_message(self, message: InboundMail) -> None:
        if await self._questions.inbound_seen(message.provider_message_id):
            return
        now = self._clock()
        if not await self._authorized_sender(str(message.sender)):
            await self._questions.record_inbound_disposition(
                message,
                "unauthorized_sender",
                processed_at=now,
            )
            return
        references = _reply_references(message.headers)
        code_match = QUESTION_CODE.search(message.subject)
        question_code = code_match.group(0).upper() if code_match else None
        candidate = await self._questions.find_pending_faq_review(
            referenced_message_ids=references,
            question_code=question_code,
        )
        if candidate is not None:
            await self._process_faq_review(candidate, message, now=now)
            return
        question = await self._questions.find_open_question(
            referenced_message_ids=references,
            question_code=question_code,
        )
        if question is None:
            await self._questions.record_inbound_disposition(
                message,
                "unmatched",
                processed_at=now,
            )
            return
        answer = parse_staff_answer_reply(message.text)
        if answer is None:
            await self._questions.record_inbound_disposition(
                message,
                "invalid_answer_reply",
                processed_at=now,
                question_id=question.id,
            )
            return
        await self._questions.record_answer(
            question,
            message,
            answer_text=answer.answer,
            publication=answer.action,
            processed_at=now,
        )

    async def _process_faq_review(
        self,
        candidate: FaqReviewCandidate,
        message: InboundMail,
        *,
        now: datetime,
    ) -> None:
        reply_text = sanitize_reply_text(message.text)
        if not reply_text:
            await self._questions.record_inbound_disposition(
                message,
                "empty_reply",
                processed_at=now,
                question_id=candidate.question_id,
            )
            return
        decision = parse_faq_review_reply(reply_text)
        if decision is None:
            await self._questions.record_inbound_disposition(
                message,
                "invalid_review_reply",
                processed_at=now,
                question_id=candidate.question_id,
            )
            return
        if decision.action == "private":
            await self._questions.record_faq_review_decision(
                candidate,
                message,
                status="declined",
                published_faq_entry_id=None,
                processed_at=now,
            )
            return
        staff = await self._auth.get_user_by_email(str(message.sender))
        published_by = (
            staff.id
            if staff is not None and staff.active and staff.role in {"ta", "instructor", "admin"}
            else None
        )
        source_question = await self._questions.get_question(candidate.question_id)
        if source_question is None:
            return
        student = await self._auth.get_user_by_id(source_question.student_user_id)
        question_text = decision.question or candidate.suggested_question
        answer_text = decision.answer or candidate.suggested_answer
        if student is not None:
            question_text = _redact_student_identity(
                question_text,
                display_name=student.display_name,
                email=str(student.email),
            )
            answer_text = _redact_student_identity(
                answer_text,
                display_name=student.display_name,
                email=str(student.email),
            )
        entry = await self._faqs.publish(
            source_question_id=candidate.question_id,
            question=question_text,
            answer=answer_text,
            published_by_user_id=published_by,
            published_at=now,
        )
        await self._questions.record_faq_review_decision(
            candidate,
            message,
            status="published",
            published_faq_entry_id=entry.id,
            processed_at=now,
        )

    async def _authorized_sender(self, sender: str) -> bool:
        normalized = sender.casefold()
        if normalized in self._authorized_reply_senders:
            return True
        user = await self._auth.get_user_by_email(normalized)
        return bool(user and user.active and user.role in {"ta", "instructor", "admin"})

    async def _record_answer_events(self) -> None:
        for answer in await self._questions.list_answers_pending_event():
            question = await self._questions.get_question(answer.question_id)
            if question is None:
                continue
            event = Event(
                id=answer.event_id,
                timestamp=answer.received_at,
                type="email.ta_answer.received",
                actor="mail-worker",
                principal_user_id=question.student_user_id,
                conversation_id=question.conversation_id,
                payload={
                    "question_id": str(question.id),
                    "question_code": question.public_question_code,
                    "subject": question.subject,
                    "answer": answer.answer_text,
                    "visibility": "private",
                },
            )
            with suppress(EventAlreadyExists):
                await self._conversations.append_events(question.conversation_id, [event])
            await self._questions.mark_answer_event_recorded(
                answer.id,
                recorded_at=self._clock(),
            )

    async def _notify_students(self) -> None:
        for answer in await self._questions.list_answers_pending_notification():
            question = await self._questions.get_question(answer.question_id)
            if question is None:
                continue
            student = await self._auth.get_user_by_id(question.student_user_id)
            if student is None or not student.active or student.role != "student":
                continue
            sent = await self._mail.send_message(
                OutboundMail(
                    to=(student.email,),
                    subject=(
                        f"[Course Agent {question.public_question_code}] Answer: {question.subject}"
                    ),
                    text=_student_answer_body(question, answer),
                    headers={"X-Course-Agent-Question": question.public_question_code},
                )
            )
            await self._questions.mark_answer_notified(
                answer.id,
                sent,
                notified_at=self._clock(),
            )

    async def _publish_requested_faqs(self) -> None:
        for candidate in await self._questions.list_faq_candidates_pending_publication():
            question = await self._questions.get_question(candidate.question_id)
            answer = await self._questions.get_answer(candidate.answer_id)
            if question is None or answer is None:
                continue
            student = await self._auth.get_user_by_id(question.student_user_id)
            question_text = candidate.suggested_question
            answer_text = candidate.suggested_answer
            if student is not None:
                question_text = _redact_student_identity(
                    question_text,
                    display_name=student.display_name,
                    email=str(student.email),
                )
                answer_text = _redact_student_identity(
                    answer_text,
                    display_name=student.display_name,
                    email=str(student.email),
                )
            staff = await self._auth.get_user_by_email(str(answer.responder_email))
            published_by = (
                staff.id
                if staff is not None
                and staff.active
                and staff.role in {"ta", "instructor", "admin"}
                else None
            )
            entry = await self._faqs.publish(
                source_question_id=question.id,
                question=question_text,
                answer=answer_text,
                published_by_user_id=published_by,
                published_at=self._clock(),
            )
            await self._questions.mark_faq_candidate_published(
                candidate.id,
                published_faq_entry_id=entry.id,
            )

    async def _send_faq_reviews(self) -> None:
        for candidate in await self._questions.list_faq_candidates_pending_delivery():
            question = await self._questions.get_question(candidate.question_id)
            answer = await self._questions.get_answer(candidate.answer_id)
            if question is None or answer is None:
                continue
            student = await self._auth.get_user_by_id(question.student_user_id)
            proposed_question = candidate.suggested_question
            proposed_answer = candidate.suggested_answer
            if student is not None:
                proposed_question = _redact_student_identity(
                    proposed_question,
                    display_name=student.display_name,
                    email=str(student.email),
                )
                proposed_answer = _redact_student_identity(
                    proposed_answer,
                    display_name=student.display_name,
                    email=str(student.email),
                )
            original = InboundMail(
                provider_message_id=answer.inbound_provider_message_id,
                internet_message_id=answer.inbound_message_id,
                sender=answer.responder_email,
                subject=f"Re: [Course Agent {question.public_question_code}] {question.subject}",
                text=answer.answer_text,
                received_at=answer.received_at,
                headers=(
                    {"message-id": answer.inbound_message_id}
                    if answer.inbound_message_id is not None
                    else {}
                ),
            )
            sent = await self._mail.reply_to_message(
                original,
                text=_faq_review_body(
                    proposed_question=proposed_question,
                    proposed_answer=proposed_answer,
                    question=question,
                ),
                headers={"X-Course-Agent-FAQ-Review": str(candidate.id)},
            )
            await self._questions.mark_faq_candidate_sent(
                candidate.id,
                sent,
                sent_at=self._clock(),
            )


def _reply_references(headers: dict[str, str]) -> list[str]:
    values = " ".join(
        value for name in ("in-reply-to", "references") if (value := headers.get(name.casefold()))
    )
    bracketed = MESSAGE_ID.findall(values)
    return bracketed or values.split()


def sanitize_reply_text(text: str) -> str:
    """Normalize provider-extracted reply text for private event storage."""

    normalized = text.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")
    lines = [line.rstrip() for line in normalized.splitlines()]
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines).strip()[:10_000]


def parse_staff_answer_reply(text: str) -> StaffAnswerDecision | None:
    """Parse one staff reply containing both the privacy decision and answer."""

    normalized = sanitize_reply_text(text)
    lines = normalized.splitlines()
    if len(lines) < 2:
        return None

    first_command = lines[0].strip().casefold()
    last_command = lines[-1].strip().casefold()
    commands = {"publish", "private"}
    if first_command in commands and last_command not in commands:
        command = first_command
        answer = "\n".join(lines[1:]).strip()
    elif last_command in commands and first_command not in commands:
        command = last_command
        answer = "\n".join(lines[:-1]).strip()
    else:
        return None
    if not answer or len(answer) > 10_000:
        return None
    action: PublicationDecision = "publish" if command == "publish" else "private"
    return StaffAnswerDecision(action=action, answer=answer)


def parse_faq_review_reply(text: str) -> FaqReviewDecision | None:
    """Parse the intentionally small staff email approval language."""

    normalized = sanitize_reply_text(text)
    first_line, _, remainder = normalized.partition("\n")
    command = first_line.strip().casefold()
    if command == "private":
        return FaqReviewDecision(action="private")
    if command != "publish":
        return None
    if not remainder.strip():
        return FaqReviewDecision(action="publish")
    match = FAQ_EDIT.fullmatch(remainder.strip())
    if match is None:
        return None
    question = match.group("question").strip()
    answer = match.group("answer").strip()
    if not question or len(question) > 5_000 or not answer or len(answer) > 10_000:
        return None
    return FaqReviewDecision(action="publish", question=question, answer=answer)


def _staff_question_body(question: TAQuestion, *, display_name: str, email: str) -> str:
    reporter = (
        "Anonymous student (identity hidden by the student)"
        if question.reporter_visibility == "anonymous"
        else display_name
    )
    question_text = question.question_text
    context_text = question.context_text
    if question.reporter_visibility == "anonymous":
        question_text = _redact_student_identity(
            question_text,
            display_name=display_name,
            email=email,
        )
        if context_text is not None:
            context_text = _redact_student_identity(
                context_text,
                display_name=display_name,
                email=email,
            )
    context = f"\nConversation context:\n{context_text}\n" if context_text else ""
    return (
        f"Student:\n{reporter}\n\n"
        f"Question:\n{question_text}\n"
        f"{context}\n"
        "Reply with one of these commands on its own line, either before or after your answer:\n"
        "PUBLISH — send the answer to the student and add the redacted question and answer "
        "to shared Course Agent knowledge.\n"
        "PRIVATE — send the answer only to the student.\n\n"
        "Do not place the command in the middle of your answer.\n\n"
        f"Reference: {question.public_question_code}."
    )


def _student_answer_body(question: TAQuestion, answer: TAAnswer) -> str:
    return (
        f"Course staff answered your question ({question.public_question_code}).\n\n"
        f"Your question:\n{question.question_text}\n\n"
        f"Course staff answer:\n{answer.answer_text}\n\n"
        "This answer is also available in your Course Agent conversation."
    )


def _redact_student_identity(text: str, *, display_name: str, email: str) -> str:
    redacted = text
    for value in (display_name.strip(), email.strip()):
        if value:
            redacted = re.sub(re.escape(value), "[student]", redacted, flags=re.IGNORECASE)
    return redacted


def _faq_review_body(
    *,
    proposed_question: str,
    proposed_answer: str,
    question: TAQuestion,
) -> str:
    return (
        "Your answer has been sent privately to the student.\n\n"
        "Should this answer become shared Course Agent knowledge? The proposed FAQ contains "
        "no student identity or conversation context.\n\n"
        f"Question:\n{proposed_question}\n\n"
        f"Answer:\n{proposed_answer}\n\n"
        "Reply with exactly one of:\n"
        "PUBLISH\n"
        "PRIVATE\n\n"
        "To edit before publishing, reply:\n"
        "PUBLISH\n"
        "Question: Your revised question\n"
        "Answer: Your revised answer\n\n"
        f"Reference: {question.public_question_code}."
    )
