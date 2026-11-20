"""Offline demonstration of one course-improvement cycle.

Run from ``class-agent/``::

    uv run python examples/improvement_loop/demo.py --decision approve
    uv run python examples/improvement_loop/demo.py --live

The platform code is real: the orchestrator, phase-scoped tools, review rules, risk gate,
human decision, and the guidance added to student runs. The evidence, replay scenarios,
and student repositories are always synthetic. Without ``--live`` a scripted model plays
the LLM so the demo needs no API key and always produces the same cycle. With ``--live``
the configured OpenAI model makes every choice; it reads ``OPENAI_API_KEY`` and optional
``MODEL_ID`` from the environment or ``.env`` and sends only the synthetic data.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import html
import json
import logging
import os
import re
import sys
import textwrap
import webbrowser
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Any, ClassVar
from uuid import UUID, uuid4

import httpx
from dotenv import load_dotenv
from pydantic import JsonValue, SecretStr
from smolagents import ChatMessage, ChatMessageToolCall, Model
from smolagents.models import ChatMessageToolCallFunction, MessageRole

from agent_core import (
    AgentContext,
    AgentInput,
    AgentResult,
    Event,
    ModelProvider,
    PrincipalContext,
)
from course_server.agent import (
    CourseAgentService,
    CourseCapabilityPolicy,
    FileResourceProvider,
    InMemoryConversationStore,
    ToolCatalog,
)
from course_server.agent.capabilities import (
    AuthorizedCapabilities,
    CourseGetScheduleTool,
    CourseReadPublicFileTool,
    CourseReadSyllabusTool,
    CourseSearchFaqTool,
    CourseSearchTool,
    CourseShowPublicFilesTool,
)
from course_server.agent.skills import ReadSkillReferenceTool, ReadSkillTool, SkillCatalog
from course_server.config import AgentSettings
from course_server.improvement import (
    EvidenceDigest,
    ImprovementLoop,
    ImprovementService,
    LoopBudget,
    LoopStep,
    PrivacyScreen,
    Proposal,
    ReplayScenarios,
    improvement_tools,
    load_charter,
    load_learning_goals,
    review_file,
)
from course_server.improvement.policy import MAX_REVIEW_ROUNDS
from course_server.improvement.tools import TrialSkillReadTool
from course_server.student_projects.client import (
    GitHubStudentProjectCatalog,
    RepositoryView,
    StudentProject,
    StudentProjectCatalog,
)
from course_server.student_projects.tools import (
    InspectStudentRepositoryTool,
    ListStudentProjectsTool,
)
from runtime_smolagents import SmolagentsRuntime
from runtime_smolagents.provider import OpenAIModelProvider

HERE = Path(__file__).resolve().parent
VISIBILITY_PLACEHOLDER = "__VISIBILITY_NOTE__"
GOAL_MAP_MOCKUP = (HERE / "goal-map.mockup.synthetic.html").read_text(encoding="utf-8")
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")

HINT_GUIDANCE = (
    "When a student asks for complete code for a weekly build, first give one targeted hint "
    "or question about their own loop, and offer the next step once they reply."
)
CODE_GUIDANCE = (
    "When a student is stuck on a weekly build, return complete working code immediately so "
    "they can keep moving."
)


class SyntheticProjects:
    """Invented repositories standing in for the course GitHub organization.

    They describe a plausible cohort in week 10 of the real schedule, so the demo runs on
    the real date and the real course materials.
    """

    _FILES: ClassVar[dict[str, dict[str, str]]] = json.loads(
        (HERE / "projects.synthetic.json").read_text(encoding="utf-8")
    )["projects"]

    def list_projects(self) -> list[StudentProject]:
        return [StudentProject(id=project_id, site_url=None) for project_id in self._FILES]

    def inspect_repository(
        self,
        project_id: str,
        view: RepositoryView,
        *,
        path: str | None = None,
        ref: str | None = None,
    ) -> dict[str, JsonValue]:
        del ref
        files = self._FILES[project_id]
        if view == "file" and path is not None:
            return {"project_id": project_id, "path": path, "text": files[path]}
        return {"project_id": project_id, "tree": sorted(files)}


class DemoPolicy(CourseCapabilityPolicy):
    """The real role rules, limited to the tools this offline demo registers."""

    def __init__(self, resources: FileResourceProvider, registered: frozenset[str]) -> None:
        super().__init__(resources, student_projects_enabled=True)
        self._registered = registered

    def authorize(self, principal: PrincipalContext) -> AuthorizedCapabilities:
        authorized = super().authorize(principal)
        return AuthorizedCapabilities(
            tool_ids=tuple(tool for tool in authorized.tool_ids if tool in self._registered),
            resource_uris=authorized.resource_uris,
        )


def _call(name: str, **arguments: Any) -> tuple[str, dict[str, Any]]:
    return name, arguments


class ScriptedCourseAgent(Model):  # type: ignore[misc]
    """Stand-in for the LLM: chooses tool calls from the phase it was given."""

    def __init__(self, service: ImprovementService, instructor: PrincipalContext) -> None:
        super().__init__(model_id="scripted-demo-model")
        self._service = service
        self._instructor = instructor
        self._plan: list[tuple[str, dict[str, Any]]] | None = None
        self._step = 0

    def generate(
        self,
        messages: list[ChatMessage],
        stop_sequences: list[str] | None = None,
        response_format: dict[str, str] | None = None,
        tools_to_call_from: list[Any] | None = None,
        **kwargs: Any,
    ) -> ChatMessage:
        del stop_sequences, response_format, kwargs
        if self._plan is None:
            text = "\n".join(str(message.content or "") for message in messages)
            self._plan = self._choose({tool.name for tool in tools_to_call_from or []}, text)
        name, arguments = self._plan[min(self._step, len(self._plan) - 1)]
        self._step += 1
        return ChatMessage(
            role=MessageRole.ASSISTANT,
            content="",
            tool_calls=[
                ChatMessageToolCall(
                    function=ChatMessageToolCallFunction(name=name, arguments=arguments),
                    id=f"call-{self._step}",
                    type="function",
                )
            ],
        )

    def _choose(self, tools: set[str], text: str) -> list[tuple[str, dict[str, Any]]]:
        brief = _call("improvement_read_brief")
        if "improvement_note_finding" in tools:
            return self._research(brief)
        if "improvement_compact_notebook" in tools:
            return [
                brief,
                _call(
                    "improvement_compact_notebook",
                    entries=[
                        {
                            "text": "Requests for complete code are common, and the sampled "
                            "week-4 loops lack a stop condition students could find themselves.",
                            "references": ["full-code-requests", "week-4/agent.py"],
                        },
                        {
                            "text": "Failure cases are missing or empty in sampled writeups; "
                            "students also ask which learning goal a build serves.",
                            "references": ["no-failure-cases", "goal-link-unclear"],
                        },
                    ],
                ),
                _call("final_answer", answer="Notebook compacted from 3 entries to 2."),
            ]
        if "improvement_propose_change" in tools:
            return [brief, *self._proposals(), _call("final_answer", answer="Proposed 4 changes.")]
        if "improvement_submit_critique" in tools:
            return self._critique(brief, text)
        if "improvement_revise_proposal" in tools:
            return self._revise(brief, text)
        if "improvement_rank_proposals" in tools:
            ranked = sorted(
                self._service.eligible(self._instructor),
                key=lambda proposal: proposal.draft.kind != "agent_guidance",
            )
            return [
                brief,
                _call("improvement_rank_proposals", proposal_ids=[str(p.id) for p in ranked]),
                _call("final_answer", answer="Ranked the hint-first guidance above the goal map."),
            ]
        if "improvement_score_replay" in tools:
            reply = text.split("The Course Agent replied:")[-1].split("Rubric:")[0]
            score = 4 if "full" not in reply else 2 if "because" in reply else 0
            return [
                _call("improvement_score_replay", score=score),
                _call("final_answer", answer=f"Scored the reply {score}/4."),
            ]
        return [_call("final_answer", answer=self._student_reply(text))]

    def _research(self, brief: tuple[str, dict[str, Any]]) -> list[tuple[str, dict[str, Any]]]:
        def inspect(project: str, path: str) -> tuple[str, dict[str, Any]]:
            return _call(
                "staff_inspect_student_repository", project_id=project, view="file", path=path
            )

        if not self._service.brief(self._instructor)["notebook"]:
            return [
                brief,
                _call("course_get_schedule"),
                inspect("agents2026-demo-a", "week-4/agent.py"),
                inspect("agents2026-demo-a", "week-4/README.md"),
                _call(
                    "improvement_note_finding",
                    text="A sampled week-4 agent loops with `while True` and never appends the "
                    "tool result, matching the evidence that students ask for complete fixed "
                    "code rather than debugging their own loop. A targeted hint about the "
                    "missing stop condition would let them find it themselves.",
                    references=["full-code-requests", "agents2026-demo-a:week-4/agent.py"],
                ),
                _call(
                    "improvement_note_finding",
                    text="The same repository's week-4 writeup has no failure-case section, "
                    "consistent with the weekly-feedback signal that this checklist item is "
                    "commonly missing. The assignment expects students to document what failed.",
                    references=["no-failure-cases", "agents2026-demo-a:week-4/README.md"],
                ),
                _call("final_answer", answer="Recorded 2 findings from one repository."),
            ]
        return [
            brief,
            inspect("agents2026-demo-b", "week-4/README.md"),
            _call(
                "improvement_note_finding",
                text="A second sampled writeup has a 'What failed' heading with no content, so "
                "the gap is in identifying failure cases, not in knowing the section exists. "
                "Staff questions also show students are unsure which learning goal each build "
                "exercises, which may be why evaluation work is skipped.",
                references=["no-failure-cases", "goal-link-unclear", "agents2026-demo-b"],
            ),
            _call("final_answer", answer="Recorded 1 further finding from a second repository."),
        ]

    @staticmethod
    def _proposals() -> list[tuple[str, dict[str, Any]]]:
        return [
            _call(
                "improvement_propose_change",
                kind="agent_guidance",
                title="Hint-first help on weekly builds",
                rationale="Many students ask for complete code; sampled loops have a bug they "
                "could find with one hint, which serves the build goal better.",
                goal_id="build-agents",
                direction="own-work",
                course_week=4,
                trigger="A student asks the Course Agent to fix their weekly build.",
                agent_action="Asks one targeted question about the student's own loop "
                "instead of giving code.",
                student_action="Checks that part of their code and reports what they find.",
                builds_on="The Course Agent chat.",
                body=HINT_GUIDANCE,
                signal_ids=["full-code-requests"],
            ),
            _call(
                "improvement_propose_change",
                kind="ui_feature",
                title="Learning-goal map on each assignment",
                rationale="Students ask which goal a build exercises and skip failure cases.",
                goal_id="evaluate-agents",
                direction="goal-progress",
                course_week=4,
                trigger="A student opens a weekly assignment.",
                agent_action="Shows the learning goals the build exercises and which ones "
                "the student's feedback already shows.",
                student_action="Picks a goal not yet shown and plans how this build will "
                "demonstrate it.",
                builds_on="The assignment view.",
                body="On each assignment view, show the learning goals the build exercises and "
                "mark which ones the student's TA feedback shows as demonstrated.",
                artifact={
                    "format": "html_mockup",
                    "content": GOAL_MAP_MOCKUP.replace(
                        VISIBILITY_PLACEHOLDER, "Status comes from TA feedback."
                    ),
                },
                signal_ids=["goal-link-unclear", "no-failure-cases"],
            ),
            _call(
                "improvement_propose_change",
                kind="agent_guidance",
                title="Unblock students with complete code",
                rationale="Students ask for complete code, so providing it removes friction.",
                goal_id="build-agents",
                direction="own-work",
                course_week=4,
                trigger="A student asks the Course Agent to fix their weekly build.",
                agent_action="Returns complete working code.",
                student_action="Pastes the code into their build.",
                builds_on="The Course Agent chat.",
                body=CODE_GUIDANCE,
                signal_ids=["full-code-requests"],
            ),
            _call(
                "improvement_propose_change",
                kind="course_content",
                title="Publish a GRPO explainer in the FAQ",
                rationale="Students asked what GRPO is.",
                goal_id="improve-performance",
                direction="goal-progress",
                course_week=11,
                trigger="A student meets GRPO in the week 11 readings.",
                agent_action="Points them to a new FAQ entry explaining GRPO.",
                student_action="Reads the entry before the tutorial.",
                builds_on="The course FAQ.",
                body="Add an FAQ entry explaining GRPO and when to use it.",
                artifact={
                    "format": "markdown",
                    "content": "### What is GRPO?\n\nGRPO is a reinforcement-learning method "
                    "that compares a group of sampled answers and reinforces the better ones.",
                },
                signal_ids=["grpo-confusion"],
            ),
        ]

    def _target(self, text: str) -> Any:
        return self._service.get(self._instructor, UUID(_UUID.findall(text)[-1]))

    def _critique(
        self, brief: tuple[str, dict[str, Any]], text: str
    ) -> list[tuple[str, dict[str, Any]]]:
        proposal = self._target(text)
        lens = self._service.next_lens(proposal)
        assert lens is not None
        verdict: dict[str, Any] = {"verdict": "accept"}
        first_look = proposal.draft.kind == "ui_feature" and proposal.revision == 1
        if proposal.draft.kind == "course_content" and lens.id == "evidence":
            verdict = {
                "verdict": "reject",
                "issues": ["Only 3 of 30 students raised this; the slides already cover GRPO."],
            }
        elif first_look and lens.id == "privacy":
            verdict = {
                "verdict": "revise",
                "issues": [
                    "Marking goals as demonstrated derives from private TA feedback, but the "
                    "proposal declares no private data and does not limit who sees it."
                ],
            }
        elif first_look and lens.id == "usefulness":
            verdict = {
                "verdict": "revise",
                "issues": [
                    "A status with nothing to compare it to tells a student little; show how "
                    "many classmates have demonstrated each goal."
                ],
            }
        return [
            brief,
            _call("staff_inspect_student_repository", project_id="agents2026-demo-b", view="tree"),
            _call("improvement_submit_critique", proposal_id=str(proposal.id), **verdict),
            _call(
                "final_answer",
                answer=f"{lens.id} · {verdict['verdict']}: {proposal.draft.title}",
            ),
        ]

    def _revise(
        self, brief: tuple[str, dict[str, Any]], text: str
    ) -> list[tuple[str, dict[str, Any]]]:
        proposal = self._target(text)
        draft = proposal.draft.model_dump(mode="json")
        draft["body"] = (
            "On each assignment view, show the learning goals the build exercises. To the "
            "logged-in student only, also mark which goals their own TA feedback shows as "
            "demonstrated; no other student's status is ever shown."
        )
        draft["data_categories"] = ["grades_feedback"]
        draft["artifact"] = {
            "format": "html_mockup",
            "content": GOAL_MAP_MOCKUP.replace(
                VISIBILITY_PLACEHOLDER,
                "Only you can see your status. It comes from your own TA feedback.",
            ),
        }
        open_issues = self._service.open_issues(proposal)
        privacy = next(item["issue_id"] for item in open_issues if item["lens"] == "privacy")
        responses = [
            {
                "issue_id": item["issue_id"],
                "action": "resolved",
                "note": "Declared grades_feedback and limited the status to the student.",
            }
            if item["lens"] == "privacy"
            else {
                "issue_id": item["issue_id"],
                "action": "declined",
                "note": "Class-wide counts would expose classmates' feedback-derived status.",
                "conflicts_with": privacy,
            }
            for item in open_issues
        ]
        return [
            brief,
            _call(
                "improvement_revise_proposal",
                proposal_id=str(proposal.id),
                responses=responses,
                **draft,
            ),
            _call("final_answer", answer=f"Revised: {proposal.draft.title}"),
        ]

    @staticmethod
    def _student_reply(text: str) -> str:
        if HINT_GUIDANCE in text:
            return (
                "Before I show anything: what does your loop do with the tool's result before "
                "the next model call? Check that, tell me what you find, and I'll help with "
                "the next step."
            )
        if CODE_GUIDANCE in text:
            return "Here is the full version, ready to paste:\n```python\n...\n```"
        return (
            "It repeats because the tool result never reaches the model. Here is the full "
            "fixed version:\n```python\n...\n```"
        )


class ScriptedProvider(ModelProvider[Model]):
    provider_id = "scripted"
    model_id = "scripted-demo-model"

    def __init__(self, service: ImprovementService, instructor: PrincipalContext) -> None:
        self._service = service
        self._instructor = instructor

    def create_model(self) -> Model:
        return ScriptedCourseAgent(self._service, self._instructor)


def _principal(username: str, role: str) -> PrincipalContext:
    return PrincipalContext(
        authenticated=True,
        user_id=uuid4(),
        username=username,
        roles=["public", role],  # type: ignore[list-item]
        session_id=uuid4(),
    )


def _print_step(step: LoopStep) -> None:
    grade = step.grade or {}
    if "verdict" in grade:
        # A graded critique: show the lens and verdict the platform recorded, not model prose.
        issues = grade.get("issues") or []
        count = f" · {len(issues)} issue{'s' if len(issues) != 1 else ''}" if issues else ""
        print(
            f"  {step.phase:<9} r{grade['revision']} {grade['lens']:<11}{grade['verdict']}{count}"
        )
        return
    print(f"  {step.phase:<9} {step.detail.splitlines()[0][:96]}")


def _short(value: object, limit: int = 220) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


class TracedRuntime:
    """Demo-only wrapper that shows each run's portable events as they happen."""

    def __init__(self, runtime: SmolagentsRuntime, trace_file: Path | None) -> None:
        self._runtime = runtime
        self._trace_file = trace_file

    def _observe(self, event: Event) -> None:
        if self._trace_file is not None:
            with self._trace_file.open("a", encoding="utf-8") as handle:
                handle.write(event.model_dump_json() + "\n")
        payload = event.payload
        if event.type == "agent.run.started":
            print("      ┌ run started")
        elif event.type == "agent.tool.requested":
            print(f"      │ call   {payload['tool_id']} {_short(payload.get('arguments', {}))}")
        elif event.type == "agent.tool.completed":
            shown = payload.get("result", payload.get("summary", "(result not stored)"))
            print(f"      │ result {_short(shown)}")
        elif event.type == "agent.tool.failed":
            print(f"      │ FAILED {payload['tool_id']} {payload['reason_code']}")
        elif event.type == "agent.message":
            print(f"      └ answer {_short(payload.get('text', payload), 400)}")

    async def run(self, *, context: AgentContext, input: AgentInput) -> AgentResult:
        return await self._runtime.run_observed(
            context=context, input=input, event_observer=self._observe
        )

    async def run_observed(
        self,
        *,
        context: AgentContext,
        input: AgentInput,
        event_observer: Callable[[Event], None],
        text_delta_observer: Callable[[str], None] | None = None,
    ) -> AgentResult:
        def both(event: Event) -> None:
            self._observe(event)
            event_observer(event)

        return await self._runtime.run_observed(
            context=context,
            input=input,
            event_observer=both,
            text_delta_observer=text_delta_observer,
        )


