"""Deliver confirmed instructor messages through the existing mailbox adapter.

The sent message and fixed recipient rows are the outbox. Row locks serialize
workers per recipient. Provider acceptance followed by a process crash can still
cause a duplicate on retry, as providers do not offer a shared idempotency API.
"""

from __future__ import annotations

import logging
from typing import Any

from psycopg_pool import AsyncConnectionPool

from course_server.config import InstructorMessageTestRecipient
from course_server.mail.models import MailAdapter, OutboundMail

logger = logging.getLogger(__name__)


def instructor_message_delivery_address(
    username: str,
    account_email: str,
    test_recipient: InstructorMessageTestRecipient | None,
) -> str:
    if test_recipient is not None and username == test_recipient.username:
        return str(test_recipient.email)
    return account_email


class InstructorEmailDelivery:
    def __init__(
        self,
        pool: AsyncConnectionPool[Any],
        mail: MailAdapter,
        *,
        test_recipient: InstructorMessageTestRecipient | None = None,
    ) -> None:
        self._pool = pool
        self._mail = mail
        self._test_recipient = test_recipient

    async def run_once(self) -> None:
        async with self._pool.connection() as connection:
            pending = await (
                await connection.execute(
                    """
                    SELECT r.message_id, r.student_user_id
                    FROM instructor_message_recipients r
                    JOIN instructor_messages m ON m.id = r.message_id
                    JOIN users u ON u.id = r.student_user_id
                    WHERE m.status = 'sent' AND m.send_email
                      AND m.source_question_id IS NULL AND r.email_sent_at IS NULL
                      AND u.active AND u.role = 'student'
                    ORDER BY m.sent_at, r.message_id, r.student_user_id
                    """
                )
            ).fetchall()
        for recipient in pending:
            # Lock and recheck after discovery so concurrent cycles cannot both send.
            async with self._pool.connection() as connection, connection.transaction():
                row = await (
                    await connection.execute(
                        """
                        SELECT m.subject, m.body, u.email, u.username
                        FROM instructor_message_recipients r
                        JOIN instructor_messages m ON m.id = r.message_id
                        JOIN users u ON u.id = r.student_user_id
                        WHERE r.message_id = %s AND r.student_user_id = %s
                          AND m.status = 'sent' AND m.send_email
                          AND m.source_question_id IS NULL AND r.email_sent_at IS NULL
                          AND u.active AND u.role = 'student'
                        FOR UPDATE OF r SKIP LOCKED
                        """,
                        (recipient["message_id"], recipient["student_user_id"]),
                    )
                ).fetchone()
                if row is None:
                    continue
                recipient_email = instructor_message_delivery_address(
                    row["username"], row["email"], self._test_recipient
                )
                try:
                    sent = await self._mail.send_message(
                        OutboundMail(
                            to=(recipient_email,),
                            subject=row["subject"],
                            text=row["body"],
                        )
                    )
                except Exception as error:
                    # Persist only the error class, never provider text or addresses.
                    logger.warning("Instructor email delivery failed (%s)", type(error).__name__)
                    await connection.execute(
                        """
                        UPDATE instructor_message_recipients
                        SET email_attempts = email_attempts + 1, email_last_error = %s
                        WHERE message_id = %s AND student_user_id = %s
                        """,
                        (
                            type(error).__name__,
                            recipient["message_id"],
                            recipient["student_user_id"],
                        ),
                    )
                    continue
                await connection.execute(
                    """
                    UPDATE instructor_message_recipients
                    SET email_sent_at = now(), email_provider_message_id = %s,
                        email_attempts = email_attempts + 1, email_last_error = NULL
                    WHERE message_id = %s AND student_user_id = %s
                    """,
                    (
                        sent.provider_message_id,
                        recipient["message_id"],
                        recipient["student_user_id"],
                    ),
                )
