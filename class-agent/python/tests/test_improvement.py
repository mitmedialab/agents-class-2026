from __future__ import annotations

import asyncio
import importlib
import importlib.util
import json
import re
from datetime import date
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from agent_core import AgentContext, AgentInput, AgentResult, PrincipalContext
from course_server.agent import (
    CourseAgentService,
    CourseCapabilityPolicy,
    FileResourceProvider,
    InMemoryConversationStore,
)
from course_server.agent.capabilities import COURSE_SYLLABUS_URI, ToolExecutionContext
from course_server.agent.skills import READ_SKILL_TOOL_ID, ReadSkillTool, SkillCatalog
from course_server.improvement import (
    Charter,
    EvidenceDigest,
    ImprovementAccessDenied,
    ImprovementLoop,
    ImprovementService,
    ImprovementStateError,
    LearningGoals,
    LoopBudget,
    PrivacyScreen,
    Proposal,
    ProposalDraft,
    ReplayScenarios,
    improvement_tools,
    load_charter,
    load_learning_goals,
)
from course_server.improvement.artifacts import MOCKUP_SHELL_CSS, review_file
from course_server.improvement.models import IssueResponse, TrialMessage
from course_server.improvement.policy import (
    MAX_IN_REVIEW_PROPOSALS,
    MAX_REVIEW_ROUNDS,
    assess_proposal,
)
from course_server.improvement.tool_ids import (
    LOOP_READ_TOOL_IDS,
    LOOP_WITHHELD_TOOL_IDS,
    PHASE_WRITE_TOOL_IDS,
    PROPOSE_CHANGE_TOOL_ID,
    SUBMIT_CRITIQUE_TOOL_ID,
)
from course_server.improvement.tools import TrialSkillReadTool
from course_server.student_project_tool_ids import INSPECT_STUDENT_REPOSITORY_TOOL_ID
from runtime_smolagents.runtime import _agent_instructions

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
GOALS = LearningGoals.model_validate(
    {
        "schema_version": 1,
        "goals": [
            {"id": "build-agents", "statement": "Build agents."},
            {"id": "evaluate-agents", "statement": "Evaluate agents."},
        ],
    }
)
CHARTER = Charter.model_validate(
    {
        "schema_version": 1,
        "purpose": "Improve the student's experience of the Course Agent.",
        "directions": [
            {"id": "own-work", "statement": "Tie goals to the student's own work."},
            {"id": "peer-connection", "statement": "Connect students."},
        ],
        "lenses": [
            {"id": "evidence", "rubric": "Claims rest on cited evidence."},
            {"id": "scope", "rubric": "One small experience."},
        ],
        "sources": ["course://schedule"],
    }
)
EVIDENCE = EvidenceDigest.model_validate(
    {
        "schema_version": 1,
        "period": "2026-W47",
        "cohort_size": 30,
        "synthetic": True,
        "signals": [
            {
                "id": "full-code",
                "goal_id": "build-agents",
                "source": "conversations",
                "observation": "Students asked for complete code.",
                "student_count": 9,
            }
        ],
    }
)
SCENARIOS = ReplayScenarios.model_validate(
    {
        "schema_version": 1,
        "synthetic": True,
        "scenarios": [
            {
                "id": "stuck-loop",
                "goal_id": "build-agents",
                "student_message": "Give me the fix.",
                "rubric": "Prefer a hint.",
            }
        ],
    }
)
NO_SCENARIOS = ReplayScenarios(schema_version=1, scenarios=[])
TRIAL_CHARTER = Charter.model_validate(
    {
        **CHARTER.model_dump(),
        "trial_personas": [
            {"id": "engaged", "description": "Answers specifically."},
            {"id": "rushed", "description": "Wants the agent to decide."},
        ],
    }
)
EXCHANGE = [
    TrialMessage(role="student", text="Help me review a failure."),
    TrialMessage(role="agent", text="What failed?"),
]


def principal(role: str) -> PrincipalContext:
    return PrincipalContext(
        authenticated=True,
        user_id=uuid4(),
        username=f"test-{role}",
        roles=["public", role],
        session_id=uuid4(),
    )


MOCKUP = "<style>.card { color: #eee; }</style>" + "".join(
    f'<section class="mk-screen" data-step="{step}"><a href="#next">Goal map</a></section>'
    for step in ("trigger", "agent", "student")
)
SKILL = "---\nname: failure-review\ndescription: Review a failure case.\n---\n\nAsk what failed."
ARTIFACTS: dict[str, dict[str, str]] = {
    "ui_feature": {"format": "html_mockup", "content": MOCKUP},
    "agent_skill": {"format": "skill", "content": SKILL},
    "course_content": {"format": "markdown", "content": "## Failure cases\n\nDescribe one."},
}