STATUS_LABELS = {
    "approved": "Adopted",
    "pending_approval": "Awaiting your decision",
    "rejected": "Rejected by you",
    "withdrawn": "Withdrawn in review",
    "shelved": "Shelved",
    "retired": "Retired",
    "in_review": "In review",
}
REASON_LABELS = {
    "kind_requires_approval": "this kind of change always needs staff approval",
    "declares_private_data": "it uses private student data",
    "mentions_course_member": "it names a course member",
    "contains_contact_detail": "it contains a contact detail",
    "replay_not_better_than_baseline": "it did not improve replies in replay",
    "critic_rejected": "a critic rejected it",
    "critique_limit_reached": "the panel never converged",
    "ranked_below_cutoff": "ranked below the cutoff",
    "review_incomplete": "review did not finish",
    "active_guidance_limit": "the guidance limit is reached",
}
REPORT_STYLE = """
  body { background: #0b0b0b; color: #f3efe6; font: 17px/1.55 Georgia, serif; margin: 0; }
  main { max-width: 860px; margin: 0 auto; padding: 56px 32px 96px; }
  h1 { font-size: 34px; font-weight: 400; margin: 0 0 6px; }
  h2 { font-size: 26px; font-weight: 400; margin: 0 0 6px; }
  .label, th { color: #8f8a80; font: 12px/1.4 Helvetica, Arial, sans-serif;
    letter-spacing: 0.08em; text-transform: uppercase; font-weight: 400; text-align: left; }
  section { border-top: 1px solid #3a3833; margin-top: 56px; padding-top: 28px; }
  table { border-collapse: collapse; width: 100%; margin-top: 20px; }
  td, th { border-bottom: 1px solid #24231f; padding: 10px 16px 10px 0; vertical-align: top; }
  .flow { display: grid; grid-template-columns: repeat(3, 1fr); gap: 24px; margin: 28px 0; }
  .flow p { margin: 6px 0 0; }
  .muted { color: #8f8a80; }
  ul { padding-left: 18px; }
  li { margin: 6px 0; }
  iframe { width: 100%; height: 900px; border: 1px solid #3a3833; background: #0b0b0b; }
  pre { white-space: pre-wrap; border: 1px solid #3a3833; padding: 20px;
    font: 14px/1.5 Menlo, monospace; }
  details { border-bottom: 1px solid #24231f; padding: 10px 0; }
  summary { cursor: pointer; }
  details p { white-space: pre-wrap; margin: 12px 0 0 18px; }
  @media (max-width: 640px) { .flow { grid-template-columns: 1fr; } }
"""


