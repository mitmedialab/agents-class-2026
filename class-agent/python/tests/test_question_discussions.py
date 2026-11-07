from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID, uuid4

import pytest

from agent_core import PrincipalContext
from course_server.auth import InMemoryAuthStore, UserAdminService, UserRole
from course_server.faq import InMemoryFaqStore
from course_server.mail import InMemoryTAQuestionStore
from course_server.notifications import (
    InMemoryNotificationItemReadStore,
    NotificationCenterService,
)
from course_server.question_discussions import (
    QuestionDiscussionError,
    QuestionDiscussionService,
    QuestionReply,
)


class MemoryReplies:
    def __init__(self) -> None:
        self.replies: list[QuestionReply] = []

    async def list_for_questions(self, question_ids: list[UUID]) -> list[QuestionReply]:
        return [reply for reply in self.replies if reply.question_id in question_ids]

    async def create(
        self,
        *,
        question_id: UUID,
        sender_user_id: UUID,
        sender_role: Literal["student", "staff"],
        body: str,
    ) -> QuestionReply:
        reply = QuestionReply(
            id=uuid4(),
            question_id=question_id,
            sender_user_id=sender_user_id,
            sender_role=sender_role,
            body=body,
            created_at=datetime.now(UTC),
        )
        self.replies.append(reply)
        return reply


async def member(auth: InMemoryAuthStore, username: str, role: UserRole) -> PrincipalContext:
    issued = await UserAdminService(auth).create_user(
        username=username,
        display_name=username.title(),
        email=f"{username}@mit.edu",
        role=role,
    )
    return PrincipalContext(
        authenticated=True,
        user_id=issued.user.id,
        username=username,
        display_name=issued.user.display_name,
        roles=["public", issued.user.role],
        session_id=uuid4(),
    )


def test_question_discussion_supports_private_anonymous_back_and_forth() -> None:
    async def scenario() -> None:
        auth = InMemoryAuthStore()
        alice = await member(auth, "alice", "student")
        bob = await member(auth, "bob", "student")
        staff = await member(auth, "ta", "ta")
        assert alice.user_id is not None
        questions = InMemoryTAQuestionStore()
        question = await questions.create_question(
            student_user_id=alice.user_id,
            conversation_id=uuid4(),
            subject="Project scope",
            question_text="May I use a local model?",
            context_text=None,
            created_at=datetime.now(UTC),
        )
        queued = await questions.transition_question(
            question.id,
            expected="pending_confirmation",
            status="queued",
            changed_at=datetime.now(UTC),
            reporter_visibility="anonymous",
        )
        assert queued is not None
        replies = MemoryReplies()
        discussions = QuestionDiscussionService(auth=auth, questions=questions, replies=replies)

        with pytest.raises(QuestionDiscussionError, match="after staff answers"):
            await discussions.send(alice, question.id, "Could you clarify?")
        with pytest.raises(QuestionDiscussionError, match="not found"):
            await discussions.get(bob, question.id)

        answer = await questions.record_online_answer(
            queued,
            instructor_message_id=uuid4(),
            responder_email="ta@mit.edu",
            answer_text="Yes, document the runtime.",
            publication="private",
            processed_at=datetime.now(UTC),
        )
        assert answer is not None
        student_thread = await discussions.send(
            alice, question.id, "Would a small local model work?"
        )
        assert student_thread["replies"][0]["sender_label"] == "You"
        staff_thread = await discussions.get(staff, question.id)
        assert staff_thread["student_label"] == "Student"
        assert staff_thread["replies"][0]["sender_label"] == "Student"
        assert "Alice" not in str(staff_thread)
        await discussions.send(staff, question.id, "Yes, that is fine.")
        student_thread = await discussions.get(alice, question.id)
        assert [item["body"] for item in student_thread["replies"]] == [
            "Would a small local model work?",
            "Yes, that is fine.",
        ]

        reads = InMemoryNotificationItemReadStore()
        center = NotificationCenterService(
            faqs=InMemoryFaqStore(),
            reads=reads,
            auth=auth,
            questions=questions,
            question_replies=replies,
        )
        staff_items = (await center.get(staff)).items
        student_items = (await center.get(alice)).items
        staff_reply = next(item for item in staff_items if item.kind == "question_reply")
        student_reply = next(item for item in student_items if item.kind == "question_reply")
        assert staff_reply.detail == "Would a small local model work?"
        assert staff_reply.sender is None
        assert staff_reply.question_id == question.id
        assert student_reply.detail == "Yes, that is fine."
        assert student_reply.unread
        assert await center.mark_read(alice, student_reply.id)
        assert not next(
            item for item in (await center.get(alice)).history_items if item.id == student_reply.id
        ).unread

    asyncio.run(scenario())