def draft(kind: str = "agent_guidance", **overrides: object) -> ProposalDraft:
    return ProposalDraft.model_validate(
        {
            "kind": kind,
            "title": "Hint first",
            "rationale": "Students ask for complete code.",
            "goal_id": "build-agents",
            "direction": "own-work",
            "course_week": 4,
            "trigger": "A student asks for the fix during a weekly build.",
            "agent_action": "Asks one question about the student's loop.",
            "student_action": "Checks that part of their code.",
            "builds_on": "The Course Agent chat.",
            "artifact": ARTIFACTS.get(kind),
            "body": "Give one targeted hint before any complete code.",
            "signal_ids": ["full-code"],
            **overrides,
        }
    )


def service(
    scenarios: ReplayScenarios = NO_SCENARIOS,
    max_rounds: int = MAX_REVIEW_ROUNDS,
    charter: Charter = CHARTER,
) -> ImprovementService:
    return ImprovementService(
        max_rounds=max_rounds,
        goals=GOALS,
        charter=charter,
        today=lambda: date(2026, 10, 8),
        evidence=EVIDENCE,
        scenarios=scenarios,
        privacy=PrivacyScreen(["Ada Lovelace", "alovelace"]),
    )


def test_learning_goal_asset_matches_the_syllabus_text() -> None:
    resources = FileResourceProvider.from_registry()
    goals = asyncio.run(load_learning_goals(resources))
    syllabus = asyncio.run(resources.read(COURSE_SYLLABUS_URI)).text

    assert len(goals.goals) == 7
    for goal in goals.goals:
        assert goal.statement in syllabus


def test_evidence_rejects_a_signal_about_too_few_students() -> None:
    payload = EVIDENCE.model_dump(mode="json")
    payload["signals"][0]["student_count"] = 2

    with pytest.raises(ValidationError):
        EvidenceDigest.model_validate(payload)


@pytest.mark.parametrize(
    ("proposal", "reasons"),
    [
        (draft(), []),
        (draft("ui_feature"), ["kind_requires_approval"]),
        (draft("course_content"), ["kind_requires_approval"]),
        (draft("agent_skill"), ["kind_requires_approval"]),
        (
            draft(
                "ui_feature", artifact={"format": "html_mockup", "content": "<p>Ada Lovelace</p>"}
            ),
            ["kind_requires_approval", "mentions_course_member"],
        ),
        (
            draft("private_data_use", data_categories=["grades_feedback"]),
            ["kind_requires_approval", "declares_private_data"],
        ),
        (draft(data_categories=["conversation_text"]), ["declares_private_data"]),
        (draft(body="Remind Ada Lovelace to add a stop condition."), ["mentions_course_member"]),
        (draft(rationale="Reported by ALOVELACE."), ["mentions_course_member"]),
        (draft(body="Send questions to ta@example.edu."), ["contains_contact_detail"]),
    ],
)
def test_only_clean_agent_guidance_skips_human_approval(
    proposal: ProposalDraft, reasons: list[str]
) -> None:
    assessment = assess_proposal(proposal, PrivacyScreen(["Ada Lovelace", "alovelace"]))

    assert assessment.reasons == reasons
    assert assessment.requires_human_approval is bool(reasons)


@pytest.mark.parametrize(
    ("kind", "artifact"),
    [
        ("ui_feature", None),
        ("agent_skill", None),
        ("course_content", None),
        ("ui_feature", ARTIFACTS["course_content"]),
        ("agent_guidance", ARTIFACTS["course_content"]),
    ],
)
def test_each_kind_requires_its_own_deliverable(kind: str, artifact: object) -> None:
    with pytest.raises(ValidationError, match="proposal requires"):
        draft(kind, artifact=artifact)


@pytest.mark.parametrize(
    "content",
    [
        "<script>alert(1)</script>",
        '<p onclick="go()">Open</p>',
        '<a href="https://example.com">Open</a>',
        '<a href="javascript:go()">Open</a>',
        '<img src="//example.com/a.png">',
        '<form action="#"><input></form>',
        "<textarea>Plan</textarea>",
        '<a href="#a b">Open</a>',
        # A single panel, or screens out of order, is not the whole flow.
        '<section data-step="agent">Goal map</section>',
        "".join(
            f'<section data-step="{step}"></section>' for step in ("agent", "trigger", "student")
        ),
        '<iframe src="#"></iframe>',
        "<style>@import 'x.css';</style>",
        '<p style="background: URL(x.png)">Hi</p>',
    ],
)
def test_mockup_that_could_run_or_load_anything_is_refused(content: str) -> None:
    improvement = service()

    with pytest.raises(ImprovementStateError, match="static, self-contained"):
        improvement.propose(
            principal("instructor"),
            uuid4(),
            draft("ui_feature", artifact={"format": "html_mockup", "content": content}),
        )
    assert improvement.proposals(principal("instructor")) == []


