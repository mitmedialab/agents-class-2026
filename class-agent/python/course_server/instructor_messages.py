"""Instructor-authored in-app messages with explicit send confirmation."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated, Any, ClassVar, Literal, Protocol
from uuid import UUID, uuid4

from psycopg import errors
from psycopg_pool import AsyncConnectionPool
from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    StringConstraints,
    ValidationError,
    model_validator,
)

from agent_core import PrincipalContext
from course_server.agent.capabilities import (
    INSTRUCTOR_MESSAGE_STUDENTS_TOOL_ID,
    ToolEmittedEvent,
    ToolExecutionContext,
    ToolExecutionResult,
    ToolValidationError,
)
from course_server.auth.models import User
from course_server.auth.store import AuthStore
from course_server.mail.models import PublicationDecision
from course_server.mail.service import parse_staff_answer_reply
from course_server.mail.store import TAQuestionStore

MessageAudience = Literal["all_students", "specific_students"]
MessageStatus = Literal["pending_confirmation", "sent", "cancelled"]
PENDING_QUESTION_RECIPIENT_PREFIX = "pending-question:"
StudentIdentifier = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=200),
]
MessageSubject = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=200),
]
MessageBody = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=10_000),
]


def _clock() -> datetime:
    return datetime.now(UTC)


class InstructorMessageModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class InstructorMessageDraft(InstructorMessageModel):
    audience: MessageAudience
    recipients: list[StudentIdentifier] = Field(default_factory=list, max_length=100)
    subject: MessageSubject
    message: MessageBody

    @model_validator(mode="after")
    def validate_audience(self) -> InstructorMessageDraft:
        if self.audience == "all_students" and self.recipients:
            raise ValueError("recipients must be empty when audience is all_students")
        if self.audience == "specific_students" and not self.recipients:
            raise ValueError("at least one recipient is required for specific_students")
        return self


class InstructorMessageContent(InstructorMessageModel):
    subject: MessageSubject
    message: MessageBody
    publication_decision: PublicationDecision | None = None


class InstructorMessage(InstructorMessageModel):
    id: UUID
    conversation_id: UUID
    sender_user_id: UUID
    audience: MessageAudience
    subject: MessageSubject
    message: MessageBody
    source_question_id: UUID | None = None
    status: MessageStatus
    created_at: AwareDatetime
    sent_at: AwareDatetime | None = None
    cancelled_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def validate_status_timestamps(self) -> InstructorMessage:
        if (self.status == "sent") != (self.sent_at is not None):
            raise ValueError("sent messages require exactly one sent timestamp")
        if (self.status == "cancelled") != (self.cancelled_at is not None):
            raise ValueError("cancelled messages require exactly one cancellation timestamp")
        if self.source_question_id is not None and self.audience != "specific_students":
            raise ValueError("question replies require a specific student audience")
        return self


@dataclass(frozen=True)
class StoredInstructorMessage:
    message: InstructorMessage
    recipient_user_ids: tuple[UUID, ...]


@dataclass(frozen=True)
class PreparedInstructorMessage:
    message: InstructorMessage
    recipients: tuple[User, ...]
    recipient_previews: tuple[InstructorMessageRecipientPreview, ...]


class InstructorMessageRecipientPreview(InstructorMessageModel):
    username: str
    display_name: str


@dataclass(frozen=True)
class ResolvedInstructorMessageRecipients:
    users: tuple[User, ...]
    previews: tuple[InstructorMessageRecipientPreview, ...]
    source_question_id: UUID | None = None


class InstructorMessageStoreError(RuntimeError):
    """The durable instructor-message state is invalid or unavailable."""


class InstructorMessageStore(Protocol):
    async def create(
        self,
        message: InstructorMessage,
        *,
        recipient_user_ids: tuple[UUID, ...],
    ) -> None: ...

    async def get(self, message_id: UUID) -> StoredInstructorMessage | None: ...

    async def transition(
        self,
        message_id: UUID,
        *,
        expected: Literal["pending_confirmation"],
        status: Literal["sent", "cancelled"],
        changed_at: datetime,
        content: InstructorMessageContent | None = None,
    ) -> InstructorMessage | None: ...

    async def list_sent_for_student(self, student_user_id: UUID) -> list[InstructorMessage]: ...


class InMemoryInstructorMessageStore:
    def __init__(self) -> None:
        self.messages: dict[UUID, StoredInstructorMessage] = {}

    async def create(
        self,
        message: InstructorMessage,
        *,
        recipient_user_ids: tuple[UUID, ...],
    ) -> None:
        if any(
            stored.message.conversation_id == message.conversation_id
            and stored.message.status == "pending_confirmation"
            for stored in self.messages.values()
        ):
            raise InstructorMessageStoreError(
                "this conversation already has a message awaiting Send or Cancel"
            )
        if message.source_question_id is not None and any(
            stored.message.source_question_id == message.source_question_id
            and stored.message.status in {"pending_confirmation", "sent"}
            for stored in self.messages.values()
        ):
            raise InstructorMessageStoreError(
                "this student question already has a prepared or sent response"
            )
        self.messages[message.id] = StoredInstructorMessage(
            message=message,
            recipient_user_ids=recipient_user_ids,
        )

    async def get(self, message_id: UUID) -> StoredInstructorMessage | None:
        return self.messages.get(message_id)

    async def transition(
        self,
        message_id: UUID,
        *,
        expected: Literal["pending_confirmation"],
        status: Literal["sent", "cancelled"],
        changed_at: datetime,
        content: InstructorMessageContent | None = None,
    ) -> InstructorMessage | None:
        stored = self.messages.get(message_id)
        if stored is None or stored.message.status != expected:
            return None
        updated = stored.message.model_copy(
            update={
                "status": status,
                "sent_at": changed_at if status == "sent" else None,
                "cancelled_at": changed_at if status == "cancelled" else None,
                **(
                    {"subject": content.subject, "message": content.message}
                    if content is not None
                    else {}
                ),
            }
        )
        self.messages[message_id] = StoredInstructorMessage(
            message=updated,
            recipient_user_ids=stored.recipient_user_ids,
        )
        return updated

    async def list_sent_for_student(self, student_user_id: UUID) -> list[InstructorMessage]:
        return sorted(
            (
                stored.message
                for stored in self.messages.values()
                if stored.message.status == "sent"
                and student_user_id in stored.recipient_user_ids
                and stored.message.source_question_id is None
            ),
            key=lambda message: (message.sent_at or message.created_at, message.id),
            reverse=True,
        )


class PostgresInstructorMessageStore:
    """PostgreSQL adapter for pending messages and their fixed recipient snapshots."""

    def __init__(self, pool: AsyncConnectionPool[Any]) -> None:
        self._pool = pool

    async def create(
        self,
        message: InstructorMessage,
        *,
        recipient_user_ids: tuple[UUID, ...],
    ) -> None:
        try:
            async with self._pool.connection() as connection, connection.transaction():
                await connection.execute(
                    """
                    INSERT INTO instructor_messages (
                        id, conversation_id, sender_user_id, audience, subject, body,
                        source_question_id, status, created_at, sent_at, cancelled_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        message.id,
                        message.conversation_id,
                        message.sender_user_id,
                        message.audience,
                        message.subject,
                        message.message,
                        message.source_question_id,
                        message.status,
                        message.created_at,
                        message.sent_at,
                        message.cancelled_at,
                    ),
                )
                async with connection.cursor() as cursor:
                    await cursor.executemany(
                        """
                        INSERT INTO instructor_message_recipients (message_id, student_user_id)
                        VALUES (%s, %s)
                        """,
                        [(message.id, user_id) for user_id in recipient_user_ids],
                    )
        except errors.UniqueViolation as error:
            raise InstructorMessageStoreError(
                "this conversation already has a message awaiting Send or Cancel"
            ) from error

    async def get(self, message_id: UUID) -> StoredInstructorMessage | None:
        async with self._pool.connection() as connection:
            row = await (
                await connection.execute(
                    """
                    SELECT id, conversation_id, sender_user_id, audience, subject,
                           body AS message, source_question_id, status, created_at, sent_at,
                           cancelled_at
                    FROM instructor_messages WHERE id = %s
                    """,
                    (message_id,),
                )
            ).fetchone()
            if row is None:
                return None
            recipients = await (
                await connection.execute(
                    """
                    SELECT student_user_id FROM instructor_message_recipients
                    WHERE message_id = %s ORDER BY student_user_id
                    """,
                    (message_id,),
                )
            ).fetchall()
        return StoredInstructorMessage(
            message=InstructorMessage.model_validate(row),
            recipient_user_ids=tuple(UUID(str(item["student_user_id"])) for item in recipients),
        )

    async def transition(
        self,
        message_id: UUID,
        *,
        expected: Literal["pending_confirmation"],
        status: Literal["sent", "cancelled"],
        changed_at: datetime,
        content: InstructorMessageContent | None = None,
    ) -> InstructorMessage | None:
        async with self._pool.connection() as connection:
            row = await (
                await connection.execute(
                    """
                    UPDATE instructor_messages
                    SET status = %s,
                        sent_at = CASE WHEN %s = 'sent' THEN %s ELSE NULL END,
                        cancelled_at = CASE WHEN %s = 'cancelled' THEN %s ELSE NULL END,
                        subject = CASE WHEN %s THEN %s ELSE subject END,
                        body = CASE WHEN %s THEN %s ELSE body END
                    WHERE id = %s AND status = %s
                    RETURNING id, conversation_id, sender_user_id, audience, subject,
                              body AS message, source_question_id, status, created_at, sent_at,
                              cancelled_at
                    """,
                    (
                        status,
                        status,
                        changed_at,
                        status,
                        changed_at,
                        content is not None,
                        content.subject if content is not None else None,
                        content is not None,
                        content.message if content is not None else None,
                        message_id,
                        expected,
                    ),
                )
            ).fetchone()
        return InstructorMessage.model_validate(row) if row is not None else None

    async def list_sent_for_student(self, student_user_id: UUID) -> list[InstructorMessage]:
        async with self._pool.connection() as connection:
            rows = await (
                await connection.execute(
                    """
                    SELECT m.id, m.conversation_id, m.sender_user_id, m.audience, m.subject,
                           m.body AS message, m.source_question_id, m.status, m.created_at,
                           m.sent_at, m.cancelled_at
                    FROM instructor_messages AS m
                    JOIN instructor_message_recipients AS r ON r.message_id = m.id
                    WHERE r.student_user_id = %s AND m.status = 'sent'
                      AND m.source_question_id IS NULL
                    ORDER BY m.sent_at DESC, m.id
                    """,
                    (student_user_id,),
                )
            ).fetchall()
        return [InstructorMessage.model_validate(row) for row in rows]