def _wrapped(label: str, text: str) -> str:
    """One labelled terminal field, wrapped so long model text stays readable."""

    return textwrap.fill(
        " ".join(text.split()),
        width=92,
        initial_indent=f"       {label:<9}",
        subsequent_indent=" " * 16,
    )


def _outcome(proposal: Proposal) -> str:
    label = STATUS_LABELS[proposal.status]
    if proposal.approval_source == "platform_policy":
        label = "Adopted automatically"
    if proposal.status_reason:
        label += f": {REASON_LABELS.get(proposal.status_reason, proposal.status_reason)}"
    return label


def _why_human(proposal: Proposal) -> str:
    reasons = proposal.assessment.reasons if proposal.assessment else []
    return "; ".join(REASON_LABELS[reason] for reason in reasons)


def _report(
    model: str, proposals: list[Proposal], service: ImprovementService, instructor: PrincipalContext
) -> str:
    """Review page for the instructor. Every model-authored string is escaped; a mock-up is
    shown only inside a script-less sandboxed frame. Proposals awaiting a decision come
    first; the rest follow with their review history, so a withdrawal can be understood."""

    e = html.escape
    rows = "".join(
        f"<tr><td>{e(item.draft.title)}</td><td>{e(item.draft.direction)}</td>"
        f"<td>{e(_outcome(item))}</td></tr>"
        for item in proposals
    )
    rubrics = "".join(
        f"<tr><td>{e(lens.id)}</td><td>{e(lens.rubric)}</td></tr>" for lens in service.lenses
    )
    lens_of = {
        issue_id: item.lens
        for proposal in proposals
        for item in proposal.critiques
        for issue_id in item.issue_ids()
    }
    conflicts = "".join(
        f"<li>{e(lens_of[answer.issue_id])} gave way to {e(lens_of[answer.conflicts_with])} "
        f"in “{e(proposal.draft.title)}”<br><span class='muted'>{e(answer.issue_id)} declined "
        f"in favour of {e(answer.conflicts_with)}: {e(answer.note)}</span></li>"
        for proposal in proposals
        for answer in proposal.responses
        if answer.conflicts_with is not None
    )
    sections = []
    pending_first = sorted(proposals, key=lambda item: item.status != "pending_approval")
    for number, proposal in enumerate(pending_first, start=1):
        draft = proposal.draft
        pending = proposal.status == "pending_approval"
        heading = f"Decision {number}" if pending else _outcome(proposal)
        needs_you = (
            f"<p><span class='label'>Why it needs you</span><br>{e(_why_human(proposal))}</p>"
            if pending
            else ""
        )
        dossier = json.loads(json.dumps(service.dossier(instructor, proposal.id)))
        week = f"Week {draft.course_week} · " if draft.course_week else ""
        evidence = "".join(
            f"<li>{signal['student_count']} students: {e(signal['observation'])}</li>"
            for signal in dossier["evidence"]
        )
        answers = {item.issue_id: item for item in proposal.responses}
        critiques = ""
        for item in proposal.critiques:
            critiques += f"<li>Revision {item.revision} · {e(item.lens)} · {e(item.verdict)}"
            for issue_id, issue in zip(item.issue_ids(), item.issues, strict=True):
                critiques += f"<br><span class='muted'>{e(issue_id)}</span> {e(issue)}"
                answer = answers.get(issue_id)
                if answer is not None:
                    against = (
                        f", conflicts with {e(answer.conflicts_with)}"
                        if answer.conflicts_with
                        else ""
                    )
                    critiques += (
                        f"<br><span class='muted'>Author {e(answer.action)}{against}: "
                        f"{e(answer.note)}</span>"
                    )
            critiques += "</li>"
        trials = ""
        for trial in proposal.trials:
            turns = "".join(
                f"<p><span class='label'>{'Student' if turn.role == 'student' else 'Course Agent'}"
                f"</span><br>{e(turn.text)}</p>"
                for turn in trial.messages
            )
            trials += (
                f"<details><summary>Revision {trial.revision} · {e(trial.persona)} student · "
                f"skill {'loaded' if trial.skill_loaded else 'NOT loaded'}</summary>{turns}"
                "</details>"
            )
        if trials:
            trials = f"<p class='label'>Trial conversations (simulated students)</p>{trials}"
        deliverable = review_file(proposal)
        if deliverable is None:
            shown = ""
        elif deliverable[0].endswith(".html"):
            shown = (
                "<p class='label'>Mock-up: three screens, in order (static, model-drafted)</p>"
                f"<iframe sandbox title='Mock-up' srcdoc='{e(deliverable[1], quote=True)}'>"
                "</iframe>"
            )
        else:
            shown = f"<p class='label'>Deliverable</p><pre>{e(deliverable[1])}</pre>"
        sections.append(
            f"<section><p class='label'>{e(heading)} · {e(draft.kind.replace('_', ' '))} · "
            f"{e(week)}{e(draft.goal_id)} · {e(draft.direction)}</p>"
            f"<h2>{e(draft.title)}</h2><p>{e(draft.body)}</p>"
            "<div class='flow'>"
            f"<div><span class='label'>When</span><p>{e(draft.trigger)}</p></div>"
            f"<div><span class='label'>The agent</span><p>{e(draft.agent_action)}</p></div>"
            f"<div><span class='label'>The student</span><p>{e(draft.student_action)}</p></div>"
            "</div>"
            f"<p><span class='label'>Continues</span><br>{e(draft.builds_on)}</p>"
            f"{needs_you}{shown}{trials}"
            f"<p class='label'>Why it was proposed</p><p>{e(draft.rationale)}</p>"
            f"<p class='label'>Evidence</p><ul>{evidence}</ul>"
            f"<p class='label'>Review history</p><ul>{critiques}</ul></section>"
        )
    return (
        "<!doctype html>\n<html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        "<meta http-equiv='Content-Security-Policy' "
        "content=\"default-src 'none'; style-src 'unsafe-inline'\">"
        f"<title>Course improvement review</title><style>{REPORT_STYLE}</style></head>"
        f"<body><main><p class='label'>{e(model)}</p>"
        "<h1>Course improvement review</h1>"
        "<table><tr><th>Proposal</th><th>Direction</th><th>Outcome</th></tr>"
        f"{rows}</table>"
        "<section><p class='label'>Review panel</p><h2>Rubrics</h2>"
        f"<table><tr><th>Lens</th><th>Rubric</th></tr>{rubrics}</table></section>"
        "<section><p class='label'>Review panel</p><h2>Where critics competed</h2>"
        + (
            f"<ul>{conflicts}</ul>"
            if conflicts
            else "<p class='muted'>No author recorded a conflict between two lenses.</p>"
        )
        + f"</section>{''.join(sections)}</main></body></html>\n"
    )


