from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import uuid4

import pytest

from agent_core import PrincipalContext
from course_server.agent import ToolExecutionContext
from course_server.auth import InMemoryAuthStore, UserAdminService
from course_server.instructor_messages import (
    InMemoryInstructorMessageStore,
    InstructorMessageDraft,
    InstructorMessageService,
)
from course_server.mail import InMemoryTAQuestionStore
from course_server.student_communications import (
    CourseListMyCommunicationsTool,
    CourseReadMyCommunicationTool,
    StudentCommunicationAccessDenied,
    StudentCommunicationNotFound,
    StudentCommunicationService,
)


async def _course_member(
    auth: InMemoryAuthStore,
    *,
    username: str,
    role: Literal["student", "ta", "instructor", "admin"],
    display_name: str | None = None,
    email: str | None = None,
) -> PrincipalContext:
    issued = await UserAdminService(auth).create_user(
        username=username,
        display_name=display_name or username.title(),
        email=email or f"{username}@mit.edu",
        role=role,
    )
    return PrincipalContext(
        authenticated=True,
        user_id=issued.user.id,
        username=issued.user.username,
        display_name=issued.user.display_name,
        roles=["public", issued.user.role],
        session_id=uuid4(),
    )


def _execution_context(principal: PrincipalContext) -> ToolExecutionContext:
    return ToolExecutionContext(
        principal=principal,
        conversation_id=uuid4(),
        permitted_resource_uris=frozenset(),
    )


def test_student_tools_list_and_read_only_the_owners_private_communications() -> None:
    async def scenario() -> None:
        now = datetime(2026, 9, 15, 14, tzinfo=UTC)
        auth = InMemoryAuthStore()
        alice = await _course_member(auth, username="alice", role="student")
        bob = await _course_member(auth, username="bob", role="student")
        instructor = await _course_member(
            auth,
            username="professor",
            role="instructor",
            display_name="Maya Chen",
        )
        ta = await _course_member(
            auth,
            username="course-ta",
            role="ta",
            display_name="Chitralekha Gupta",
            email="chitra_g@mit.edu",
        )
        assert alice.user_id is not None
        assert bob.user_id is not None
        assert instructor.user_id is not None

        questions = InMemoryTAQuestionStore()
        alice_question = await questions.create_question(
            student_user_id=alice.user_id,
            conversation_id=uuid4(),
            subject="Project scope",
            question_text="Can my final project use a local model?",
            context_text=None,
            created_at=now - timedelta(days=2),
        )
        queued = await questions.transition_question(
            alice_question.id,
            expected="pending_confirmation",
            status="queued",
            changed_at=now - timedelta(days=2),
            reporter_visibility="anonymous",
        )
        assert queued is not None
        answer = await questions.record_online_answer(
            queued,
            instructor_message_id=uuid4(),
            responder_email="chitra_g@mit.edu",
            answer_text="Yes, if you document the local runtime.",
            publication="private",
            processed_at=now - timedelta(days=1),
        )
        assert answer is not None

        bob_question = await questions.create_question(
            student_user_id=bob.user_id,
            conversation_id=uuid4(),
            subject="Extension",
            question_text="Can I have an extension?",
            context_text=None,
            created_at=now,
        )
        bob_queued = await questions.transition_question(
            bob_question.id,
            expected="pending_confirmation",
            status="queued",
            changed_at=now,
        )
        assert bob_queued is not None
        assert bob_queued.id != alice_question.id

        messages = InMemoryInstructorMessageStore()
        messaging = InstructorMessageService(
            messages=messages,
            auth=auth,
            clock=lambda: now,
        )
        prepared = await messaging.prepare(
            principal=instructor,
            conversation_id=uuid4(),
            draft=InstructorMessageDraft(
                audience="specific_students",
                recipients=["alice"],
                subject="Studio reminder",
                message="Bring your prototype to tomorrow's studio.",
            ),
        )
        await messaging.confirm(
            principal=instructor,
            conversation_id=prepared.message.conversation_id,
            message_id=prepared.message.id,
        )

        service = StudentCommunicationService(
            auth=auth,
            questions=questions,
            instructor_messages=messages,
        )
        listed = await CourseListMyCommunicationsTool(service).execute(
            {"limit": 10},
            _execution_context(alice),
        )

        assert listed.storage_policy == "server_summary"
        assert isinstance(listed.content, dict)
        communication_summaries = listed.content["communications"]
        assert isinstance(communication_summaries, list)
        assert [item["subject"] for item in communication_summaries if isinstance(item, dict)] == [
            "Studio reminder",
            "Project scope",
        ]
        assert listed.content["total"] == 2
        assert listed.content["next_offset"] is None
        assert str(bob_question.id) not in str(listed.content)
        assert str(alice.user_id) not in str(listed.content)
        assert "chitra_g@mit.edu" not in str(listed.content)

        read = await CourseReadMyCommunicationTool(service).execute(
            {"communication_id": str(alice_question.id)},
            _execution_context(alice),
        )
        assert read.storage_policy == "server_summary"
        assert isinstance(read.content, dict)
        assert read.content["question"] == "Can my final project use a local model?"
        assert read.content["answer"] == "Yes, if you document the local runtime."
        assert read.content["reporter_visibility"] == "anonymous"
        assert read.content["publication_decision"] == "private"
        assert read.content["sender_first_name"] == "Chitralekha"

        with pytest.raises(StudentCommunicationNotFound):
            await service.get_mine(bob, alice_question.id)
        with pytest.raises(StudentCommunicationAccessDenied):
            await service.list_mine(instructor)
        with pytest.raises(StudentCommunicationAccessDenied):
            await service.list_mine(
                PrincipalContext(
                    authenticated=False,
                    anonymous_session_id=uuid4(),
                    roles=["public"],
                    session_id=uuid4(),
                )
            )
        assert ta.user_id is not None

    asyncio.run(scenario())
