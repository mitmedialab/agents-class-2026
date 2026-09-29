"""Staff-only weekly selection: agent-owned assessments, platform-owned draws and policy."""

from __future__ import annotations

import asyncio
from collections import Counter
from collections.abc import Mapping
from pathlib import Path
from random import SystemRandom
from typing import Annotated, ClassVar, Literal, Self, cast

from pydantic import BaseModel, ConfigDict, Field, JsonValue, ValidationError, model_validator

from course_server.agent.capabilities import (
    ToolExecutionContext,
    ToolExecutionResult,
    ToolValidationError,
)
from course_server.student_project_tool_ids import (
    READ_SHOWCASE_HISTORY_TOOL_ID,
    SELECT_SHOWCASE_TOOL_ID,
)

from .client import StudentProjectCatalog, StudentProjectProviderError
from .tools import _require_course_staff, _translate_provider_error

ProjectId = Annotated[str, Field(pattern=r"^agents2026-[A-Za-z0-9_.-]{1,80}$")]
Score = Annotated[float, Field(ge=0, le=10, allow_inf_nan=False)]
Evidence = Annotated[str, Field(min_length=1, max_length=4000, pattern=r"\S")]
# The requested rubric is an intentional course policy, not a model-supplied weight.
RUBRIC_WEIGHTS = {
    "originality": 0.30,
    "assignment_fit": 0.25,
    "cognitive_augmentation": 0.25,
    "execution": 0.20,
}


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Issue(StrictModel):
    week: int = Field(ge=1, le=100)
    project_ids: list[ProjectId] = Field(max_length=100)

    @model_validator(mode="after")
    def unique_projects(self) -> Self:
        if len(set(self.project_ids)) != len(self.project_ids):
            raise ValueError("duplicate project in issue")
        return self


class ShowcaseHistory(StrictModel):
    schema_version: Literal[1] = 1
    issues: list[Issue] = Field(max_length=100)

    @model_validator(mode="after")
    def unique_weeks(self) -> Self:
        if len({issue.week for issue in self.issues}) != len(self.issues):
            raise ValueError("duplicate issue week")
        return self


class Eligibility(StrictModel):
    project_id: ProjectId
    student_name: Evidence
    post_evidence: Evidence | None = None
    repository_evidence: Evidence | None = None

    @model_validator(mode="after")
    def evidence_required(self) -> Self:
        if self.post_evidence is None and self.repository_evidence is None:
            raise ValueError("weekly post or repository documentation evidence is required")
        return self


class Assessment(Eligibility):
    originality: Score
    assignment_fit: Score
    cognitive_augmentation: Score
    execution: Score
    repository_evidence: Evidence
    rationale: Evidence


class SelectionRequest(StrictModel):
    week: int = Field(ge=1, le=100)
    assignment_evidence: Evidence
    candidates: list[Assessment] = Field(min_length=1, max_length=100)
    eligible_projects: list[Eligibility] | None = Field(default=None, min_length=4, max_length=100)

    @model_validator(mode="after")
    def unique_projects(self) -> Self:
        if len({item.project_id for item in self.candidates}) != len(self.candidates):
            raise ValueError("duplicate candidate")
        if self.eligible_projects is not None:
            ids = {item.project_id for item in self.eligible_projects}
            if len(ids) != len(self.eligible_projects):
                raise ValueError("duplicate eligible project")
            if not {item.project_id for item in self.candidates} <= ids:
                raise ValueError("ranked candidates must belong to the eligible pool")
        return self


def read_history(path: Path) -> ShowcaseHistory:
    try:
        if path.stat().st_size > 100_000:
            raise ValueError("history too large")
        return ShowcaseHistory.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ToolValidationError(
            "Showcase history is missing or invalid. Ask staff to configure the history file; "
            "do not assume nobody has presented."
        ) from error