LANGFUSE_DEFAULT_HOST = "https://cloud.langfuse.com"


class LangfuseSink:
    """Demo-only: names each phase run's trace and attaches its rubric and recorded grade."""

    def __init__(self, *, tracer: Any, session_id: str, host: str, authorization: str) -> None:
        self.tracer = tracer
        self.session_id = session_id
        self.host = host
        self.authorization = authorization
        self.last_trace_id: str | None = None

    def score(self, grade: Mapping[str, JsonValue]) -> None:
        """Attach a platform-recorded grade to the trace of the run that produced it."""

        if self.last_trace_id is None:
            return
        if "verdict" in grade:
            issues = grade.get("issues")
            body: dict[str, JsonValue] = {
                "name": f"critic.{grade['lens']}",
                "value": grade["verdict"],
                "dataType": "CATEGORICAL",
                "comment": "\n".join(str(issue) for issue in issues)
                if isinstance(issues, list) and issues
                else "No issues raised.",
            }
        else:
            body = {
                "name": f"replay.{grade['scenario_id']}",
                "value": grade["score"],
                "dataType": "NUMERIC",
                "comment": str(grade["rubric"]),
            }
        body["traceId"] = self.last_trace_id
        body["metadata"] = {key: value for key, value in grade.items() if key != "issues"}
        try:
            httpx.post(
                f"{self.host}/api/public/scores",
                headers={"Authorization": self.authorization},
                json=body,
                timeout=10,
            ).raise_for_status()
        except httpx.HTTPError as error:
            print(f"      (Langfuse score not recorded: {type(error).__name__})")


