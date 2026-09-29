from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Literal, cast

import pytest
from pydantic import JsonValue, ValidationError
from test_student_projects import FakeStudentProjects, context, principal

from course_server.agent import CourseCapabilityPolicy, ToolValidationError
from course_server.student_project_tool_ids import SHOWCASE_TOOL_IDS
from course_server.student_projects import StudentProject
from course_server.student_projects.showcase import (
    Assessment,
    Issue,
    ReadShowcaseHistoryTool,
    SelectionRequest,
    SelectShowcaseTool,
    ShowcaseHistory,
    read_history,
    select_builds,
)


def candidate(name: str, score: float = 8, fit: float = 8) -> Assessment:
    return Assessment(
        project_id=f"agents2026-{name}",
        student_name=name,
        originality=score,
        assignment_fit=fit,
        cognitive_augmentation=score,
        execution=score,
        repository_evidence="week2/README.md at commit abc",
        post_evidence="https://example.edu/week2",
        rationale="Evidence-based review",
    )


def request(*candidates: Assessment, week: int = 4) -> SelectionRequest:
    return SelectionRequest(
        week=week, assignment_evidence="Week 4 assignment", candidates=list(candidates)
    )


def ids(result: dict[str, JsonValue], key: str) -> list[str]:
    return [str(row["project_id"]) for row in cast(list[dict[str, JsonValue]], result[key])]


def test_fit_priority_cooldown_and_participation_adjustment() -> None:
    history = ShowcaseHistory(
        issues=[
            Issue(week=1, project_ids=["agents2026-old"]),
            Issue(week=2, project_ids=["agents2026-recent"]),
            Issue(week=3, project_ids=[]),
        ]
    )
    result = select_builds(
        request(
            candidate("old", 10, 10),
            candidate("new", 8, 8),
            candidate("recent", 10, 10),
            candidate("lowfit", 10, 4),
            candidate("other", 6, 6),
            candidate("last", 5, 5),
        ),
        history,
    )
    assert ids(result, "ranked") == ["agents2026-new", "agents2026-other"]
    assert ids(result, "ranking")[-1] == "agents2026-lowfit"
    assert "agents2026-recent" not in ids(result, "ranking")
    rows = cast(list[dict[str, JsonValue]], result["ranking"])
    old = next(row for row in rows if row["project_id"] == "agents2026-old")
    assert old["raw_score"] == 10
    assert old["adjusted_score"] == 5
    assert old["sampling_weight"] == 0.5
    assert len(set(ids(result, "ranked") + ids(result, "random"))) == 4


def test_ties_use_fit_then_originality() -> None:
    # Totals all 5: higher fit wins, then originality.
    a = candidate("a", 5, 5)
    b = a.model_copy(
        update={"project_id": "agents2026-b", "assignment_fit": 6.0, "execution": 3.75}
    )
    c = b.model_copy(update={"project_id": "agents2026-c", "originality": 6.0, "execution": 2.25})
    result = select_builds(request(a, b, c, candidate("d", 1, 1)), ShowcaseHistory(issues=[]))
    assert ids(result, "ranked") == ["agents2026-c", "agents2026-b"]


def test_sampler_receives_history_weights_and_removes_each_draw(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[list[str], list[float]]] = []

    class ControlledRandom:
        def choices(
            self, population: list[dict[str, JsonValue]], *, weights: list[float], k: int
        ) -> list[dict[str, JsonValue]]:
            assert k == 1
            calls.append(([str(row["project_id"]) for row in population], weights))
            return [population[-1]]

    monkeypatch.setattr("course_server.student_projects.showcase.SystemRandom", ControlledRandom)
    history = ShowcaseHistory(
        issues=[
            Issue(week=1, project_ids=["agents2026-d"]),
            Issue(week=2, project_ids=[]),
            Issue(week=3, project_ids=[]),
        ]
    )
    result = select_builds(request(*(candidate(name) for name in "abcde")), history)
    assert ids(result, "random") == ["agents2026-d", "agents2026-e"]
    assert calls[0][1] == [1.0, 1.0, 0.5]
    assert "agents2026-d" not in calls[1][0]


