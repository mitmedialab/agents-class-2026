"""Student-owned read access to private course-staff communications."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import ClassVar, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, JsonValue

from agent_core import PrincipalContext
from course_server.agent.capabilities import (
    LIST_MY_COMMUNICATIONS_TOOL_ID,
    READ_MY_COMMUNICATION_TOOL_ID,
    ToolExecutionContext,
    ToolExecutionResult,
)
from course_server.auth.models import User
from course_server.auth.store import AuthStore
from course_server.instructor_messages import InstructorMessageStore
from course_server.mail import TAQuestionStore, parse_staff_answer_reply

CommunicationKind = Literal["staff_question", "instructor_message"]
CommunicationState = Literal["pending", "answered", "received"]

_DEFAULT_LIST_LIMIT = 10
_MAX_LIST_LIMIT = 25


class StudentCommunication(BaseModel):
    """One private communication visible only to its owning student."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID
    kind: CommunicationKind
    state: CommunicationState
    subject: str = Field(min_length=1, max_length=500)
    question: str | None = Field(default=None, min_length=1, max_length=5_000)
    answer: str | None = Field(default=None, min_length=1, max_length=10_000)
    message: str | None = Field(default=None, min_length=1, max_length=10_000)
    reporter_visibility: Literal["named", "anonymous"] | None = None
    publication_decision: Literal["publish", "private"] | None = None
    sender_first_name: str | None = Field(default=None, min_length=1, max_length=200)
    created_at: AwareDatetime
    responded_at: AwareDatetime | None = None


class StudentCommunicationAccessDenied(PermissionError):
    """The current principal is not the active student who owns the data."""


class StudentCommunicationNotFound(LookupError):
    """No owned communication has the requested opaque identifier."""


class StudentCommunicationService:
    """Project private question threads and instructor messages for one student."""

    def __init__(
        self,
        *,
        auth: AuthStore,
        questions: TAQuestionStore,
        instructor_messages: InstructorMessageStore,
    ) -> None:
        self._auth = auth
        self._questions = questions
        self._instructor_messages = instructor_messages

    async def list_mine(self, principal: PrincipalContext) -> list[StudentCommunication]:
        student_user_id = await self._student_user_id(principal)
        communications: list[StudentCommunication] = []

        for thread in await self._questions.list_student_threads(
            student_user_id=student_user_id,
            limit=None,
        ):
            answer = thread.answer
            communications.append(
                StudentCommunication(
                    id=thread.question.id,
                    kind="staff_question",
                    state="answered" if answer is not None else "pending",
                    subject=thread.question.subject,
                    question=thread.question.question_text,
                    answer=(
                        _student_facing_answer_text(answer.answer_text)
                        if answer is not None
                        else None
                    ),
                    reporter_visibility=thread.question.reporter_visibility,
                    publication_decision=(
                        answer.publication_decision if answer is not None else None
                    ),
                    sender_first_name=(
                        await self._sender_first_name_by_email(str(answer.responder_email))
                        if answer is not None
                        else None
                    ),
                    created_at=thread.question.created_at,
                    responded_at=answer.received_at if answer is not None else None,
                )
            )

        for message in await self._instructor_messages.list_sent_for_student(student_user_id):
            communications.append(
                StudentCommunication(
                    id=message.id,
                    kind="instructor_message",
                    state="received",
                    subject=message.subject,
                    message=message.message,
                    sender_first_name=await self._sender_first_name_by_id(message.sender_user_id),
                    created_at=message.sent_at or message.created_at,
                )
            )

        return sorted(communications, key=_communication_sort_key, reverse=True)

    async def get_mine(
        self,
        principal: PrincipalContext,
        communication_id: UUID,
    ) -> StudentCommunication:
        communication = next(
            (item for item in await self.list_mine(principal) if item.id == communication_id),
            None,
        )
        if communication is None:
            raise StudentCommunicationNotFound("communication not found for current student")
        return communication

    async def _student_user_id(self, principal: PrincipalContext) -> UUID:
        if (
            not principal.authenticated
            or principal.user_id is None
            or "student" not in principal.roles
        ):
            raise StudentCommunicationAccessDenied("active student login required")
        user = await self._auth.get_user_by_id(principal.user_id)
        if user is None or not user.active or user.role != "student":
            raise StudentCommunicationAccessDenied("active student login required")
        return user.id

    async def _sender_first_name_by_email(self, email: str) -> str | None:
        user = await self._auth.get_user_by_email(email)
        return _staff_first_name(user)

    async def _sender_first_name_by_id(self, user_id: UUID) -> str | None:
        user = await self._auth.get_user_by_id(user_id)
        return _staff_first_name(user)


