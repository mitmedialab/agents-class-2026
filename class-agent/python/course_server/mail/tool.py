"""Authenticated-student tool for preparing a staff escalation."""

from __future__ import annotations

from collections.abc import Mapping
from typing import ClassVar

from pydantic import JsonValue

from course_server.agent.capabilities import (
    ASK_TA_TOOL_ID as ASK_TA_TOOL_ID,
)
from course_server.agent.capabilities import (
    ToolEmittedEvent,
    ToolExecutionContext,
    ToolExecutionResult,
    ToolValidationError,
)

from .service import TAQuestionAccessDenied, TAQuestionService, TAQuestionStateError


class CourseAskTATool:
    """Prepare, but never directly send, a student-authored staff question."""

    id = ASK_TA_TOOL_ID
    description = (
        "Prepare a concise question for course staff only when official course sources and "
        "appropriate public research cannot answer it. The platform will show the authenticated "
        "student the substance of the question and require a separate Send confirmation before "
        "email is sent. Write question as content only, without an email greeting, sign-off, or "
        "transport metadata; the platform owns the email formatting."
    )
    redact_arguments_in_events = True
    input_schema: ClassVar[dict[str, JsonValue]] = {
        "type": "object",
        "properties": {
            "subject": {
                "type": "string",
                "minLength": 1,
                "maxLength": 200,
                "description": "Internal staff email subject; not part of the student preview.",
            },
            "question": {
                "type": "string",
                "minLength": 1,
                "maxLength": 5_000,
                "description": (
                    "Concise content-only question reflecting the details agreed with the student; "
                    "do not add a greeting, sign-off, student identity, or email formatting."
                ),
            },
            "context": {
                "type": "string",
                "minLength": 1,
                "maxLength": 5_000,
                "description": "Only additional context necessary to answer the question.",
            },
        },
        "required": ["subject", "question"],
        "additionalProperties": False,
    }

    def __init__(self, service: TAQuestionService) -> None:
        self._service = service

    async def execute(
        self,
        arguments: Mapping[str, JsonValue],
        context: ToolExecutionContext,
    ) -> ToolExecutionResult:
        allowed = {"subject", "question", "context"}
        if not set(arguments) <= allowed or not {"subject", "question"} <= set(arguments):
            raise ToolValidationError("subject and question are required; context is optional")
        subject = arguments.get("subject")
        question_text = arguments.get("question")
        raw_context = arguments.get("context")
        if not isinstance(subject, str) or not subject.strip() or len(subject.strip()) > 200:
            raise ToolValidationError("subject must be 1 to 200 characters")
        if (
            not isinstance(question_text, str)
            or not question_text.strip()
            or len(question_text.strip()) > 5_000
        ):
            raise ToolValidationError("question must be 1 to 5000 characters")
        if raw_context is not None and (
            not isinstance(raw_context, str)
            or not raw_context.strip()
            or len(raw_context.strip()) > 5_000
        ):
            raise ToolValidationError("context must be 1 to 5000 characters when supplied")
        try:
            question = await self._service.prepare(
                principal=context.principal,
                conversation_id=context.conversation_id,
                subject=subject.strip(),
                question=question_text.strip(),
                context=raw_context.strip() if isinstance(raw_context, str) else None,
            )
        except TAQuestionAccessDenied as error:
            raise ToolValidationError(
                "A current student login is required to email course staff."
            ) from error
        except TAQuestionStateError as error:
            raise ToolValidationError(
                "This conversation already has a staff question awaiting Send or Cancel."
            ) from error
        payload: dict[str, JsonValue] = {
            "question_id": str(question.id),
            "question_code": question.public_question_code,
            "subject": question.subject,
            "question": question.question_text,
            "status": "pending_confirmation",
        }
        if question.context_text is not None:
            payload["context"] = question.context_text
        return ToolExecutionResult(
            content={
                "question_code": question.public_question_code,
                "confirmation_required": True,
                "message": "The student must use the platform Send control before email is sent.",
            },
            summary="Prepared a staff question awaiting student confirmation.",
            storage_policy="server_summary",
            emitted_events=[
                ToolEmittedEvent(
                    type="email.ta_question.confirmation_requested",
                    payload=payload,
                    metadata={"visibility": "private"},
                )
            ],
        )
