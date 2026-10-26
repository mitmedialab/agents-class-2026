"""Instructor-only Course Agent tools that run the newsletter pipeline.

The agent chooses when to call these; platform code checks the trusted principal, runs the
deterministic pipeline, and requires the instructor's separate Send action before delivery.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import ClassVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, ValidationError

from agent_core import PrincipalContext
from course_server.agent.capabilities import (
    ExecutableTool,
    ToolEmittedEvent,
    ToolExecutionContext,
    ToolExecutionResult,
    ToolValidationError,
)
from course_server.auth.store import AuthStore
from course_server.newsletter_tool_ids import (
    INSTRUCTOR_DRAFT_NEWSLETTER_TOOL_ID,
    INSTRUCTOR_NEWSLETTER_STATUS_TOOL_ID,
    INSTRUCTOR_SEND_NEWSLETTER_TOOL_ID,
)

from .jobs import NewsletterJobRunner
from .models import ISSUE_ID_PATTERN, NewsletterIssue, NewsletterJob, NewsletterSettings
from .render import render_text
from .service import NewsletterService, NewsletterStateError
from .store import FileNewsletterStore, NewsletterStoreError

NEWSLETTER_CONFIRMATION_EVENT = "instructor.newsletter.confirmation_requested"
# Per-run marker: once a running job has been reported in a turn, further polls are refused so
# the agent ends its turn instead of spinning until the step limit.
_POLLED_KEY = "newsletter_running_reported"
_WAIT_MESSAGE = (
    "The draft is still running and takes about five minutes in total. Do not check again in "
    "this turn: end your reply now and tell the instructor to ask for the status in a few minutes."
)
_PREVIEW_CHARS = 1_200
_SCOREBOARD_ROWS = 10


def _require_instructor(principal: PrincipalContext) -> UUID:
    if (
        not principal.authenticated
        or "instructor" not in principal.roles
        or principal.user_id is None
    ):
        raise ToolValidationError("A current instructor login is required.")
    return principal.user_id


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class DraftArguments(_Strict):
    week: int | None = Field(default=None, ge=1, le=52)
    force: bool = False


class StatusArguments(_Strict):
    job_id: str | None = Field(default=None, min_length=36, max_length=36)
    issue_id: str | None = Field(default=None, pattern=ISSUE_ID_PATTERN)


class SendArguments(_Strict):
    issue_id: str = Field(pattern=ISSUE_ID_PATTERN)
    audience: str = Field(pattern=r"^(all_students|test)$")
    test_recipients: list[str] = Field(default_factory=list, max_length=5)


def job_summary(job: NewsletterJob) -> dict[str, JsonValue]:
    return {
        "job_id": str(job.job_id),
        "status": job.status,
        "week": job.week_number,
        "issue_id": job.issue_id,
        "error": job.error,
        "started_at": job.started_at.isoformat(),
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
        "recent_log": list(job.log[-8:]),
    }


def _label(issue: NewsletterIssue, project_id: str) -> str:
    link = issue.link_for(project_id)
    return link.label if link else project_id


def issue_summary(issue: NewsletterIssue, store: FileNewsletterStore) -> dict[str, JsonValue]:
    """What the agent needs to present a draft: copy, selection, reasons, and file paths."""

    _, text_path, html_path = store.paths_for(issue.issue_id)
    pdf_path = store.pdf_path(issue.issue_id)
    highlights: list[JsonValue] = []
    for index, highlight in enumerate(issue.body.highlights, start=1):
        link = issue.link_for(highlight.project_id)
        highlights.append(
            {
                "position": index,
                "student": link.label if link else highlight.project_id,
                "headline": highlight.headline,
                "description": highlight.description,
                "site_url": issue.open_url(highlight.project_id),
                "has_image": issue.image_for(highlight.project_id) is not None,
            }
        )
    scoreboard: list[JsonValue] = [
        {
            "project": score.project_id,
            "total": score.total,
            "originality": score.originality,
            "goal_fit": score.goal_fit,
            "augmentation": score.augmentation,
            "execution": score.execution,
            "blank": score.blank,
            "eligible": score.eligible,
            "rationale": score.rationale,
        }
        for score in issue.scores[:_SCOREBOARD_ROWS]
    ]
    return {
        "issue_id": issue.issue_id,
        "status": issue.status,
        "week": issue.week.number,
        "assignment": issue.week.tutorial,
        "subject": issue.subject,
        "headline": issue.body.headline,
        "editorial": issue.body.editorial,
        "who_to_ask": [
            {
                "question": entry.question,
                "students": [_label(issue, project_id) for project_id in entry.project_ids],
            }
            for entry in issue.body.ask_around
        ],
        "highlights": highlights,
        "other_builds": len(issue.other_projects()),
        "build_groups": [
            {"heading": heading, "students": [link.label for link in links]}
            for heading, links in issue.grouped_other_projects()
        ],
        "quote": {
            "text": issue.quote.text,
            "author": issue.quote.author,
            "kind": issue.quote.kind,
        },
        "scoreboard_top": scoreboard,
        "files": {
            "html": str(html_path),
            "pdf": str(pdf_path) if pdf_path.is_file() else None,
            "text": str(text_path),
        },
        "plain_text": render_text(issue)[:6_000],
    }


@dataclass(frozen=True)
class NewsletterTools:
    """Everything the three tools share; built once by the application."""

    settings: NewsletterSettings
    store: FileNewsletterStore
    service: NewsletterService
    runner: NewsletterJobRunner
    auth: AuthStore

    def tools(self) -> list[ExecutableTool]:
        return [
            InstructorDraftNewsletterTool(self),
            InstructorNewsletterStatusTool(self),
            InstructorSendNewsletterTool(self),
        ]


class InstructorDraftNewsletterTool:
    id = INSTRUCTOR_DRAFT_NEWSLETTER_TOOL_ID
    description = (
        "Start drafting the weekly class newsletter, The Class Runtime, for the most recently "
        "finished class week (or a given week). Platform code reads every student repository "
        "and site, scores each build against the week's assignment, selects the highlights, "
        "captures images, and writes the copy; this takes about five minutes and runs in the "
        "background. Returns a job id: use instructor.newsletter_status to check on it. Nothing "
        "is emailed by this tool."
    )
    input_schema: ClassVar[dict[str, JsonValue]] = {
        "type": "object",
        "properties": {
            "week": {
                "type": "integer",
                "minimum": 1,
                "maximum": 52,
                "description": "Schedule week number; omit for the last finished week.",
            },
            "force": {
                "type": "boolean",
                "description": "Redraft a week whose issue was already sent.",
            },
        },
        "additionalProperties": False,
    }

    def __init__(self, shared: NewsletterTools) -> None:
        self._shared = shared

    async def execute(
        self, arguments: Mapping[str, JsonValue], context: ToolExecutionContext
    ) -> ToolExecutionResult:
        user_id = _require_instructor(context.principal)
        try:
            parsed = DraftArguments.model_validate(arguments)
        except ValidationError as error:
            raise ToolValidationError("Invalid newsletter draft request.") from error
        job, started = self._shared.runner.start(
            week_number=parsed.week, force=parsed.force, requested_by_user_id=user_id
        )
        return ToolExecutionResult(
            content={
                "job": job_summary(job),
                "started": started,
                "message": (
                    "Drafting started in the background; it takes about five minutes. Do not "
                    "check the status in this turn: end your reply now and tell the instructor "
                    "to ask for the newsletter status in a few minutes."
                    if started
                    else "A draft is already running; tell the instructor to ask again shortly."
                ),
            },
            summary="Started a newsletter draft." if started else "A newsletter draft is running.",
            storage_policy="server_summary",
        )


class InstructorNewsletterStatusTool:
    id = INSTRUCTOR_NEWSLETTER_STATUS_TOOL_ID
    description = (
        "Check a newsletter draft job or read a stored issue. With no arguments, reports the "
        "latest job and, when it has finished, the resulting draft: headline, editorial, the "
        "four highlights, the closing quote, the scoreboard with reasons, and the file paths. "
        "Present the draft faithfully and ask the instructor whether to send, redraft, or wait."
    )
    input_schema: ClassVar[dict[str, JsonValue]] = {
        "type": "object",
        "properties": {
            "job_id": {"type": "string", "minLength": 36, "maxLength": 36},
            "issue_id": {"type": "string", "pattern": ISSUE_ID_PATTERN},
        },
        "additionalProperties": False,
    }

    def __init__(self, shared: NewsletterTools) -> None:
        self._shared = shared

    async def execute(
        self, arguments: Mapping[str, JsonValue], context: ToolExecutionContext
    ) -> ToolExecutionResult:
        _require_instructor(context.principal)
        try:
            parsed = StatusArguments.model_validate(arguments)
        except ValidationError as error:
            raise ToolValidationError("Invalid newsletter status request.") from error
        job: NewsletterJob | None = None
        issue: NewsletterIssue | None = None
        job_id: UUID | None = None
        if parsed.job_id is not None:
            try:
                job_id = UUID(parsed.job_id)
            except ValueError as error:
                raise ToolValidationError("Invalid newsletter job id.") from error
        try:
            if job_id is not None:
                job = self._shared.runner.status(job_id)
                if job is None:
                    raise ToolValidationError("That newsletter job does not exist.")
            elif parsed.issue_id is None:
                job = self._shared.runner.latest()
            issue_id = parsed.issue_id or (job.issue_id if job is not None else None)
            if issue_id is not None:
                issue = self._shared.store.load(issue_id)
        except NewsletterStoreError as error:
            raise ToolValidationError(str(error)) from error
        if job is None and issue is None:
            raise ToolValidationError("No newsletter has been drafted yet.")
        running = job is not None and job.status == "running" and issue is None
        if running:
            if context.transient_state.get(_POLLED_KEY) is True:
                raise ToolValidationError(_WAIT_MESSAGE)
            context.transient_state[_POLLED_KEY] = True
        return ToolExecutionResult(
            content={
                "job": job_summary(job) if job is not None else None,
                "issue": issue_summary(issue, self._shared.store) if issue is not None else None,
                **({"message": _WAIT_MESSAGE} if running else {}),
            },
            summary=(
                f"Newsletter {issue.issue_id} is {issue.status}."
                if issue is not None
                else f"Newsletter draft job is {job.status}."
                if job is not None
                else "No newsletter yet."
            ),
            storage_policy="server_summary",
        )


class InstructorSendNewsletterTool:
    id = INSTRUCTOR_SEND_NEWSLETTER_TOOL_ID
    description = (
        "Prepare a stored newsletter draft for sending. audience=all_students resolves every "
        "active student account plus the configured staff list; audience=test sends only to the "
        "given test_recipients. The platform shows the recipients and requires the instructor to "
        "press Send before anything is delivered by the mail worker. Never call this before the "
        "instructor has reviewed the draft and asked to send it."
    )
    redact_arguments_in_events = True
    input_schema: ClassVar[dict[str, JsonValue]] = {
        "type": "object",
        "properties": {
            "issue_id": {"type": "string", "pattern": ISSUE_ID_PATTERN},
            "audience": {"type": "string", "enum": ["all_students", "test"]},
            "test_recipients": {
                "type": "array",
                "items": {"type": "string", "minLength": 3, "maxLength": 200},
                "maxItems": 5,
                "description": "Required for audience=test; ignored otherwise.",
            },
        },
        "required": ["issue_id", "audience"],
        "additionalProperties": False,
    }

    def __init__(self, shared: NewsletterTools) -> None:
        self._shared = shared

    async def execute(
        self, arguments: Mapping[str, JsonValue], context: ToolExecutionContext
    ) -> ToolExecutionResult:
        user_id = _require_instructor(context.principal)
        try:
            parsed = SendArguments.model_validate(arguments)
        except ValidationError as error:
            raise ToolValidationError("Invalid newsletter send request.") from error
        if parsed.audience == "test":
            recipients = list(parsed.test_recipients)
            if not recipients:
                raise ToolValidationError("A test send needs at least one test recipient.")
        else:
            users = await self._shared.auth.list_users()
            recipients = [
                str(user.email) for user in users if user.active and user.role == "student"
            ]
            recipients.extend(str(address) for address in self._shared.settings.recipients)
        try:
            issue = self._shared.service.request_send(
                parsed.issue_id,
                audience=parsed.audience,
                recipients=recipients,
                conversation_id=context.conversation_id,
                requested_by_user_id=user_id,
            )
        except NewsletterStateError as error:
            raise ToolValidationError(str(error)) from error
        approval = issue.approval
        assert approval is not None
        preview = render_text(issue)
        return ToolExecutionResult(
            content={
                "issue_id": issue.issue_id,
                "confirmation_id": str(approval.confirmation_id),
                "audience": approval.audience,
                "recipient_count": len(approval.recipients),
                "confirmation_required": True,
                "message": "The instructor must press Send in the platform before delivery.",
            },
            summary="Prepared the newsletter for the instructor's Send confirmation.",
            storage_policy="server_summary",
            emitted_events=[
                ToolEmittedEvent(
                    type=NEWSLETTER_CONFIRMATION_EVENT,
                    payload={
                        "issue_id": issue.issue_id,
                        "confirmation_id": str(approval.confirmation_id),
                        "audience": approval.audience,
                        "recipient_count": len(approval.recipients),
                        "recipients": (
                            list(approval.recipients) if approval.audience == "test" else []
                        ),
                        "subject": issue.subject,
                        "headline": issue.body.headline,
                        "week": issue.week.number,
                        "preview": preview[:_PREVIEW_CHARS],
                        "status": "awaiting_confirmation",
                    },
                    metadata={"visibility": "private"},
                )
            ],
        )
