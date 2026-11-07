"""Authenticated, privacy-preserving follow-ups to course-staff answers."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Literal, Protocol
from uuid import UUID, uuid4

from psycopg_pool import AsyncConnectionPool
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from agent_core import PrincipalContext
from course_server.auth import AuthStore, StoredUser
from course_server.mail import TAQuestion, TAQuestionStore, parse_staff_answer_reply


class QuestionDiscussionError(ValueError):
    """The question or reply is unavailable to this account."""


class QuestionReply(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID
    question_id: UUID
    sender_user_id: UUID
    sender_role: Literal["student", "staff"]
    body: str = Field(min_length=1, max_length=10_000)
    created_at: AwareDatetime


class QuestionReplyStore(Protocol):
    async def list_for_questions(self, question_ids: list[UUID]) -> list[QuestionReply]: ...

    async def create(
        self,
        *,
        question_id: UUID,
        sender_user_id: UUID,
        sender_role: Literal["student", "staff"],
        body: str,
    ) -> QuestionReply: ...


class PostgresQuestionReplyStore:
    def __init__(self, pool: AsyncConnectionPool[Any]) -> None:
        self._pool = pool

    async def list_for_questions(self, question_ids: list[UUID]) -> list[QuestionReply]:
        if not question_ids:
            return []
        async with self._pool.connection() as connection:
            rows = await (
                await connection.execute(
                    """SELECT * FROM course_question_replies
                    WHERE question_id = ANY(%s) ORDER BY created_at, id""",
                    (question_ids,),
                )
            ).fetchall()
        return [QuestionReply.model_validate(row) for row in rows]

    async def create(
        self,
        *,
        question_id: UUID,
        sender_user_id: UUID,
        sender_role: Literal["student", "staff"],
        body: str,
    ) -> QuestionReply:
        now = datetime.now(UTC)
        async with self._pool.connection() as connection, connection.transaction():
            await connection.execute(
                "SELECT id FROM users WHERE id = %s FOR UPDATE", (sender_user_id,)
            )
            count = await (
                await connection.execute(
                    """SELECT count(*) AS total FROM course_question_replies
                    WHERE sender_user_id = %s AND created_at > %s""",
                    (sender_user_id, now - timedelta(days=1)),
                )
            ).fetchone()
            if count is not None and count["total"] >= 20:
                raise QuestionDiscussionError("The daily reply limit has been reached.")
            row = await (
                await connection.execute(
                    """INSERT INTO course_question_replies
                    (id, question_id, sender_user_id, sender_role, body, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s) RETURNING *""",
                    (uuid4(), question_id, sender_user_id, sender_role, body, now),
                )
            ).fetchone()
        assert row is not None
        return QuestionReply.model_validate(row)


class QuestionDiscussionService:
    def __init__(
        self,
        *,
        auth: AuthStore,
        questions: TAQuestionStore,
        replies: QuestionReplyStore,
    ) -> None:
        self._auth = auth
        self._questions = questions
        self._replies = replies

    async def _access(
        self, principal: PrincipalContext, question_id: UUID
    ) -> tuple[StoredUser, TAQuestion, Literal["student", "staff"]]:
        if not principal.authenticated or principal.user_id is None:
            raise QuestionDiscussionError("Course login required.")
        user = await self._auth.get_user_by_id(principal.user_id)
        if user is None or not user.active or user.role not in principal.roles:
            raise QuestionDiscussionError("Course login required.")
        question = await self._questions.get_question(question_id)
        if question is None or question.status not in {"queued", "open", "answered"}:
            raise QuestionDiscussionError("Question not found.")
        if user.role == "student":
            if question.student_user_id != user.id:
                raise QuestionDiscussionError("Question not found.")
            role: Literal["student", "staff"] = "student"
        elif user.role in {"ta", "instructor"}:
            role = "staff"
        else:
            raise QuestionDiscussionError("Question not found.")
        return user, question, role

    async def get(self, principal: PrincipalContext, question_id: UUID) -> dict[str, Any]:
        user, question, role = await self._access(principal, question_id)
        threads = await self._questions.list_student_threads(
            student_user_id=question.student_user_id,
            limit=None,
        )
        thread = next((item for item in threads if item.question.id == question_id), None)
        if thread is None:
            raise QuestionDiscussionError("Question not found.")
        answer = thread.answer
        answer_text = None
        if answer is not None:
            parsed = parse_staff_answer_reply(answer.answer_text)
            answer_text = parsed.answer if parsed is not None else answer.answer_text.strip()
        replies = await self._replies.list_for_questions([question_id])
        student = (
            await self._auth.get_user_by_id(question.student_user_id)
            if role == "staff" and question.reporter_visibility == "named"
            else None
        )
        return {
            "question_id": str(question_id),
            "subject": question.subject,
            "question": question.question_text,
            "question_at": question.sent_at or question.confirmed_at or question.created_at,
            "answer": answer_text,
            "answer_at": answer.received_at if answer is not None else None,
            "viewer_role": role,
            "student_label": (
                "You"
                if role == "student"
                else student.display_name
                if student is not None
                else "Student"
            ),
            "can_reply": answer is not None,
            "replies": [
                {
                    "id": str(reply.id),
                    "sender_role": reply.sender_role,
                    "sender_label": (
                        "You"
                        if reply.sender_user_id == user.id
                        else "Course staff"
                        if reply.sender_role == "staff"
                        else student.display_name
                        if student is not None
                        else "Student"
                    ),
                    "body": reply.body,
                    "created_at": reply.created_at,
                }
                for reply in replies
            ],
        }

    async def send(
        self,
        principal: PrincipalContext,
        question_id: UUID,
        body: str,
    ) -> dict[str, Any]:
        user, question, role = await self._access(principal, question_id)
        if question.status != "answered":
            raise QuestionDiscussionError("Replies open after staff answers the question.")
        body = body.strip()
        if not 1 <= len(body) <= 10_000:
            raise QuestionDiscussionError("Reply must be between 1 and 10000 characters.")
        await self._replies.create(
            question_id=question_id,
            sender_user_id=user.id,
            sender_role=role,
            body=body,
        )
        return await self.get(principal, question_id)
