"""Agent-facing tools for the course-improvement loop.

Every tool re-checks the instructor role through the service. None of them decides
whether a proposal takes effect.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import ClassVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, ValidationError

from course_server.agent.capabilities import (
    ToolEmittedEvent,
    ToolExecutionContext,
    ToolExecutionResult,
    ToolValidationError,
)
from course_server.agent.skills import READ_SKILL_TOOL_ID, ReadSkillTool

from .artifacts import MOCKUP_RULES
from .models import CritiqueVerdict, IssueResponse, NotebookEntry, Proposal, ProposalDraft
from .policy import MAX_REPLAY_SCORE
from .service import ImprovementService, ImprovementStateError
from .tool_ids import (
    COMPACT_NOTEBOOK_TOOL_ID,
    NOTE_FINDING_TOOL_ID,
    PROPOSE_CHANGE_TOOL_ID,
    RANK_PROPOSALS_TOOL_ID,
    READ_BRIEF_TOOL_ID,
    REVISE_PROPOSAL_TOOL_ID,
    SCORE_REPLAY_TOOL_ID,
    SUBMIT_CRITIQUE_TOOL_ID,
)

_STRING_LIST: dict[str, JsonValue] = {"type": "array", "items": {"type": "string"}}
_DRAFT_PROPERTIES: dict[str, JsonValue] = {
    "kind": {
        "type": "string",
        "enum": [
            "agent_guidance",
            "agent_skill",
            "course_content",
            "ui_feature",
            "private_data_use",
        ],
        "description": (
            "agent_guidance is a short rule for how the Course Agent tutors students; "
            "agent_skill is a reusable workflow the Course Agent loads on demand; "
            "course_content is published material; ui_feature is an interface change; "
            "private_data_use shows or derives anything from private student data."
        ),
    },
    "title": {"type": "string", "description": "Short name of the change."},
    "rationale": {
        "type": "string",
        "description": "Why the cited evidence and learning goals call for this change.",
    },
    "goal_id": {
        "type": "string",
        "description": "The one learning goal this feature serves.",
    },
    "direction": {
        "type": "string",
        "description": "The one charter direction ID this feature belongs to.",
    },
    "course_week": {
        "type": "integer",
        "description": "Course week whose build or topic this feature is tied to, if any.",
    },
    "trigger": {
        "type": "string",
        "description": (
            "The single moment in a student's course work that starts the experience. "
            "One sentence, at most 200 characters."
        ),
    },
    "agent_action": {
        "type": "string",
        "description": "The one thing the Course Agent then does. At most 200 characters.",
    },
    "student_action": {
        "type": "string",
        "description": "The one thing the student then does. At most 200 characters.",
    },
    "builds_on": {
        "type": "string",
        "description": (
            "The existing experience this continues: the chat, an assignment or project "
            "view, or an adopted feature from the brief. At most 200 characters."
        ),
    },
    "body": {
        "type": "string",
        "description": (
            "For agent_guidance, the exact guidance text. For every other kind, a short "
            "summary of the change; the deliverable itself goes in artifact. Never name or "
            "quote an individual student."
        ),
    },
    "artifact": {
        "type": "object",
        "description": (
            "The finished deliverable a reviewer can inspect. Required as html_mockup for "
            "ui_feature, skill for agent_skill, and markdown for course_content; omit it "
            "for agent_guidance and private_data_use. "
            + MOCKUP_RULES
            + " A skill is a complete SKILL.md with name and description frontmatter and "
            "the workflow steps as its body. markdown is the exact text to publish."
        ),
        "properties": {
            "format": {"type": "string", "enum": ["html_mockup", "skill", "markdown"]},
            "content": {"type": "string"},
        },
        "required": ["format", "content"],
    },
    "signal_ids": {**_STRING_LIST, "description": "Evidence signal IDs that motivate it."},
    "data_categories": {
        **_STRING_LIST,
        "description": (
            "Private data the change would use: conversation_text, grades_feedback, roster, "
            "or staff_questions. Repository builds and commits are public within the course "
            "and are not private data. Omit when it uses none."
        ),
    },
}
_DRAFT_REQUIRED: list[JsonValue] = [
    "kind",
    "title",
    "rationale",
    "goal_id",
    "direction",
    "trigger",
    "agent_action",
    "student_action",
    "builds_on",
    "body",
    "signal_ids",
]


def _proposal_event(proposal: Proposal) -> ToolEmittedEvent:
    return ToolEmittedEvent(
        type="improvement.proposal.updated",
        payload={
            "proposal_id": str(proposal.id),
            "kind": proposal.draft.kind,
            "revision": proposal.revision,
            "status": proposal.status,
            "status_reason": proposal.status_reason,
        },
    )


class _ImprovementTool:
    """Shared argument validation and safe, model-actionable failures."""

    id: ClassVar[str]
    description: ClassVar[str]
    input_schema: ClassVar[dict[str, JsonValue]]

    def __init__(self, service: ImprovementService) -> None:
        self._service = service

    async def execute(
        self, arguments: Mapping[str, JsonValue], context: ToolExecutionContext
    ) -> ToolExecutionResult:
        try:
            return self._run(dict(arguments), context)
        except ValidationError as error:
            details = "; ".join(
                f"{'.'.join(str(part) for part in item['loc'])}: {item['msg']}"
                for item in error.errors()
            )
            raise ToolValidationError(details) from error
        except ImprovementStateError as error:
            raise ToolValidationError(str(error)) from error

    def _run(
        self, arguments: dict[str, JsonValue], context: ToolExecutionContext
    ) -> ToolExecutionResult:
        raise NotImplementedError


def _schema(
    properties: dict[str, JsonValue], required: list[JsonValue] | None = None
) -> dict[str, JsonValue]:
    return {
        "type": "object",
        "properties": properties,
        "required": required if required is not None else list(properties),
        "additionalProperties": False,
    }


def _proposal_id(arguments: dict[str, JsonValue]) -> UUID:
    value = arguments.pop("proposal_id", None)
    try:
        return UUID(str(value))
    except ValueError as error:
        raise ToolValidationError("proposal_id must be an ID from the brief") from error


class ReadBriefTool(_ImprovementTool):
    id = READ_BRIEF_TOOL_ID
    description = (
        "Read today's date, the charter and its directions, the learning goals, adopted "
        "features, the review panel's lenses and rubrics, the de-identified cohort "
        "evidence, the research notebook, and every proposal with its cited critique "
        "issues and the author's response to each."
    )
    input_schema = _schema({})

    def _run(
        self, arguments: dict[str, JsonValue], context: ToolExecutionContext
    ) -> ToolExecutionResult:
        if arguments:
            raise ToolValidationError("improvement.read_brief does not accept arguments")
        return ToolExecutionResult(
            content=self._service.brief(context.principal),
            summary="Read the improvement brief.",
            storage_policy="server_summary",
        )


class _NotebookArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str
    references: list[str] = Field(default_factory=list)


class NoteFindingTool(_ImprovementTool):
    id = NOTE_FINDING_TOOL_ID
    description = (
        "Record one research finding in the notebook, with references to the evidence "
        "signals, assignments, or repository paths that support it. Never name a student."
    )
    input_schema = _schema(
        {
            "text": {"type": "string", "description": "The finding, at most 600 characters."},
            "references": {**_STRING_LIST, "description": "Where the finding can be checked."},
        },
        ["text"],
    )

    def _run(
        self, arguments: dict[str, JsonValue], context: ToolExecutionContext
    ) -> ToolExecutionResult:
        parsed = _NotebookArguments.model_validate(arguments)
        entry = NotebookEntry(phase="research", text=parsed.text, references=parsed.references)
        self._service.note(context.principal, entry)
        return ToolExecutionResult(content={"recorded": True}, summary="Recorded a finding.")


class ProposeChangeTool(_ImprovementTool):
    id = PROPOSE_CHANGE_TOOL_ID
    description = (
        "Propose one feature: a single small agentic experience for one learning goal and "
        "one charter direction, grounded in cited evidence, with its finished deliverable. "
        "A feature that needs a second flow is a second proposal. The proposal enters "
        "independent review; this does not adopt it."
    )
    input_schema = _schema(_DRAFT_PROPERTIES, _DRAFT_REQUIRED)

    def _run(
        self, arguments: dict[str, JsonValue], context: ToolExecutionContext
    ) -> ToolExecutionResult:
        proposal = self._service.propose(
            context.principal,
            context.conversation_id,
            ProposalDraft.model_validate(arguments),
        )
        return ToolExecutionResult(
            content={"proposal_id": str(proposal.id), "status": proposal.status},
            summary="Recorded a proposal for review.",
            emitted_events=[_proposal_event(proposal)],
        )


class _Responses(BaseModel):
    model_config = ConfigDict(extra="forbid")

    responses: list[IssueResponse]


class ReviseProposalTool(_ImprovementTool):
    id = REVISE_PROPOSAL_TOOL_ID
    description = (
        "Replace a proposal's draft and answer every open issue from the review panel by its "
        "issue_id. The kind cannot change, and the whole panel reviews the revision again."
    )
    input_schema = _schema(
        {
            "proposal_id": {"type": "string", "description": "ID from the brief."},
            "responses": {
                "type": "array",
                "description": "One answer for each open issue.",
                "items": _schema(
                    {
                        "issue_id": {"type": "string", "description": "For example r1.scope.2."},
                        "action": {"type": "string", "enum": ["resolved", "declined"]},
                        "note": {
                            "type": "string",
                            "description": "What changed, or why not; at most 300 characters.",
                        },
                        "conflicts_with": {
                            "type": "string",
                            "description": (
                                "On a declined issue only: the issue_id it could not be "
                                "satisfied alongside."
                            ),
                        },
                    },
                    ["issue_id", "action", "note"],
                ),
            },
            **_DRAFT_PROPERTIES,
        },
        ["proposal_id", "responses", *_DRAFT_REQUIRED],
    )

    def _run(
        self, arguments: dict[str, JsonValue], context: ToolExecutionContext
    ) -> ToolExecutionResult:
        proposal_id = _proposal_id(arguments)
        responses = _Responses.model_validate({"responses": arguments.pop("responses", [])})
        proposal = self._service.revise(
            context.principal,
            proposal_id,
            ProposalDraft.model_validate(arguments),
            responses.responses,
        )
        return ToolExecutionResult(
            content={"proposal_id": str(proposal.id), "revision": proposal.revision},
            summary="Recorded a proposal revision.",
            emitted_events=[_proposal_event(proposal)],
        )


class _CritiqueArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verdict: CritiqueVerdict
    issues: list[str] = Field(default_factory=list)


class SubmitCritiqueTool(_ImprovementTool):
    id = SUBMIT_CRITIQUE_TOOL_ID
    description = (
        "Record your verdict on one proposal under the rubric you were assigned. Use accept "
        "when nothing under that rubric blocks adoption, revise when it can be fixed, and "
        "reject when the proposal cannot meet the rubric in any revision."
    )
    input_schema = _schema(
        {
            "proposal_id": {"type": "string", "description": "ID from the brief."},
            "verdict": {"type": "string", "enum": ["accept", "revise", "reject"]},
            "issues": {**_STRING_LIST, "description": "Up to five specific, checkable issues."},
        },
        ["proposal_id", "verdict"],
    )

    def _run(
        self, arguments: dict[str, JsonValue], context: ToolExecutionContext
    ) -> ToolExecutionResult:
        proposal_id = _proposal_id(arguments)
        parsed = _CritiqueArguments.model_validate(arguments)
        proposal = self._service.critique(
            context.principal, proposal_id, parsed.verdict, parsed.issues
        )
        return ToolExecutionResult(
            content={
                "proposal_id": str(proposal.id),
                "status": proposal.status,
                "recorded_under_lens": proposal.critiques[-1].lens,
            },
            summary="Recorded a critique.",
            emitted_events=[_proposal_event(proposal)],
        )


class ScoreReplayTool(_ImprovementTool):
    id = SCORE_REPLAY_TOOL_ID
    description = (
        "Score the reply under review against the supplied rubric. The platform has already "
        "fixed which scenario and proposal the score belongs to."
    )
    input_schema = _schema(
        {
            "score": {
                "type": "integer",
                "description": f"0 (fails the rubric) to {MAX_REPLAY_SCORE} (fully meets it).",
            }
        }
    )

    def _run(
        self, arguments: dict[str, JsonValue], context: ToolExecutionContext
    ) -> ToolExecutionResult:
        score = arguments.get("score")
        if set(arguments) != {"score"} or not isinstance(score, int) or isinstance(score, bool):
            raise ToolValidationError("score must be the only argument and an integer")
        self._service.score_open_replay(context.principal, score)
        return ToolExecutionResult(content={"recorded": True}, summary="Recorded a replay score.")


class _RankArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    proposal_ids: list[UUID]


class RankProposalsTool(_ImprovementTool):
    id = RANK_PROPOSALS_TOOL_ID
    description = (
        "Order every proposal that passed review from most to least valuable for the "
        "learning goals. Only the best-ranked proposals continue."
    )
    input_schema = _schema(
        {"proposal_ids": {**_STRING_LIST, "description": "Proposal IDs, best first."}}
    )

    def _run(
        self, arguments: dict[str, JsonValue], context: ToolExecutionContext
    ) -> ToolExecutionResult:
        parsed = _RankArguments.model_validate(arguments)
        self._service.rank(context.principal, parsed.proposal_ids)
        return ToolExecutionResult(content={"recorded": True}, summary="Recorded a ranking.")


class _CompactArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entries: list[_NotebookArguments] = Field(min_length=1, max_length=8)


class CompactNotebookTool(_ImprovementTool):
    id = COMPACT_NOTEBOOK_TOOL_ID
    description = (
        "Replace the research notebook with a shorter version that keeps every finding still "
        "needed, its references, and the reasons proposals were withdrawn."
    )
    input_schema = _schema(
        {
            "entries": {
                "type": "array",
                "description": "The complete replacement notebook.",
                "items": {
                    "type": "object",
                    "properties": {"text": {"type": "string"}, "references": _STRING_LIST},
                    "required": ["text"],
                },
            }
        }
    )

    def _run(
        self, arguments: dict[str, JsonValue], context: ToolExecutionContext
    ) -> ToolExecutionResult:
        parsed = _CompactArguments.model_validate(arguments)
        self._service.compact(
            context.principal,
            [
                NotebookEntry(phase="compact", text=entry.text, references=entry.references)
                for entry in parsed.entries
            ],
        )
        return ToolExecutionResult(content={"recorded": True}, summary="Compacted the notebook.")


class TrialSkillReadTool:
    """The Course Agent's skill reader, which also serves the one candidate under trial.

    Registered in place of ``ReadSkillTool`` where the loop runs. A proposed skill is
    model-authored and unapproved, so it is served only inside the conversation the platform
    opened for its trial; every other call goes to the registered catalog unchanged.
    """

    id = READ_SKILL_TOOL_ID
    description = ReadSkillTool.description
    input_schema = ReadSkillTool.input_schema

    def __init__(self, service: ImprovementService, registered: ReadSkillTool) -> None:
        self._service = service
        self._registered = registered

    async def execute(
        self, arguments: Mapping[str, JsonValue], context: ToolExecutionContext
    ) -> ToolExecutionResult:
        raw = arguments.get("skill_id")
        skill_id = raw.strip() if isinstance(raw, str) and set(arguments) == {"skill_id"} else ""
        instructions = self._service.load_trial_skill(context.conversation_id, skill_id)
        if instructions is None:
            return await self._registered.execute(arguments, context)
        return ToolExecutionResult(
            content={"skill_id": skill_id, "instructions": instructions, "references": []},
            summary=f"Loaded candidate skill {skill_id} for a trial.",
            storage_policy="server_summary",
        )


def improvement_tools(service: ImprovementService) -> list[_ImprovementTool]:
    return [
        ReadBriefTool(service),
        NoteFindingTool(service),
        ProposeChangeTool(service),
        ReviseProposalTool(service),
        SubmitCritiqueTool(service),
        ScoreReplayTool(service),
        RankProposalsTool(service),
        CompactNotebookTool(service),
    ]