@pytest.mark.parametrize("content", ["Just steps.", "---\nname: Bad Name\n---\nSteps", SKILL[:-16]])
def test_skill_deliverable_must_be_a_valid_skill_file(content: str) -> None:
    with pytest.raises(ImprovementStateError, match=r"SKILL\.md"):
        service().propose(
            principal("instructor"),
            uuid4(),
            draft("agent_skill", artifact={"format": "skill", "content": content}),
        )


def test_review_file_isolates_a_mockup_and_passes_other_deliverables_through() -> None:
    improvement = service()
    instructor = principal("instructor")
    mockup = improvement.propose(instructor, uuid4(), draft("ui_feature"))
    skill = improvement.propose(instructor, uuid4(), draft("agent_skill"))
    guidance = improvement.propose(instructor, uuid4(), draft())

    name, document = review_file(mockup) or ("", "")
    assert name.endswith(".html")
    assert "Content-Security-Policy" in document and "default-src 'none'" in document
    assert MOCKUP in document
    assert review_file(skill) == (f"agent_skill-{str(skill.id)[:8]}-r1.md", SKILL)
    assert review_file(guidance) is None


def test_review_queue_is_bounded() -> None:
    improvement = service()
    instructor = principal("instructor")
    for _ in range(MAX_IN_REVIEW_PROPOSALS):
        improvement.propose(instructor, uuid4(), draft())

    with pytest.raises(ImprovementStateError, match="already in review"):
        improvement.propose(instructor, uuid4(), draft())


def test_charter_asset_loads_and_orients_the_brief() -> None:
    charter = asyncio.run(load_charter(FileResourceProvider.from_registry()))

    assert "experience of a student using the Course Agent" in charter.purpose
    assert [direction.id for direction in charter.directions] == [
        "goal-progress",
        "peer-connection",
        "own-work",
    ]
    brief = service().brief(principal("instructor"))
    assert brief["today"] == "2026-10-08"
    assert brief["charter"] == CHARTER.model_dump(mode="json", exclude={"schema_version"})


