"""Portable course-staff email workflow and provider adapters."""

from .gmail import GoogleGmailMailAdapter
from .graph import MicrosoftGraphMailAdapter
from .models import (
    FaqReviewCandidate,
    InboundMail,
    MailAdapter,
    OutboundMail,
    ReporterVisibility,
    SentMail,
    TAAnswer,
    TAQuestion,
)
from .service import (
    MailWorker,
    TAQuestionAccessDenied,
    TAQuestionService,
    TAQuestionStateError,
    parse_faq_review_reply,
    parse_staff_answer_reply,
    sanitize_reply_text,
)
from .store import InMemoryTAQuestionStore, PostgresTAQuestionStore, TAQuestionStore
from .tool import ASK_TA_TOOL_ID, CourseAskTATool

__all__ = [
    "ASK_TA_TOOL_ID",
    "CourseAskTATool",
    "FaqReviewCandidate",
    "GoogleGmailMailAdapter",
    "InMemoryTAQuestionStore",
    "InboundMail",
    "MailAdapter",
    "MailWorker",
    "MicrosoftGraphMailAdapter",
    "OutboundMail",
    "PostgresTAQuestionStore",
    "ReporterVisibility",
    "SentMail",
    "TAAnswer",
    "TAQuestion",
    "TAQuestionAccessDenied",
    "TAQuestionService",
    "TAQuestionStateError",
    "TAQuestionStore",
    "parse_faq_review_reply",
    "parse_staff_answer_reply",
    "sanitize_reply_text",
]