class PhaseTraceRuntime:
    """Demo-only wrapper: one named root span per run, carrying the phase's rubric."""

    def __init__(self, runtime: Any, sink: LangfuseSink) -> None:
        self._runtime = runtime
        self._sink = sink

    @contextmanager
    def _span(self, context: AgentContext, input: AgentInput) -> Iterator[Any]:
        raw = context.metadata.get("improvement_phase")
        subject: dict[str, Any] = dict(raw) if isinstance(raw, dict) else {"phase": "student"}
        name = " · ".join(
            str(subject[key])
            for key in ("phase", "lens", "scenario_id", "persona", "role")
            if subject.get(key)
        )
        with self._sink.tracer.start_as_current_span(name) as span:
            self._sink.last_trace_id = format(span.get_span_context().trace_id, "032x")
            span.set_attribute("langfuse.trace.name", name)
            span.set_attribute("session.id", self._sink.session_id)
            span.set_attribute("input.value", input.text)
            for key, value in subject.items():
                if value is not None:
                    span.set_attribute(f"langfuse.trace.metadata.{key}", str(value))
            yield span

    async def run(self, *, context: AgentContext, input: AgentInput) -> AgentResult:
        with self._span(context, input) as span:
            result: AgentResult = await self._runtime.run(context=context, input=input)
            span.set_attribute("output.value", result.output_text)
            return result

    async def run_observed(
        self,
        *,
        context: AgentContext,
        input: AgentInput,
        event_observer: Callable[[Event], None],
        text_delta_observer: Callable[[str], None] | None = None,
    ) -> AgentResult:
        with self._span(context, input) as span:
            result: AgentResult = await self._runtime.run_observed(
                context=context,
                input=input,
                event_observer=event_observer,
                text_delta_observer=text_delta_observer,
            )
            span.set_attribute("output.value", result.output_text)
            return result