def select_builds(request: SelectionRequest, history: ShowcaseHistory) -> dict[str, JsonValue]:
    previous = sorted(
        (issue for issue in history.issues if issue.week < request.week),
        key=lambda issue: issue.week,
    )
    counts = Counter(project for issue in previous for project in issue.project_ids)
    excluded = {project for issue in previous[-2:] for project in issue.project_ids}
    rows: list[dict[str, JsonValue]] = []
    for candidate in request.candidates:
        if candidate.project_id in excluded:
            continue
        raw = sum(getattr(candidate, key) * weight for key, weight in RUBRIC_WEIGHTS.items())
        participation_weight = 1 / (1 + counts[candidate.project_id])
        rows.append(
            {
                **candidate.model_dump(mode="json"),
                "raw_score": round(raw, 6),
                "adjusted_score": round(raw * participation_weight, 6),
                "prior_appearances": counts[candidate.project_id],
                "sampling_weight": participation_weight,
            }
        )
    # Fit >= 5 is a priority tier, not a blanket rejection of lower-fit builds.
    rows.sort(
        key=lambda row: (
            -int(cast(float, row["assignment_fit"]) >= 5),
            -cast(float, row["adjusted_score"]),
            -cast(float, row["assignment_fit"]),
            -cast(float, row["originality"]),
            cast(str, row["project_id"]),  # Stable final fallback after the requested tie-breaks.
        )
    )
    pool = request.eligible_projects
    eligible = (
        [
            {
                **item.model_dump(mode="json"),
                "prior_appearances": counts[item.project_id],
                "sampling_weight": 1 / (1 + counts[item.project_id]),
            }
            for item in pool
            if item.project_id not in excluded
        ]
        if pool is not None
        else rows
    )
    if len(eligible) < 4:
        raise ToolValidationError(
            "Fewer than four eligible builds remain after the two-issue cooldown."
        )
    if len(rows) < 2:
        raise ToolValidationError("At least two assessed builds must remain after cooldown.")
    ranked = rows[:2]
    ranked_ids = {row["project_id"] for row in ranked}
    remaining = [row for row in eligible if row["project_id"] not in ranked_ids]
    sampled = []
    rng = SystemRandom()
    for _ in range(2):
        chosen = rng.choices(
            remaining, weights=[cast(float, row["sampling_weight"]) for row in remaining], k=1
        )[0]
        sampled.append(chosen)
        remaining.remove(chosen)
    return cast(
        dict[str, JsonValue],
        {
            "week": request.week,
            "ranked": ranked,
            "random": sampled,
            "ranking": rows,
            "eligible_count": len(eligible),
            "ranking_scope": "Reviewed shortlist"
            if pool is not None
            else "All submitted candidates",
            "excluded_project_ids": sorted(excluded),
            "rubric_weights": RUBRIC_WEIGHTS,
            "method": "Two ranked first, then two weighted random draws without replacement; "
            "weight = 1 / (1 + prior appearances). History is not modified.",
            "assessment_source": "Agent-supplied evidence and scores; not independently verified.",
        },
    )


class ReadShowcaseHistoryTool:
    id = READ_SHOWCASE_HISTORY_TOOL_ID
    description = (
        "Read staff-maintained weekly presentation history before selecting builds. "
        "Lists previous issues used for the two-issue cooldown and participation weights. "
        "Supply week to retrieve its saved review and draw; reuse that request with selection "
        "to restore the same four students without repeating the assessment."
    )
    input_schema: ClassVar[dict[str, JsonValue]] = {
        "type": "object",
        "properties": {"week": {"type": "integer", "minimum": 1, "maximum": 100}},
        "additionalProperties": False,
    }

    def __init__(self, history_path: Path) -> None:
        self._history_path = history_path

    async def execute(
        self, arguments: Mapping[str, JsonValue], context: ToolExecutionContext
    ) -> ToolExecutionResult:
        _require_course_staff(context.principal)
        week = arguments.get("week")
        if set(arguments) - {"week"} or (
            week is not None and (type(week) is not int or not 1 <= week <= 100)
        ):
            raise ToolValidationError("Supply only an optional week from 1 to 100.")
        history = read_history(self._history_path)
        from .showcase_store import read_snapshot

        content = history.model_dump(mode="json")
        if isinstance(week, int):
            path = self._history_path.parent / "selections" / f"week-{week:02d}.json"
            content["saved_review"] = (
                read_snapshot(path).model_dump(mode="json") if path.exists() else None
            )
        else:
            content["saved_review_weeks"] = [
                number
                for number in range(1, 101)
                if (self._history_path.parent / "selections" / f"week-{number:02d}.json").exists()
            ]
        return ToolExecutionResult(
            content=content,
            summary="Read weekly presentation history.",
            storage_policy="server_summary",
        )


