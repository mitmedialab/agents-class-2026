"""Persistence boundary for private course-staff questions and answers."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import Any, Literal, Protocol
from uuid import UUID, uuid4

from psycopg_pool import AsyncConnectionPool

from .models import (
    FaqReviewCandidate,
    InboundMail,
    PublicationDecision,
    QuestionStatus,
    ReporterVisibility,
    SentMail,
    TAAnswer,
    TAQuestion,
)

InboundDisposition = Literal[
    "answered",
    "answer_publish_requested",
    "answer_private",
    "faq_declined",
    "faq_published",
    "invalid_review_reply",
    "invalid_answer_reply",
    "unauthorized_sender",
    "unmatched",
    "empty_reply",
]


class TAQuestionStore(Protocol):
    async def create_question(
        self,
        *,
        student_user_id: UUID,
        conversation_id: UUID,
        subject: str,
        question_text: str,
        context_text: str | None,
        created_at: datetime,
    ) -> TAQuestion: ...

    async def get_question(self, question_id: UUID) -> TAQuestion | None: ...

    async def get_pending_question(
        self,
        *,
        student_user_id: UUID,
        conversation_id: UUID,
    ) -> TAQuestion | None: ...

    async def transition_question(
        self,
        question_id: UUID,
        *,
        expected: QuestionStatus,
        status: QuestionStatus,
        changed_at: datetime,
        reporter_visibility: ReporterVisibility | None = None,
    ) -> TAQuestion | None: ...

    async def list_queued_questions(self, *, limit: int = 20) -> list[TAQuestion]: ...

    async def mark_question_sent(
        self,
        question_id: UUID,
        sent: SentMail,
        *,
        sent_at: datetime,
    ) -> TAQuestion | None: ...

    async def list_questions_pending_event(self, *, limit: int = 20) -> list[TAQuestion]: ...

    async def mark_question_event_recorded(
        self,
        question_id: UUID,
        *,
        recorded_at: datetime,
    ) -> None: ...

    async def inbound_seen(self, provider_message_id: str) -> bool: ...

    async def record_inbound_disposition(
        self,
        message: InboundMail,
        disposition: InboundDisposition,
        *,
        processed_at: datetime,
        question_id: UUID | None = None,
    ) -> None: ...

    async def find_open_question(
        self,
        *,
        referenced_message_ids: Iterable[str],
        question_code: str | None,
    ) -> TAQuestion | None: ...

    async def record_answer(
        self,
        question: TAQuestion,
        message: InboundMail,
        *,
        answer_text: str,
        publication: PublicationDecision,
        processed_at: datetime,
    ) -> TAAnswer | None: ...

    async def get_answer(self, answer_id: UUID) -> TAAnswer | None: ...

    async def list_answers_pending_event(self, *, limit: int = 20) -> list[TAAnswer]: ...

    async def mark_answer_event_recorded(
        self, answer_id: UUID, *, recorded_at: datetime
    ) -> None: ...

    async def list_answers_pending_notification(self, *, limit: int = 20) -> list[TAAnswer]: ...

    async def mark_answer_notified(
        self,
        answer_id: UUID,
        sent: SentMail,
        *,
        notified_at: datetime,
    ) -> None: ...

    async def list_faq_candidates_pending_publication(
        self, *, limit: int = 20
    ) -> list[FaqReviewCandidate]: ...

    async def mark_faq_candidate_published(
        self,
        candidate_id: UUID,
        *,
        published_faq_entry_id: UUID,
    ) -> None: ...

    async def list_faq_candidates_pending_delivery(
        self, *, limit: int = 20
    ) -> list[FaqReviewCandidate]: ...

    async def mark_faq_candidate_sent(
        self,
        candidate_id: UUID,
        sent: SentMail,
        *,
        sent_at: datetime,
    ) -> None: ...

    async def find_pending_faq_review(
        self,
        *,
        referenced_message_ids: Iterable[str],
        question_code: str | None,
    ) -> FaqReviewCandidate | None: ...

    async def record_faq_review_decision(
        self,
        candidate: FaqReviewCandidate,
        message: InboundMail,
        *,
        status: Literal["published", "declined"],
        published_faq_entry_id: UUID | None,
        processed_at: datetime,
    ) -> bool: ...

    async def get_sync_checkpoint(self, mailbox_key: str) -> datetime | None: ...

    async def set_sync_checkpoint(
        self,
        mailbox_key: str,
        *,
        last_received_at: datetime,
        updated_at: datetime,
    ) -> None: ...


class InMemoryTAQuestionStore:
    """Deterministic adapter for authorization and worker tests."""

    def __init__(self) -> None:
        self.questions: dict[UUID, TAQuestion] = {}
        self.answers: dict[UUID, TAAnswer] = {}
        self.faq_candidates: dict[UUID, FaqReviewCandidate] = {}
        self.receipts: dict[str, InboundDisposition] = {}
        self.checkpoints: dict[str, datetime] = {}
        self._sequence = 0

    async def create_question(
        self,
        *,
        student_user_id: UUID,
        conversation_id: UUID,
        subject: str,
        question_text: str,
        context_text: str | None,
        created_at: datetime,
    ) -> TAQuestion:
        self._sequence += 1
        question = TAQuestion(
            id=uuid4(),
            public_question_code=f"Q-{created_at.year:04d}-{self._sequence:05d}",
            student_user_id=student_user_id,
            conversation_id=conversation_id,
            subject=subject,
            question_text=question_text,
            context_text=context_text,
            status="pending_confirmation",
            sent_event_id=uuid4(),
            created_at=created_at,
        )
        self.questions[question.id] = question
        return question

    async def get_question(self, question_id: UUID) -> TAQuestion | None:
        return self.questions.get(question_id)

    async def get_pending_question(
        self,
        *,
        student_user_id: UUID,
        conversation_id: UUID,
    ) -> TAQuestion | None:
        return next(
            (
                question
                for question in self.questions.values()
                if question.student_user_id == student_user_id
                and question.conversation_id == conversation_id
                and question.status == "pending_confirmation"
            ),
            None,
        )

    async def transition_question(
        self,
        question_id: UUID,
        *,
        expected: QuestionStatus,
        status: QuestionStatus,
        changed_at: datetime,
        reporter_visibility: ReporterVisibility | None = None,
    ) -> TAQuestion | None:
        question = self.questions.get(question_id)
        if question is None or question.status != expected:
            return None
        updates: dict[str, object] = {"status": status}
        if status == "queued":
            updates["confirmed_at"] = changed_at
            if reporter_visibility is not None:
                updates["reporter_visibility"] = reporter_visibility
        if status == "closed":
            updates["resolved_at"] = changed_at
        updated = question.model_copy(update=updates)
        self.questions[question_id] = updated
        return updated

    async def list_questions_pending_event(self, *, limit: int = 20) -> list[TAQuestion]:
        return sorted(
            (
                question
                for question in self.questions.values()
                if question.sent_at is not None and question.sent_event_recorded_at is None
            ),
            key=lambda question: question.sent_at or question.created_at,
        )[:limit]

    async def mark_question_event_recorded(
        self,
        question_id: UUID,
        *,
        recorded_at: datetime,
    ) -> None:
        question = self.questions[question_id]
        self.questions[question_id] = question.model_copy(
            update={"sent_event_recorded_at": recorded_at}
        )

    async def list_queued_questions(self, *, limit: int = 20) -> list[TAQuestion]:
        return sorted(
            (question for question in self.questions.values() if question.status == "queued"),
            key=lambda question: question.created_at,
        )[:limit]

    async def mark_question_sent(
        self,
        question_id: UUID,
        sent: SentMail,
        *,
        sent_at: datetime,
    ) -> TAQuestion | None:
        question = self.questions.get(question_id)
        if question is None or question.status != "queued":
            return None
        updated = question.model_copy(
            update={
                "status": "open",
                "provider_message_id": sent.provider_message_id,
                "outbound_message_id": sent.internet_message_id,
                "sent_at": sent_at,
            }
        )
        self.questions[question_id] = updated
        return updated

    async def inbound_seen(self, provider_message_id: str) -> bool:
        return provider_message_id in self.receipts

    async def record_inbound_disposition(
        self,
        message: InboundMail,
        disposition: InboundDisposition,
        *,
        processed_at: datetime,
        question_id: UUID | None = None,
    ) -> None:
        del processed_at, question_id
        self.receipts.setdefault(message.provider_message_id, disposition)

    async def find_open_question(
        self,
        *,
        referenced_message_ids: Iterable[str],
        question_code: str | None,
    ) -> TAQuestion | None:
        normalized = {_normalize_message_id(value) for value in referenced_message_ids}
        for question in self.questions.values():
            if question.status != "open":
                continue
            if (
                question.outbound_message_id
                and _normalize_message_id(question.outbound_message_id) in normalized
            ):
                return question
        if question_code is None:
            return None
        return next(
            (
                question
                for question in self.questions.values()
                if question.status == "open" and question.public_question_code == question_code
            ),
            None,
        )

    async def record_answer(
        self,
        question: TAQuestion,
        message: InboundMail,
        *,
        answer_text: str,
        publication: PublicationDecision,
        processed_at: datetime,
    ) -> TAAnswer | None:
        if message.provider_message_id in self.receipts:
            return None
        current = self.questions.get(question.id)
        if current is None or current.status != "open":
            return None
        answer = TAAnswer(
            id=uuid4(),
            question_id=question.id,
            event_id=uuid4(),
            inbound_provider_message_id=message.provider_message_id,
            inbound_message_id=message.internet_message_id,
            responder_email=message.sender,
            answer_text=answer_text,
            received_at=message.received_at,
        )
        self.answers[answer.id] = answer
        publish = publication == "publish"
        candidate = FaqReviewCandidate(
            id=uuid4(),
            question_id=question.id,
            answer_id=answer.id,
            suggested_question=question.question_text,
            suggested_answer=answer_text,
            status="pending_publication" if publish else "declined",
            decision_inbound_provider_message_id=message.provider_message_id,
            reviewed_by_email=message.sender,
            reviewed_at=processed_at,
            created_at=processed_at,
        )
        self.faq_candidates[candidate.id] = candidate
        self.questions[question.id] = current.model_copy(
            update={"status": "answered", "resolved_at": processed_at}
        )
        self.receipts[message.provider_message_id] = (
            "answer_publish_requested" if publish else "answer_private"
        )
        return answer

    async def get_answer(self, answer_id: UUID) -> TAAnswer | None:
        return self.answers.get(answer_id)

    async def list_answers_pending_event(self, *, limit: int = 20) -> list[TAAnswer]:
        return sorted(
            (answer for answer in self.answers.values() if answer.event_recorded_at is None),
            key=lambda answer: answer.received_at,
        )[:limit]

    async def mark_answer_event_recorded(self, answer_id: UUID, *, recorded_at: datetime) -> None:
        answer = self.answers[answer_id]
        self.answers[answer_id] = answer.model_copy(update={"event_recorded_at": recorded_at})

    async def list_answers_pending_notification(self, *, limit: int = 20) -> list[TAAnswer]:
        return sorted(
            (answer for answer in self.answers.values() if answer.notified_at is None),
            key=lambda answer: answer.received_at,
        )[:limit]

    async def mark_answer_notified(
        self,
        answer_id: UUID,
        sent: SentMail,
        *,
        notified_at: datetime,
    ) -> None:
        answer = self.answers[answer_id]
        self.answers[answer_id] = answer.model_copy(
            update={
                "notification_provider_message_id": sent.provider_message_id,
                "notified_at": notified_at,
            }
        )

    async def list_faq_candidates_pending_publication(
        self, *, limit: int = 20
    ) -> list[FaqReviewCandidate]:
        return sorted(
            (
                candidate
                for candidate in self.faq_candidates.values()
                if candidate.status == "pending_publication"
                and self.answers[candidate.answer_id].notified_at is not None
            ),
            key=lambda candidate: candidate.created_at,
        )[:limit]

    async def mark_faq_candidate_published(
        self,
        candidate_id: UUID,
        *,
        published_faq_entry_id: UUID,
    ) -> None:
        candidate = self.faq_candidates[candidate_id]
        if candidate.status != "pending_publication":
            return
        self.faq_candidates[candidate_id] = candidate.model_copy(
            update={
                "status": "published",
                "published_faq_entry_id": published_faq_entry_id,
            }
        )

    async def list_faq_candidates_pending_delivery(
        self, *, limit: int = 20
    ) -> list[FaqReviewCandidate]:
        return sorted(
            (
                candidate
                for candidate in self.faq_candidates.values()
                if candidate.status == "pending_delivery"
                and self.answers[candidate.answer_id].notified_at is not None
            ),
            key=lambda candidate: candidate.created_at,
        )[:limit]

    async def mark_faq_candidate_sent(
        self,
        candidate_id: UUID,
        sent: SentMail,
        *,
        sent_at: datetime,
    ) -> None:
        candidate = self.faq_candidates[candidate_id]
        if candidate.status != "pending_delivery":
            return
        self.faq_candidates[candidate_id] = candidate.model_copy(
            update={
                "status": "pending_review",
                "review_provider_message_id": sent.provider_message_id,
                "review_outbound_message_id": sent.internet_message_id,
                "review_sent_at": sent_at,
            }
        )

    async def find_pending_faq_review(
        self,
        *,
        referenced_message_ids: Iterable[str],
        question_code: str | None,
    ) -> FaqReviewCandidate | None:
        normalized = {_normalize_message_id(value) for value in referenced_message_ids}
        for candidate in self.faq_candidates.values():
            if candidate.status != "pending_review":
                continue
            if (
                candidate.review_outbound_message_id
                and _normalize_message_id(candidate.review_outbound_message_id) in normalized
            ):
                return candidate
        if question_code is None:
            return None
        return next(
            (
                candidate
                for candidate in self.faq_candidates.values()
                if candidate.status == "pending_review"
                and self.questions[candidate.question_id].public_question_code == question_code
            ),
            None,
        )

    async def record_faq_review_decision(
        self,
        candidate: FaqReviewCandidate,
        message: InboundMail,
        *,
        status: Literal["published", "declined"],
        published_faq_entry_id: UUID | None,
        processed_at: datetime,
    ) -> bool:
        if message.provider_message_id in self.receipts:
            return False
        current = self.faq_candidates.get(candidate.id)
        if current is None or current.status != "pending_review":
            return False
        self.faq_candidates[candidate.id] = current.model_copy(
            update={
                "status": status,
                "decision_inbound_provider_message_id": message.provider_message_id,
                "reviewed_by_email": message.sender,
                "reviewed_at": processed_at,
                "published_faq_entry_id": published_faq_entry_id,
            }
        )
        self.receipts[message.provider_message_id] = (
            "faq_published" if status == "published" else "faq_declined"
        )
        return True

    async def get_sync_checkpoint(self, mailbox_key: str) -> datetime | None:
        return self.checkpoints.get(mailbox_key.casefold())

    async def set_sync_checkpoint(
        self,
        mailbox_key: str,
        *,
        last_received_at: datetime,
        updated_at: datetime,
    ) -> None:
        del updated_at
        self.checkpoints[mailbox_key.casefold()] = last_received_at


class PostgresTAQuestionStore:
    """Explicit PostgreSQL adapter for durable email workflow state."""

    def __init__(self, pool: AsyncConnectionPool[Any]) -> None:
        self._pool = pool

    async def create_question(
        self,
        *,
        student_user_id: UUID,
        conversation_id: UUID,
        subject: str,
        question_text: str,
        context_text: str | None,
        created_at: datetime,
    ) -> TAQuestion:
        async with self._pool.connection() as connection, connection.transaction():
            sequence_row = await (
                await connection.execute("SELECT nextval('ta_question_number_sequence') AS value")
            ).fetchone()
            assert sequence_row is not None
            code = f"Q-{created_at.year:04d}-{int(sequence_row['value']):05d}"
            question_id = uuid4()
            sent_event_id = uuid4()
            cursor = await connection.execute(
                """
                INSERT INTO ta_questions (
                    id, public_question_code, student_user_id, conversation_id,
                    subject, question_text, context_text, status, sent_event_id, created_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, 'pending_confirmation', %s, %s)
                RETURNING *
                """,
                (
                    question_id,
                    code,
                    student_user_id,
                    conversation_id,
                    subject,
                    question_text,
                    context_text,
                    sent_event_id,
                    created_at,
                ),
            )
            row = await cursor.fetchone()
        assert row is not None
        return TAQuestion.model_validate(row)

    async def get_question(self, question_id: UUID) -> TAQuestion | None:
        async with self._pool.connection() as connection:
            row = await (
                await connection.execute("SELECT * FROM ta_questions WHERE id = %s", (question_id,))
            ).fetchone()
        return TAQuestion.model_validate(row) if row is not None else None

    async def get_pending_question(
        self,
        *,
        student_user_id: UUID,
        conversation_id: UUID,
    ) -> TAQuestion | None:
        async with self._pool.connection() as connection:
            row = await (
                await connection.execute(
                    """
                    SELECT * FROM ta_questions
                    WHERE student_user_id = %s AND conversation_id = %s
                      AND status = 'pending_confirmation'
                    """,
                    (student_user_id, conversation_id),
                )
            ).fetchone()
        return TAQuestion.model_validate(row) if row is not None else None

    async def transition_question(
        self,
        question_id: UUID,
        *,
        expected: QuestionStatus,
        status: QuestionStatus,
        changed_at: datetime,
        reporter_visibility: ReporterVisibility | None = None,
    ) -> TAQuestion | None:
        confirmed_at = changed_at if status == "queued" else None
        resolved_at = changed_at if status == "closed" else None
        async with self._pool.connection() as connection:
            cursor = await connection.execute(
                """
                UPDATE ta_questions
                SET status = %s,
                    confirmed_at = COALESCE(%s, confirmed_at),
                    resolved_at = COALESCE(%s, resolved_at),
                    reporter_visibility = COALESCE(%s, reporter_visibility)
                WHERE id = %s AND status = %s
                RETURNING *
                """,
                (
                    status,
                    confirmed_at,
                    resolved_at,
                    reporter_visibility,
                    question_id,
                    expected,
                ),
            )
            row = await cursor.fetchone()
        return TAQuestion.model_validate(row) if row is not None else None

    async def list_queued_questions(self, *, limit: int = 20) -> list[TAQuestion]:
        async with self._pool.connection() as connection:
            rows = await (
                await connection.execute(
                    """
                    SELECT * FROM ta_questions
                    WHERE status = 'queued'
                    ORDER BY created_at
                    LIMIT %s
                    """,
                    (limit,),
                )
            ).fetchall()
        return [TAQuestion.model_validate(row) for row in rows]

    async def mark_question_sent(
        self,
        question_id: UUID,
        sent: SentMail,
        *,
        sent_at: datetime,
    ) -> TAQuestion | None:
        async with self._pool.connection() as connection:
            row = await (
                await connection.execute(
                    """
                    UPDATE ta_questions
                    SET status = 'open', provider_message_id = %s,
                        outbound_message_id = %s, sent_at = %s
                    WHERE id = %s AND status = 'queued'
                    RETURNING *
                    """,
                    (
                        sent.provider_message_id,
                        sent.internet_message_id,
                        sent_at,
                        question_id,
                    ),
                )
            ).fetchone()
        return TAQuestion.model_validate(row) if row is not None else None

    async def list_questions_pending_event(self, *, limit: int = 20) -> list[TAQuestion]:
        async with self._pool.connection() as connection:
            rows = await (
                await connection.execute(
                    """
                    SELECT * FROM ta_questions
                    WHERE sent_at IS NOT NULL AND sent_event_recorded_at IS NULL
                    ORDER BY sent_at
                    LIMIT %s
                    """,
                    (limit,),
                )
            ).fetchall()
        return [TAQuestion.model_validate(row) for row in rows]

    async def mark_question_event_recorded(
        self,
        question_id: UUID,
        *,
        recorded_at: datetime,
    ) -> None:
        async with self._pool.connection() as connection:
            await connection.execute(
                """
                UPDATE ta_questions
                SET sent_event_recorded_at = COALESCE(sent_event_recorded_at, %s)
                WHERE id = %s
                """,
                (recorded_at, question_id),
            )

    async def inbound_seen(self, provider_message_id: str) -> bool:
        async with self._pool.connection() as connection:
            row = await (
                await connection.execute(
                    "SELECT 1 FROM mail_inbound_receipts WHERE provider_message_id = %s",
                    (provider_message_id,),
                )
            ).fetchone()
        return row is not None

    async def record_inbound_disposition(
        self,
        message: InboundMail,
        disposition: InboundDisposition,
        *,
        processed_at: datetime,
        question_id: UUID | None = None,
    ) -> None:
        async with self._pool.connection() as connection:
            await connection.execute(
                """
                INSERT INTO mail_inbound_receipts (
                    provider_message_id, disposition, received_at, processed_at, question_id
                )
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (provider_message_id) DO NOTHING
                """,
                (
                    message.provider_message_id,
                    disposition,
                    message.received_at,
                    processed_at,
                    question_id,
                ),
            )

    async def find_open_question(
        self,
        *,
        referenced_message_ids: Iterable[str],
        question_code: str | None,
    ) -> TAQuestion | None:
        message_ids = [
            value for value in {_normalize_message_id(v) for v in referenced_message_ids} if value
        ]
        async with self._pool.connection() as connection:
            row = None
            if message_ids:
                rows = await (
                    await connection.execute(
                        """
                        SELECT * FROM ta_questions
                        WHERE status = 'open' AND outbound_message_id IS NOT NULL
                        """
                    )
                ).fetchall()
                row = next(
                    (
                        candidate
                        for candidate in rows
                        if _normalize_message_id(str(candidate["outbound_message_id"]))
                        in message_ids
                    ),
                    None,
                )
            if row is None and question_code is not None:
                row = await (
                    await connection.execute(
                        """
                        SELECT * FROM ta_questions
                        WHERE status = 'open' AND public_question_code = %s
                        """,
                        (question_code,),
                    )
                ).fetchone()
        return TAQuestion.model_validate(row) if row is not None else None

    async def record_answer(
        self,
        question: TAQuestion,
        message: InboundMail,
        *,
        answer_text: str,
        publication: PublicationDecision,
        processed_at: datetime,
    ) -> TAAnswer | None:
        answer = TAAnswer(
            id=uuid4(),
            question_id=question.id,
            event_id=uuid4(),
            inbound_provider_message_id=message.provider_message_id,
            inbound_message_id=message.internet_message_id,
            responder_email=message.sender,
            answer_text=answer_text,
            received_at=message.received_at,
        )
        publish = publication == "publish"
        candidate_status = "pending_publication" if publish else "declined"
        disposition = "answer_publish_requested" if publish else "answer_private"
        async with self._pool.connection() as connection, connection.transaction():
            cursor = await connection.execute(
                """
                UPDATE ta_questions
                SET status = 'answered', resolved_at = %s
                WHERE id = %s AND status = 'open'
                RETURNING id
                """,
                (processed_at, question.id),
            )
            if await cursor.fetchone() is None:
                return None
            await connection.execute(
                """
                INSERT INTO ta_answers (
                    id, question_id, event_id, inbound_provider_message_id,
                    inbound_message_id, responder_email, answer_text, received_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    answer.id,
                    answer.question_id,
                    answer.event_id,
                    answer.inbound_provider_message_id,
                    answer.inbound_message_id,
                    str(answer.responder_email),
                    answer.answer_text,
                    answer.received_at,
                ),
            )
            await connection.execute(
                """
                INSERT INTO faq_review_candidates (
                    id, question_id, answer_id, suggested_question,
                    suggested_answer, status, decision_inbound_provider_message_id,
                    reviewed_by_email, reviewed_at, created_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    uuid4(),
                    question.id,
                    answer.id,
                    question.question_text,
                    answer_text,
                    candidate_status,
                    message.provider_message_id,
                    str(message.sender),
                    processed_at,
                    processed_at,
                ),
            )
            await connection.execute(
                """
                INSERT INTO mail_inbound_receipts (
                    provider_message_id, disposition, received_at, processed_at, question_id
                )
                VALUES (%s, %s, %s, %s, %s)
                """,
                (
                    message.provider_message_id,
                    disposition,
                    message.received_at,
                    processed_at,
                    question.id,
                ),
            )
        return answer

    async def get_answer(self, answer_id: UUID) -> TAAnswer | None:
        async with self._pool.connection() as connection:
            row = await (
                await connection.execute("SELECT * FROM ta_answers WHERE id = %s", (answer_id,))
            ).fetchone()
        return TAAnswer.model_validate(row) if row is not None else None

    async def list_answers_pending_event(self, *, limit: int = 20) -> list[TAAnswer]:
        return await self._list_answers("event_recorded_at IS NULL", limit)

    async def mark_answer_event_recorded(self, answer_id: UUID, *, recorded_at: datetime) -> None:
        async with self._pool.connection() as connection:
            await connection.execute(
                """
                UPDATE ta_answers
                SET event_recorded_at = COALESCE(event_recorded_at, %s)
                WHERE id = %s
                """,
                (recorded_at, answer_id),
            )

    async def list_answers_pending_notification(self, *, limit: int = 20) -> list[TAAnswer]:
        return await self._list_answers("notified_at IS NULL", limit)

    async def mark_answer_notified(
        self,
        answer_id: UUID,
        sent: SentMail,
        *,
        notified_at: datetime,
    ) -> None:
        async with self._pool.connection() as connection:
            await connection.execute(
                """
                UPDATE ta_answers
                SET notification_provider_message_id = %s, notified_at = %s
                WHERE id = %s AND notified_at IS NULL
                """,
                (sent.provider_message_id, notified_at, answer_id),
            )

    async def list_faq_candidates_pending_publication(
        self, *, limit: int = 20
    ) -> list[FaqReviewCandidate]:
        async with self._pool.connection() as connection:
            rows = await (
                await connection.execute(
                    """
                    SELECT candidate.*
                    FROM faq_review_candidates AS candidate
                    JOIN ta_answers AS answer ON answer.id = candidate.answer_id
                    WHERE candidate.status = 'pending_publication'
                      AND answer.notified_at IS NOT NULL
                    ORDER BY candidate.created_at
                    LIMIT %s
                    """,
                    (limit,),
                )
            ).fetchall()
        return [FaqReviewCandidate.model_validate(row) for row in rows]

    async def mark_faq_candidate_published(
        self,
        candidate_id: UUID,
        *,
        published_faq_entry_id: UUID,
    ) -> None:
        async with self._pool.connection() as connection:
            await connection.execute(
                """
                UPDATE faq_review_candidates
                SET status = 'published', published_faq_entry_id = %s
                WHERE id = %s AND status = 'pending_publication'
                """,
                (published_faq_entry_id, candidate_id),
            )

    async def list_faq_candidates_pending_delivery(
        self, *, limit: int = 20
    ) -> list[FaqReviewCandidate]:
        async with self._pool.connection() as connection:
            rows = await (
                await connection.execute(
                    """
                    SELECT candidate.*
                    FROM faq_review_candidates AS candidate
                    JOIN ta_answers AS answer ON answer.id = candidate.answer_id
                    WHERE candidate.status = 'pending_delivery'
                      AND answer.notified_at IS NOT NULL
                    ORDER BY candidate.created_at
                    LIMIT %s
                    """,
                    (limit,),
                )
            ).fetchall()
        return [FaqReviewCandidate.model_validate(row) for row in rows]

    async def mark_faq_candidate_sent(
        self,
        candidate_id: UUID,
        sent: SentMail,
        *,
        sent_at: datetime,
    ) -> None:
        async with self._pool.connection() as connection:
            await connection.execute(
                """
                UPDATE faq_review_candidates
                SET status = 'pending_review', review_provider_message_id = %s,
                    review_outbound_message_id = %s, review_sent_at = %s
                WHERE id = %s AND status = 'pending_delivery'
                """,
                (
                    sent.provider_message_id,
                    sent.internet_message_id,
                    sent_at,
                    candidate_id,
                ),
            )

    async def find_pending_faq_review(
        self,
        *,
        referenced_message_ids: Iterable[str],
        question_code: str | None,
    ) -> FaqReviewCandidate | None:
        message_ids = {
            value for value in (_normalize_message_id(v) for v in referenced_message_ids) if value
        }
        async with self._pool.connection() as connection:
            rows = await (
                await connection.execute(
                    """
                    SELECT candidate.*, question.public_question_code
                    FROM faq_review_candidates AS candidate
                    JOIN ta_questions AS question ON question.id = candidate.question_id
                    WHERE candidate.status = 'pending_review'
                    """
                )
            ).fetchall()
        row = next(
            (
                candidate
                for candidate in rows
                if candidate["review_outbound_message_id"]
                and _normalize_message_id(str(candidate["review_outbound_message_id"]))
                in message_ids
            ),
            None,
        )
        if row is None and question_code is not None:
            row = next(
                (
                    candidate
                    for candidate in rows
                    if candidate["public_question_code"] == question_code
                ),
                None,
            )
        if row is None:
            return None
        candidate_data = dict(row)
        candidate_data.pop("public_question_code", None)
        return FaqReviewCandidate.model_validate(candidate_data)

    async def record_faq_review_decision(
        self,
        candidate: FaqReviewCandidate,
        message: InboundMail,
        *,
        status: Literal["published", "declined"],
        published_faq_entry_id: UUID | None,
        processed_at: datetime,
    ) -> bool:
        disposition = "faq_published" if status == "published" else "faq_declined"
        async with self._pool.connection() as connection, connection.transaction():
            cursor = await connection.execute(
                """
                UPDATE faq_review_candidates
                SET status = %s, decision_inbound_provider_message_id = %s,
                    reviewed_by_email = %s, reviewed_at = %s,
                    published_faq_entry_id = %s
                WHERE id = %s AND status = 'pending_review'
                RETURNING question_id
                """,
                (
                    status,
                    message.provider_message_id,
                    str(message.sender),
                    processed_at,
                    published_faq_entry_id,
                    candidate.id,
                ),
            )
            row = await cursor.fetchone()
            if row is None:
                return False
            await connection.execute(
                """
                INSERT INTO mail_inbound_receipts (
                    provider_message_id, disposition, received_at, processed_at, question_id
                )
                VALUES (%s, %s, %s, %s, %s)
                """,
                (
                    message.provider_message_id,
                    disposition,
                    message.received_at,
                    processed_at,
                    row["question_id"],
                ),
            )
        return True

    async def _list_answers(self, condition: str, limit: int) -> list[TAAnswer]:
        query = f"SELECT * FROM ta_answers WHERE {condition} ORDER BY received_at LIMIT %s"
        async with self._pool.connection() as connection:
            rows = await (await connection.execute(query, (limit,))).fetchall()
        return [TAAnswer.model_validate(row) for row in rows]

    async def get_sync_checkpoint(self, mailbox_key: str) -> datetime | None:
        async with self._pool.connection() as connection:
            row = await (
                await connection.execute(
                    "SELECT last_received_at FROM mail_sync_state WHERE mailbox_key = %s",
                    (mailbox_key.casefold(),),
                )
            ).fetchone()
        return row["last_received_at"] if row is not None else None

    async def set_sync_checkpoint(
        self,
        mailbox_key: str,
        *,
        last_received_at: datetime,
        updated_at: datetime,
    ) -> None:
        async with self._pool.connection() as connection:
            await connection.execute(
                """
                INSERT INTO mail_sync_state (mailbox_key, last_received_at, updated_at)
                VALUES (%s, %s, %s)
                ON CONFLICT (mailbox_key) DO UPDATE
                SET last_received_at = GREATEST(
                        mail_sync_state.last_received_at,
                        EXCLUDED.last_received_at
                    ),
                    updated_at = EXCLUDED.updated_at
                """,
                (mailbox_key.casefold(), last_received_at, updated_at),
            )


def _normalize_message_id(value: str) -> str:
    return value.strip().strip("<>").casefold()
