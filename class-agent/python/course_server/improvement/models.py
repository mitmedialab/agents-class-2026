"""Portable records for the governed course-improvement loop."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

# Validation bound: an aggregate describing fewer students could identify one of them.
MIN_SIGNAL_STUDENTS = 3
# Validation bound: adopted guidance is added to student runs, so each entry stays short.
MAX_GUIDANCE_CHARACTERS = 600

# Validation bound: a deliverable is reviewed by a person, so it stays readable in one sitting.
MAX_ARTIFACT_CHARACTERS = 12_000

ChangeKind = Literal[
    "agent_guidance", "agent_skill", "course_content", "ui_feature", "private_data_use"
]
ArtifactFormat = Literal["html_mockup", "skill", "markdown"]
# The concrete deliverable each kind must attach so a reviewer sees the thing itself.
# Guidance and private-data proposals are fully stated by their body.
REQUIRED_ARTIFACT_FORMAT: dict[ChangeKind, ArtifactFormat | None] = {
    "agent_guidance": None,
    "agent_skill": "skill",
    "course_content": "markdown",
    "ui_feature": "html_mockup",
    "private_data_use": None,
}
PrivateDataCategory = Literal["conversation_text", "grades_feedback", "roster", "staff_questions"]
ProposalStatus = Literal[
    "in_review",
    "withdrawn",
    "shelved",
    "pending_approval",
    "approved",
    "rejected",
    "retired",
]
CritiqueVerdict = Literal["accept", "revise", "reject"]
LoopPhase = Literal[
    "research", "propose", "replay", "trial", "critique", "revise", "rank", "compact", "gate"
]
# Validation bound: each part of a feature's flow is one short sentence, so a proposal
# describes a single experience rather than a bundle.
MAX_FLOW_STEP_CHARACTERS = 200
# Validation bound: a human's reason for a gate decision is carried into later cycles.
MAX_DECISION_REASON_CHARACTERS = 300
ApprovalSource = Literal["platform_policy", "human"]
EscalationReason = Literal[
    "kind_requires_approval",
    "declares_private_data",
    "mentions_course_member",
    "contains_contact_detail",
]


class LearningGoal(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(pattern=r"^[a-z][a-z0-9-]{1,48}$")
    statement: str = Field(min_length=1, max_length=400)


class LearningGoals(BaseModel):
    """Machine-readable form of the syllabus learning goals."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1]
    goals: list[LearningGoal] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_ids(self) -> LearningGoals:
        ids = [goal.id for goal in self.goals]
        if len(ids) != len(set(ids)):
            raise ValueError("learning goal IDs must be unique")
        return self


