"""Platform-owned orchestration of one course-improvement cycle.

Each phase is a fresh run of the one Course Agent through ``AgentRuntime``. The loop, not
the model, decides which phase runs next, which tools that run receives, and when to stop.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from functools import partial
from uuid import UUID, uuid4

from pydantic import JsonValue

from agent_core import (
    AgentContext,
    AgentInput,
    AgentResult,
    AgentRuntime,
    Conversation,
    Event,
    PrincipalContext,
)
from course_server.agent.capabilities import CourseCapabilityPolicy
from course_server.agent.skills import (
    READ_SKILL_REFERENCE_TOOL_ID,
    READ_SKILL_TOOL_ID,
    SkillCatalog,
)
from course_server.agent.store import ConversationStore

from .models import (
    MAX_TRIAL_MESSAGE_CHARACTERS,
    MAX_TRIAL_MESSAGES,
    LoopPhase,
    Proposal,
    ReplayScenario,
    TrialMessage,
)
from .service import ImprovementService
from .tool_ids import LOOP_READ_TOOL_IDS, PHASE_WRITE_TOOL_IDS, READ_PHASES

_RESEARCH_TASK = (
    "Orientation phase of the course-improvement cycle. Read the brief, then use the "
    "available read-only tools to read the charter's sources and establish where the "
    "course is today: this week's topic and build, which learning goal it serves, how it "
    "leads toward the final project, and who the staff are. Then check what students "
    "actually built against that. Record each distinct, checkable finding in the notebook. "
    "Do not propose changes yet, and do not repeat a finding the notebook already holds."
)
_PROPOSE_TASK = (
    "Proposal phase. Read the brief. Every proposal must serve the charter's purpose above "
    "all else. Propose one feature for each charter direction the "
    "notebook and evidence can support, up to {count} in total, so staff can compare "
    "candidates across directions. Each is one small agentic experience: one moment that "
    "starts it, "
    "one thing the Course Agent does, one thing the student then does. Choose the most "
    "obvious, direct feature for one learning goal and one charter direction at this point "
    "in the weekly progression, and say which existing experience it continues. Do not "
    "bundle several experiences, do not propose two variants of one idea, and skip ideas "
    "the notebook records as withdrawn or rejected. Attach the finished deliverable: a "
    "full-screen, three-screen mock-up for an interface change (see `mockup` in the brief), "
    "a skill for a reusable workflow, or the exact "
    "text for content or guidance."
)
_CRITIQUE_TASK = (
    "Critique phase. You did not write proposal {proposal_id}. You are the {lens} critic on "
    "a review panel; other critics cover the other concerns, so grade only against this "
    "rubric:\n\n{rubric}\n\n"
    "Read the brief, re-check with the read-only tools whatever your rubric depends on, and "
    "submit one verdict. The brief lists earlier critiques by issue_id and the author's "
    "response to each. When a proposal in the brief carries `trials`, those are transcripts "
    "of the Course Agent using the current deliverable with simulated students: grade what "
    "the agent actually did in them, including whether it loaded the skill at all, and "
    "quote the turn an issue refers to. For an interface mock-up, walk its three screens in "
    "order as the student would and grade what each one actually shows; the brief's "
    "`mockup.rules` say what a mock-up may and may not contain, so do not ask for anything "
    "they forbid. "
    "Start with your own lens's earlier issues: treat a resolved one as "
    "settled if the revision bears it out. Where the author declined one and cited a "
    "conflicting issue from another lens, weigh that trade-off and insist only if what "
    "remains should by itself stop staff adopting the proposal. Raise an issue only under "
    "your rubric, stated so the author can fix it in one revision by changing or cutting, "
    "not by adding caveats. Accept when nothing under your rubric blocks adoption."
)
_REVISE_TASK = (
    "Revision phase. Read the brief and revise proposal {proposal_id}. The review panel left "
    "these open issues, cited by issue_id and lens:\n\n{issues}\n\n"
    "Answer every one in `responses`: resolved, with a note naming what changed, or "
    "declined, with the reason. When two issues pull in opposite directions, resolve the "
    "one that better serves the charter's purpose, decline the other, and cite the issue "
    "it conflicts with. Keep the proposal one small experience: fix by changing or cutting, "
    "not by adding caveats. Keep what no issue questioned, and update the deliverable to "
    "match. Where an issue cites a trial transcript, change the deliverable so the Course "
    "Agent would behave differently; the revision is tried again before the panel sees it."
)
_RANK_TASK = (
    "Ranking phase. Read the brief and rank these reviewed proposals from most to least "
    "valuable for the charter's purpose, and then for their learning goals: {proposal_ids}."
)
_COMPACT_TASK = (
    "Compaction phase. Read the brief and replace the notebook with a shorter one. Keep "
    "every finding a later phase still needs, its references, and why proposals were "
    "withdrawn. Drop duplicates and detail that no open proposal depends on."
)
_STUDENT_TASK = (
    "Trial simulation. Play one student in this course who is talking to the Course Agent; "
    "you are not the agent. The student: {persona}\nTheir situation: {situation}\n\n"
    "{so_far}\n\nWrite only the student's next message, in their own voice, in at most a "
    "few sentences. Stay in character: do not become more cooperative, more articulate, or "
    "better informed than this student would be, and do not mention that this is a "
    "simulation."
)
_JUDGE_TASK = (
    "Replay scoring. A student wrote:\n{message}\n\nThe Course Agent replied:\n{reply}\n\n"
    "Rubric:\n{rubric}\n\nScore the reply against the rubric only."
)


@dataclass(frozen=True)
class LoopBudget:
    """Deployment-tunable limits for one cycle."""

    max_runs: int = 60
    research_runs: int = 2
    max_proposals: int = 3
    top_k: int = 2
    # Student messages, each answered once, in one simulated trial conversation.
    trial_exchanges: int = 3


@dataclass(frozen=True)
class LoopStep:
    """Inspectable record of one orchestration step."""

    phase: LoopPhase | str
    detail: str
    conversation_id: UUID | None = None
    # For a graded phase: what was graded, the rubric used, and the grade recorded. Present
    # only when the run actually recorded a grade.
    grade: Mapping[str, JsonValue] | None = None


class _BudgetExhausted(Exception):
    pass


class ImprovementLoop:
    def __init__(
        self,
        *,
        runtime: AgentRuntime,
        conversations: ConversationStore,
        service: ImprovementService,
        capability_policy: CourseCapabilityPolicy,
        skills: SkillCatalog | None = None,
        budget: LoopBudget | None = None,
        observer: Callable[[LoopStep], None] | None = None,
    ) -> None:
        self._runtime = runtime
        self._conversations = conversations
        self._service = service
        self._capability_policy = capability_policy
        self._skills = skills
        self._budget = budget or LoopBudget()
        self._observer = observer or (lambda _step: None)
        self._runs = 0

    def _spend_run(self) -> None:
        if self._runs >= self._budget.max_runs:
            raise _BudgetExhausted
        self._runs += 1

    async def _run_phase(
        self,
        principal: PrincipalContext,
        phase: LoopPhase,
        task: str,
        *,
        subject: Mapping[str, JsonValue] | None = None,
        grade: Callable[[], Mapping[str, JsonValue] | None] | None = None,
    ) -> str:
        """Run the Course Agent once with only this phase's tools and a fresh context.

        ``subject`` names what a graded phase is grading and under which rubric; it is
        recorded with the run. ``grade`` reads the recorded grade back from loop state.
        """

        self._spend_run()
        authorized = self._capability_policy.authorize(principal)
        reads = phase in READ_PHASES
        read_tools = [tool for tool in authorized.tool_ids if reads and tool in LOOP_READ_TOOL_IDS]
        skills = self._skills.authorized_metadata(principal) if self._skills and reads else ()
        if skills:
            read_tools += [READ_SKILL_TOOL_ID, READ_SKILL_REFERENCE_TOOL_ID]
        conversation = Conversation(
            user_id=principal.user_id, title=f"Course improvement · {phase}"
        )
        await self._conversations.create_conversation(conversation)
        request = Event(
            type="improvement.phase.requested",
            actor="platform",
            principal_user_id=principal.user_id,
            conversation_id=conversation.id,
            payload={"phase": phase, **{k: v for k, v in (subject or {}).items() if k != "rubric"}},
        )
        result = await self._runtime.run(
            context=AgentContext(
                principal=principal,
                conversation_id=conversation.id,
                permitted_tool_ids=[*PHASE_WRITE_TOOL_IDS[phase], *read_tools],
                permitted_resource_uris=list(authorized.resource_uris) if reads else [],
                metadata={
                    "improvement_phase": {"phase": phase, **(subject or {})},
                    "authorized_resource_index": list(authorized.resource_index) if reads else [],
                    "authorized_skill_index": [
                        {"id": skill.id, "name": skill.name, "description": skill.description}
                        for skill in skills
                    ],
                },
            ),
            input=AgentInput(conversation_id=conversation.id, text=task),
        )
        await self._conversations.append_events(conversation.id, [request, *result.events])
        recorded = grade() if grade is not None else None
        self._observer(
            LoopStep(
                phase,
                result.output_text,
                conversation.id,
                {**(subject or {}), **recorded} if recorded is not None else None,
            )
        )
        return result.output_text

    async def _student_reply(
        self,
        principal: PrincipalContext,
        scenario: ReplayScenario,
        proposal_id: UUID | None,
    ) -> AgentResult:
        """Answer a synthetic scenario as a tool-less student run; nothing is persisted."""

        self._spend_run()
        student = PrincipalContext(
            authenticated=True,
            user_id=uuid4(),
            username="replay-student",
            roles=["public", "student"],
            session_id=uuid4(),
        )
        conversation_id = uuid4()
        return await self._runtime.run(
            context=AgentContext(
                principal=student,
                conversation_id=conversation_id,
                metadata={
                    "adaptive_guidance": self._service.guidance_for_replay(principal, proposal_id)
                },
            ),
            input=AgentInput(conversation_id=conversation_id, text=scenario.student_message),
        )

    async def _trial(self, principal: PrincipalContext, proposal: Proposal) -> None:
        """Try the proposed skill in one simulated student conversation and record it.

        A second model plays the student from the charter's persona. The Course Agent
        answers as it would a real student, with the candidate added to its skill index;
        whether it loads the skill is its own choice and is recorded.
        """

        persona = self._service.next_trial_persona(proposal)
        if persona is None:
            return
        conversation_id = uuid4()
        skill = self._service.open_trial(principal, proposal.id, conversation_id)
        student = PrincipalContext(
            authenticated=True,
            user_id=uuid4(),
            username="trial-student",
            roles=["public", "student"],
            session_id=uuid4(),
        )
        subject: dict[str, JsonValue] = {
            "proposal_id": str(proposal.id),
            "revision": proposal.revision,
            "persona": persona.id,
        }
        registered = self._skills.authorized_metadata(student) if self._skills else ()
        messages: list[TrialMessage] = []
        events: list[Event] = []
        for _exchange in range(min(self._budget.trial_exchanges, MAX_TRIAL_MESSAGES // 2)):
            so_far = "\n".join(
                f"{'Student' if item.role == 'student' else 'Course Agent'}: {item.text}"
                for item in messages
            )
            said = (
                await self._run_phase(
                    principal,
                    "trial",
                    _STUDENT_TASK.format(
                        persona=persona.description,
                        situation=proposal.draft.trigger,
                        so_far=f"The conversation so far:\n{so_far}"
                        if so_far
                        else "The conversation has not started; write the opening message.",
                    ),
                    subject=subject,
                )
            ).strip()[:MAX_TRIAL_MESSAGE_CHARACTERS]
            if not said:
                break
            self._spend_run()
            reply = await self._runtime.run(
                context=AgentContext(
                    principal=student,
                    conversation_id=conversation_id,
                    recent_events=list(events),
                    permitted_tool_ids=[
                        READ_SKILL_TOOL_ID,
                        *([READ_SKILL_REFERENCE_TOOL_ID] if registered else []),
                    ],
                    metadata={
                        "improvement_phase": {"phase": "trial", "role": "agent", **subject},
                        "authorized_skill_index": [
                            *(
                                {"id": item.id, "name": item.name, "description": item.description}
                                for item in registered
                                if item.id != skill["id"]
                            ),
                            skill,
                        ],
                        "adaptive_guidance": self._service.guidance_for_replay(principal, None),
                    },
                ),
                input=AgentInput(conversation_id=conversation_id, text=said),
            )
            answered = reply.output_text.strip()[:MAX_TRIAL_MESSAGE_CHARACTERS]
            if not answered:
                break
            messages += [
                TrialMessage(role="student", text=said),
                TrialMessage(role="agent", text=answered),
            ]
            events += [
                Event(
                    type="user.message",
                    actor="user",
                    principal_user_id=student.user_id,
                    conversation_id=conversation_id,
                    payload={"text": said},
                ),
                Event(
                    type="agent.message",
                    actor="course-agent",
                    principal_user_id=student.user_id,
                    conversation_id=conversation_id,
                    payload={"text": answered},
                ),
            ]
        if messages:
            recorded = self._service.record_trial(principal, proposal.id, messages).trials[-1]
            self._observer(
                LoopStep(
                    "trial",
                    f"{persona.id}: {len(messages) // 2} exchanges, skill "
                    f"{'loaded' if recorded.skill_loaded else 'not loaded'}",
                )
            )

    async def _replay(self, principal: PrincipalContext, proposal_id: UUID | None) -> None:
        for scenario in self._service.scenarios:
            reply = await self._student_reply(principal, scenario, proposal_id)
            self._service.open_replay(principal, proposal_id, scenario.id)
            await self._run_phase(
                principal,
                "replay",
                _JUDGE_TASK.format(
                    message=scenario.student_message,
                    reply=reply.output_text,
                    rubric=scenario.rubric,
                ),
                subject={
                    "proposal_id": str(proposal_id) if proposal_id else None,
                    "scenario_id": scenario.id,
                    "rubric": scenario.rubric,
                },
                grade=partial(self._replay_grade, principal, proposal_id, scenario.id),
            )

    def _replay_grade(
        self, principal: PrincipalContext, proposal_id: UUID | None, scenario_id: str
    ) -> Mapping[str, JsonValue] | None:
        score = self._service.replay_score(principal, proposal_id, scenario_id)
        return None if score is None else {"score": score}

    def _critique_grade(
        self, principal: PrincipalContext, proposal_id: UUID, lens: str, revision: int
    ) -> Mapping[str, JsonValue] | None:
        for item in reversed(self._service.get(principal, proposal_id).critiques):
            if item.lens == lens and item.revision == revision:
                return {"verdict": item.verdict, "issues": list(item.issues)}
        return None

    async def _compact_if_needed(self, principal: PrincipalContext) -> None:
        if self._service.notebook_needs_compaction():
            await self._run_phase(principal, "compact", _COMPACT_TASK)

    def _in_review(self, principal: PrincipalContext) -> list[Proposal]:
        return [
            proposal
            for proposal in self._service.proposals(principal)
            if proposal.status == "in_review" and self._service.outcome(proposal)[0] != "eligible"
        ]

    async def _review(self, principal: PrincipalContext) -> None:
        # Bound: per proposal, at most max_rounds revisions, each tried once per persona or
        # replayed, graded once per lens, then revised. A run that records nothing cannot
        # extend the loop.
        steps_per_round = len(self._service.lenses) + len(self._service.personas) + 2
        for _round in range(steps_per_round * self._service.max_rounds):
            pending = self._in_review(principal)
            if not pending:
                return
            for proposal in pending:
                outcome, _reason = self._service.outcome(proposal)
                if outcome == "needs_replay":
                    await self._replay(principal, proposal.id)
                elif outcome == "needs_trial":
                    await self._trial(principal, proposal)
                elif outcome == "needs_critique":
                    lens = self._service.next_lens(proposal)
                    if lens is None:
                        continue
                    await self._run_phase(
                        principal,
                        "critique",
                        _CRITIQUE_TASK.format(
                            proposal_id=proposal.id, lens=lens.id, rubric=lens.rubric
                        ),
                        subject={
                            "proposal_id": str(proposal.id),
                            "revision": proposal.revision,
                            "lens": lens.id,
                            "rubric": lens.rubric,
                        },
                        grade=partial(
                            self._critique_grade,
                            principal,
                            proposal.id,
                            lens.id,
                            proposal.revision,
                        ),
                    )
                elif outcome == "needs_revision":
                    issues = "\n".join(
                        f"- {item['issue_id']} ({item['lens']}): {item['text']}"
                        for item in self._service.open_issues(proposal)
                    )
                    await self._run_phase(
                        principal,
                        "revise",
                        _REVISE_TASK.format(proposal_id=proposal.id, issues=issues),
                        subject={"proposal_id": str(proposal.id), "revision": proposal.revision},
                    )
            await self._compact_if_needed(principal)

    async def run_cycle(self, principal: PrincipalContext) -> list[Proposal]:
        """Run one cycle and return the proposals that passed review and ranking."""

        self._service.brief(principal)  # Fails closed for a non-instructor before any run.
        self._runs = 0
        try:
            for _ in range(self._budget.research_runs):
                await self._run_phase(principal, "research", _RESEARCH_TASK)
                await self._compact_if_needed(principal)
            await self._run_phase(
                principal, "propose", _PROPOSE_TASK.format(count=self._budget.max_proposals)
            )
            if self._service.scenarios and any(
                proposal.draft.kind == "agent_guidance" for proposal in self._in_review(principal)
            ):
                await self._replay(principal, None)
            await self._review(principal)
            eligible = self._service.eligible(principal)
            if len(eligible) > 1:
                await self._run_phase(
                    principal,
                    "rank",
                    _RANK_TASK.format(
                        proposal_ids=", ".join(str(proposal.id) for proposal in eligible)
                    ),
                )
        except _BudgetExhausted:
            self._observer(LoopStep("budget", "Run budget exhausted; closing the cycle early."))
        graduated = self._service.close_cycle(principal, top_k=self._budget.top_k)
        for proposal in graduated:
            self._observer(LoopStep("gate", f"{proposal.draft.title}: {proposal.status}"))
        return graduated