@contextmanager
def _langfuse_trace(enabled: bool, name: str) -> Iterator[LangfuseSink | None]:
    """Export every smolagents run in this demo to Langfuse as OpenTelemetry traces.

    The export contains full model prompts and tool results, so this is demo-only: it is
    safe here because every input is synthetic.
    """

    if not enabled:
        yield None
        return
    load_dotenv(override=False)
    public_key = (os.environ.get("LANGFUSE_PUBLIC_KEY") or "").strip()
    secret_key = (os.environ.get("LANGFUSE_SECRET_KEY") or "").strip()
    if not public_key or not secret_key:
        raise SystemExit(
            "--langfuse needs LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY "
            "in the environment or class-agent/.env"
        )
    try:
        from openinference.instrumentation import using_session
        from openinference.instrumentation.smolagents import SmolagentsInstrumentor
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError as error:
        raise SystemExit("--langfuse needs the tracing group: uv run --group tracing …") from error
    host = (
        (
            os.environ.get("LANGFUSE_BASE_URL")
            or os.environ.get("LANGFUSE_HOST")
            or LANGFUSE_DEFAULT_HOST
        )
        .strip()
        .rstrip("/")
    )
    credentials = base64.b64encode(f"{public_key}:{secret_key}".encode()).decode()
    provider = TracerProvider()
    provider.add_span_processor(
        BatchSpanProcessor(
            OTLPSpanExporter(
                endpoint=f"{host}/api/public/otel/v1/traces",
                headers={"Authorization": f"Basic {credentials}"},
            )
        )
    )
    SmolagentsInstrumentor().instrument(tracer_provider=provider)
    session_id = f"{name}-{uuid4().hex[:8]}"
    print(f"Langfuse: exporting to {host} · session {session_id}")
    # Each agent run is its own trace, exported as soon as it ends and grouped by session,
    # so the cycle can be watched while it runs and nothing waits on the human gate.
    sink = LangfuseSink(
        tracer=provider.get_tracer("improvement_loop_demo"),
        session_id=session_id,
        host=host,
        authorization=f"Basic {credentials}",
    )
    try:
        with using_session(session_id):
            yield sink
    finally:
        provider.shutdown()