class Direction(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(pattern=r"^[a-z][a-z0-9-]{1,48}$")
    statement: str = Field(min_length=1, max_length=400)


# Validation bound: the purpose is one sentence of orientation, not a feature list.
MAX_PURPOSE_CHARACTERS = 300
# Validation bound: a rubric is read in full by every critic run and by the reviewing human.
MAX_RUBRIC_CHARACTERS = 700


class Lens(BaseModel):
    """One critic's single concern and the rubric it grades a proposal against."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(pattern=r"^[a-z][a-z0-9-]{1,48}$")
    rubric: str = Field(min_length=1, max_length=MAX_RUBRIC_CHARACTERS)


# Validation bounds: every critic run reads a trial transcript in full.
MAX_TRIAL_MESSAGE_CHARACTERS = 1200
MAX_TRIAL_MESSAGES = 8
MAX_TRIAL_PERSONAS = 4


class TrialPersona(BaseModel):
    """A kind of student a simulated trial conversation is played as."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(pattern=r"^[a-z][a-z0-9-]{1,48}$")
    description: str = Field(min_length=1, max_length=300)


class Charter(BaseModel):
    """Staff-maintained aims for the loop; it orients proposals without listing features."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1]
    # The overriding aim every proposal is judged and ranked against.
    purpose: str = Field(min_length=1, max_length=MAX_PURPOSE_CHARACTERS)
    directions: list[Direction] = Field(min_length=1)
    # The review panel: every revision is graded once under each lens.
    lenses: list[Lens] = Field(min_length=1)
    # Simulated students a proposed skill is tried with before the panel grades it. With
    # none, skills are graded from their text alone.
    trial_personas: list[TrialPersona] = Field(default_factory=list, max_length=MAX_TRIAL_PERSONAS)
    sources: list[Annotated[str, Field(pattern=r"^course://")]] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique_ids(self) -> Charter:
        for name, ids in (
            ("direction", [direction.id for direction in self.directions]),
            ("lens", [lens.id for lens in self.lenses]),
            ("trial persona", [persona.id for persona in self.trial_personas]),
        ):
            if len(ids) != len(set(ids)):
                raise ValueError(f"{name} IDs must be unique")
        return self


class EvidenceSignal(BaseModel):
    """One de-identified cohort-level observation about a learning goal."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(pattern=r"^[a-z][a-z0-9-]{1,48}$")
    goal_id: str
    source: Literal["conversations", "weekly_feedback", "staff_questions", "student_projects"]
    observation: str = Field(min_length=1, max_length=400)
    student_count: int = Field(ge=MIN_SIGNAL_STUDENTS)


class EvidenceDigest(BaseModel):
    """Aggregates only: no student identifier, message text, grade, or feedback note."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1]
    period: str = Field(pattern=r"^\d{4}-W\d{2}$")
    cohort_size: int = Field(ge=MIN_SIGNAL_STUDENTS)
    synthetic: bool = False
    signals: list[EvidenceSignal]

    @model_validator(mode="after")
    def consistent_signals(self) -> EvidenceDigest:
        ids = [signal.id for signal in self.signals]
        if len(ids) != len(set(ids)):
            raise ValueError("evidence signal IDs must be unique")
        if any(signal.student_count > self.cohort_size for signal in self.signals):
            raise ValueError("a signal cannot describe more students than the cohort")
        return self


class ProposalArtifact(BaseModel):
    """Model-authored deliverable for review; never rendered or loaded by the platform."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    format: ArtifactFormat
    content: str = Field(min_length=1, max_length=MAX_ARTIFACT_CHARACTERS)


class ProposalDraft(BaseModel):
    """Model-authored change request; every field is untrusted until assessed."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: ChangeKind
    title: str = Field(min_length=1, max_length=120)
    rationale: str = Field(min_length=1, max_length=1000)
    # One goal and one direction per proposal: a second aim is a second proposal.
    goal_id: str
    direction: str
    course_week: int | None = Field(default=None, ge=1, le=30)
    # The single flow of the experience, and the existing experience it continues.
    trigger: str = Field(min_length=1, max_length=MAX_FLOW_STEP_CHARACTERS)
    agent_action: str = Field(min_length=1, max_length=MAX_FLOW_STEP_CHARACTERS)
    student_action: str = Field(min_length=1, max_length=MAX_FLOW_STEP_CHARACTERS)
    builds_on: str = Field(min_length=1, max_length=MAX_FLOW_STEP_CHARACTERS)
    body: str = Field(min_length=1, max_length=2000)
    artifact: ProposalArtifact | None = None
    signal_ids: list[str] = Field(min_length=1, max_length=12)
    data_categories: list[PrivateDataCategory] = Field(default_factory=list, max_length=4)

    @model_validator(mode="after")
    def bounded_by_kind(self) -> ProposalDraft:
        if self.kind == "agent_guidance" and len(self.body) > MAX_GUIDANCE_CHARACTERS:
            raise ValueError(f"agent guidance is limited to {MAX_GUIDANCE_CHARACTERS} characters")
        if self.kind == "private_data_use" and not self.data_categories:
            raise ValueError("a private data proposal must declare its data categories")
        required = REQUIRED_ARTIFACT_FORMAT[self.kind]
        attached = self.artifact.format if self.artifact else None
        if attached != required:
            raise ValueError(
                f"a {self.kind} proposal requires "
                + (f"an artifact with format {required}" if required else "no artifact")
            )
        return self


class Critique(BaseModel):
    """One independent critic verdict on a specific revision, under one lens."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    revision: int = Field(ge=1)
    lens: str
    verdict: CritiqueVerdict
    issues: list[Annotated[str, Field(min_length=1, max_length=300)]] = Field(
        default_factory=list, max_length=5
    )

    def issue_ids(self) -> list[str]:
        """Stable citations for this critique's issues: revision, lens, position."""

        return [
            f"r{self.revision}.{self.lens}.{number}" for number in range(1, len(self.issues) + 1)
        ]


class IssueResponse(BaseModel):
    """The author's recorded answer to one cited issue."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    issue_id: str
    action: Literal["resolved", "declined"]
    note: str = Field(min_length=1, max_length=300)
    # The issue this one could not be satisfied alongside, when the author had to choose.
    conflicts_with: str | None = None

    @model_validator(mode="after")
    def conflict_only_on_decline(self) -> IssueResponse:
        if self.conflicts_with is not None and self.action != "declined":
            raise ValueError("conflicts_with is recorded on the declined issue")
        if self.conflicts_with == self.issue_id:
            raise ValueError("an issue cannot conflict with itself")
        return self


class TrialMessage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    role: Literal["student", "agent"]
    text: str = Field(min_length=1, max_length=MAX_TRIAL_MESSAGE_CHARACTERS)


class Trial(BaseModel):
    """One simulated conversation in which the Course Agent could load the proposed skill."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    revision: int = Field(ge=1)
    persona: str
    # Whether the agent actually loaded the candidate; recorded by the platform's skill tool.
    skill_loaded: bool
    messages: list[TrialMessage] = Field(min_length=2, max_length=MAX_TRIAL_MESSAGES)


class NotebookEntry(BaseModel):
    """Compact research state carried between otherwise fresh agent runs."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    phase: LoopPhase
    text: str = Field(min_length=1, max_length=600)
    references: list[Annotated[str, Field(min_length=1, max_length=200)]] = Field(
        default_factory=list, max_length=8
    )


class ReplayScenario(BaseModel):
    """A de-identified student situation with the rubric used to score a reply."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(pattern=r"^[a-z][a-z0-9-]{1,48}$")
    goal_id: str
    student_message: str = Field(min_length=1, max_length=600)
    rubric: str = Field(min_length=1, max_length=600)


class ReplayScenarios(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1]
    synthetic: bool = False
    scenarios: list[ReplayScenario]


class RiskAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    requires_human_approval: bool
    reasons: list[EscalationReason]


class Proposal(BaseModel):
    """A recorded change request and the decision that governs it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID = Field(default_factory=uuid4)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    proposed_in_conversation_id: UUID
    requested_by_user_id: UUID
    evidence_period: str
    draft: ProposalDraft
    revision: int = Field(default=1, ge=1)
    critiques: list[Critique] = Field(default_factory=list)
    responses: list[IssueResponse] = Field(default_factory=list)
    trials: list[Trial] = Field(default_factory=list)
    replay_scores: dict[str, int] = Field(default_factory=dict)
    rank: int | None = None
    status: ProposalStatus = "in_review"
    status_reason: str | None = None
    assessment: RiskAssessment | None = None
    approval_source: ApprovalSource | None = None
    decided_by_user_id: UUID | None = None
    decided_at: datetime | None = None
    decision_reason: str | None = Field(default=None, max_length=MAX_DECISION_REASON_CHARACTERS)

    @property
    def guidance_in_effect(self) -> bool:
        return self.draft.kind == "agent_guidance" and self.status == "approved"
