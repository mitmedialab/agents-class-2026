"""Provider-neutral records for private course-staff email escalation."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, StringConstraints

from course_server.auth.models import AwareDatetime

QuestionStatus = Literal[
    "pending_confirmation",
    "queued",
    "open",
    "answered",
    "closed",
]
ReporterVisibility = Literal["named", "anonymous"]
FaqReviewStatus = Literal[
    "pending_publication",
    "pending_delivery",
    "pending_review",
    "published",
    "declined",
]
PublicationDecision = Literal["publish", "private"]
NonBlank = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class MailModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class TAQuestion(MailModel):
    id: UUID
    public_question_code: Annotated[
        str,
        StringConstraints(pattern=r"^Q-[0-9]{4}-[0-9]{5}$"),
    ]
    student_user_id: UUID
    conversation_id: UUID
    subject: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    question_text: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=5_000),
    ]
    context_text: (
        Annotated[
            str,
            StringConstraints(strip_whitespace=True, min_length=1, max_length=5_000),
        ]
        | None
    ) = None
    reporter_visibility: ReporterVisibility = "named"
    status: QuestionStatus
    sent_event_id: UUID
    sent_event_recorded_at: AwareDatetime | None = None
    provider_message_id: str | None = None
    outbound_message_id: str | None = None
    created_at: AwareDatetime
    confirmed_at: AwareDatetime | None = None
    sent_at: AwareDatetime | None = None
    resolved_at: AwareDatetime | None = None


class TAAnswer(MailModel):
    id: UUID
    question_id: UUID
    event_id: UUID
    inbound_provider_message_id: NonBlank
    inbound_message_id: str | None = None
    responder_email: EmailStr
    answer_text: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=10_000),
    ]
    received_at: AwareDatetime
    event_recorded_at: AwareDatetime | None = None
    notification_provider_message_id: str | None = None
    notified_at: AwareDatetime | None = None


class FaqReviewCandidate(MailModel):
    id: UUID
    question_id: UUID
    answer_id: UUID
    suggested_question: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=5_000),
    ]
    suggested_answer: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=10_000),
    ]
    status: FaqReviewStatus
    review_provider_message_id: str | None = None
    review_outbound_message_id: str | None = None
    review_sent_at: AwareDatetime | None = None
    decision_inbound_provider_message_id: str | None = None
    reviewed_by_email: EmailStr | None = None
    reviewed_at: AwareDatetime | None = None
    published_faq_entry_id: UUID | None = None
    created_at: AwareDatetime


class OutboundMail(MailModel):
    to: tuple[EmailStr, ...] = Field(min_length=1, max_length=20)
    subject: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=998)]
    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50_000)]
    headers: dict[str, str] = Field(default_factory=dict)


class SentMail(MailModel):
    provider_message_id: NonBlank
    internet_message_id: NonBlank


class InboundMail(MailModel):
    provider_message_id: NonBlank
    internet_message_id: str | None = None
    sender: EmailStr
    subject: str = Field(max_length=998)
    text: str = Field(max_length=50_000)
    received_at: AwareDatetime
    headers: dict[str, str] = Field(default_factory=dict)


class MailAdapter(Protocol):
    """Replaceable provider boundary; no provider objects cross it."""

    async def send_message(self, message: OutboundMail) -> SentMail: ...

    async def reply_to_message(
        self,
        original: InboundMail,
        *,
        text: str,
        headers: dict[str, str] | None = None,
    ) -> SentMail: ...

    async def fetch_new_messages(self, *, since: datetime) -> list[InboundMail]: ...
