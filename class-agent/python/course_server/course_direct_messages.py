"""Human-confirmed, account-scoped course messages and reply resolution."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import UUID, uuid4

from psycopg_pool import AsyncConnectionPool
from pydantic import BaseModel, ConfigDict

from agent_core import PrincipalContext
from course_server.auth.models import User
from course_server.auth.store import AuthStore
from course_server.course_roster import CourseRoster

_STAFF_ROLES = frozenset({"ta", "instructor"})
_DRAFT_LIFETIME = timedelta(days=1)
_MAX_PENDING = 5
_MAX_DAILY_SENDS = 20
COURSE_STAFF_RECIPIENT = "@course_staff"
_MESSAGE_SELECT = """
    SELECT m.*, sender.username AS sender_username,
           sender.display_name AS sender_display_name,
           recipient.username AS recipient_username,
           recipient.display_name AS recipient_display_name
    FROM course_direct_messages m
    JOIN users sender ON sender.id = m.sender_user_id
    LEFT JOIN users recipient ON recipient.id = m.recipient_user_id
"""


class CourseMessageError(ValueError):
    """Safe message validation, visibility, or state failure."""


class CourseMessage(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    id: UUID
    sender_user_id: UUID
    sender_username: str
    sender_display_name: str
    recipient_user_id: UUID | None
    recipient_kind: Literal["user", "course_staff"]
    recipient_username: str | None
    recipient_display_name: str | None
    reply_to_message_id: UUID | None = None
    reply_to_instructor_message_id: UUID | None = None
    reply_to_question_id: UUID | None = None
    subject: str
    body: str
    status: Literal["pending_confirmation", "sent", "cancelled"]
    created_at: datetime
    expires_at: datetime
    sent_at: datetime | None = None

    @property
    def recipient_label(self) -> str:
        return self.recipient_display_name or "Course staff"

    def public(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "sender": {"username": self.sender_username, "display_name": self.sender_display_name},
            "recipient": {
                "username": self.recipient_username,
                "display_name": self.recipient_label,
                "kind": self.recipient_kind,
            },
            "subject": self.subject,
            "body": self.body,
            "status": self.status,
            "created_at": self.created_at.isoformat(),
            "sent_at": self.sent_at.isoformat() if self.sent_at else None,
            "reply_to_message_id": str(self.reply_to_message_id)
            if self.reply_to_message_id
            else None,
            "reply_to_instructor_message_id": (
                str(self.reply_to_instructor_message_id)
                if self.reply_to_instructor_message_id
                else None
            ),
            "reply_to_question_id": (
                str(self.reply_to_question_id) if self.reply_to_question_id else None
            ),
        }

    def summary(self) -> dict[str, Any]:
        result = self.public()
        del result["body"]
        return result


class CourseDirectMessageService:
    def __init__(
        self,
        pool: AsyncConnectionPool[Any],
        auth: AuthStore,
        roster: CourseRoster,
    ) -> None:
        self._pool = pool
        self._auth = auth
        self._roster = roster

    async def _member(self, principal: PrincipalContext) -> User:
        if not principal.authenticated or principal.user_id is None:
            raise CourseMessageError("A course login is required.")
        stored = await self._auth.get_user_by_id(principal.user_id)
        if stored is None or not stored.active or stored.role not in principal.roles:
            raise CourseMessageError("An active course login is required.")
        user = stored.public()
        if user.role == "student" and not self._roster.permits_student_username(user.username):
            raise CourseMessageError("Active course membership is required.")
        if user.role not in {"student", "ta", "instructor"}:
            raise CourseMessageError("Course messaging is unavailable for this role.")
        return user

    def _recipient_allowed(self, user: User) -> bool:
        return user.active and (
            user.role in _STAFF_ROLES
            or (user.role == "student" and self._roster.permits_student_username(user.username))
        )

    async def list_recipients(self, principal: PrincipalContext) -> list[dict[str, str]]:
        sender = await self._member(principal)
        users = await self._auth.list_users()
        recipients = [
            {"username": user.username, "display_name": user.display_name, "role": user.role}
            for user in users
            if user.id != sender.id and self._recipient_allowed(user.public())
        ]
        if any(user.active and user.role in _STAFF_ROLES for user in users):
            recipients.append(
                {
                    "username": COURSE_STAFF_RECIPIENT,
                    "display_name": "Course staff",
                    "role": "staff",
                }
            )
        return sorted(recipients, key=lambda item: (item["role"], item["display_name"]))

    async def _target(
        self, sender: User, recipient_username: str
    ) -> tuple[Literal["user", "course_staff"], UUID | None]:
        if recipient_username == COURSE_STAFF_RECIPIENT:
            if not any(
                user.active and user.role in _STAFF_ROLES for user in await self._auth.list_users()
            ):
                raise CourseMessageError("The course staff inbox is unavailable.")
            return "course_staff", None
        user = await self._auth.get_user_by_username(recipient_username)
        if user is None or user.id == sender.id or not self._recipient_allowed(user.public()):
            raise CourseMessageError("Recipient is not an active course member.")
        return "user", user.id

    async def _reply_target(
        self, sender: User, communication_id: UUID
    ) -> tuple[str, UUID | None, UUID | None, UUID | None]:
        # Direct messages are readable only by their two parties, or active staff
        # when addressed to the shared course-staff inbox.
        try:
            direct = await self.read_mine_by_user(sender, communication_id)
        except CourseMessageError:
            direct = None
        if direct is not None:
            if direct.sender_user_id == sender.id:
                target = direct.recipient_username or COURSE_STAFF_RECIPIENT
            else:
                target = direct.sender_username
            return target, direct.id, None, None
        async with self._pool.connection() as connection:
            instructor = await (
                await connection.execute(
                    """
                    SELECT m.sender_user_id, m.subject, sender.username
                    FROM instructor_messages m
                    JOIN instructor_message_recipients r ON r.message_id = m.id
                    JOIN users sender ON sender.id = m.sender_user_id
                    WHERE m.id = %s AND r.student_user_id = %s AND m.status = 'sent'
                      AND m.source_question_id IS NULL
                    """,
                    (communication_id, sender.id),
                )
            ).fetchone()
            if instructor is not None:
                return instructor["username"], None, communication_id, None
            question = await (
                await connection.execute(
                    """
                    SELECT id FROM ta_questions
                    WHERE id = %s AND student_user_id = %s
                      AND status IN ('queued', 'open', 'answered')
                    """,
                    (communication_id, sender.id),
                )
            ).fetchone()
            if question is not None:
                return COURSE_STAFF_RECIPIENT, None, None, communication_id
        raise CourseMessageError("This communication cannot be replied to by this account.")

    @staticmethod
    def _content(subject: str, body: str) -> tuple[str, str]:
        subject, body = subject.strip(), body.strip()
        if not 1 <= len(subject) <= 200 or not 1 <= len(body) <= 10_000:
            raise CourseMessageError("A subject and message of valid length are required.")
        return subject, body

    async def prepare(
        self,
        principal: PrincipalContext,
        *,
        recipient_username: str,
        subject: str,
        body: str,
        reply_to: UUID | None = None,
    ) -> CourseMessage:
        sender = await self._member(principal)
        if reply_to is not None:
            recipient_username, direct_id, instructor_id, question_id = await self._reply_target(
                sender, reply_to
            )
        else:
            direct_id = instructor_id = question_id = None
        recipient_kind, recipient_id = await self._target(sender, recipient_username)
        subject, body = self._content(subject, body)
        now = datetime.now(UTC)
        message_id = uuid4()
        async with self._pool.connection() as connection, connection.transaction():
            await connection.execute("SELECT id FROM users WHERE id = %s FOR UPDATE", (sender.id,))
            counts = await (
                await connection.execute(
                    """
                    SELECT count(*) FILTER (WHERE status = 'pending_confirmation'
                                              AND expires_at > %s) AS pending,
                           count(*) FILTER (WHERE status = 'sent' AND sent_at > %s) AS sent
                    FROM course_direct_messages WHERE sender_user_id = %s
                    """,
                    (now, now - timedelta(days=1), sender.id),
                )
            ).fetchone()
            assert counts is not None
            if counts["pending"] >= _MAX_PENDING or counts["sent"] >= _MAX_DAILY_SENDS:
                raise CourseMessageError("The course message limit has been reached.")
            await connection.execute(
                """
                INSERT INTO course_direct_messages (
                    id, sender_user_id, recipient_user_id, recipient_kind,
                    reply_to_message_id, reply_to_instructor_message_id,
                    reply_to_question_id, subject, body, status, created_at, expires_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s,
                          'pending_confirmation', %s, %s)
                """,
                (
                    message_id,
                    sender.id,
                    recipient_id,
                    recipient_kind,
                    direct_id,
                    instructor_id,
                    question_id,
                    subject,
                    body,
                    now,
                    now + _DRAFT_LIFETIME,
                ),
            )
        return await self.get_draft(principal, message_id)

    async def get_draft(self, principal: PrincipalContext, message_id: UUID) -> CourseMessage:
        sender = await self._member(principal)
        async with self._pool.connection() as connection:
            row = await (
                await connection.execute(
                    _MESSAGE_SELECT + " WHERE m.id = %s AND m.sender_user_id = %s",
                    (message_id, sender.id),
                )
            ).fetchone()
        if row is None or row["status"] != "pending_confirmation":
            raise CourseMessageError("This message draft is unavailable.")
        if row["expires_at"] <= datetime.now(UTC):
            raise CourseMessageError("This message draft has expired.")
        return CourseMessage.model_validate(row)

    async def confirm(
        self,
        principal: PrincipalContext,
        message_id: UUID,
        *,
        action: Literal["send", "cancel"],
        subject: str | None = None,
        body: str | None = None,
    ) -> CourseMessage:
        sender = await self._member(principal)
        now = datetime.now(UTC)
        async with self._pool.connection() as connection, connection.transaction():
            await connection.execute("SELECT id FROM users WHERE id = %s FOR UPDATE", (sender.id,))
            row = await (
                await connection.execute(
                    _MESSAGE_SELECT + " WHERE m.id = %s AND m.sender_user_id = %s FOR UPDATE OF m",
                    (message_id, sender.id),
                )
            ).fetchone()
            if row is None or row["status"] != "pending_confirmation" or row["expires_at"] <= now:
                raise CourseMessageError("This message draft is no longer awaiting confirmation.")
            if action == "send":
                if row["recipient_kind"] == "course_staff":
                    await self._target(sender, COURSE_STAFF_RECIPIENT)
                else:
                    recipient = await self._auth.get_user_by_id(row["recipient_user_id"])
                    if recipient is None or not self._recipient_allowed(recipient.public()):
                        raise CourseMessageError("Recipient is no longer an active course member.")
                content = self._content(subject or row["subject"], body or row["body"])
                sent_count = await (
                    await connection.execute(
                        """
                        SELECT count(*) AS count FROM course_direct_messages
                        WHERE sender_user_id = %s AND status = 'sent' AND sent_at > %s
                        """,
                        (sender.id, now - timedelta(days=1)),
                    )
                ).fetchone()
                assert sent_count is not None
                if sent_count["count"] >= _MAX_DAILY_SENDS:
                    raise CourseMessageError("The course message limit has been reached.")
                await connection.execute(
                    """
                    UPDATE course_direct_messages
                    SET subject = %s, body = %s, status = 'sent', sent_at = %s
                    WHERE id = %s
                    """,
                    (*content, now, message_id),
                )
            else:
                await connection.execute(
                    """
                    UPDATE course_direct_messages
                    SET status = 'cancelled', cancelled_at = %s WHERE id = %s
                    """,
                    (now, message_id),
                )
            updated = await (
                await connection.execute(_MESSAGE_SELECT + " WHERE m.id = %s", (message_id,))
            ).fetchone()
        assert updated is not None
        return CourseMessage.model_validate(updated)

    async def list_mine(
        self, principal: PrincipalContext, *, offset: int = 0, limit: int = 25
    ) -> dict[str, Any]:
        viewer = await self._member(principal)
        if not 0 <= offset <= 10_000 or not 1 <= limit <= 50:
            raise CourseMessageError("Invalid message range.")
        where = (
            "m.status = 'sent' AND (m.sender_user_id = %s OR m.recipient_user_id = %s"
            + (" OR m.recipient_kind = 'course_staff'" if viewer.role in _STAFF_ROLES else "")
            + ")"
        )
        async with self._pool.connection() as connection:
            total_row = await (
                await connection.execute(
                    "SELECT count(*) AS total FROM course_direct_messages m WHERE " + where,
                    (viewer.id, viewer.id),
                )
            ).fetchone()
            rows = await (
                await connection.execute(
                    _MESSAGE_SELECT
                    + " WHERE "
                    + where
                    + " ORDER BY m.sent_at DESC, m.id DESC LIMIT %s OFFSET %s",
                    (viewer.id, viewer.id, limit, offset),
                )
            ).fetchall()
        total = int(total_row["total"]) if total_row else 0
        next_offset = offset + len(rows)
        return {
            "total": total,
            "next_offset": next_offset if next_offset < total else None,
            "messages": [CourseMessage.model_validate(row).summary() for row in rows],
        }

    async def read_mine(self, principal: PrincipalContext, message_id: UUID) -> CourseMessage:
        return await self.read_mine_by_user(await self._member(principal), message_id)

    async def read_mine_by_user(self, viewer: User, message_id: UUID) -> CourseMessage:
        async with self._pool.connection() as connection:
            row = await (
                await connection.execute(
                    _MESSAGE_SELECT + " WHERE m.id = %s AND m.status = 'sent'",
                    (message_id,),
                )
            ).fetchone()
        if row is None or not (
            row["sender_user_id"] == viewer.id
            or row["recipient_user_id"] == viewer.id
            or (viewer.role in _STAFF_ROLES and row["recipient_kind"] == "course_staff")
        ):
            raise CourseMessageError("This course message is unavailable to this account.")
        return CourseMessage.model_validate(row)
