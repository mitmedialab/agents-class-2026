"""Deliver confirmed course-message email copies from the durable outbox."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any
from uuid import UUID

from psycopg_pool import AsyncConnectionPool

from course_server.course_roster import CourseRoster, load_course_roster
from course_server.mail.models import MailAdapter, OutboundMail

logger = logging.getLogger(__name__)


class CourseMessageEmailDelivery:
    def __init__(
        self,
        pool: AsyncConnectionPool[Any],
        mail: MailAdapter,
        *,
        staff_recipient: str,
        public_base_url: str | None,
        roster_path: Path | None = None,
        roster: CourseRoster | None = None,
    ) -> None:
        self._pool = pool
        self._mail = mail
        self._staff_recipient = staff_recipient
        self._public_base_url = public_base_url.rstrip("/") if public_base_url else None
        self._roster_path = roster_path
        self._roster = roster

    async def run_once(self) -> None:
        async with self._pool.connection() as connection:
            pending = await (
                await connection.execute(
                    """
                    SELECT id FROM course_direct_messages
                    WHERE status = 'sent' AND email_sent_at IS NULL
                      AND email_abandoned_at IS NULL
                    ORDER BY sent_at, id LIMIT 100
                    """
                )
            ).fetchall()
        for item in pending:
            await self._deliver(UUID(str(item["id"])))

    async def _deliver(self, message_id: UUID) -> None:
        # A row lock makes concurrent worker cycles skip work already in flight.
        async with self._pool.connection() as connection, connection.transaction():
            row = await (
                await connection.execute(
                    """
                    SELECT m.id, m.subject, m.body, m.recipient_kind,
                           sender.display_name AS sender_name,
                           recipient.email AS recipient_email,
                           recipient.username AS recipient_username,
                           recipient.active AS recipient_active,
                           recipient.role AS recipient_role
                    FROM course_direct_messages m
                    JOIN users sender ON sender.id = m.sender_user_id
                    LEFT JOIN users recipient ON recipient.id = m.recipient_user_id
                    WHERE m.id = %s AND m.status = 'sent' AND m.email_sent_at IS NULL
                      AND m.email_abandoned_at IS NULL
                    FOR UPDATE OF m SKIP LOCKED
                    """,
                    (message_id,),
                )
            ).fetchone()
            if row is None:
                return
            if row["recipient_kind"] == "course_staff":
                recipient = self._staff_recipient
            elif row["recipient_active"] and row["recipient_role"] in {"ta", "instructor"}:
                recipient = row["recipient_email"]
            elif row["recipient_active"] and row["recipient_role"] == "student":
                current_roster = (
                    load_course_roster(self._roster_path)
                    if self._roster_path is not None
                    else self._roster
                )
                if current_roster is None:
                    await connection.execute(
                        """
                        UPDATE course_direct_messages
                        SET email_last_error = 'roster_unavailable',
                            email_attempts = email_attempts + 1
                        WHERE id = %s
                        """,
                        (message_id,),
                    )
                    return
                if not current_roster.permits_student_username(row["recipient_username"]):
                    await connection.execute(
                        """
                        UPDATE course_direct_messages
                        SET email_last_error = 'recipient_unavailable',
                            email_abandoned_at = now(),
                            email_attempts = email_attempts + 1
                        WHERE id = %s
                        """,
                        (message_id,),
                    )
                    return
                recipient = row["recipient_email"]
            else:
                # Do not email a deactivated or changed-role account.
                await connection.execute(
                    """
                    UPDATE course_direct_messages
                    SET email_last_error = 'recipient_unavailable',
                        email_abandoned_at = now(),
                        email_attempts = email_attempts + 1
                    WHERE id = %s
                    """,
                    (message_id,),
                )
                return
            inbox = (
                f"{self._public_base_url}/messages/{message_id}"
                if self._public_base_url
                else "the course website Messages page"
            )
            try:
                sent = await self._mail.send_message(
                    OutboundMail(
                        to=(recipient,),
                        subject=f"Course message: {row['subject']}",
                        text=(
                            f"From: {row['sender_name']}\n\n{row['body']}\n\n"
                            f"Read and reply in the course inbox: {inbox}\n"
                        ),
                    )
                )
            except Exception as error:
                logger.warning("Course message email delivery failed (%s)", type(error).__name__)
                await connection.execute(
                    """
                    UPDATE course_direct_messages
                    SET email_last_error = %s, email_attempts = email_attempts + 1
                    WHERE id = %s
                    """,
                    (type(error).__name__, message_id),
                )
                return
            await connection.execute(
                """
                UPDATE course_direct_messages
                SET email_sent_at = now(), email_provider_message_id = %s,
                    email_attempts = email_attempts + 1, email_last_error = NULL
                WHERE id = %s
                """,
                (sent.provider_message_id, message_id),
            )