class SelectShowcaseTool:
    id = SELECT_SHOWCASE_TOOL_ID
    description = (
        "Select four weekly builds: two ranked plus two genuinely random, weighted draws. "
        "The first successful weekly review and draw is saved privately and reused on retries, "
        "including across conversations. Read history for saved reviews before doing new work. "
        "Supply eligible_projects for the full site-screened pool; only candidates in the ranked "
        "shortlist need scores and repository review. Inspect their folder, notes and commits, "
        "and weekly site post when accessible. Repository documentation can verify weekly work "
        "when the site is hard to navigate; supply repository_evidence and describe the site "
        "limitation rather than inventing post_evidence. A filename alone is insufficient. "
        "Score each 0-10: originality, assignment fit, cognitive augmentation "
        "(helps thinking, memory, learning, focus or decisions with human control), execution "
        "(working evidence in repository/post). Weights are 30/25/25/20 percent. Platform enforces "
        "history cooldown, participation weights, fit priority and tie-breaks. Supply evidence "
        "references and reasons. This proposes selections without recording "
        "an actual presentation. Call staff.discover_showcase_images for each selected student "
        "using their weekly-page URLs before declaring images unavailable. Display one verified "
        "weekly build image per selected student "
        "using browser.compare with presentation=thumbnails for a 2x2 gallery with links below. "
        "If webpage and repository lookup find no image, omit image_url to capture the "
        "verified weekly build page as a screenshot. Do not reroll."
    )
    input_schema: ClassVar[dict[str, JsonValue]] = {
        "type": "object",
        "properties": {
            "week": {"type": "integer", "minimum": 1, "maximum": 100},
            "assignment_evidence": {"type": "string", "minLength": 1, "maxLength": 4000},
            "eligible_projects": {
                "type": "array",
                "minItems": 4,
                "maxItems": 100,
                "items": cast(JsonValue, Eligibility.model_json_schema()),
                "description": "Full eligible pool verified by posts or repository documentation, "
                "including unscored builds.",
            },
            "candidates": {
                "type": "array",
                "minItems": 1,
                "maxItems": 100,
                "items": cast(JsonValue, Assessment.model_json_schema()),
            },
        },
        "required": ["week", "assignment_evidence", "candidates"],
        "additionalProperties": False,
    }

    def __init__(self, projects: StudentProjectCatalog, history_path: Path) -> None:
        self._projects = projects
        self._history_path = history_path

    async def execute(
        self, arguments: Mapping[str, JsonValue], context: ToolExecutionContext
    ) -> ToolExecutionResult:
        _require_course_staff(context.principal)
        try:
            request = SelectionRequest.model_validate(dict(arguments))
        except ValidationError as error:
            raise ToolValidationError(
                "Invalid showcase request: use unique projects, evidence, and scores from 0 to 10."
            ) from error
        history = read_history(self._history_path)
        if any(issue.week == request.week for issue in history.issues):
            raise ToolValidationError(
                "This week's issue is already recorded; review history instead of drawing again."
            )
        try:
            projects = await asyncio.to_thread(self._projects.list_projects)
        except StudentProjectProviderError as error:
            raise _translate_provider_error(error) from error
        sites = {project.id: project.site_url for project in projects if project.site_url}
        pool = request.eligible_projects or request.candidates
        if any(candidate.project_id not in sites for candidate in pool):
            raise ToolValidationError(
                "Every candidate must be a registered project with a deployed site."
            )
        from .showcase_store import saved_selection

        result, reused = await asyncio.to_thread(
            saved_selection, self._history_path, request, history, sites
        )
        result["reused_saved_selection"] = reused
        selected = cast(list[dict[str, JsonValue]], result["ranked"]) + cast(
            list[dict[str, JsonValue]], result["random"]
        )
        context.transient_state["showcase_selection_sites"] = [
            sites[str(row["project_id"])] for row in selected
        ]
        return ToolExecutionResult(
            content=result,
            summary="Selected two ranked and two randomly sampled weekly builds.",
            storage_policy="server_summary",
        )
