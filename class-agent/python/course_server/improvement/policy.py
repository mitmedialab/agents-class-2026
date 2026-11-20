"""Deterministic decision on which proposed changes a human must approve."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from typing import Literal

from .models import ChangeKind, EscalationReason, Proposal, ProposalDraft, RiskAssessment

# Trusted allowlist: the only change kind the platform may adopt without a human decision.
# Interface changes, published content, and any use of private data always wait for staff.
POLICY_APPROVED_KINDS: frozenset[ChangeKind] = frozenset({"agent_guidance"})

_CONTACT_DETAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+|\b\d{3}[-.\s]\d{3}[-.\s]\d{4}\b")


class PrivacyScreen:
    """Finds course-member identifiers in text that could reach other users."""

    def __init__(self, member_identifiers: Iterable[str] = ()) -> None:
        terms = sorted(
            {term.strip().casefold() for term in member_identifiers if len(term.strip()) >= 3}
        )
        self._members = (
            re.compile(r"(?<!\w)(?:" + "|".join(re.escape(term) for term in terms) + r")(?!\w)")
            if terms
            else None
        )

    def reasons(self, text: str) -> list[EscalationReason]:
        found: list[EscalationReason] = []
        if self._members is not None and self._members.search(text.casefold()):
            found.append("mentions_course_member")
        if _CONTACT_DETAIL.search(text):
            found.append("contains_contact_detail")
        return found


def assess_proposal(draft: ProposalDraft, privacy: PrivacyScreen) -> RiskAssessment:
    """Fail toward human approval; the proposing model has no say in this result."""

    reasons: list[EscalationReason] = []
    if draft.kind not in POLICY_APPROVED_KINDS:
        reasons.append("kind_requires_approval")
    if draft.data_categories:
        reasons.append("declares_private_data")
    artifact = draft.artifact.content if draft.artifact else ""
    reasons.extend(
        privacy.reasons(
            "\n".join(
                (
                    draft.title,
                    draft.rationale,
                    draft.trigger,
                    draft.agent_action,
                    draft.student_action,
                    draft.builds_on,
                    draft.body,
                    artifact,
                )
            )
        )
    )
    return RiskAssessment(requires_human_approval=bool(reasons), reasons=reasons)


# Validation bound: proposals a cycle may hold in review at once, so reviewers and the
# human compare a few distinct changes rather than near-duplicates.
MAX_IN_REVIEW_PROPOSALS = 4

# Review bounds: a proposal reaches the gate only when every lens on the panel accepts the
# same revision, and is withdrawn rather than escalated once this many revisions have failed
# to converge. The default is safe; a deployment may raise it, but review is always bounded.
MAX_REVIEW_ROUNDS = 6
# Validation bound for one replay score.
MAX_REPLAY_SCORE = 4

# Trusted allowlist: kinds whose deliverable the platform can run as written. A skill is
# loaded into simulated student conversations; the panel then grades those transcripts.
TRIALLED_KINDS: frozenset[ChangeKind] = frozenset({"agent_skill"})

ReviewOutcome = Literal[
    "needs_replay", "needs_trial", "needs_critique", "needs_revision", "withdrawn", "eligible"
]


def replay_mean(scores: Mapping[str, int]) -> float | None:
    return sum(scores.values()) / len(scores) if scores else None


def review_outcome(
    proposal: Proposal,
    *,
    scenario_ids: frozenset[str],
    baseline_scores: Mapping[str, int],
    lens_ids: Sequence[str],
    max_rounds: int = MAX_REVIEW_ROUNDS,
    trial_persona_ids: Sequence[str] = (),
) -> tuple[ReviewOutcome, str | None]:
    """Decide the next step for an in-review proposal from recorded facts only."""

    if proposal.draft.kind == "agent_guidance" and scenario_ids:
        if set(proposal.replay_scores) != scenario_ids:
            return "needs_replay", None
        candidate = replay_mean(proposal.replay_scores)
        baseline = replay_mean(baseline_scores)
        if candidate is None or baseline is None or candidate <= baseline:
            return "withdrawn", "replay_not_better_than_baseline"
    current = [item for item in proposal.critiques if item.revision == proposal.revision]
    if any(item.verdict == "reject" for item in current):
        return "withdrawn", "critic_rejected"
    if next_trial_persona(proposal, trial_persona_ids) is not None:
        return "needs_trial", None
    if next_lens(proposal, lens_ids) is not None:
        return "needs_critique", None
    if all(item.verdict == "accept" for item in current):
        return "eligible", None
    if proposal.revision >= max_rounds:
        return "withdrawn", "critique_limit_reached"
    return "needs_revision", None


def next_lens(proposal: Proposal, lens_ids: Sequence[str]) -> str | None:
    """The panel lens that has not yet graded the current revision, in charter order.

    The platform derives this from recorded state, so a critic run cannot choose its lens.
    """

    graded = {item.lens for item in proposal.critiques if item.revision == proposal.revision}
    return next((lens for lens in lens_ids if lens not in graded), None)


def next_trial_persona(proposal: Proposal, persona_ids: Sequence[str]) -> str | None:
    """The persona the current revision of a triallable proposal has not been tried with."""

    if proposal.draft.kind not in TRIALLED_KINDS:
        return None
    tried = {item.persona for item in proposal.trials if item.revision == proposal.revision}
    return next((persona for persona in persona_ids if persona not in tried), None)


def open_issue_ids(proposal: Proposal) -> list[str]:
    """Issues raised against the current revision, which its revision must answer."""

    return [
        issue_id
        for item in proposal.critiques
        if item.revision == proposal.revision
        for issue_id in item.issue_ids()
    ]
