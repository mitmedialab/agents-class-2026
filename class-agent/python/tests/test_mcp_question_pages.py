from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID, uuid4

import httpx
from mcp.server.fastmcp import FastMCP

from course_server.auth import AuthenticationService, InMemoryAuthStore, UserAdminService
from course_server.mail import InMemoryTAQuestionStore
from course_server.mcp_message_pages import register_course_message_pages
from course_server.question_discussions import (
    QuestionDiscussionService,
    QuestionReply,
)


class MemoryReplies:
    def __init__(self) -> None:
        self.items: list[QuestionReply] = []

    async def list_for_questions(self, question_ids: list[UUID]) -> list[QuestionReply]:
        return [item for item in self.items if item.question_id in question_ids]

    async def create(
        self,
        *,
        question_id: UUID,
        sender_user_id: UUID,
        sender_role: Literal["student", "staff"],
        body: str,
    ) -> QuestionReply:
        item = QuestionReply(
            id=uuid4(),
            question_id=question_id,
            sender_user_id=sender_user_id,
            sender_role=sender_role,
            body=body,
            created_at=datetime.now(UTC),
        )
        self.items.append(item)
        return item


def test_question_reply_page_requires_owner_and_browser_send() -> None:
    async def scenario() -> None:
        auth_store = InMemoryAuthStore()
        admin = UserAdminService(auth_store)
        alice = await admin.create_user(
            username="alice", display_name="Alice", email="alice@example.edu", role="student"
        )
        bob = await admin.create_user(
            username="bob", display_name="Bob", email="bob@example.edu", role="student"
        )
        questions = InMemoryTAQuestionStore()
        question = await questions.create_question(
            student_user_id=alice.user.id,
            conversation_id=uuid4(),
            subject="Project <scope>",
            question_text="Can I use <script>?",
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
        answer = await questions.record_online_answer(
            queued,
            instructor_message_id=uuid4(),
            responder_email="ta@example.edu",
            answer_text="Yes, explain why.",
            publication="private",
            processed_at=datetime.now(UTC),
        )
        assert answer is not None
        replies = MemoryReplies()
        service = QuestionDiscussionService(auth=auth_store, questions=questions, replies=replies)
        base_url = "https://127.0.0.1:8001"
        mcp = FastMCP("test", stateless_http=True)
        register_course_message_pages(
            mcp, None, AuthenticationService(auth_store), base_url, service
        )
        app = mcp.streamable_http_app()
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url=base_url, follow_redirects=False
            ) as browser:
                path = f"/questions/{question.id}"
                unauthenticated = await browser.get(path)
                assert unauthenticated.status_code == 303
                assert unauthenticated.headers["location"].startswith("/messages/login")
                login = await browser.post(
                    "/messages/login",
                    headers={"Origin": base_url},
                    data={
                        "username": "alice",
                        "access_code": alice.access_code,
                        "next": path,
                    },
                )
                assert login.status_code == 303
                assert login.headers["location"] == path
                page = await browser.get(path)
                assert page.status_code == 200
                assert "Project &lt;scope&gt;" in page.text
                assert "Can I use &lt;script&gt;?" in page.text
                assert "Can I use <script>?" not in page.text
                rejected = await browser.post(
                    path, headers={"Origin": "https://attacker.example"}, data={"body": "No"}
                )
                assert rejected.status_code == 400
                assert replies.items == []
                blank = await browser.post(path, headers={"Origin": base_url}, data={"body": "  "})
                assert blank.status_code == 200
                assert "Reply not sent" in blank.text
                assert replies.items == []
                sent = await browser.post(
                    path,
                    headers={"Origin": base_url},
                    data={"body": "I will explain <why>."},
                )
                assert sent.status_code == 303
                assert len(replies.items) == 1
                refreshed = await browser.get(path)
                assert "I will explain &lt;why&gt;." in refreshed.text
            async with httpx.AsyncClient(
                transport=transport, base_url=base_url, follow_redirects=False
            ) as other_browser:
                await other_browser.post(
                    "/messages/login",
                    headers={"Origin": base_url},
                    data={"username": "bob", "access_code": bob.access_code},
                )
                assert (await other_browser.get(path)).status_code == 404
                assert (
                    await other_browser.post(
                        path, headers={"Origin": base_url}, data={"body": "Read it"}
                    )
                ).status_code == 404
                assert len(replies.items) == 1

    asyncio.run(scenario())
