"""State transitions for the governed course-improvement loop."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Literal
from uuid import UUID

from pydantic import JsonValue

from agent_core import PrincipalContext
from course_server.agent.capabilities import COURSE_SYLLABUS_URI, CourseResourceCatalog
from course_server.agent.skills import split_skill_text

from .artifacts import MOCKUP_RULES, MOCKUP_SHELL_CSS, ArtifactError, validate_artifact
from .models import (
    MAX_DECISION_REASON_CHARACTERS,
    Charter,
    Critique,
    CritiqueVerdict,
    EvidenceDigest,
    IssueResponse,
    LearningGoals,
    Lens,
    NotebookEntry,
    Proposal,
    ProposalDraft,
    ReplayScenario,
    ReplayScenarios,
    Trial,
    TrialMessage,
    TrialPersona,
)
from .policy import (
    MAX_IN_REVIEW_PROPOSALS,
    MAX_REPLAY_SCORE,
    MAX_REVIEW_ROUNDS,
    PrivacyScreen,
    ReviewOutcome,
    assess_proposal,
    next_lens,
    next_trial_persona,
    open_issue_ids,
    replay_mean,
    review_outcome,
)

# Safe default: the notebook is re-read by every run, so it is compacted past this size.
DEFAULT_NOTEBOOK_CHARACTER_LIMIT = 2400
# Validation bound: adopted guidance is added to every student run.
MAX_ACTIVE_GUIDANCE = 8


class ImprovementAccessDenied(PermissionError):
    """The principal is not an authenticated instructor."""


class ImprovementStateError(ValueError):
    """The requested transition is not valid for the current recorded state."""


@dataclass
class ImprovementState:
    """In-memory loop state. A durable adapter must keep the same portable records."""

    proposals: dict[UUID, Proposal] = field(default_factory=dict)
    notebook: list[NotebookEntry] = field(default_factory=list)
    baseline_scores: dict[str, int] = field(default_factory=dict)


@dataclass
class _OpenTrial:
    """The one simulated conversation in which the candidate skill may be loaded."""

    conversation_id: UUID
    proposal_id: UUID
    persona: str
    skill_id: str
    instructions: str
    loaded: bool = False


def _require_instructor(principal: PrincipalContext) -> UUID:
    if (
        not principal.authenticated
        or principal.user_id is None
        or "instructor" not in principal.roles
    ):
        raise ImprovementAccessDenied("Instructor access is required.")
    return principal.user_id


class ImprovementService:
    def __init__(
        self,
        *,
        goals: LearningGoals,
        charter: Charter,
        evidence: EvidenceDigest,
        scenarios: ReplayScenarios,
        privacy: PrivacyScreen,
        state: ImprovementState | None = None,
        notebook_character_limit: int = DEFAULT_NOTEBOOK_CHARACTER_LIMIT,
        today: Callable[[], date] = date.today,
        max_rounds: int = MAX_REVIEW_ROUNDS,
    ) -> None:
        if max_rounds < 1:
            raise ValueError("max_rounds must allow at least one review round")
        self.max_rounds = max_rounds
        self._goal_ids = frozenset(goal.id for goal in goals.goals)
        unknown = {signal.goal_id for signal in evidence.signals} | {
            scenario.goal_id for scenario in scenarios.scenarios
        }
        if not unknown <= self._goal_ids:
            raise ValueError("evidence and scenarios must reference registered learning goals")
        self._goals = goals
        self._charter = charter
        self._direction_ids = frozenset(direction.id for direction in charter.directions)
        self._today = today
        self._evidence = evidence
        self._scenarios = {scenario.id: scenario for scenario in scenarios.scenarios}
        self._privacy = privacy
        self._state = state or ImprovementState()
        self._open_replay: tuple[UUID | None, str] | None = None
        self._open_trial: _OpenTrial | None = None
        self._notebook_limit = notebook_character_limit

    @property
    def scenarios(self) -> tuple[ReplayScenario, ...]:
        return tuple(self._scenarios.values())

    @property
    def lenses(self) -> tuple[Lens, ...]:
        return tuple(self._charter.lenses)

    @property
    def personas(self) -> tuple[TrialPersona, ...]:
        return tuple(self._charter.trial_personas)

    def next_lens(self, proposal: Proposal) -> Lens | None:
        """The lens the platform assigns to this proposal's next critique."""

        lens_id = next_lens(proposal, [lens.id for lens in self._charter.lenses])
        return next((lens for lens in self._charter.lenses if lens.id == lens_id), None)

    def next_trial_persona(self, proposal: Proposal) -> TrialPersona | None:
        """The persona the platform assigns to this proposal's next trial conversation."""

        persona_id = next_trial_persona(proposal, [persona.id for persona in self.personas])
        return next((persona for persona in self.personas if persona.id == persona_id), None)

    def open_issues(self, proposal: Proposal) -> list[dict[str, str]]:
        """Cited issues the next revision must answer, each with its lens."""

        return [
            {"issue_id": issue_id, "lens": item.lens, "text": text}
            for item in proposal.critiques
            if item.revision == proposal.revision
            for issue_id, text in zip(item.issue_ids(), item.issues, strict=True)
        ]

    def brief(self, principal: PrincipalContext) -> dict[str, JsonValue]:
        """Everything a fresh run needs: goals, aggregates, notebook, and review state."""

        _require_instructor(principal)
        return {
            "today": self._today().isoformat(),
            "charter": self._charter.model_dump(mode="json", exclude={"schema_version"}),
            "learning_goals": self._goals.model_dump(mode="json")["goals"],
            "adopted_features": [
                {
                    "proposal_id": str(proposal.id),
                    "kind": proposal.draft.kind,
                    "title": proposal.draft.title,
                    "direction": proposal.draft.direction,
                    "trigger": proposal.draft.trigger,
                }
                for proposal in self._state.proposals.values()
                if proposal.status == "approved"
            ],
            "evidence": self._evidence.model_dump(mode="json"),
            # What an interface mock-up must be, for its author and for whoever grades it.
            "mockup": {"rules": MOCKUP_RULES, "shell_stylesheet": MOCKUP_SHELL_CSS},
            "notebook": [entry.model_dump(mode="json") for entry in self._state.notebook],
            "proposals": [
                {
                    "proposal_id": str(proposal.id),
                    "status": proposal.status,
                    "revision": proposal.revision,
                    "draft": proposal.draft.model_dump(mode="json"),
                    "critiques": [
                        {
                            "revision": item.revision,
                            "lens": item.lens,
                            "verdict": item.verdict,
                            "issues": [
                                {"issue_id": issue_id, "text": text}
                                for issue_id, text in zip(
                                    item.issue_ids(), item.issues, strict=True
                                )
                            ],
                        }
                        for item in proposal.critiques
                    ],
                    "author_responses": [
                        item.model_dump(mode="json", exclude_none=True)
                        for item in proposal.responses
                    ],
                    # What the Course Agent actually did with the current deliverable.
                    "trials": [
                        item.model_dump(mode="json", exclude={"revision"})
                        for item in proposal.trials
                        if proposal.status == "in_review" and item.revision == proposal.revision
                    ],
                }
                for proposal in self._state.proposals.values()
            ],
        }

    def note(self, principal: PrincipalContext, entry: NotebookEntry) -> None:
        _require_instructor(principal)
        self._state.notebook.append(entry)

    def notebook_needs_compaction(self) -> bool:
        return sum(len(entry.text) for entry in self._state.notebook) > self._notebook_limit

    def compact(self, principal: PrincipalContext, entries: list[NotebookEntry]) -> None:
        _require_instructor(principal)
        if sum(len(entry.text) for entry in entries) > self._notebook_limit // 2:
            raise ImprovementStateError(
                f"a compacted notebook is limited to {self._notebook_limit // 2} characters"
            )
        self._state.notebook = list(entries)

    def _validate_draft(self, draft: ProposalDraft) -> None:
        if draft.goal_id not in self._goal_ids:
            raise ImprovementStateError("goal_id must name a registered learning goal")
        if draft.direction not in self._direction_ids:
            raise ImprovementStateError("direction must name a direction in the charter")
        if not set(draft.signal_ids) <= {signal.id for signal in self._evidence.signals}:
            raise ImprovementStateError("signal_ids must name signals in the current evidence")
        if draft.artifact is not None:
            try:
                validate_artifact(draft.artifact)
            except ArtifactError as error:
                raise ImprovementStateError(str(error)) from error

    def propose(
        self,
        principal: PrincipalContext,
        conversation_id: UUID,
        draft: ProposalDraft,
    ) -> Proposal:
        user_id = _require_instructor(principal)
        self._validate_draft(draft)
        in_review = sum(item.status == "in_review" for item in self._state.proposals.values())
        if in_review >= MAX_IN_REVIEW_PROPOSALS:
            raise ImprovementStateError(
                f"{MAX_IN_REVIEW_PROPOSALS} proposals are already in review; propose no more"
            )
        proposal = Proposal(
            proposed_in_conversation_id=conversation_id,
            requested_by_user_id=user_id,
            evidence_period=self._evidence.period,
            draft=draft,
        )
        self._state.proposals[proposal.id] = proposal
        return proposal

    def get(self, principal: PrincipalContext, proposal_id: UUID) -> Proposal:
        _require_instructor(principal)
        proposal = self._state.proposals.get(proposal_id)
        if proposal is None:
            raise ImprovementStateError("proposal not found")
        return proposal

    def proposals(self, principal: PrincipalContext) -> list[Proposal]:
        _require_instructor(principal)
        return list(self._state.proposals.values())

    def outcome(self, proposal: Proposal) -> tuple[ReviewOutcome, str | None]:
        return review_outcome(
            proposal,
            scenario_ids=frozenset(self._scenarios),
            baseline_scores=self._state.baseline_scores,
            lens_ids=[lens.id for lens in self._charter.lenses],
            max_rounds=self.max_rounds,
            trial_persona_ids=[persona.id for persona in self._charter.trial_personas],
        )

    def _save(self, proposal: Proposal) -> Proposal:
        """Store a proposal, withdrawing it when the recorded facts now require that."""

        if proposal.status == "in_review":
            outcome, reason = self.outcome(proposal)
            if outcome == "withdrawn":
                proposal = proposal.model_copy(
                    update={"status": "withdrawn", "status_reason": reason}
                )
                # Later runs start fresh, so the lesson has to live in the notebook.
                self._state.notebook.append(
                    NotebookEntry(
                        phase="critique",
                        text=f"Withdrawn ({reason}): {proposal.draft.title}",
                        references=[str(proposal.id)],
                    )
                )
        self._state.proposals[proposal.id] = proposal
        return proposal

    def _in_review(self, principal: PrincipalContext, proposal_id: UUID) -> Proposal:
        proposal = self.get(principal, proposal_id)
        if proposal.status != "in_review":
            raise ImprovementStateError("proposal is no longer in review")
        return proposal

    def revise(
        self,
        principal: PrincipalContext,
        proposal_id: UUID,
        draft: ProposalDraft,
        responses: Sequence[IssueResponse],
    ) -> Proposal:
        proposal = self._in_review(principal, proposal_id)
        if self.outcome(proposal)[0] != "needs_revision":
            raise ImprovementStateError("the panel has not requested a revision")
        if draft.kind != proposal.draft.kind:
            raise ImprovementStateError("a revision cannot change the proposal kind")
        # Convergence depends on every objection being answered on the record, by citation.
        open_ids = open_issue_ids(proposal)
        answered = [response.issue_id for response in responses]
        if sorted(answered) != sorted(open_ids):
            raise ImprovementStateError(
                "responses must answer each open issue exactly once: " + ", ".join(open_ids)
            )
        known = {issue_id for item in proposal.critiques for issue_id in item.issue_ids()}
        if any(
            response.conflicts_with is not None and response.conflicts_with not in known
            for response in responses
        ):
            raise ImprovementStateError("conflicts_with must cite an issue raised on this proposal")
        self._validate_draft(draft)
        return self._save(
            proposal.model_copy(
                update={
                    "draft": draft,
                    "revision": proposal.revision + 1,
                    "replay_scores": {},
                    "responses": [*proposal.responses, *responses],
                }
            )
        )

    def critique(
        self,
        principal: PrincipalContext,
        proposal_id: UUID,
        verdict: CritiqueVerdict,
        issues: list[str],
    ) -> Proposal:
        proposal = self._in_review(principal, proposal_id)
        lens = self.next_lens(proposal)
        if self.outcome(proposal)[0] != "needs_critique" or lens is None:
            raise ImprovementStateError("this proposal is not awaiting a critique")
        if verdict != "accept" and not issues:
            raise ImprovementStateError("a revise or reject verdict must state its issues")
        # The lens comes from recorded state, never from the critic's own arguments.
        critique = Critique(
            revision=proposal.revision, lens=lens.id, verdict=verdict, issues=issues
        )
        return self._save(
            proposal.model_copy(update={"critiques": [*proposal.critiques, critique]})
        )

    def open_trial(
        self, principal: PrincipalContext, proposal_id: UUID, conversation_id: UUID
    ) -> dict[str, JsonValue]:
        """Make the candidate skill loadable in one platform-created conversation only.

        Returns the metadata a student run would see in its skill index. The skill text is
        model-authored, so no other conversation can ever load it.
        """

        proposal = self._in_review(principal, proposal_id)
        persona = self.next_trial_persona(proposal)
        if self.outcome(proposal)[0] != "needs_trial" or persona is None:
            raise ImprovementStateError("this proposal is not awaiting a trial")
        assert proposal.draft.artifact is not None  # Required for the kind by ProposalDraft.
        frontmatter, instructions = split_skill_text(proposal.draft.artifact.content)
        self._open_trial = _OpenTrial(
            conversation_id=conversation_id,
            proposal_id=proposal_id,
            persona=persona.id,
            skill_id=frontmatter.name,
            instructions=instructions,
        )
        return {
            "id": frontmatter.name,
            "name": frontmatter.name,
            "description": frontmatter.description,
        }

    def load_trial_skill(self, conversation_id: UUID, skill_id: str) -> str | None:
        """Instructions of the candidate under trial in this conversation, else None.

        Called by the skill tool with the trusted conversation ID of the run, not a
        model-supplied one. Loading is recorded so critics can see whether it happened.
        """

        trial = self._open_trial
        if trial is None or trial.conversation_id != conversation_id or trial.skill_id != skill_id:
            return None
        trial.loaded = True
        return trial.instructions

    def record_trial(
        self, principal: PrincipalContext, proposal_id: UUID, messages: Sequence[TrialMessage]
    ) -> Proposal:
        """Close the open trial and store its transcript against the current revision."""

        proposal = self._in_review(principal, proposal_id)
        trial = self._open_trial
        if trial is None or trial.proposal_id != proposal_id:
            raise ImprovementStateError("no trial is open for this proposal")
        self._open_trial = None
        record = Trial(
            revision=proposal.revision,
            persona=trial.persona,
            skill_loaded=trial.loaded,
            messages=list(messages),
        )
        return self._save(proposal.model_copy(update={"trials": [*proposal.trials, record]}))

    def guidance_for_replay(
        self, principal: PrincipalContext, proposal_id: UUID | None
    ) -> list[dict[str, JsonValue]]:
        """Adopted guidance plus, for a candidate replay, the proposal under test."""

        _require_instructor(principal)
        guidance = self._guidance_in_effect()
        if proposal_id is not None:
            guidance.append(self._guidance_item(self._in_review(principal, proposal_id)))
        return guidance

    def open_replay(
        self, principal: PrincipalContext, proposal_id: UUID | None, scenario_id: str
    ) -> None:
        """Bind the next score to a platform-chosen target; the judge supplies only a number."""

        _require_instructor(principal)
        if scenario_id not in self._scenarios:
            raise ImprovementStateError("unknown replay scenario")
        if proposal_id is not None:
            self._in_review(principal, proposal_id)
        self._open_replay = (proposal_id, scenario_id)

    def replay_score(
        self, principal: PrincipalContext, proposal_id: UUID | None, scenario_id: str
    ) -> int | None:
        """The recorded score for one replay, or None when the judge recorded nothing."""

        _require_instructor(principal)
        if proposal_id is None:
            return self._state.baseline_scores.get(scenario_id)
        return self.get(principal, proposal_id).replay_scores.get(scenario_id)

    def score_open_replay(self, principal: PrincipalContext, score: int) -> None:
        _require_instructor(principal)
        if self._open_replay is None:
            raise ImprovementStateError("no replay is awaiting a score")
        if not 0 <= score <= MAX_REPLAY_SCORE:
            raise ImprovementStateError(f"score must be between 0 and {MAX_REPLAY_SCORE}")
        proposal_id, scenario_id = self._open_replay
        self._open_replay = None
        if proposal_id is None:
            self._state.baseline_scores[scenario_id] = score
            return
        proposal = self._in_review(principal, proposal_id)
        self._save(
            proposal.model_copy(
                update={"replay_scores": {**proposal.replay_scores, scenario_id: score}}
            )
        )

    def eligible(self, principal: PrincipalContext) -> list[Proposal]:
        return [
            proposal
            for proposal in self.proposals(principal)
            if proposal.status == "in_review" and self.outcome(proposal)[0] == "eligible"
        ]

    def rank(self, principal: PrincipalContext, ordered_ids: list[UUID]) -> None:
        eligible = {proposal.id: proposal for proposal in self.eligible(principal)}
        if len(ordered_ids) != len(set(ordered_ids)) or set(ordered_ids) != set(eligible):
            raise ImprovementStateError("a ranking must order every eligible proposal exactly once")
        for position, proposal_id in enumerate(ordered_ids, start=1):
            self._state.proposals[proposal_id] = eligible[proposal_id].model_copy(
                update={"rank": position}
            )

    def close_cycle(self, principal: PrincipalContext, *, top_k: int) -> list[Proposal]:
        """Send the best-ranked survivors through the risk gate and shelve everything else."""

        _require_instructor(principal)
        eligible = sorted(
            self.eligible(principal),
            key=lambda proposal: (proposal.rank is None, proposal.rank or 0, proposal.created_at),
        )
        graduated: list[Proposal] = []
        for index, proposal in enumerate(eligible):
            if index >= top_k:
                update: dict[str, object] = {
                    "status": "shelved",
                    "status_reason": "ranked_below_cutoff",
                }
            else:
                assessment = assess_proposal(proposal.draft, self._privacy)
                if assessment.requires_human_approval:
                    update = {"status": "pending_approval", "assessment": assessment}
                elif len(self._guidance_in_effect()) >= MAX_ACTIVE_GUIDANCE:
                    update = {"status": "shelved", "status_reason": "active_guidance_limit"}
                else:
                    update = {
                        "status": "approved",
                        "assessment": assessment,
                        "approval_source": "platform_policy",
                        "decided_at": datetime.now(UTC),
                    }
            saved = proposal.model_copy(update=update)
            self._state.proposals[saved.id] = saved
            if index < top_k:
                graduated.append(saved)
        for proposal in self.proposals(principal):
            if proposal.status == "in_review":
                self._state.proposals[proposal.id] = proposal.model_copy(
                    update={"status": "shelved", "status_reason": "review_incomplete"}
                )
        return graduated

    def decide(
        self,
        principal: PrincipalContext,
        proposal_id: UUID,
        decision: Literal["approve", "reject"],
        reason: str | None = None,
    ) -> Proposal:
        """The human gate. Deliberately not reachable from any agent tool."""

        user_id = _require_instructor(principal)
        proposal = self.get(principal, proposal_id)
        if proposal.status != "pending_approval":
            raise ImprovementStateError("proposal is not awaiting a human decision")
        reason = (reason or "").strip() or None
        if reason is not None and len(reason) > MAX_DECISION_REASON_CHARACTERS:
            raise ImprovementStateError(
                f"a decision reason is limited to {MAX_DECISION_REASON_CHARACTERS} characters"
            )
        status = "approved" if decision == "approve" else "rejected"
        # Later cycles start fresh, so the human's judgement has to live in the notebook.
        self._state.notebook.append(
            NotebookEntry(
                phase="gate",
                text=f"Human {status}{f' ({reason})' if reason else ''}: {proposal.draft.title}",
                references=[str(proposal.id)],
            )
        )
        decided = proposal.model_copy(
            update={
                "status": status,
                "decision_reason": reason,
                "approval_source": "human",
                "decided_by_user_id": user_id,
                "decided_at": datetime.now(UTC),
            }
        )
        self._state.proposals[decided.id] = decided
        return decided

    def retire(self, principal: PrincipalContext, proposal_id: UUID) -> Proposal:
        """Roll back an adopted change, including one the platform approved by policy."""

        _require_instructor(principal)
        proposal = self.get(principal, proposal_id)
        if proposal.status != "approved":
            raise ImprovementStateError("only an approved proposal can be retired")
        retired = proposal.model_copy(update={"status": "retired"})
        self._state.proposals[retired.id] = retired
        return retired

    def dossier(self, principal: PrincipalContext, proposal_id: UUID) -> dict[str, JsonValue]:
        """The full record a human reviews: change, evidence, scores, and critique history."""

        proposal = self.get(principal, proposal_id)
        cited = set(proposal.draft.signal_ids)
        return {
            "proposal": proposal.model_dump(mode="json"),
            "evidence": [
                signal.model_dump(mode="json")
                for signal in self._evidence.signals
                if signal.id in cited
            ],
            "evidence_is_synthetic": self._evidence.synthetic,
            "replay": {
                "baseline_mean": replay_mean(self._state.baseline_scores),
                "candidate_mean": replay_mean(proposal.replay_scores),
            },
        }

    @staticmethod
    def _guidance_item(proposal: Proposal) -> dict[str, JsonValue]:
        return {"guidance": proposal.draft.body, "goal_ids": [proposal.draft.goal_id]}

    def _guidance_in_effect(self) -> list[dict[str, JsonValue]]:
        return [
            self._guidance_item(proposal)
            for proposal in self._state.proposals.values()
            if proposal.guidance_in_effect
        ]

    async def agent_guidance(self, principal: PrincipalContext) -> list[dict[str, JsonValue]]:
        """Adopted guidance for a student run; other principals receive none."""

        if not principal.authenticated or "student" not in principal.roles:
            return []
        return self._guidance_in_effect()


# Asset ID registered on the syllabus resource for its machine-readable learning goals.
LEARNING_GOALS_ASSET_ID = "learning_goals"


# Asset ID registered on the syllabus resource for the staff-maintained loop charter.
IMPROVEMENT_CHARTER_ASSET_ID = "improvement_charter"


async def load_charter(resources: CourseResourceCatalog) -> Charter:
    asset = await resources.read_asset(COURSE_SYLLABUS_URI, IMPROVEMENT_CHARTER_ASSET_ID)
    return Charter.model_validate_json(asset.data)


async def load_learning_goals(resources: CourseResourceCatalog) -> LearningGoals:
    asset = await resources.read_asset(COURSE_SYLLABUS_URI, LEARNING_GOALS_ASSET_ID)
    return LearningGoals.model_validate_json(asset.data)