class InstructorMessageAccessDenied(RuntimeError):
    """Only the current active instructor may manage an instructor message."""


class InstructorMessageStateError(RuntimeError):
    """The message is missing, foreign, or no longer awaiting confirmation."""


class InstructorMessageRecipientError(ValueError):
    """One or more requested student recipients cannot be resolved safely."""


class InstructorMessageService:
    def __init__(
        self,
        *,
        messages: InstructorMessageStore,
        auth: AuthStore,
        questions: TAQuestionStore | None = None,
        clock: Callable[[], datetime] = _clock,
    ) -> None:
        self._messages = messages
        self._auth = auth
        self._questions = questions
        self._clock = clock

    async def prepare(
        self,
        *,
        principal: PrincipalContext,
        conversation_id: UUID,
        draft: InstructorMessageDraft,
    ) -> PreparedInstructorMessage:
        instructor = await self._active_instructor(principal)
        resolved_recipients = await self._resolve_recipients(draft)
        recipients = resolved_recipients.users
        message_body = draft.message.strip()
        if resolved_recipients.source_question_id is not None:
            publication, answer = _online_reply_content(message_body)
            message_body = f"{publication.upper()}\n\n{answer}"
        message = InstructorMessage(
            id=uuid4(),
            conversation_id=conversation_id,
            sender_user_id=instructor.id,
            audience=draft.audience,
            subject=draft.subject.strip(),
            message=message_body,
            source_question_id=resolved_recipients.source_question_id,
            status="pending_confirmation",
            created_at=self._clock(),
        )
        try:
            await self._messages.create(
                message,
                recipient_user_ids=tuple(recipient.id for recipient in recipients),
            )
        except InstructorMessageStoreError as error:
            raise InstructorMessageStateError(str(error)) from error
        return PreparedInstructorMessage(
            message=message,
            recipients=recipients,
            recipient_previews=resolved_recipients.previews,
        )

    async def confirm(
        self,
        *,
        principal: PrincipalContext,
        conversation_id: UUID,
        message_id: UUID,
        content: InstructorMessageContent | None = None,
    ) -> StoredInstructorMessage:
        return await self._transition(
            principal=principal,
            conversation_id=conversation_id,
            message_id=message_id,
            status="sent",
            content=content,
        )

    async def cancel(
        self,
        *,
        principal: PrincipalContext,
        conversation_id: UUID,
        message_id: UUID,
    ) -> StoredInstructorMessage:
        return await self._transition(
            principal=principal,
            conversation_id=conversation_id,
            message_id=message_id,
            status="cancelled",
        )

    async def _transition(
        self,
        *,
        principal: PrincipalContext,
        conversation_id: UUID,
        message_id: UUID,
        status: Literal["sent", "cancelled"],
        content: InstructorMessageContent | None = None,
    ) -> StoredInstructorMessage:
        instructor = await self._active_instructor(principal)
        stored = await self._messages.get(message_id)
        if (
            stored is None
            or stored.message.conversation_id != conversation_id
            or stored.message.sender_user_id != instructor.id
            or stored.message.status != "pending_confirmation"
        ):
            raise InstructorMessageStateError("message is no longer awaiting confirmation")
        if status == "sent" and stored.message.source_question_id is not None:
            if self._questions is None:
                raise InstructorMessageStateError("question replies are not available")
            reply_content = content or InstructorMessageContent(
                subject=stored.message.subject,
                message=stored.message.message,
            )
            publication, answer_text = _online_reply_content(
                reply_content.message,
                publication=reply_content.publication_decision,
            )
            question = await self._questions.get_question(stored.message.source_question_id)
            if question is None:
                raise InstructorMessageStateError("student question is no longer available")
            answer = await self._questions.record_online_answer(
                question,
                instructor_message_id=stored.message.id,
                responder_email=str(instructor.email),
                answer_text=answer_text,
                publication=publication,
                processed_at=self._clock(),
            )
            if answer is None:
                raise InstructorMessageStateError(
                    "student question has already been answered elsewhere"
                )
            content = InstructorMessageContent(
                subject=reply_content.subject,
                message=answer.answer_text,
            )
        elif status == "sent" and content is not None and content.publication_decision is not None:
            raise InstructorMessageStateError(
                "publication decisions apply only to pending-question replies"
            )
        updated = await self._messages.transition(
            message_id,
            expected="pending_confirmation",
            status=status,
            changed_at=self._clock(),
            content=content,
        )
        if updated is None:
            raise InstructorMessageStateError("message is no longer awaiting confirmation")
        return StoredInstructorMessage(
            message=updated,
            recipient_user_ids=stored.recipient_user_ids,
        )

    async def _active_instructor(self, principal: PrincipalContext) -> User:
        if (
            not principal.authenticated
            or principal.user_id is None
            or "instructor" not in principal.roles
        ):
            raise InstructorMessageAccessDenied("instructor login required")
        user = await self._auth.get_user_by_id(principal.user_id)
        if user is None or not user.active or user.role != "instructor":
            raise InstructorMessageAccessDenied("instructor login required")
        return user.public()

    async def _resolve_recipients(
        self,
        draft: InstructorMessageDraft,
    ) -> ResolvedInstructorMessageRecipients:
        students = [
            user.public()
            for user in await self._auth.list_users()
            if user.active and user.role == "student"
        ]
        if draft.audience == "all_students":
            recipients = {user.id: user for user in students}
            previews = {
                user.id: InstructorMessageRecipientPreview(
                    username=user.username,
                    display_name=user.display_name,
                )
                for user in students
            }
            source_question_id = None
        else:
            question_references = [
                identifier
                for identifier in draft.recipients
                if identifier.startswith(PENDING_QUESTION_RECIPIENT_PREFIX)
            ]
            if question_references and len(draft.recipients) != 1:
                raise InstructorMessageRecipientError(
                    "A pending-question reply reference must be the only recipient."
                )
            recipients = {}
            previews = {}
            source_question_id = None
            for identifier in draft.recipients:
                if identifier.startswith(PENDING_QUESTION_RECIPIENT_PREFIX):
                    (
                        recipient,
                        preview,
                        source_question_id,
                    ) = await self._resolve_pending_question_recipient(
                        identifier,
                        students,
                    )
                    recipients[recipient.id] = recipient
                    previews[recipient.id] = preview
                    continue
                normalized = identifier.casefold()
                matches = {
                    user.id: user
                    for user in students
                    if normalized
                    in {
                        user.username.casefold(),
                        str(user.email).casefold(),
                        user.display_name.casefold(),
                    }
                }
                if not matches:
                    raise InstructorMessageRecipientError(
                        f"No active student matches recipient {identifier!r}."
                    )
                if len(matches) > 1:
                    raise InstructorMessageRecipientError(
                        f"Recipient {identifier!r} is ambiguous; use a username or email."
                    )
                recipient = next(iter(matches.values()))
                recipients[recipient.id] = recipient
                previews[recipient.id] = InstructorMessageRecipientPreview(
                    username=recipient.username,
                    display_name=recipient.display_name,
                )
        if not recipients:
            raise InstructorMessageRecipientError("No active student recipients were found.")
        ordered = tuple(sorted(recipients.values(), key=lambda user: user.username))
        return ResolvedInstructorMessageRecipients(
            users=ordered,
            previews=tuple(previews[user.id] for user in ordered),
            source_question_id=source_question_id,
        )

    async def _resolve_pending_question_recipient(
        self,
        reference: str,
        students: list[User],
    ) -> tuple[User, InstructorMessageRecipientPreview, UUID]:
        if self._questions is None:
            raise InstructorMessageRecipientError(
                "Pending student question replies are not available."
            )
        try:
            question_id = UUID(reference.removeprefix(PENDING_QUESTION_RECIPIENT_PREFIX))
        except ValueError as error:
            raise InstructorMessageRecipientError(
                "The pending student question reply reference is invalid."
            ) from error
        question = await self._questions.get_question(question_id)
        if question is None or question.status not in {"queued", "open"}:
            raise InstructorMessageRecipientError(
                "The pending student question no longer needs a response."
            )
        recipient = next(
            (student for student in students if student.id == question.student_user_id),
            None,
        )
        if recipient is None:
            raise InstructorMessageRecipientError(
                "The pending student question has no active student recipient."
            )
        if question.reporter_visibility == "anonymous":
            preview = InstructorMessageRecipientPreview(
                username="anonymous",
                display_name="Anonymous student",
            )
        else:
            preview = InstructorMessageRecipientPreview(
                username=recipient.username,
                display_name=recipient.display_name,
            )
        return recipient, preview, question.id