class CourseListMyCommunicationsTool:
    """List bounded summaries of the current student's private communication history."""

    id = LIST_MY_COMMUNICATIONS_TOOL_ID
    description = (
        "List the logged-in student's own private Q&A and communication history with course "
        "staff, including questions submitted anonymously to staff and instructor messages. "
        "Use course.read_my_communication for the complete selected thread."
    )
    input_schema: ClassVar[dict[str, JsonValue]] = {
        "type": "object",
        "properties": {
            "limit": {
                "type": "integer",
                "minimum": 1,
                "maximum": _MAX_LIST_LIMIT,
                "description": "Maximum number of newest communications to return.",
            },
            "offset": {
                "type": "integer",
                "minimum": 0,
                "maximum": 10_000,
                "description": "Number of newer communications to skip for pagination.",
            },
        },
        "additionalProperties": False,
    }

    def __init__(self, communications: StudentCommunicationService) -> None:
        self._communications = communications

    async def execute(
        self,
        arguments: Mapping[str, JsonValue],
        context: ToolExecutionContext,
    ) -> ToolExecutionResult:
        if set(arguments) - {"limit", "offset"}:
            raise ValueError("unexpected tool arguments")
        limit = arguments.get("limit", _DEFAULT_LIST_LIMIT)
        if (
            not isinstance(limit, int)
            or isinstance(limit, bool)
            or not 1 <= limit <= _MAX_LIST_LIMIT
        ):
            raise ValueError(f"limit must be between 1 and {_MAX_LIST_LIMIT}")
        offset = arguments.get("offset", 0)
        if not isinstance(offset, int) or isinstance(offset, bool) or not 0 <= offset <= 10_000:
            raise ValueError("offset must be between 0 and 10000")
        all_communications = await self._communications.list_mine(context.principal)
        communications = all_communications[offset : offset + limit]
        next_offset = offset + len(communications)
        return ToolExecutionResult(
            content={
                "communications": [_communication_summary(item) for item in communications],
                "total": len(all_communications),
                "next_offset": (next_offset if next_offset < len(all_communications) else None),
            },
            summary=f"Listed {len(communications)} owned private staff communications.",
            storage_policy="server_summary",
        )


class CourseReadMyCommunicationTool:
    """Read one complete communication after rechecking student ownership."""

    id = READ_MY_COMMUNICATION_TOOL_ID
    description = (
        "Read one complete private Q&A thread or instructor message owned by the logged-in "
        "student, using an ID returned by course.list_my_communications."
    )
    input_schema: ClassVar[dict[str, JsonValue]] = {
        "type": "object",
        "properties": {
            "communication_id": {
                "type": "string",
                "format": "uuid",
                "description": "Opaque communication ID from course.list_my_communications.",
            }
        },
        "required": ["communication_id"],
        "additionalProperties": False,
    }

    def __init__(self, communications: StudentCommunicationService) -> None:
        self._communications = communications

    async def execute(
        self,
        arguments: Mapping[str, JsonValue],
        context: ToolExecutionContext,
    ) -> ToolExecutionResult:
        if set(arguments) != {"communication_id"}:
            raise ValueError("communication_id is required")
        raw_id = arguments.get("communication_id")
        if not isinstance(raw_id, str):
            raise ValueError("communication_id must be a UUID")
        try:
            communication_id = UUID(raw_id)
        except ValueError as error:
            raise ValueError("communication_id must be a UUID") from error
        communication = await self._communications.get_mine(
            context.principal,
            communication_id,
        )
        return ToolExecutionResult(
            content=communication.model_dump(mode="json", exclude_none=True),
            summary="Read one owned private staff communication.",
            storage_policy="server_summary",
        )


def _communication_summary(communication: StudentCommunication) -> dict[str, JsonValue]:
    preview = communication.answer or communication.message or communication.question or ""
    if len(preview) > 300:
        preview = preview[:297] + "..."
    timestamp: datetime = communication.responded_at or communication.created_at
    return {
        "communication_id": str(communication.id),
        "kind": communication.kind,
        "state": communication.state,
        "subject": communication.subject,
        "preview": preview,
        "timestamp": timestamp.isoformat(),
    }


def _communication_sort_key(communication: StudentCommunication) -> tuple[datetime, str]:
    return (communication.responded_at or communication.created_at, str(communication.id))


def _student_facing_answer_text(answer_text: str) -> str:
    decision = parse_staff_answer_reply(answer_text)
    return decision.answer if decision is not None else answer_text.strip()


def _staff_first_name(user: User | None) -> str | None:
    if user is None or user.role not in {"ta", "instructor", "admin"} or not user.active:
        return None
    return user.display_name.strip().split(maxsplit=1)[0]