def _real_projects() -> GitHubStudentProjectCatalog:
    """The Course Agent's own read-only GitHub reader, confined to the course prefix."""

    load_dotenv(override=False)
    token = (os.environ.get("GITHUB_TOKEN") or "").strip()
    if not token:
        raise SystemExit("--real-projects needs GITHUB_TOKEN in the environment or .env")
    fields = AgentSettings.model_fields
    return GitHubStudentProjectCatalog(
        token,
        organization=fields["github_organization"].default,
        repository_prefix=fields["github_repository_prefix"].default,
        excluded_repositories=fields["github_excluded_repositories"].default,
    )


def _live_provider() -> OpenAIModelProvider:
    load_dotenv(override=False)
    api_key = (os.environ.get("OPENAI_API_KEY") or "").strip()
    if not api_key:
        raise SystemExit("--live needs OPENAI_API_KEY in the environment or class-agent/.env")
    default_model = AgentSettings.model_fields["model_id"].default
    return OpenAIModelProvider(
        model_id=os.environ.get("MODEL_ID", "").strip() or default_model,
        api_key=SecretStr(api_key),
    )


async def run_demo(
    decision: str | None,
    *,
    live: bool = False,
    trace: bool = False,
    trace_file: Path | None = None,
    out: Path | None = None,
    reason: str | None = None,
    real_projects: bool = False,
    evidence: Path | None = None,
    max_rounds: int = MAX_REVIEW_ROUNDS,
    langfuse: LangfuseSink | None = None,
    trial_exchanges: int = LoopBudget.trial_exchanges,
) -> None:
    projects: StudentProjectCatalog = _real_projects() if real_projects else SyntheticProjects()
    # Real repository names identify students, so a proposal that repeats one is escalated.
    members = ["demo-student"]
    if real_projects:
        prefix = AgentSettings.model_fields["github_repository_prefix"].default
        for project in projects.list_projects():
            members += [project.id, project.id.removeprefix(prefix)]
    instructor = _principal("demo-instructor", "instructor")
    student = _principal("demo-student", "student")
    resources = FileResourceProvider.from_registry()
    service = ImprovementService(
        goals=await load_learning_goals(resources),
        charter=await load_charter(resources),
        evidence=EvidenceDigest.model_validate_json(
            (evidence or HERE / "evidence.synthetic.json").read_text(encoding="utf-8")
        ),
        scenarios=ReplayScenarios.model_validate_json(
            (HERE / "scenarios.synthetic.json").read_text(encoding="utf-8")
        ),
        privacy=PrivacyScreen(members),
        notebook_character_limit=700,
        max_rounds=max_rounds,
    )
    skills = SkillCatalog.from_registry(AgentSettings.model_fields["skills_path"].default)
    # The read tools that work offline. A deployment registers the Course Agent's full
    # catalog; the loop then offers every tool in LOOP_READ_TOOL_IDS the policy authorizes.
    tools = [
        *improvement_tools(service),
        ListStudentProjectsTool(projects),
        InspectStudentRepositoryTool(projects),
        CourseGetScheduleTool(resources),
        CourseReadSyllabusTool(resources),
        CourseReadPublicFileTool(resources),
        CourseSearchTool(resources),
        CourseSearchFaqTool(resources),
        CourseShowPublicFilesTool(resources),
        # Also serves a proposed skill, but only inside the trial conversation the loop opens.
        TrialSkillReadTool(service, ReadSkillTool(skills)),
        ReadSkillReferenceTool(skills),
    ]
    policy = DemoPolicy(resources, frozenset(tool.id for tool in tools))
    provider: ModelProvider[Model] = (
        _live_provider() if live else ScriptedProvider(service, instructor)
    )
    base_runtime = SmolagentsRuntime(
        model_provider=provider, tools=ToolCatalog(tools), max_steps=16
    )
    runtime: Any = TracedRuntime(base_runtime, trace_file) if trace or trace_file else base_runtime
    if langfuse is not None:
        runtime = PhaseTraceRuntime(runtime, langfuse)
    conversations = InMemoryConversationStore()
    agent = CourseAgentService(
        runtime=runtime, conversations=conversations, capability_policy=policy, guidance=service
    )
    question = "My tool-calling agent keeps calling the same tool forever. Just give me the fix?"

    async def ask_as_student() -> str:
        conversation = await agent.create_conversation(student)
        result = await agent.run(principal=student, conversation_id=conversation.id, text=question)
        return result.output_text

    data = (
        "REAL STUDENT REPOSITORIES · SYNTHETIC SCENARIOS"
        if real_projects
        else "SYNTHETIC EVIDENCE, SCENARIOS, AND REPOSITORIES"
    )
    model = f"{f'LIVE MODEL {provider.model_id}' if live else 'SCRIPTED MODEL'} · {data}"
    print(f"{model}\n")
    print("1. Student asks before the cycle")
    first_line = (await ask_as_student()).strip().splitlines()[0]
    print(textwrap.indent(textwrap.fill(first_line, width=92), "   "))

    def observe(step: LoopStep) -> None:
        _print_step(step)
        if langfuse is not None and step.grade is not None:
            langfuse.score(step.grade)

    print("\n2. Improvement cycle (each line is one fresh Course Agent run)")
    loop = ImprovementLoop(
        runtime=runtime,
        conversations=conversations,
        service=service,
        capability_policy=policy,
        skills=skills,
        # Each round is one critique per lens plus a revision, and for a skill one trial
        # conversation per persona (two runs per exchange), so the budget scales with all.
        budget=LoopBudget(
            max_runs=30
            + 4
            * max_rounds
            * (len(service.lenses) + 1 + 2 * trial_exchanges * len(service.personas)),
            max_proposals=4,
            top_k=3,
            trial_exchanges=trial_exchanges,
        ),
        observer=observe,
    )
    await loop.run_cycle(instructor)

    proposals = service.proposals(instructor)
    print("\n3. Outcome")
    for proposal in proposals:
        print(f"   {proposal.draft.title}\n       {_outcome(proposal)}")

    out = out or HERE / "out"
    out.mkdir(parents=True, exist_ok=True)
    for proposal in proposals:
        deliverable = review_file(proposal)
        if deliverable is not None and proposal.status in {"pending_approval", "approved"}:
            (out / deliverable[0]).write_text(deliverable[1], encoding="utf-8")
    report_path = out / "report.html"
    report_path.write_text(_report(model, proposals, service, instructor), encoding="utf-8")

    pending = [p for p in proposals if p.status == "pending_approval"]
    interactive = decision is None and sys.stdin.isatty()
    if pending:
        print(f"\n4. Awaiting your decision ({len(pending)})")
    for number, proposal in enumerate(pending, start=1):
        draft = proposal.draft
        week = f"week {draft.course_week} · " if draft.course_week else ""
        print(f"\n   [{number}] {draft.title}")
        print(f"       {draft.kind} · {week}{draft.goal_id} · {draft.direction}")
        print(_wrapped("When", draft.trigger))
        print(_wrapped("Agent", draft.agent_action))
        print(_wrapped("Student", draft.student_action))
        print(_wrapped("Why you", _why_human(proposal)))
    print(f"\n   Full review, with mock-ups, evidence and critiques:\n   {report_path.as_uri()}")
    if pending and interactive:
        webbrowser.open(report_path.as_uri())

    # Decisions come only after every dossier has been shown, so they can be compared.
    if pending:
        print("\n5. Human decisions")
    for number, proposal in enumerate(pending, start=1):
        choice, why = decision, reason
        if choice is None and sys.stdin.isatty():
            answer = input(f"   [{number}] {proposal.draft.title} — approve? [y/N] ")
            choice = "approve" if answer.strip().lower() == "y" else "reject"
            why = input("       Reason for the next cycle (optional): ").strip() or None
        if choice is None:
            print(f"   [{number}] Left pending: pass --decision approve|reject to decide.")
            continue
        decided = service.decide(instructor, proposal.id, choice, why)  # type: ignore[arg-type]
        print(f"   [{number}] Human decision recorded: {decided.status}")

    print("\n6. Same student question after the cycle")
    print(textwrap.indent(textwrap.fill((await ask_as_student()).strip(), width=92), "   "))