def _online_reply_content(
    message: str,
    *,
    publication: PublicationDecision | None = None,
) -> tuple[PublicationDecision, str]:
    parsed = parse_staff_answer_reply(message)
    if parsed is not None:
        if publication is not None and publication != parsed.action:
            raise InstructorMessageStateError(
                "The selected visibility conflicts with the message command."
            )
        return parsed.action, parsed.answer
    command_lines = {
        line.strip().casefold()
        for line in message.splitlines()
        if line.strip().casefold() in {"publish", "public", "private"}
    }
    if command_lines:
        raise InstructorMessageStateError(
            "Use one PUBLIC, PUBLISH, or PRIVATE line before or after a non-empty response."
        )
    return publication or "private", message.strip()


class InstructorMessageStudentsTool:
    """Prepare a fixed in-app recipient snapshot for separate platform confirmation."""

    id = INSTRUCTOR_MESSAGE_STUDENTS_TOOL_ID
    description = (
        "Prepare an in-app message to all active students or specific active students. The "
        "platform displays the exact message and resolved recipients and requires the instructor "
        "to press Send before students receive it. Use recipients=[] for all_students; for "
        "specific_students use student usernames, emails, exact display names, or the trusted "
        "reply_reference supplied with a pending student question. Pending-question replies use "
        "a PUBLISH or PRIVATE line; an omitted decision is safely prepared as PRIVATE."
    )
    redact_arguments_in_events = True
    input_schema: ClassVar[dict[str, JsonValue]] = {
        "type": "object",
        "properties": {
            "audience": {
                "type": "string",
                "enum": ["all_students", "specific_students"],
            },
            "recipients": {
                "type": "array",
                "items": {"type": "string", "minLength": 1, "maxLength": 200},
                "maxItems": 100,
                "description": (
                    "Empty for all_students; otherwise student usernames, emails, or exact "
                    "display names. When replying to a pending question, use its trusted "
                    "reply_reference as the sole recipient."
                ),
            },
            "subject": {"type": "string", "minLength": 1, "maxLength": 200},
            "message": {"type": "string", "minLength": 1, "maxLength": 10_000},
        },
        "required": ["audience", "recipients", "subject", "message"],
        "additionalProperties": False,
    }

    def __init__(self, service: InstructorMessageService) -> None:
        self._service = service

    async def execute(
        self,
        arguments: Mapping[str, JsonValue],
        context: ToolExecutionContext,
    ) -> ToolExecutionResult:
        try:
            draft = InstructorMessageDraft.model_validate(arguments)
            prepared = await self._service.prepare(
                principal=context.principal,
                conversation_id=context.conversation_id,
                draft=draft,
            )
        except ValidationError as error:
            invalid = [str(item["loc"][0]) for item in error.errors() if item["loc"]]
            detail = ", ".join(dict.fromkeys(invalid)) or "message fields"
            raise ToolValidationError(f"Invalid instructor message: {detail}.") from error
        except InstructorMessageAccessDenied as error:
            raise ToolValidationError("A current instructor login is required.") from error
        except (InstructorMessageRecipientError, InstructorMessageStateError) as error:
            raise ToolValidationError(str(error)) from error

        message = prepared.message
        confirmation_message = message.message
        reply_fields: dict[str, JsonValue] = {}
        if message.source_question_id is not None:
            publication, confirmation_message = _online_reply_content(message.message)
            reply_fields = {
                "source_question_id": str(message.source_question_id),
                "publication_decision": publication,
            }
        recipient_preview: list[JsonValue] = [
            preview.model_dump(mode="json") for preview in prepared.recipient_previews
        ]
        return ToolExecutionResult(
            content={
                "message_id": str(message.id),
                "recipient_count": len(prepared.recipients),
                "confirmation_required": True,
                "message": "The instructor must use the platform Send control before delivery.",
            },
            summary="Prepared an instructor message awaiting confirmation.",
            storage_policy="server_summary",
            emitted_events=[
                ToolEmittedEvent(
                    type="instructor.message.confirmation_requested",
                    payload={
                        "message_id": str(message.id),
                        "audience": message.audience,
                        "recipients": recipient_preview,
                        "recipient_count": len(prepared.recipients),
                        "subject": message.subject,
                        "message": confirmation_message,
                        "status": message.status,
                        **reply_fields,
                    },
                    metadata={"visibility": "private"},
                )
            ],
        )
