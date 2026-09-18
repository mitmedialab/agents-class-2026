from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from agent_core import PrincipalContext
from course_server.agent import (
    FileResourceProvider,
    ResourceAnnouncement,
    ResourceDeadline,
    ResourceDefinition,
)
from course_server.assignments import AssignmentDraft, FileAssignmentStore
from course_server.auth import InMemoryAuthStore, UserAdminService
from course_server.faq import InMemoryFaqStore
from course_server.instructor_messages import (
    InMemoryInstructorMessageStore,
    InstructorMessageDraft,
    InstructorMessageService,
)
from course_server.mail import InboundMail, InMemoryTAQuestionStore, SentMail
from course_server.notifications import (
    InMemoryNotificationItemReadStore,
    NotificationCenterService,
)


async def _course_member(
    store: InMemoryAuthStore,
    *,
    username: str,
    role: str,
    display_name: str | None = None,
    email: str | None = None,
) -> PrincipalContext:
    issued = await UserAdminService(store).create_user(
        username=username,
        display_name=display_name or username.title(),
        email=email or f"{username}@mit.edu",
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


def test_student_center_composes_updates_communications_and_upcoming_work(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        now = datetime(2026, 9, 5, 12, tzinfo=UTC)
        assignment_file = tmp_path / "assignment.md"
        assignment_file.write_text("# Assignment one", encoding="utf-8")
        resources = FileResourceProvider(
            [
                ResourceDefinition(
                    uri="course://students/assignment-one",
                    title="Assignment one",
                    media_type="text/markdown",
                    path=assignment_file,
                    visibility="students",
                    announcement=ResourceAnnouncement(
                        revision="v1",
                        published_at=now - timedelta(hours=1),
                        summary="Assignment one is now available.",
                    ),
                    deadline=ResourceDeadline(due_at=now + timedelta(days=12)),
                ),
                ResourceDefinition(
                    uri="course://instructors",
                    title="Course Staff",
                    media_type="text/markdown",
                    path=assignment_file,
                    assets={"chitralekha_gupta_portrait": assignment_file},
                ),
            ]
        )
        auth = InMemoryAuthStore()
        student = await _course_member(auth, username="alice", role="student")
        await _course_member(
            auth,
            username="chitralekha",
            display_name="Chitralekha Gupta",
            email="chitra_g@mit.edu",
            role="ta",
        )
        assert student.user_id is not None
        faqs = InMemoryFaqStore()
        await faqs.publish(
            source_question_id=uuid4(),
            question="May we work in pairs?",
            answer="Pairs are allowed for assignment one.",
            published_by_user_id=None,
            published_at=now - timedelta(hours=2),
        )
        questions = InMemoryTAQuestionStore()
        question = await questions.create_question(
            student_user_id=student.user_id,
            conversation_id=uuid4(),
            subject="Model choice",
            question_text="May I use a local model?",
            context_text=None,
            created_at=now - timedelta(days=1),
        )
        await questions.transition_question(
            question.id,
            expected="pending_confirmation",
            status="queued",
            changed_at=now - timedelta(hours=23),
        )
        await questions.mark_question_sent(
            question.id,
            SentMail(provider_message_id="provider-question", internet_message_id="<q@mit.edu>"),
            sent_at=now - timedelta(hours=22),
        )
        reads = InMemoryNotificationItemReadStore()
        center = NotificationCenterService(
            faqs=faqs,
            reads=reads,
            auth=auth,
            resources=resources,
            questions=questions,
            clock=lambda: now,
        )

        first = await center.get(student)
        assert [item.kind for item in first.items] == [
            "course_update",
            "course_update",
            "pending_message",
            "assignment_deadline",
        ]
        assert first.unread_count == 2
        assert first.items[-1].due_at == now + timedelta(days=12)
        assert first.history_items == first.items
        assert all("Ask what I want to do next." in item.action_prompt for item in first.items)
        assert all("suggest" not in item.action_prompt.casefold() for item in first.items)
        attention = await center.agent_attention(student)
        assert {item["kind"] for item in attention} == {
            "course_update",
            "pending_message",
            "assignment_deadline",
        }
        assert {item["category"] for item in attention} == {
            "new_since_last_visit",
            "pending_communication",
            "upcoming_assignment",
        }

        await center.mark_updates_seen(student)
        after_open = await center.get(student)
        assert [item.kind for item in after_open.items] == [
            "pending_message",
            "assignment_deadline",
        ]
        read_updates = [
            item for item in after_open.history_items if item.section == "notifications"
        ]
        assert len(read_updates) == 2
        assert all(item.state == "read" for item in read_updates)
        assert all(not item.unread and not item.dismissible for item in read_updates)
        assert all([await center.mark_read(student, item.id) for item in read_updates])
        deadline = next(item for item in after_open.items if item.kind == "assignment_deadline")
        assert not await center.mark_read(student, deadline.id)

        await questions.record_answer(
            question,
            InboundMail(
                provider_message_id="provider-answer",
                internet_message_id="<a@mit.edu>",
                sender="chitra_g@mit.edu",
                subject="Re: Model choice",
                text="PRIVATE\nYes.",
                received_at=now,
            ),
            answer_text="PUBLIC\n\n\nYes, a local model is allowed.",
            publication="publish",
            processed_at=now,
        )
        answered = await center.get(student)
        communication = next(item for item in answered.items if item.section == "communications")
        assert communication.kind == "staff_reply"
        assert communication.detail == "Yes, a local model is allowed."
        assert communication.sender is not None
        assert communication.sender.first_name == "Chitralekha"
        assert communication.sender.resource_uri == "course://instructors"
        assert communication.sender.image_asset_id == "chitralekha_gupta_portrait"
        assert "chitra_g@mit.edu" not in communication.model_dump_json()
        assert "Gupta" not in communication.model_dump_json()
        assert "pending_message" not in {item.kind for item in answered.items}

        assert await center.mark_read(student, communication.id)
        after_read = await center.get(student)
        assert all(item.id != communication.id for item in after_read.items)
        assert any(item.kind == "assignment_deadline" for item in after_read.items)
        historical_reply = next(
            item for item in after_read.history_items if item.id == communication.id
        )
        assert historical_reply.state == "responded"
        assert not historical_reply.unread and not historical_reply.dismissible

    asyncio.run(scenario())


def test_staff_center_exposes_only_questions_that_still_need_a_reply() -> None:
    async def scenario() -> None:
        now = datetime(2026, 9, 5, 12, tzinfo=UTC)
        auth = InMemoryAuthStore()
        student = await _course_member(auth, username="alice", role="student")
        instructor = await _course_member(auth, username="prof", role="instructor")
        assert student.user_id is not None
        questions = InMemoryTAQuestionStore()
        question = await questions.create_question(
            student_user_id=student.user_id,
            conversation_id=uuid4(),
            subject="Extension",
            question_text="May I have a one-day extension?",
            context_text=None,
            created_at=now,
        )
        await questions.transition_question(
            question.id,
            expected="pending_confirmation",
            status="queued",
            changed_at=now,
        )
        await questions.mark_question_sent(
            question.id,
            SentMail(
                provider_message_id="provider-question",
                internet_message_id="<question@mit.edu>",
            ),
            sent_at=now,
        )
        center = NotificationCenterService(
            faqs=InMemoryFaqStore(),
            reads=InMemoryNotificationItemReadStore(),
            auth=auth,
            questions=questions,
            clock=lambda: now,
        )

        result = await center.get(instructor)

        assert len(result.items) == 1
        assert result.items[0].kind == "pending_student_question"
        assert result.items[0].detail == "May I have a one-day extension?"
        attention = await center.agent_attention(instructor)
        assert attention[0]["suggested_action"] == result.items[0].action_prompt
        assert attention[0]["reply_reference"] == f"pending-question:{question.id}"
        assert str(student.user_id) not in str(attention[0])

        await questions.record_answer(
            question,
            InboundMail(
                provider_message_id="provider-answer",
                internet_message_id="<answer@mit.edu>",
                sender="prof@mit.edu",
                subject="Re: Extension",
                text="PRIVATE\nYes.",
                received_at=now + timedelta(minutes=5),
            ),
            answer_text="Yes.",
            publication="private",
            processed_at=now + timedelta(minutes=5),
        )
        answered = await center.get(instructor)
        assert answered.items == []
        assert len(answered.history_items) == 1
        assert answered.history_items[0].state == "responded"

    asyncio.run(scenario())


def test_published_assignment_drives_release_and_two_week_deadline_items(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        now = datetime(2026, 9, 6, 15, tzinfo=UTC)
        auth = InMemoryAuthStore()
        instructor = await _course_member(auth, username="prof", role="instructor")
        student = await _course_member(auth, username="alice", role="student")
        assert instructor.user_id is not None
        assignments = FileAssignmentStore(tmp_path / "assignments", clock=lambda: now)
        await assignments.create(
            AssignmentDraft(
                title="Agent observation",
                content_markdown=(
                    "# Agent observation\n\nObserve one agent interaction and document what "
                    "changed.\n\nChoose an interaction, analyze it, and submit a repository "
                    "link with your reflection."
                ),
                release_at=now - timedelta(hours=1),
                due_at=now + timedelta(days=12),
                publish=True,
            ),
            created_by_user_id=instructor.user_id,
        )
        center = NotificationCenterService(
            faqs=InMemoryFaqStore(),
            reads=InMemoryNotificationItemReadStore(),
            auth=auth,
            assignments=assignments,
            clock=lambda: now,
        )

        result = await center.get(student)

        assert [item.section for item in result.items] == ["notifications", "upcoming"]
        assert result.items[0].title == "Agent observation is available"
        assert "course.get_assignment" in result.items[0].action_prompt
        assert result.items[1].due_at == now + timedelta(days=12)
        attention = await center.agent_attention(student)
        assert {item["kind"] for item in attention} == {
            "course_update",
            "assignment_deadline",
        }

    asyncio.run(scenario())


def test_confirmed_instructor_message_appears_only_for_its_students() -> None:
    async def scenario() -> None:
        now = datetime(2026, 9, 14, 12, tzinfo=UTC)
        auth = InMemoryAuthStore()
        instructor = await _course_member(
            auth,
            username="prof",
            role="instructor",
            display_name="Maya Chen",
        )
        alice = await _course_member(auth, username="alice", role="student")
        bob = await _course_member(auth, username="bob", role="student")
        messages = InMemoryInstructorMessageStore()
        messaging = InstructorMessageService(messages=messages, auth=auth, clock=lambda: now)
        prepared = await messaging.prepare(
            principal=instructor,
            conversation_id=uuid4(),
            draft=InstructorMessageDraft(
                audience="specific_students",
                recipients=["alice"],
                subject="Office hours",
                message="Please come to office hours this afternoon.",
            ),
        )
        await messaging.confirm(
            principal=instructor,
            conversation_id=prepared.message.conversation_id,
            message_id=prepared.message.id,
        )
        reads = InMemoryNotificationItemReadStore()
        center = NotificationCenterService(
            faqs=InMemoryFaqStore(),
            reads=reads,
            auth=auth,
            instructor_messages=messages,
            clock=lambda: now,
        )

        alice_center = await center.get(alice)
        bob_center = await center.get(bob)

        assert len(alice_center.items) == 1
        item = alice_center.items[0]
        assert item.kind == "instructor_message"
        assert item.title == "Office hours"
        assert item.detail == "Please come to office hours this afternoon."
        assert item.unread and item.dismissible
        assert item.sender is not None
        assert item.sender.first_name == "Maya"
        assert item.sender.resource_uri is None
        assert item.sender.image_asset_id is None
        assert "Chen" not in item.model_dump_json()
        assert bob_center.items == []
        attention = await center.agent_attention(alice)
        assert attention[0]["category"] == "pending_communication"
        assert attention[0]["detail"] == item.detail

        assert await center.mark_read(alice, item.id)
        assert (await center.get(alice)).items == []

    asyncio.run(scenario())


def test_lecture_slides_are_authorized_persistent_and_sorted_numerically(tmp_path: Path) -> None:
    async def scenario() -> None:
        auth = InMemoryAuthStore()
        student = await _course_member(auth, username="alice", role="student")
        resources = FileResourceProvider(
            [
                ResourceDefinition(
                    uri=f"course://slides/week-{number:02}",
                    title=f"Week {number} Slides",
                    media_type="application/pdf",
                    path=tmp_path / f"{number}.pdf",
                    assets={"first_slide": tmp_path / f"{number}.png"},
                    visibility="instructors" if number == 4 else "public",
                    status="provisional" if number == 5 else "published",
                )
                for number in [1, 10, 2, 4, 5]
            ]
        )
        service = NotificationCenterService(
            faqs=InMemoryFaqStore(),
            reads=InMemoryNotificationItemReadStore(),
            auth=auth,
            resources=resources,
        )
        center = await service.get(student)
        assert [item.title for item in center.history_items] == [
            "Lecture 10",
            "Lecture 2",
            "Lecture 1",
        ]
        assert center.history_items[0].detail == "Week 10 Slides"
        assert center.history_items[0].thumbnail is not None
        assert center.history_items[0].thumbnail.resource_uri == "course://slides/week-10"
        assert center.history_items[0].thumbnail.asset_id == "first_slide"
        assert center.items == []
        assert center.unread_count == 0
        assert all(not item.dismissible for item in center.history_items)
        assert "course://slides/week-10" in center.history_items[0].action_prompt
        assert str(tmp_path) not in center.model_dump_json()
        assert not await service.mark_read(student, center.history_items[0].id)
        await service.mark_updates_seen(student)
        assert (await service.get(student)).history_items == center.history_items
        assert await service.agent_attention(student) == []
        staff = await _course_member(auth, username="prof", role="instructor")
        assert "Lecture 4" in [item.title for item in (await service.get(staff)).history_items]

    asyncio.run(scenario())