def test_invalid_history_and_insufficient_candidates_fail_closed(tmp_path: Path) -> None:
    path = tmp_path / "history.json"
    with pytest.raises(ToolValidationError, match="missing or invalid"):
        read_history(path)
    path.write_text('{"schema_version": 2, "issues": []}')
    with pytest.raises(ToolValidationError):
        read_history(path)
    with pytest.raises(ValidationError):
        ShowcaseHistory(issues=[Issue(week=1, project_ids=[]), Issue(week=1, project_ids=[])])
    with pytest.raises(ValidationError):
        Issue(week=1, project_ids=["agents2026-a", "agents2026-a"])
    with pytest.raises(ToolValidationError, match="Fewer than four"):
        select_builds(request(candidate("a")), ShowcaseHistory(issues=[]))
    with pytest.raises(ValidationError):
        request(candidate("a"), candidate("a"))
    for score in [11, -1, float("nan"), float("inf")]:
        with pytest.raises(ValidationError):
            candidate("a", score)


def test_staff_tools_and_capability_filtering(tmp_path: Path) -> None:
    path = tmp_path / "history.json"
    path.write_text('{"schema_version": 1, "issues": []}')
    initial = path.read_bytes()

    class Catalog(FakeStudentProjects):
        def list_projects(self) -> list[StudentProject]:
            return [
                StudentProject(f"agents2026-{name}", f"https://{name}.example.edu")
                for name in "abcd"
            ]

    async def scenario() -> None:
        tool = SelectShowcaseTool(Catalog(), path)
        arguments = request(*(candidate(name) for name in "abcd")).model_dump(mode="json")
        for role in (None, "student"):
            assert not set(SHOWCASE_TOOL_IDS) & set(
                CourseCapabilityPolicy(student_projects_enabled=True)
                .authorize(principal(role))
                .tool_ids
            )
            with pytest.raises(ToolValidationError, match="TA, instructor, or admin"):
                await tool.execute(arguments, context(role))
            with pytest.raises(ToolValidationError, match="TA, instructor, or admin"):
                await ReadShowcaseHistoryTool(path).execute({}, context(role))
        staff_roles: tuple[Literal["ta", "instructor", "admin"], ...] = (
            "ta",
            "instructor",
            "admin",
        )
        for role in staff_roles:
            assert set(SHOWCASE_TOOL_IDS) <= set(
                CourseCapabilityPolicy(student_projects_enabled=True)
                .authorize(principal(role))
                .tool_ids
            )
            result = await tool.execute(arguments, context(role))
            assert result.storage_policy == "server_summary"
        assert not set(SHOWCASE_TOOL_IDS) & set(
            CourseCapabilityPolicy().authorize(principal("instructor")).tool_ids
        )
        bad = request(candidate("unknown"), *(candidate(name) for name in "abc")).model_dump(
            mode="json"
        )
        with pytest.raises(ToolValidationError, match="registered project"):
            await tool.execute(bad, context("instructor"))
        with pytest.raises(ToolValidationError, match="Invalid showcase"):
            await tool.execute({**arguments, "history_path": "/etc/passwd"}, context("instructor"))
        assert path.read_bytes() == initial
        path.write_text('{"schema_version": 1, "issues": [{"week": 4, "project_ids": []}]}')
        with pytest.raises(ToolValidationError, match="already recorded"):
            await tool.execute(arguments, context("instructor"))

    asyncio.run(scenario())