@pytest.mark.parametrize(
    "overrides",
    [
        {"goal_ids": ["build-agents", "evaluate-agents"]},
        {"goal_id": ["build-agents", "evaluate-agents"]},
        {"direction": ["own-work", "peer-connection"]},
        {"trigger": "A student submits a build, joins a group, and books a review. " * 4},
        {"agent_action": ""},
        {"builds_on": None},
    ],
)
def test_a_proposal_is_one_flow_for_one_goal_and_one_direction(
    overrides: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        draft("agent_guidance", **overrides)


@pytest.mark.parametrize("overrides", [{"direction": "team-building"}, {"goal_id": "have-fun"}])
def test_proposal_anchors_must_be_registered(overrides: dict[str, object]) -> None:
    with pytest.raises(ImprovementStateError, match="must name"):
        service().propose(principal("instructor"), uuid4(), draft("agent_guidance", **overrides))


def test_private_data_proposal_must_declare_its_categories() -> None:
    with pytest.raises(ValidationError):
        draft("private_data_use")


@pytest.mark.parametrize("role", ["student", "ta"])
def test_only_instructors_can_use_or_decide_the_loop(role: str) -> None:
    improvement = service()
    instructor = principal("instructor")
    proposal = improvement.propose(instructor, uuid4(), draft("ui_feature"))
    outsider = principal(role)

    with pytest.raises(ImprovementAccessDenied):
        improvement.brief(outsider)
    with pytest.raises(ImprovementAccessDenied):
        improvement.propose(outsider, uuid4(), draft())
    with pytest.raises(ImprovementAccessDenied):
        improvement.decide(outsider, proposal.id, "approve")


def resolved(improvement: ImprovementService, proposal_id: UUID) -> list[IssueResponse]:
    """Answer every open issue as resolved, as a compliant author would."""

    proposal = improvement.get(principal("instructor"), proposal_id)
    return [
        IssueResponse(issue_id=item["issue_id"], action="resolved", note="Fixed.")
        for item in improvement.open_issues(proposal)
    ]


def test_every_lens_must_accept_the_same_revision() -> None:
    improvement = service()
    instructor = principal("instructor")
    proposal = improvement.propose(instructor, uuid4(), draft("ui_feature"))

    improvement.critique(instructor, proposal.id, "revise", ["No cited signal."])
    with pytest.raises(ImprovementStateError):  # The panel has not finished this revision.
        improvement.revise(instructor, proposal.id, draft("ui_feature"), [])
    improvement.critique(instructor, proposal.id, "accept", [])
    assert improvement.eligible(instructor) == []
    with pytest.raises(ImprovementStateError):
        improvement.critique(instructor, proposal.id, "accept", [])
    with pytest.raises(ImprovementStateError):
        improvement.revise(
            instructor, proposal.id, draft("agent_guidance"), resolved(improvement, proposal.id)
        )
    improvement.revise(
        instructor,
        proposal.id,
        draft("ui_feature", title="Narrower"),
        resolved(improvement, proposal.id),
    )
    improvement.critique(instructor, proposal.id, "accept", [])
    assert improvement.eligible(instructor) == []
    improvement.critique(instructor, proposal.id, "accept", [])

    assert [item.draft.title for item in improvement.eligible(instructor)] == ["Narrower"]
    graded = improvement.get(instructor, proposal.id).critiques
    assert [(item.revision, item.lens) for item in graded] == [
        (1, "evidence"),
        (1, "scope"),
        (2, "evidence"),
        (2, "scope"),
    ]


def test_a_revision_must_answer_each_open_issue_by_citation() -> None:
    improvement = service()
    instructor = principal("instructor")
    proposal = improvement.propose(instructor, uuid4(), draft("ui_feature"))
    improvement.critique(instructor, proposal.id, "revise", ["Add a safeguard."])
    improvement.critique(instructor, proposal.id, "revise", ["Too many safeguards."])

    brief = improvement.brief(instructor)["proposals"]
    assert isinstance(brief, list) and isinstance(brief[0], dict)
    assert brief[0]["critiques"] == [
        {
            "revision": 1,
            "lens": "evidence",
            "verdict": "revise",
            "issues": [{"issue_id": "r1.evidence.1", "text": "Add a safeguard."}],
        },
        {
            "revision": 1,
            "lens": "scope",
            "verdict": "revise",
            "issues": [{"issue_id": "r1.scope.1", "text": "Too many safeguards."}],
        },
    ]
    kept = IssueResponse(issue_id="r1.evidence.1", action="resolved", note="Added one.")
    with pytest.raises(ImprovementStateError, match=r"r1\.evidence\.1, r1\.scope\.1"):
        improvement.revise(instructor, proposal.id, draft("ui_feature"), [kept])
    with pytest.raises(ImprovementStateError, match="conflicts_with"):
        improvement.revise(
            instructor,
            proposal.id,
            draft("ui_feature"),
            [
                kept,
                IssueResponse(
                    issue_id="r1.scope.1",
                    action="declined",
                    note="Needed.",
                    conflicts_with="r9.privacy.1",
                ),
            ],
        )
    declined = IssueResponse(
        issue_id="r1.scope.1",
        action="declined",
        note="The safeguard is needed.",
        conflicts_with="r1.evidence.1",
    )
    revised = improvement.revise(instructor, proposal.id, draft("ui_feature"), [kept, declined])

    assert revised.revision == 2 and revised.responses == [kept, declined]
    with pytest.raises(ValidationError):
        IssueResponse(
            issue_id="r1.scope.1", action="resolved", note="x", conflicts_with="r1.evidence.1"
        )


def test_rejection_and_round_limit_withdraw_without_reaching_a_human() -> None:
    improvement = service()
    instructor = principal("instructor")
    rejected = improvement.propose(instructor, uuid4(), draft("ui_feature"))
    endless = improvement.propose(instructor, uuid4(), draft("ui_feature"))

    improvement.critique(instructor, rejected.id, "reject", ["Unsupported."])
    for _ in range(MAX_REVIEW_ROUNDS):
        improvement.critique(instructor, endless.id, "revise", ["Still vague."])
        improvement.critique(instructor, endless.id, "accept", [])
        if improvement.get(instructor, endless.id).status == "in_review":
            improvement.revise(
                instructor, endless.id, draft("ui_feature"), resolved(improvement, endless.id)
            )
    graduated = improvement.close_cycle(instructor, top_k=5)

    assert graduated == []
    assert improvement.get(instructor, rejected.id).status_reason == "critic_rejected"
    assert improvement.get(instructor, endless.id).status_reason == "critique_limit_reached"
    assert improvement.get(instructor, endless.id).revision == MAX_REVIEW_ROUNDS
    with pytest.raises(ImprovementStateError):
        improvement.critique(instructor, rejected.id, "accept", [])


def test_guidance_must_beat_the_replay_baseline_before_any_critique() -> None:
    improvement = service(SCENARIOS)
    instructor = principal("instructor")
    proposal = improvement.propose(instructor, uuid4(), draft())

    with pytest.raises(ImprovementStateError):
        improvement.critique(instructor, proposal.id, "accept", [])
    with pytest.raises(ImprovementStateError):
        improvement.score_open_replay(instructor, 4)
    improvement.open_replay(instructor, None, "stuck-loop")
    improvement.score_open_replay(instructor, 2)
    improvement.open_replay(instructor, proposal.id, "stuck-loop")
    with pytest.raises(ImprovementStateError):
        improvement.score_open_replay(instructor, 5)
    improvement.open_replay(instructor, proposal.id, "stuck-loop")
    improvement.score_open_replay(instructor, 2)

    withdrawn = improvement.get(instructor, proposal.id)
    assert withdrawn.status == "withdrawn"
    assert withdrawn.status_reason == "replay_not_better_than_baseline"


def reviewed(
    improvement: ImprovementService, instructor: PrincipalContext, item: ProposalDraft
) -> Proposal:
    proposal = improvement.propose(instructor, uuid4(), item)
    improvement.critique(instructor, proposal.id, "accept", [])
    improvement.critique(instructor, proposal.id, "accept", [])
    return proposal


def test_gate_adopts_guidance_holds_critical_changes_and_shelves_the_rest() -> None:
    improvement = service()
    instructor = principal("instructor")
    student = principal("student")
    guidance = reviewed(improvement, instructor, draft())
    feature = reviewed(improvement, instructor, draft("ui_feature"))
    extra = reviewed(improvement, instructor, draft("course_content"))
    unreviewed = improvement.propose(instructor, uuid4(), draft("ui_feature"))

    with pytest.raises(ImprovementStateError):
        improvement.rank(instructor, [guidance.id, feature.id])
    improvement.rank(instructor, [guidance.id, feature.id, extra.id])
    improvement.close_cycle(instructor, top_k=2)

    adopted = improvement.get(instructor, guidance.id)
    assert (adopted.status, adopted.approval_source) == ("approved", "platform_policy")
    assert improvement.get(instructor, feature.id).status == "pending_approval"
    assert improvement.get(instructor, extra.id).status_reason == "ranked_below_cutoff"
    assert improvement.get(instructor, unreviewed.id).status_reason == "review_incomplete"
    assert asyncio.run(improvement.agent_guidance(student)) == [
        {
            "guidance": "Give one targeted hint before any complete code.",
            "goal_ids": ["build-agents"],
        }
    ]
    assert asyncio.run(improvement.agent_guidance(instructor)) == []

    with pytest.raises(ImprovementStateError):
        improvement.decide(instructor, guidance.id, "reject")
    decided = improvement.decide(instructor, feature.id, "approve", " Clear and small. ")
    assert (decided.approval_source, decided.decided_by_user_id) == ("human", instructor.user_id)
    assert decided.decision_reason == "Clear and small."
    # The human's judgement reaches later cycles, which start with no memory of this one.
    brief = json.loads(json.dumps(improvement.brief(instructor)))
    assert brief["notebook"][-1] == {
        "phase": "gate",
        "text": "Human approved (Clear and small.): Hint first",
        "references": [str(feature.id)],
    }
    assert [item["proposal_id"] for item in brief["adopted_features"]] == [
        str(guidance.id),
        str(feature.id),
    ]
    # An approved interface brief is a record for implementation, never runtime guidance.
    assert len(asyncio.run(improvement.agent_guidance(student))) == 1

    improvement.retire(instructor, guidance.id)
    assert asyncio.run(improvement.agent_guidance(student)) == []


def test_guidance_naming_a_course_member_waits_for_a_human() -> None:
    improvement = service()
    instructor = principal("instructor")
    named = reviewed(improvement, instructor, draft(body="Tell alovelace to add a stop check."))

    improvement.close_cycle(instructor, top_k=1)

    assert improvement.get(instructor, named.id).status == "pending_approval"
    assert asyncio.run(improvement.agent_guidance(principal("student"))) == []


def test_no_tool_can_decide_and_tools_recheck_the_instructor_role() -> None:
    improvement = service()
    tools = {tool.id: tool for tool in improvement_tools(improvement)}

    assert set(tools) == {tool for phase in PHASE_WRITE_TOOL_IDS.values() for tool in phase}
    assert not any(word in tool for tool in tools for word in ("approve", "decide", "retire"))
    assert PROPOSE_CHANGE_TOOL_ID not in PHASE_WRITE_TOOL_IDS["critique"]
    assert SUBMIT_CRITIQUE_TOOL_ID not in (
        *PHASE_WRITE_TOOL_IDS["propose"],
        *PHASE_WRITE_TOOL_IDS["revise"],
    )
    context = ToolExecutionContext(
        principal=principal("student"),
        conversation_id=uuid4(),
        permitted_resource_uris=frozenset(),
    )
    with pytest.raises(PermissionError):
        asyncio.run(tools[PROPOSE_CHANGE_TOOL_ID].execute(draft().model_dump(mode="json"), context))


class RecordingRuntime:
    """Runtime double that records the context of each run and does nothing."""

    def __init__(self) -> None:
        self.contexts: list[AgentContext] = []

    async def run(self, *, context: AgentContext, input: AgentInput) -> AgentResult:
        self.contexts.append(context)
        return AgentResult(
            input_id=input.id,
            conversation_id=context.conversation_id,
            output_text="done",
            events=[],
        )


def test_loop_scopes_tools_per_phase_and_requires_an_instructor() -> None:
    runtime = RecordingRuntime()
    conversations = InMemoryConversationStore()
    improvement = service()
    loop = ImprovementLoop(
        runtime=runtime,
        conversations=conversations,
        service=improvement,
        capability_policy=CourseCapabilityPolicy(
            student_projects_enabled=True, instructor_messaging_enabled=True
        ),
        budget=LoopBudget(research_runs=1),
    )

    with pytest.raises(ImprovementAccessDenied):
        asyncio.run(loop.run_cycle(principal("student")))
    assert runtime.contexts == []

    instructor = principal("instructor")
    asyncio.run(loop.run_cycle(instructor))

    research, propose = runtime.contexts
    # A read phase gets its one write plus every read tool the role policy authorizes;
    # the agent chooses among them. Nothing that acts or opens private records is offered.
    for context in (research, propose):
        offered = set(context.permitted_tool_ids)
        assert INSPECT_STUDENT_REPOSITORY_TOOL_ID in offered
        assert "course.get_schedule" in offered
        assert offered <= LOOP_READ_TOOL_IDS | set(PHASE_WRITE_TOOL_IDS["research"]) | set(
            PHASE_WRITE_TOOL_IDS["propose"]
        )
        assert offered.isdisjoint(LOOP_WITHHELD_TOOL_IDS)
    assert set(PHASE_WRITE_TOOL_IDS["propose"]) <= set(propose.permitted_tool_ids)
    assert PROPOSE_CHANGE_TOOL_ID not in research.permitted_tool_ids
    assert research.recent_events == []
    stored = [events[0] for events in conversations.events.values()]
    assert {event.type for event in stored} == {"improvement.phase.requested"}
    assert {event.principal_user_id for event in stored} == {instructor.user_id}


def test_every_course_agent_tool_is_classified_for_the_loop() -> None:
    modules = [
        "course_server.agent.capabilities",
        "course_server.agent.skills",
        "course_server.browser.constants",
        "course_server.student_project_tool_ids",
        "course_server.workspace.constants",
    ]
    known = {
        value
        for name in modules
        for attribute, value in vars(importlib.import_module(name)).items()
        if attribute.endswith("_TOOL_ID") and isinstance(value, str)
    }

    assert LOOP_READ_TOOL_IDS.isdisjoint(LOOP_WITHHELD_TOOL_IDS)
    assert known == LOOP_READ_TOOL_IDS | set(LOOP_WITHHELD_TOOL_IDS)
    assert "instructor.message_students" in LOOP_WITHHELD_TOOL_IDS
    assert "grades.get_mine" in LOOP_WITHHELD_TOOL_IDS


def test_loop_stops_at_its_run_budget_and_shelves_unfinished_review() -> None:
    runtime = RecordingRuntime()
    improvement = service()
    instructor = principal("instructor")
    improvement.propose(instructor, uuid4(), draft("ui_feature"))
    loop = ImprovementLoop(
        runtime=runtime,
        conversations=InMemoryConversationStore(),
        service=improvement,
        capability_policy=CourseCapabilityPolicy(),
        budget=LoopBudget(max_runs=4, research_runs=1),
    )

    assert asyncio.run(loop.run_cycle(instructor)) == []
    assert len(runtime.contexts) == 4
    assert [item.status_reason for item in improvement.proposals(instructor)] == [
        "review_incomplete"
    ]


def test_runtime_renders_adopted_guidance_and_ignores_malformed_items() -> None:
    context = AgentContext(
        principal=principal("student"),
        conversation_id=uuid4(),
        metadata={"adaptive_guidance": [{"guidance": "Hint before code."}, {"other": 1}, "x"]},
    )

    instructions = _agent_instructions(context, (), "")

    assert "Staff-governed teaching guidance" in instructions
    assert "- Hint before code." in instructions
    assert "Staff-governed" not in _agent_instructions(
        AgentContext(principal=principal("student"), conversation_id=uuid4()), (), ""
    )


def test_agent_service_supplies_adopted_guidance_to_student_runs_only() -> None:
    improvement = service()
    instructor = principal("instructor")
    reviewed(improvement, instructor, draft())
    improvement.close_cycle(instructor, top_k=1)
    runtime = RecordingRuntime()
    agent = CourseAgentService(
        runtime=runtime,
        conversations=InMemoryConversationStore(),
        capability_policy=CourseCapabilityPolicy(),
        guidance=improvement,
    )

    async def ask(user: PrincipalContext) -> None:
        conversation = await agent.create_conversation(user)
        await agent.run(principal=user, conversation_id=conversation.id, text="Help me.")

    asyncio.run(ask(principal("student")))
    asyncio.run(ask(instructor))

    student_run, instructor_run = runtime.contexts
    assert student_run.metadata["adaptive_guidance"] == [
        {
            "guidance": "Give one targeted hint before any complete code.",
            "goal_ids": ["build-agents"],
        }
    ]
    assert "adaptive_guidance" not in instructor_run.metadata


def test_offline_demo_runs_the_whole_cycle(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    path = REPOSITORY_ROOT / "examples/improvement_loop/demo.py"
    spec = importlib.util.spec_from_file_location("improvement_loop_demo", path)
    assert spec is not None and spec.loader is not None
    demo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(demo)

    asyncio.run(demo.run_demo("approve", out=tmp_path))

    output = capsys.readouterr().out
    assert "Adopted automatically" in output
    assert "it did not improve replies in replay" in output
    assert "a critic rejected it" in output
    assert "Human decision recorded: approved" in output
    (mockup,) = tmp_path.glob("ui_feature-*-r2.html")
    assert "Only you can see your status" in mockup.read_text(encoding="utf-8")
    after_cycle = output.split("6. Same student question after the cycle")[1]
    assert after_cycle.strip().startswith("Before I show anything")
    report = (tmp_path / "report.html").read_text(encoding="utf-8")
    assert "Learning-goal map on each assignment" in report
    assert "Publish a GRPO explainer in the FAQ</h2>" in report  # withdrawn, still explained
    assert "r1 privacy    revise · 1 issue" in output and "r2 usefulness accept" in output
    assert "<h2>Rubrics</h2>" in report and "leaves the thinking to the student" in report
    assert "usefulness gave way to privacy" in report
    assert "r1.usefulness.1 declined in favour of r1.privacy.1" in report
    assert "<iframe sandbox " in report and "srcdoc=" in report and "<script" not in report


@pytest.mark.parametrize(
    "arguments",
    [
        ["--real-projects", "--evidence", "digest.json"],
        ["--real-projects", "--live"],
    ],
)
def test_demo_refuses_real_repositories_with_scripted_or_synthetic_inputs(
    arguments: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    path = REPOSITORY_ROOT / "examples/improvement_loop/demo.py"
    spec = importlib.util.spec_from_file_location("improvement_loop_demo", path)
    assert spec is not None and spec.loader is not None
    demo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(demo)
    monkeypatch.setattr("sys.argv", ["demo.py", *arguments])

    with pytest.raises(SystemExit):
        demo.main()


def test_a_raised_round_limit_keeps_review_open_but_still_bounded() -> None:
    improvement = service(max_rounds=MAX_REVIEW_ROUNDS + 1)
    instructor = principal("instructor")
    proposal = improvement.propose(instructor, uuid4(), draft("ui_feature"))

    for _ in range(MAX_REVIEW_ROUNDS):
        improvement.critique(instructor, proposal.id, "revise", ["Still vague."])
        improvement.critique(instructor, proposal.id, "accept", [])
        improvement.revise(
            instructor, proposal.id, draft("ui_feature"), resolved(improvement, proposal.id)
        )
    assert improvement.get(instructor, proposal.id).status == "in_review"

    improvement.critique(instructor, proposal.id, "revise", ["Still vague."])
    improvement.critique(instructor, proposal.id, "accept", [])
    assert improvement.get(instructor, proposal.id).status_reason == "critique_limit_reached"

    with pytest.raises(ValueError):
        service(max_rounds=0)


def test_a_skill_is_tried_with_every_persona_before_each_panel_round() -> None:
    improvement = service(charter=TRIAL_CHARTER)
    instructor = principal("instructor")
    skill = improvement.propose(instructor, uuid4(), draft("agent_skill"))
    mockup = improvement.propose(instructor, uuid4(), draft("ui_feature"))

    # Only a kind the platform can run as written is tried; the rest go straight to the panel.
    assert improvement.outcome(mockup)[0] == "needs_critique"
    assert improvement.outcome(skill)[0] == "needs_trial"
    with pytest.raises(ImprovementStateError):
        improvement.critique(instructor, skill.id, "accept", [])
    with pytest.raises(ImprovementStateError):
        improvement.record_trial(instructor, skill.id, EXCHANGE)  # No trial was opened.
    with pytest.raises(ImprovementStateError):
        improvement.open_trial(instructor, mockup.id, uuid4())

    for persona in ("engaged", "rushed"):
        assert improvement.outcome(improvement.get(instructor, skill.id))[0] == "needs_trial"
        improvement.open_trial(instructor, skill.id, uuid4())
        tried = improvement.record_trial(instructor, skill.id, EXCHANGE)
        assert (tried.trials[-1].persona, tried.trials[-1].skill_loaded) == (persona, False)
    (briefed,) = [
        item
        for item in improvement.brief(instructor)["proposals"]  # type: ignore[union-attr]
        if item["proposal_id"] == str(skill.id)  # type: ignore[index,call-overload]
    ]
    assert [item["persona"] for item in briefed["trials"]] == ["engaged", "rushed"]  # type: ignore[index,call-overload,union-attr]

    improvement.critique(instructor, skill.id, "revise", ["The agent chose for the student."])
    improvement.critique(instructor, skill.id, "accept", [])
    revised = improvement.revise(
        instructor, skill.id, draft("agent_skill"), resolved(improvement, skill.id)
    )
    # A revision is a new implementation: it is tried again before the panel sees it.
    assert improvement.outcome(revised)[0] == "needs_trial"
    assert len(revised.trials) == 2

    # Without personas in the charter a skill is graded from its text, as before.
    untried = service()
    assert (
        untried.outcome(untried.propose(instructor, uuid4(), draft("agent_skill")))[0]
        == "needs_critique"
    )


def test_a_candidate_skill_loads_only_inside_its_own_trial_conversation() -> None:
    improvement = service(charter=TRIAL_CHARTER)
    instructor = principal("instructor")
    proposal = improvement.propose(instructor, uuid4(), draft("agent_skill"))
    tool = TrialSkillReadTool(improvement, ReadSkillTool(SkillCatalog([])))
    trial_conversation = uuid4()
    metadata = improvement.open_trial(instructor, proposal.id, trial_conversation)
    assert metadata == {
        "id": "failure-review",
        "name": "failure-review",
        "description": "Review a failure case.",
    }

    def read(conversation_id: UUID, skill_id: str) -> object:
        context = ToolExecutionContext(
            principal=principal("student"),
            conversation_id=conversation_id,
            permitted_resource_uris=frozenset(),
        )
        return asyncio.run(tool.execute({"skill_id": skill_id}, context)).content

    # Any other conversation, including a real student's, falls through to the registered
    # catalog, which has never heard of the unapproved skill.
    with pytest.raises(PermissionError):
        read(uuid4(), "failure-review")
    with pytest.raises(PermissionError):
        read(trial_conversation, "other")
    assert improvement.record_trial(instructor, proposal.id, EXCHANGE).trials[-1].skill_loaded is (
        False
    )

    improvement.open_trial(instructor, proposal.id, trial_conversation)
    assert read(trial_conversation, "failure-review") == {
        "skill_id": "failure-review",
        "instructions": "Ask what failed.",
        "references": [],
    }
    assert improvement.record_trial(instructor, proposal.id, EXCHANGE).trials[-1].skill_loaded
    # The trial is closed: the same conversation can no longer load the candidate.
    with pytest.raises(PermissionError):
        read(trial_conversation, "failure-review")


def test_loop_trials_a_skill_as_a_student_with_only_the_skill_reader() -> None:
    runtime = RecordingRuntime()
    improvement = service(charter=TRIAL_CHARTER, max_rounds=1)
    instructor = principal("instructor")
    proposal = improvement.propose(instructor, uuid4(), draft("agent_skill"))
    steps: list[str] = []
    loop = ImprovementLoop(
        runtime=runtime,
        conversations=InMemoryConversationStore(),
        service=improvement,
        capability_policy=CourseCapabilityPolicy(),
        budget=LoopBudget(research_runs=0, trial_exchanges=2),
        observer=lambda step: steps.append(f"{step.phase}:{step.detail}"),
    )

    asyncio.run(loop.run_cycle(instructor))

    trials = improvement.get(instructor, proposal.id).trials
    assert [(item.persona, len(item.messages)) for item in trials] == [
        ("engaged", 4),
        ("rushed", 4),
    ]
    assert "trial:engaged: 2 exchanges, skill not loaded" in steps
    agent_runs = [
        context
        for context in runtime.contexts
        if context.metadata.get("improvement_phase", {}).get("role") == "agent"  # type: ignore[union-attr]
    ]
    assert len(agent_runs) == 4
    for context in agent_runs:
        # The agent under trial is an ordinary student run: no loop tools, no instructor role.
        assert context.principal.roles == ["public", "student"]
        assert context.permitted_tool_ids == [READ_SKILL_TOOL_ID]
        assert context.permitted_resource_uris == []
        assert [item["id"] for item in context.metadata["authorized_skill_index"]] == [  # type: ignore[index,union-attr,call-overload]
            "failure-review"
        ]
    # Each trial is one conversation: the second exchange sees the first.
    assert [len(context.recent_events) for context in agent_runs] == [0, 2, 0, 2]
    assert agent_runs[0].conversation_id != agent_runs[2].conversation_id
    simulators = [
        context
        for context in runtime.contexts
        if context.metadata.get("improvement_phase", {}).get("phase") == "trial"  # type: ignore[union-attr]
        and context not in agent_runs
    ]
    assert len(simulators) == 4 and all(not item.permitted_tool_ids for item in simulators)


def test_mockup_shell_uses_the_site_tokens_and_reaches_author_and_reviewer() -> None:
    site = (REPOSITORY_ROOT / "packages/ui/src/styles.css").read_text(encoding="utf-8")
    tokens = re.findall(r"(--color-[a-z-]+): (#[0-9a-f]{6});", MOCKUP_SHELL_CSS)
    assert len(tokens) == 6
    for name, value in tokens:
        assert f"{name}: {value};" in site

    improvement = service()
    instructor = principal("instructor")
    guide = improvement.brief(instructor)["mockup"]
    assert isinstance(guide, dict) and guide["shell_stylesheet"] == MOCKUP_SHELL_CSS
    assert 'data-step="trigger"' in str(guide["rules"])
    exported = review_file(improvement.propose(instructor, uuid4(), draft("ui_feature")))
    assert exported is not None and ".mk-screen" in exported[1]