def main() -> None:
    # Course PDFs with imperfect cross-reference tables make pypdf warn once per object.
    logging.getLogger("pypdf").setLevel(logging.ERROR)
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--decision", choices=["approve", "reject"])
    parser.add_argument("--live", action="store_true", help="use the configured OpenAI model")
    parser.add_argument("--trace", action="store_true", help="print every tool call and answer")
    parser.add_argument("--trace-file", type=Path, help="append every run event as JSON lines")
    parser.add_argument("--reason", help="reason recorded with --decision for later cycles")
    parser.add_argument("--out", type=Path, help="directory for proposal deliverables")
    parser.add_argument("--langfuse", action="store_true", help="export model traces to Langfuse")
    parser.add_argument(
        "--real-projects",
        action="store_true",
        help="read the course GitHub repositories instead of the synthetic ones",
    )
    parser.add_argument(
        "--evidence", type=Path, help="evidence digest to use instead of the fixture"
    )
    parser.add_argument(
        "--max-rounds",
        type=int,
        default=MAX_REVIEW_ROUNDS,
        help="revisions the review panel may see before a proposal is withdrawn",
    )
    parser.add_argument(
        "--trial-exchanges",
        type=int,
        default=LoopBudget.trial_exchanges,
        help="student messages in each simulated trial of a proposed skill",
    )
    arguments = parser.parse_args()
    # The scripted model and synthetic evidence describe repositories that do not exist in
    # the course organization. Repository builds and commits are public within the course,
    # so tracing is allowed; no private record (chat, grades, feedback) is registered here.
    if arguments.real_projects and (not arguments.live or arguments.evidence is None):
        parser.error("--real-projects needs --live and --evidence")
    name = "improvement-cycle-live" if arguments.live else "improvement-cycle-scripted"
    with _langfuse_trace(arguments.langfuse, name) as langfuse:
        asyncio.run(
            run_demo(
                arguments.decision,
                live=arguments.live,
                trace=arguments.trace,
                trace_file=arguments.trace_file,
                out=arguments.out,
                reason=arguments.reason,
                real_projects=arguments.real_projects,
                evidence=arguments.evidence,
                max_rounds=arguments.max_rounds,
                langfuse=langfuse,
                trial_exchanges=arguments.trial_exchanges,
            )
        )


if __name__ == "__main__":
    main()