def test_random_pool_does_not_require_repository_scores() -> None:
    from course_server.student_projects.showcase import Eligibility

    pool = [
        Eligibility(project_id=f"agents2026-{name}", student_name=name, post_evidence="Week 4 post")
        for name in "abcde"
    ]
    selection = SelectionRequest(
        week=4,
        assignment_evidence="Week 4",
        candidates=[candidate("a"), candidate("b")],
        eligible_projects=pool,
    )
    history = ShowcaseHistory(issues=[Issue(week=3, project_ids=["agents2026-e"])])
    result = select_builds(selection, history)
    assert ids(result, "ranked") == ["agents2026-a", "agents2026-b"]
    assert set(ids(result, "random")) == {"agents2026-c", "agents2026-d"}
    assert result["ranking_scope"] == "Reviewed shortlist"
    assert result["eligible_count"] == 4
    with pytest.raises(ValidationError, match="belong"):
        SelectionRequest(
            week=4,
            assignment_evidence="Week 4",
            candidates=[candidate("z")],
            eligible_projects=pool,
        )
    with pytest.raises(ValidationError, match="duplicate eligible"):
        SelectionRequest(
            week=4,
            assignment_evidence="Week 4",
            candidates=[candidate("a")],
            eligible_projects=[*pool, pool[0]],
        )
    with pytest.raises(ToolValidationError, match="two assessed"):
        select_builds(selection.model_copy(update={"candidates": [candidate("a")]}), history)


def test_repository_documentation_can_establish_eligibility_without_post() -> None:
    from course_server.student_projects.showcase import Eligibility

    pool = [
        Eligibility(
            project_id=f"agents2026-{name}",
            student_name=name,
            repository_evidence="week2/README.md at abc describes the implemented Week 2 build",
        )
        for name in "abcd"
    ]
    assessed = [candidate(name, fit=4).model_dump(exclude={"post_evidence"}) for name in "ab"]
    selection = SelectionRequest(
        week=2,
        assignment_evidence="Week 2 requires five tools",
        candidates=[Assessment.model_validate(item) for item in assessed],
        eligible_projects=pool,
    )
    result = select_builds(selection, ShowcaseHistory(issues=[]))
    assert len(ids(result, "ranked") + ids(result, "random")) == 4
    assert all(item.post_evidence is None for item in selection.candidates)
    with pytest.raises(ValidationError, match="documentation evidence"):
        Eligibility(project_id="agents2026-missing", student_name="Missing")
    with pytest.raises(ValidationError):
        Assessment.model_validate(
            {
                **candidate("missing").model_dump(),
                "repository_evidence": None,
            }
        )


def test_saved_review_survives_retries_restart_and_history_changes(tmp_path: Path) -> None:
    from course_server.student_projects.showcase_store import read_snapshot, saved_selection

    history_path = tmp_path / "history.json"
    history = ShowcaseHistory(issues=[])
    original = request(*(candidate(n) for n in "abcde"))
    sites = {f"agents2026-{n}": f"https://example.edu/{n}/" for n in "abcde"}
    first, reused = saved_selection(history_path, original, history, sites)
    assert reused is False
    changed = request(*(candidate(n, 10 if n == "e" else 1) for n in "bcde"))
    second, reused = saved_selection(history_path, changed, history, sites)
    assert reused is True
    assert first == second
    saved = read_snapshot(tmp_path / "selections/week-04.json")
    assert saved.request == original
    assert not history_path.exists()  # Never write presentation history.
    with pytest.raises(ToolValidationError, match="history changed"):
        saved_selection(
            history_path, changed, ShowcaseHistory(issues=[Issue(week=1, project_ids=[])]), sites
        )
    (tmp_path / "selections/week-04.json").write_text("invalid")
    with pytest.raises(ToolValidationError, match="invalid"):
        saved_selection(history_path, original, history, sites)


def test_concurrent_draws_share_one_saved_selection(tmp_path: Path) -> None:
    from concurrent.futures import ThreadPoolExecutor

    from course_server.student_projects.showcase_store import saved_selection

    args = (
        tmp_path / "history.json",
        request(*(candidate(n) for n in "abcdef")),
        ShowcaseHistory(issues=[]),
        {f"agents2026-{n}": f"https://{n}.example.edu" for n in "abcdef"},
    )
    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(lambda _: saved_selection(*args), range(4)))
    assert sum(not reused for _, reused in results) == 1
    assert all(result == results[0][0] for result, _ in results)
