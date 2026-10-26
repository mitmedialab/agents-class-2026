from __future__ import annotations

import asyncio
import io
import json
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest
from PIL import Image
from pydantic import JsonValue

from agent_core import PrincipalContext
from course_server.agent import ToolExecutionContext, ToolValidationError
from course_server.auth import InMemoryAuthStore, UserAdminService
from course_server.config import ConfigurationError
from course_server.mail import InboundMail, OutboundMail, SentMail
from course_server.newsletter import (
    MIN_GOAL_FIT,
    NEWSLETTER_URI,
    PIONEER_QUOTES,
    RUBRIC,
    SCORE_SCHEMA,
    SCORE_WEIGHTS,
    AssignmentBrief,
    CourseWeek,
    EvidenceLimits,
    FileNewsletterStore,
    FoundImage,
    Highlight,
    HighlightImage,
    LectureNotes,
    NewsletterBranding,
    NewsletterCompositionError,
    NewsletterCopy,
    NewsletterIssue,
    NewsletterResourceCatalog,
    NewsletterScheduleError,
    NewsletterScoringError,
    NewsletterService,
    NewsletterSettings,
    NewsletterStateError,
    NewsletterStoreError,
    PioneerQuote,
    ProjectDocument,
    ProjectEvidence,
    ProjectLink,
    ProjectScore,
    RenderedPost,
    ScreenshotError,
    SiteScreenshot,
    WeeklyDigest,
    WeeklyEvidenceCollector,
    build_editorial_user_prompt,
    build_highlights_user_prompt,
    choose_quote,
    cid_image_source,
    compact_slides_text,
    compose_editorial,
    compose_highlights,
    compose_newsletter,
    encode_jpeg,
    learning_goals_from_syllabus,
    load_assignment_brief,
    load_lecture_notes,
    parse_schedule,
    parse_score,
    project_label,
    render_html,
    render_markdown,
    render_text,
    score_breakdown,
    select_highlights,
    select_week,
    validate_editorial,
    verify_quote,
)
from course_server.newsletter.cli import main as newsletter_main
from course_server.newsletter.collect import WeekPageFinder, notebook_prose, week_site_pages
from course_server.newsletter.compose import (
    EDITORIAL_MARKER,
    HIGHLIGHTS_MARKER,
    build_editorial_system_prompt,
    headline_names_topic,
    topic_terms,
    validate_highlights,
)
from course_server.newsletter.images import filter_candidates, fragment_shell, is_html_fragment
from course_server.newsletter.jobs import NewsletterJobRunner
from course_server.newsletter.score import SCORING_MARKER, build_score_system_prompt
from course_server.newsletter.screenshots import still_png
from course_server.newsletter.service import adopt_browser_pages
from course_server.newsletter.tools import NewsletterTools
from course_server.student_projects import (
    RepositoryView,
    StudentProject,
    StudentProjectNotFound,
)

EASTERN = ZoneInfo("America/New_York")
SCHEDULE = """# Fall 2026 Schedule

| Date / Week | Lecture Topics (45 min) | Hands-on tutorial (50 min) |
| ----- | ----- | ----- |
| Week 1 (9/15) | **What is an AI agent?** *Prof. Pattie Maes* | Build a minimal agent loop. *WZ* |
| Week 2 (9/22) | **Tool use and agent interfaces.** *VD* | Build a tool-calling agent. |
| Week 3 (9/29) | No class | No class |
| Week 4 (10/6) | **Agent environments and evaluation** | Build an environment. |
| Week 14 TBD | **Final project presentations** | Final demos |
"""


def weeks() -> tuple[CourseWeek, ...]:
    return parse_schedule(SCHEDULE, timezone="America/New_York")


def test_schedule_ignores_columns_after_the_tutorial() -> None:
    """The maintained schedule also lists suggested readings; they are not part of a week."""

    with_readings = (
        "# Fall 2026 Schedule\n\n"
        "| Date / Week | Lecture Topics | Hands-on tutorial | Suggested readings |\n"
        "| ----- | ----- | ----- | ----- |\n"
        "| Week 1 (9/15) | **What is an AI agent?** *PM* | Build a loop. *WZ* "
        "| 1. A, [\u201cB\u201d](https://x.example/a).<br>2. C. |\n"
        "| Week 2 (9/22) | No class | No class | No assigned readings. |\n"
    )
    first, second = parse_schedule(with_readings, timezone="America/New_York")
    assert (first.number, first.topic, first.tutorial) == (
        1,
        "What is an AI agent?",
        "Build a loop.",
    )
    assert second.has_class is False


def test_schedule_parses_dated_weeks_windows_and_goals() -> None:
    parsed = weeks()

    assert [week.number for week in parsed] == [1, 2, 3, 4]
    week1 = parsed[0]
    assert week1.class_date == date(2026, 9, 15)
    assert week1.starts_at == datetime(2026, 9, 15, tzinfo=EASTERN)
    assert week1.ends_at == datetime(2026, 9, 22, tzinfo=EASTERN)
    assert week1.topic == "What is an AI agent?"
    assert week1.tutorial == "Build a minimal agent loop."
    assert parsed[1].topic == "Tool use and agent interfaces."
    assert parsed[2].has_class is False
    assert parsed[3].ends_at == datetime(2026, 10, 13, tzinfo=EASTERN)


def test_select_week_uses_the_last_class_week_whose_build_window_closed() -> None:
    parsed = weeks()

    assert select_week(parsed, as_of=date(2026, 9, 22)).number == 1
    assert select_week(parsed, as_of=date(2026, 9, 28)).number == 1
    assert select_week(parsed, as_of=date(2026, 9, 29)).number == 2
    # Week 3 has no class, so it is never the "previous week" even after its window closes.
    assert select_week(parsed, as_of=date(2026, 10, 6)).number == 2
    assert select_week(parsed, as_of=date(2026, 10, 13)).number == 4
    assert select_week(parsed, week_number=2, as_of=date(2026, 9, 16)).number == 2
    with pytest.raises(NewsletterScheduleError):
        select_week(parsed, as_of=date(2026, 9, 20))
    with pytest.raises(NewsletterScheduleError):
        select_week(parsed, week_number=9, as_of=date(2026, 12, 1))
    with pytest.raises(NewsletterScheduleError):
        parse_schedule("# Schedule without dated rows\n", timezone="America/New_York")


@dataclass
class FakeRepository:
    site_url: str | None
    tree: list[str]
    files: dict[str, str]
    commits: list[tuple[str, str]]
    broken: bool = False


@dataclass
class FakeCatalog:
    repositories: dict[str, FakeRepository]
    requests: list[tuple[str, str, str | None]] = field(default_factory=list)

    def list_projects(self) -> list[StudentProject]:
        return [
            StudentProject(project_id, repository.site_url)
            for project_id, repository in sorted(self.repositories.items())
        ]

    def inspect_repository(
        self,
        project_id: str,
        view: RepositoryView,
        *,
        path: str | None = None,
        ref: str | None = None,
    ) -> dict[str, JsonValue]:
        self.requests.append((project_id, view, path))
        repository = self.repositories[project_id]
        if repository.broken:
            raise StudentProjectNotFound("Student project data was not found.")
        if view == "tree":
            return {
                "ref": ref or "main",
                "entries": [{"path": item, "type": "blob", "size": 1} for item in repository.tree],
                "truncated": False,
            }
        if view == "file":
            assert path is not None
            if path not in repository.files:
                raise StudentProjectNotFound("missing")
            return {"ref": "main", "path": path, "text": repository.files[path], "truncated": False}
        if view == "commits":
            return {
                "ref": "main",
                "commits": [
                    {"sha": "abc", "message": message, "date": when, "author": "Student"}
                    for when, message in repository.commits
                ],
            }
        raise AssertionError(f"unexpected view {view}")


def fake_catalog() -> FakeCatalog:
    template = ["LICENSE", "README.md", "website/index.html", "weekly_builds/week01/.gitkeep"]
    return FakeCatalog(
        {
            "agents2026-ada": FakeRepository(
                site_url="https://mitmedialab.github.io/agents2026-ada/",
                tree=[
                    *template,
                    "weekly_builds/week01/README.md",
                    "weekly_builds/week01/agent.py",
                    "weekly_builds/week01/notes/PLAN.md",
                    "weekly_builds/week01/node_modules/pkg/README.md",
                    "weekly_builds/week02/README.md",
                    "website/style.css",
                ],
                files={
                    "weekly_builds/week01/README.md": "# Loop\n\nA   minimal   agent loop with  "
                    "a scratch-built planner that is described at some length here.",
                    "weekly_builds/week01/notes/PLAN.md": "Plan: observe, think, act.",
                },
                commits=[
                    ("2026-09-23T12:00:00Z", "Week 2 start"),
                    ("2026-09-21T23:30:00Z", "Week 1: agent loop\n\nDetails"),
                    ("2026-09-14T17:00:00Z", "Personalize repository README"),
                ],
            ),
            "agents2026-grace": FakeRepository(
                site_url="https://mitmedialab.github.io/agents2026-grace/",
                tree=template,
                files={},
                commits=[("2026-09-14T17:00:00Z", "Initial commit")],
            ),
            "agents2026-hal-9000": FakeRepository(
                site_url=None,
                tree=[*template, "weekly_builds/week01/README.md"],
                files={"weekly_builds/week01/README.md": "Hal's loop."},
                commits=[("2026-09-20T12:00:00Z", "week 1")],
            ),
            "agents2026-zed": FakeRepository(
                site_url="https://mitmedialab.github.io/agents2026-zed/",
                tree=template,
                files={},
                commits=[],
                broken=True,
            ),
        }
    )


def read_site(url: str) -> str | dict[str, object]:
    if url.endswith("week01.html"):
        return {"url": url, "text": "Post: I built a loop that   renames files.", "images": []}
    return {"url": url, "text": f"Welcome to {url}\n\n\n\nWeek 1 write-up", "images": []}


def find_week_page_for_tests(site_url: str, week: CourseWeek) -> str | None:
    if "ada" in site_url:
        return f"{site_url}week01.html"
    if "grace" in site_url:
        return f"{site_url}#week-01"
    if "zed" in site_url:
        raise RuntimeError("discovery exploded")
    return None


def test_collector_gathers_bounded_week_evidence_without_stopping_on_failures() -> None:
    catalog = fake_catalog()
    collector = WeeklyEvidenceCollector(
        catalog,
        repository_prefix="agents2026-",
        read_site=read_site,
        find_week_page=find_week_page_for_tests,
        limits=EvidenceLimits(max_document_chars=60, workers=1),
    )

    evidence = collector.collect(weeks()[0])

    assert [item.label for item in evidence] == ["Ada", "Grace", "Hal 9000", "Zed"]
    ada, grace, hal, zed = evidence
    assert ada.active and ada.week_file_count == 3 and ada.site_file_count == 2
    assert [document.path for document in ada.documents] == [
        "weekly_builds/week01/README.md",
        "weekly_builds/week01/notes/PLAN.md",
    ]
    assert ada.documents[0].truncated is True
    assert "   " not in ada.documents[0].text
    assert ada.commit_count == 1
    assert ada.commits[0].subject == "Week 1: agent loop"
    assert (
        ada.site_text
        == "Welcome to https://mitmedialab.github.io/agents2026-ada/\n\nWeek 1 write-up"
    )
    assert ada.week_page_url == "https://mitmedialab.github.io/agents2026-ada/week01.html"
    assert ada.week_page_text == "Post: I built a loop that renames files."
    assert grace.week_page_url == "https://mitmedialab.github.io/agents2026-grace/#week-01"
    assert grace.week_page_text is None  # a section of the root page, already in site_text
    assert hal.week_page_url is None
    assert any("discovery failed" in note for note in zed.notes)
    assert grace.active is False and grace.documents == () and grace.commit_count == 0
    assert hal.active and hal.site_url is None and hal.site_text is None
    assert zed.active is False
    assert any("unavailable" in note for note in zed.notes)
    assert all(
        request[2] is None or "node_modules" not in request[2] for request in catalog.requests
    )
    assert project_label("agents2026-juan-ruben", repository_prefix="agents2026-") == "Juan Ruben"
    assert project_label("other", repository_prefix="agents2026-") == "other"


def test_collector_reads_what_the_site_folder_holds_for_the_week() -> None:
    """A post the home page does not link, and a write-up a script loads, are still files."""

    site = "https://mitmedialab.github.io/agents2026-mo/"
    notebook = json.dumps(
        {
            "cells": [
                {"cell_type": "markdown", "metadata": {}, "source": ["# Knit\n", "It weaves."]},
                {"cell_type": "code", "metadata": {}, "source": ["print('x')"], "outputs": []},
            ]
        }
    )
    catalog = FakeCatalog(
        {
            "agents2026-mo": FakeRepository(
                site_url=site,
                tree=[
                    "website/index.html",
                    "website/rooms/week01.html",
                    "website/rooms/week01/extra/index.html",
                    "website/rooms/week02.html",
                    "website/docs/week01/part-1.md",
                    "website/docs/week11/part-1.md",
                    "weekly_builds/week01/.gitkeep",
                    "weekly_builds/week01/Agent.ipynb",
                ],
                files={
                    "website/docs/week01/part-1.md": "Glasses that prompt curiosity.",
                    "weekly_builds/week01/Agent.ipynb": notebook,
                },
                commits=[],
            ),
            # A site with earlier work but nothing named for this week, and no commits.
            "agents2026-quiet": FakeRepository(
                site_url="https://mitmedialab.github.io/agents2026-quiet/",
                tree=["website/index.html", "website/style.css", "website/week02.html"],
                files={},
                commits=[("2026-09-08T12:00:00Z", "Earlier work")],
            ),
        }
    )
    read: list[str] = []

    def reader(url: str) -> str | dict[str, object]:
        read.append(url)
        if url.endswith("rooms/week01.html"):
            return {"url": url, "text": "week 1   Melody, a music partner.", "images": []}
        return {"url": url, "text": "Home", "images": []}

    collector = WeeklyEvidenceCollector(
        catalog,
        repository_prefix="agents2026-",
        read_site=reader,
        find_week_page=lambda site_url, week: None,
        limits=EvidenceLimits(workers=1),
    )
    mo, quiet = collector.collect(weeks()[0])

    assert mo.week_page_url == f"{site}rooms/week01.html"
    assert mo.week_page_text == "week 1 Melody, a music partner."
    assert any("found among the site's files" in note for note in mo.notes)
    # Week-folder documents first (the notebook's prose only), then the site's write-up.
    assert [(document.path, document.text) for document in mo.documents] == [
        ("weekly_builds/week01/Agent.ipynb", "# Knit\nIt weaves."),
        ("website/docs/week01/part-1.md", "Glasses that prompt curiosity."),
    ]
    assert mo.week_site_file_count == 3 and mo.active
    assert f"{site}rooms/week02.html" not in read
    # A site that was not touched this week is not this week's work.
    assert quiet.site_file_count == 3 and quiet.week_site_file_count == 0
    assert quiet.week_page_url is None and quiet.active is False


def test_week_site_pages_put_the_post_before_pages_nested_inside_it() -> None:
    site = "https://mitmedialab.github.io/agents2026-mo"
    assert week_site_pages(
        [
            "week03/demo/app/index.html",
            "week03/notes page.html",
            "week03/index.html",
            "docs/week03/part-1.md",
        ],
        site_url=site,
    ) == [
        f"{site}/week03/",
        f"{site}/week03/notes%20page.html",
        f"{site}/week03/demo/app/",
    ]
    assert week_site_pages(["index.html"], site_url=site) == [f"{site}/index.html"]


def test_notebook_prose_survives_a_file_cut_off_mid_cell() -> None:
    notebook = json.dumps(
        {
            "cells": [
                {"cell_type": "markdown", "id": "a", "metadata": {}, "source": ["# One\n", "x"]},
                {"cell_type": "code", "metadata": {}, "source": ['"cell_type": "markdown"']},
                {"cell_type": "markdown", "metadata": {}, "source": "Two as a string"},
                {"cell_type": "markdown", "metadata": {}, "source": ["Three is cut off here"]},
            ]
        }
    )
    assert notebook_prose(notebook) == "# One\nx\n\nTwo as a string\n\nThree is cut off here"
    cut = notebook[: notebook.index("cut off here")]
    assert notebook_prose(cut) == "# One\nx\n\nTwo as a string"
    assert notebook_prose("not a notebook") == ""


def test_collector_opens_a_browser_only_when_served_html_names_no_week_post() -> None:
    rendered: list[str] = []

    def render(site_url: str, week: CourseWeek) -> RenderedPost | None:
        rendered.append(site_url)
        if "grace" in site_url:
            return RenderedPost(
                url=f"{site_url}week.html?id=week01", text="Week 01   A tool agent."
            )
        raise RuntimeError("browser exploded")

    collector = WeeklyEvidenceCollector(
        fake_catalog(),
        repository_prefix="agents2026-",
        read_site=read_site,
        find_week_page=lambda site_url, week: (
            f"{site_url}week01.html" if "ada" in site_url else None
        ),
        render_week_page=render,
        limits=EvidenceLimits(workers=1),
    )
    evidence = {item.label: item for item in collector.collect(weeks()[0])}

    # Ada's post was in the served HTML and Hal has no site, so neither opened a browser.
    assert sorted(rendered) == [
        "https://mitmedialab.github.io/agents2026-grace/",
        "https://mitmedialab.github.io/agents2026-zed/",
    ]
    assert evidence["Ada"].week_page_text == "Post: I built a loop that renames files."
    grace = evidence["Grace"]
    assert (
        grace.week_page_url == "https://mitmedialab.github.io/agents2026-grace/week.html?id=week01"
    )
    assert grace.week_page_text == "Week 01 A tool agent."
    assert grace.visitor_url == grace.week_page_url
    zed = evidence["Zed"]
    assert zed.week_page_url is None and zed.week_page_text is None
    assert any("browser discovery failed: RuntimeError" in note for note in zed.notes)


def evidence(project_id: str, label: str, *, active: bool, site: bool = True) -> ProjectEvidence:
    return ProjectEvidence(
        project_id=project_id,
        label=label,
        site_url=f"https://example.edu/{project_id}/" if site else None,
        week_file_count=2 if active else 0,
        site_file_count=1,
        commit_count=1 if active else 0,
        documents=(),
    )


def digest_for(week: CourseWeek, *, cooldown: frozenset[str] = frozenset()) -> WeeklyDigest:
    return WeeklyDigest(
        week=week,
        projects=(
            evidence("agents2026-ada", "Ada", active=True),
            evidence("agents2026-grace", "Grace", active=True),
            evidence("agents2026-hal", "Hal", active=True, site=False),
            evidence("agents2026-idle", "Idle", active=False),
        ),
        cooldown_project_ids=cooldown,
        highlight_count=2,
    )


def copy_json(*project_ids: str, extra: str = "") -> str:
    return json.dumps(
        {
            "highlights": [
                {
                    "project_id": project_id,
                    "headline": f"{project_id} gets loopy",
                    "description": (
                        f"A tiny loop made by {project_id.rsplit('-', 1)[-1]}. It looks, then "
                        f"acts, then stops when the job is done for "
                        f"{project_id.rsplit('-', 1)[-1]}." + extra
                    ),
                }
                for project_id in project_ids
            ],
        }
    )


EDITORIAL = (
    " ".join(["The loop ran and it worked well."] * 8)
    + "\n\n"
    + " ".join(["Next week, show each run from start to end."] * 7)
)
DENSE = (
    "Notwithstanding the aforementioned considerations, the heterogeneous submissions "
    "demonstrated extraordinarily sophisticated architectural instrumentation, particularly "
    "regarding observational fidelity; consequently, evaluation methodologies necessitate "
    "comprehensive reconsideration across every conceivable dimension of implementation. "
) * 3


def editorial_json(
    headline: str = "Agent Loop, There It Is", editorial: str = EDITORIAL, quote_choice: int = 0
) -> str:
    return json.dumps({"headline": headline, "editorial": editorial, "quote_choice": quote_choice})


def score_json(
    goal_fit: int,
    originality: int,
    execution: int,
    rationale: str = "ok",
    augmentation: int = 6,
    blank: bool = False,
) -> str:
    return json.dumps(
        {
            "originality": originality,
            "execution": execution,
            "goal_fit": goal_fit,
            "augmentation": augmentation,
            "blank": blank,
            "rationale": rationale,
            "built": "A tidy agent loop.",
            "went_well": "Clear loop.",
            "struggled": "Thin docs.",
            "quotes": [],
        }
    )


@dataclass
class ScriptedWriter:
    """Highlight and editorial responses are consumed in order; scores by project id."""

    responses: list[str]
    scores: dict[str, str] = field(default_factory=dict)
    editorials: list[str] = field(default_factory=lambda: [editorial_json()])
    prompts: list[str] = field(default_factory=list)
    editorial_prompts: list[str] = field(default_factory=list)
    score_prompts: list[str] = field(default_factory=list)
    judge_prompts: list[str] = field(default_factory=list)
    judge_choice: int = 1

    def write(self, *, system_prompt: str, user_prompt: str, schema: dict[str, object]) -> str:
        assert schema["type"] == "object"
        if system_prompt.startswith(SCORING_MARKER):
            self.score_prompts.append(user_prompt)
            project_id = user_prompt.split("Project id: ", 1)[1].split("\n", 1)[0]
            return self.scores.get(project_id, score_json(6, 6, 6))
        if system_prompt.startswith(EDITORIAL_MARKER):
            self.editorial_prompts.append(user_prompt)
            return self.editorials.pop(0) if len(self.editorials) > 1 else self.editorials[0]
        assert system_prompt.startswith(HIGHLIGHTS_MARKER)
        self.prompts.append(user_prompt)
        # The last scripted response is repeated so rule-breaking scripts exhaust every retry.
        return self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]

    def judge_images(self, *, prompt: str, images: Sequence[bytes]) -> int:
        self.judge_prompts.append(prompt)
        return self.judge_choice


def test_rubric_weights_four_criteria_and_old_scores_still_load() -> None:
    assert [criterion.key for criterion in RUBRIC] == [
        "originality",
        "goal_fit",
        "augmentation",
        "execution",
    ]
    assert SCORE_WEIGHTS == {
        "originality": 0.30,
        "goal_fit": 0.25,
        "augmentation": 0.25,
        "execution": 0.20,
    }
    assert set(cast(list[str], SCORE_SCHEMA["required"])) >= set(SCORE_WEIGHTS)

    score = parse_score(
        score_json(goal_fit=6, originality=9, execution=5, augmentation=8),
        project_id="agents2026-ada",
        eligible=True,
    )
    assert (score.originality, score.goal_fit, score.augmentation, score.execution) == (9, 6, 8, 5)
    assert score.total == round(0.30 * 9 + 0.25 * 6 + 0.25 * 8 + 0.20 * 5, 2)
    assert score_breakdown(score) == (
        "originality 9, assignment fit 6, cognitive augmentation 8, execution 5"
    )

    missing = json.loads(score_json(6, 6, 6))
    del missing["augmentation"]
    with pytest.raises(NewsletterScoringError, match="rubric"):
        parse_score(json.dumps(missing), project_id="agents2026-ada", eligible=True)

    # Issues scored before the rename stored originality as `interest`, with no augmentation.
    legacy = ProjectScore.model_validate(
        {"project_id": "agents2026-ada", "interest": 7, "execution": 6, "goal_fit": 8, "total": 7.2}
    )
    assert legacy.originality == 7 and legacy.augmentation is None
    assert "interest" not in legacy.model_dump() and score_breakdown(legacy).endswith(
        "cognitive augmentation -, execution 6"
    )

    # Ties on the weighted total go to assignment fit, then originality.
    tied = [
        ProjectScore(
            project_id="agents2026-bea",
            originality=8,
            execution=6,
            goal_fit=6,
            augmentation=6,
            total=6.6,
        ),
        ProjectScore(
            project_id="agents2026-cal",
            originality=6,
            execution=6,
            goal_fit=8,
            augmentation=6,
            total=6.6,
        ),
        ProjectScore(
            project_id="agents2026-dee",
            originality=10,
            execution=10,
            goal_fit=4,
            augmentation=10,
            total=8.5,
        ),
    ]
    assert select_highlights(tied, count=3) == (
        "agents2026-cal",
        "agents2026-bea",
        "agents2026-dee",
    )

    # A blank submission (only a starter or welcome site) is never featured.
    blank = parse_score(
        score_json(goal_fit=9, originality=9, execution=9, blank=True),
        project_id="agents2026-eve",
        eligible=True,
    )
    assert blank.blank and not score.blank
    assert select_highlights([*tied, blank], count=4) == (
        "agents2026-cal",
        "agents2026-bea",
        "agents2026-dee",
    )

    prompt = build_score_system_prompt(NewsletterBranding())
    assert "Score 4 things from 0 to 10" in prompt
    # Blank is about this week: a site holding only earlier weeks' work is still blank.
    assert "Set `blank` true only when the evidence shows nothing made for this week" in prompt
    assert "only work from earlier weeks and final-project ideas" in prompt
    assert "describe this week's build, not the site" in prompt
    for criterion in RUBRIC:
        assert f"- {criterion.key}: {criterion.guidance}" in prompt


def test_public_highlights_page_restates_the_rubric_and_selection_rules() -> None:
    """course://newsletter-highlights is what the email links to; it must match the code."""

    page = (
        Path(__file__).resolve().parents[2] / "shared/course/newsletter/highlights.md"
    ).read_text(encoding="utf-8")
    criterion_line = re.compile(
        r"^- \*\*(?P<name>[^,*]+), (?P<weight>\d+%)\.\*\* (?P<question>.+)$"
    )
    rows = {
        match["name"]: (match["weight"], match["question"])
        for match in map(criterion_line.match, page.splitlines())
        if match
    }
    assert rows == {
        criterion.name: (f"{round(criterion.weight * 100)}%", criterion.question)
        for criterion in RUBRIC
    }
    defaults = NewsletterSettings.from_environment({})
    words = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six"}
    assert f"**Highlights per issue:** {defaults.highlight_count}" in page
    assert f"features the {words[defaults.highlight_count]} that score highest" in page
    assert f"The {words[defaults.highlight_count]} highest weighted totals" in page
    assert f"at least {MIN_GOAL_FIT} on assignment fit" in page
    cooldown = defaults.highlight_cooldown_issues
    assert (
        "featured in the last issue sits this one out"
        if cooldown == 1
        else f"featured in either of the last {words[cooldown]} issues"
    ) in page
    assert "A tie goes to assignment fit, then to originality." in page


def test_links_send_readers_to_pages_that_render_on_their_own() -> None:
    site = "https://mitmedialab.github.io/agents2026-mo/"
    base = ProjectEvidence(
        project_id="agents2026-mo",
        label="Mo",
        site_url=site,
        week_file_count=1,
        site_file_count=3,
        commit_count=1,
    )
    post = base.model_copy(update={"week_page_url": f"{site}week01.html"})
    fragment = base.model_copy(
        update={"week_page_url": f"{site}rooms/week01.html", "week_page_fragment": True}
    )
    assert base.visitor_url == site and post.visitor_url == f"{site}week01.html"
    # A fragment is addressed on its site by name: a shell that loads posts by name opens it
    # there, and any other site just shows its home page.
    assert fragment.visitor_url == f"{site}#week01"
    odd = fragment.model_copy(update={"week_page_url": f"{site}rooms/week 1 (draft).html"})
    assert odd.visitor_url == site

    # The collector flags a fragment post and still reads its text for scoring.
    collector = WeeklyEvidenceCollector(
        fake_catalog(),
        repository_prefix="agents2026-",
        read_site=read_site,
        find_week_page=find_week_page_for_tests,
        is_fragment=lambda url: url.endswith("week01.html"),
        limits=EvidenceLimits(workers=1),
    )
    evidence = {item.label: item for item in collector.collect(weeks()[0])}
    ada, grace = evidence["Ada"], evidence["Grace"]
    assert ada.week_page_fragment and ada.week_page_text is not None
    assert ada.visitor_url == f"{ada.site_url}#week01"
    assert "links open the site" in " ".join(ada.notes)
    # A section of the root page is never a fragment.
    assert not grace.week_page_fragment and grace.visitor_url == grace.week_page_url

    # A post only the browser reached becomes the link, never the root or another site.
    browser_page = f"{site}?view=week01"
    assert adopt_browser_pages([base], {"agents2026-mo": browser_page})[0].week_page_url == (
        browser_page
    )
    assert adopt_browser_pages([post], {"agents2026-mo": browser_page})[0] == post
    assert adopt_browser_pages([base], {"agents2026-mo": site})[0] == base
    assert adopt_browser_pages([base], {"agents2026-mo": "https://elsewhere.example/w1"})[0] == base


def test_compose_writes_only_the_selected_projects_in_order_and_reprompts_once() -> None:
    week = weeks()[0]
    digest = digest_for(week, cooldown=frozenset({"agents2026-hal"}))
    selected = ("agents2026-ada", "agents2026-grace")
    branding = NewsletterBranding()
    writer = ScriptedWriter(
        [
            copy_json("agents2026-grace", "agents2026-ada", "agents2026-ada"),
            copy_json("agents2026-ada", "agents2026-grace"),
        ]
    )

    highlights = compose_highlights(digest, writer, selected=selected, branding=branding)

    assert [item.project_id for item in highlights] == list(selected)
    assert len(writer.prompts) == 2
    assert "Featured projects, in order: agents2026-ada, agents2026-grace" in writer.prompts[0]
    assert "FEATURED #1" in writer.prompts[0] and "agents2026-idle" not in writer.prompts[0]
    assert "assignment: Build a minimal agent loop.\n" in writer.prompts[0]
    assert "rejected" in writer.prompts[1]
    assert "exactly these project ids in this order" in writer.prompts[1]

    with pytest.raises(NewsletterCompositionError, match="broke platform rules"):
        compose_highlights(
            digest,
            ScriptedWriter([copy_json("agents2026-idle"), copy_json("agents2026-idle")]),
            selected=selected,
            branding=branding,
        )
    with pytest.raises(NewsletterCompositionError, match="invalid JSON"):
        compose_highlights(
            digest, ScriptedWriter(["not json"]), selected=selected, branding=branding
        )
    with pytest.raises(NewsletterCompositionError, match="must not contain links"):
        compose_highlights(
            digest,
            ScriptedWriter(
                [
                    copy_json(*selected, extra=" See https://x.y"),
                    copy_json(*selected, extra=" Mail me@x.edu"),
                ]
            ),
            selected=selected,
            branding=branding,
        )
    with pytest.raises(NewsletterCompositionError, match='must not use the word "brief"'):
        compose_highlights(
            digest,
            ScriptedWriter(
                [
                    copy_json(*selected, extra=" Fits the brief."),
                    copy_json(*selected, extra=" The brief."),
                ]
            ),
            selected=selected,
            branding=branding,
        )
    wordy = " ".join(["word"] * 60)
    with pytest.raises(NewsletterCompositionError, match=r"\d+ words; the limit is 48"):
        compose_highlights(
            digest,
            ScriptedWriter(
                [
                    copy_json(*selected).replace("A tiny loop", wordy),
                    copy_json(*selected).replace("A tiny loop", wordy),
                ]
            ),
            selected=selected,
            branding=branding,
        )
    with pytest.raises(NewsletterCompositionError, match="No project was selected"):
        compose_highlights(digest, ScriptedWriter([]), selected=(), branding=branding)
    dense = copy_json(*selected).replace(
        "A tiny loop made by",
        "Notwithstanding heterogeneous architectural instrumentation, the STALLED_SHORT "
        "outcome taxonomy substantiates a sophisticated observe_act loop by",
    )
    with pytest.raises(NewsletterCompositionError, match=r"reading ease|internal name"):
        compose_highlights(
            digest, ScriptedWriter([dense, dense]), selected=selected, branding=branding
        )
    same = copy_json(*selected).replace("for grace.", "for ada.")
    repeated = ScriptedWriter([same, same])
    with pytest.raises(NewsletterCompositionError, match="repeats a sentence from agents2026-ada"):
        compose_highlights(digest, repeated, selected=selected, branding=branding)
    assert "This week's assignment: Build a minimal agent loop." in build_highlights_user_prompt(
        digest, selected=selected
    )


def assignment_record(**changes: object) -> dict[str, object]:
    record: dict[str, object] = {
        "schema_version": 3,
        "assignment_id": "week-1",
        "revision": 2,
        "status": "published",
        "title": "Week 1: Designing Human\u2013Agent Interfaces",
        "summary": "Design an interface between an agent and a human.",
        "content_markdown": "# Week 1: Designing Human\u2013Agent Interfaces\n\nThink beyond chat.",
        "release_at": "2026-09-15T00:00:00-04:00",
        "due_at": "2026-09-21T23:59:00-04:00",
        "created_at": "2026-09-14T12:00:00-04:00",
        "updated_at": "2026-09-14T12:00:00-04:00",
        "created_by_user_id": "00000000-0000-4000-8000-000000000001",
    }
    record.update(changes)
    return record


def test_the_weeks_assignment_is_the_published_record_due_in_its_window(tmp_path: Path) -> None:
    week = weeks()[0]  # Sep 15 through Sep 21
    assert load_assignment_brief(tmp_path / "missing", week) is None
    (tmp_path / "week-1").mkdir()
    # The deployment keeps one folder per assignment; a flat file works the same way.
    (tmp_path / "week-1/week-1.json").write_text(json.dumps(assignment_record()))
    (tmp_path / "week-2.json").write_text(
        json.dumps(
            assignment_record(
                assignment_id="week-2",
                title="Week 2: Building Tools",
                release_at="2026-09-22T00:00:00-04:00",
                due_at="2026-09-28T23:59:00-04:00",
            )
        )
    )
    (tmp_path / "draft.json").write_text(
        json.dumps(assignment_record(assignment_id="draft", status="draft", title="Not posted"))
    )
    (tmp_path / "broken.json").write_text("{not json")
    (tmp_path / "notes.json").write_text(json.dumps({"title": "not an assignment record"}))

    brief = load_assignment_brief(tmp_path, week, limit=42)
    assert brief == AssignmentBrief(
        assignment_id="week-1",
        revision=2,
        title="Week 1: Designing Human\u2013Agent Interfaces",
        text="# Week 1: Designing Human\u2013Agent Interfaces",
        truncated=True,
    )
    second = load_assignment_brief(tmp_path, weeks()[1])
    assert second is not None and second.title == "Week 2: Building Tools"
    assert second.truncated is False
    assert load_assignment_brief(tmp_path, weeks()[2]) is None


def test_headline_must_reflect_the_assignments_main_topic() -> None:
    title = "Week 3: Designing Human\u2013Agent Interfaces"
    assert topic_terms(title) == ("designing", "human", "agent", "interfaces")
    assert "week" not in topic_terms("What this week is about: tools") and topic_terms("") == ()
    for related in (
        "Interface the Music",
        "Design of the Times",  # another form of "designing"
        "Only Human: Agents Mind Their Manners",
    ):
        assert headline_names_topic(related, title), related
    for unrelated in (
        "Hand-Off, Hands On",
        "Delegation Station: Agency Gets the Green Light",  # "agency" is not "agent"
        "Internal Affairs",  # "inter-" is not "interfaces"
    ):
        assert not headline_names_topic(unrelated, title), unrelated
    assert headline_names_topic("Anything Goes", "")  # nothing to check against

    problems = validate_editorial("Hand-Off, Hands On", EDITORIAL, topic=title)
    assert len(problems) == 1
    assert problems[0].startswith("headline must reflect the main topic of this week's assignment")
    assert "designing, human, agent, interfaces" in problems[0]
    assert validate_editorial("Interface the Music", EDITORIAL, topic=title) == ()

    # The composer shows the model the assignment as posted, feeds a miss back, and accepts a
    # headline that uses the title's terms.
    brief = AssignmentBrief(
        assignment_id="week-1", revision=1, title=title, text=f"# {title}\n\nThink beyond chat."
    )
    writer = ScriptedWriter(
        [], editorials=[editorial_json("Agency Station"), editorial_json("Interface Value")]
    )
    draft = compose_editorial(
        digest_for(weeks()[0]),
        (),
        writer,
        branding=NewsletterBranding(),
        assignment=brief,
        link_checker=None,
    )
    assert draft.headline == "Interface Value"
    first, retry = writer.editorial_prompts
    assert f"## The assignment as given to the class\nTitle: {title}" in first
    assert "Think beyond chat." in first
    assert "headline must reflect the main topic of this week's assignment" in retry
    system_prompt = build_editorial_system_prompt(NewsletterBranding())
    assert "the main topic of this week's assignment as the class received it" in system_prompt
    # Without a record, the schedule's assignment line and topic stand in.
    fallback = ScriptedWriter([], editorials=[editorial_json("Agent Loop, There It Is")])
    compose_editorial(
        digest_for(weeks()[0]), (), fallback, branding=NewsletterBranding(), link_checker=None
    )
    assert "No assignment record covers this week" in fallback.editorial_prompts[0]


def test_first_paragraph_synthesizes_approaches_instead_of_listing_builds() -> None:
    sites = [f"https://mitmedialab.github.io/agents2026-{name}/" for name in ("a", "b", "c", "d")]
    practice = " ".join(["Next week, show each run from start to end."] * 7)

    def editorial(first: str) -> str:
        return first + " " + " ".join(["The loop ran and it worked well."] * 5) + "\n\n" + practice

    grouped = editorial(
        f"Many of you moved the agent off the screen, into [glasses]({sites[0]}) "
        f"and [a watch]({sites[1]}). Others kept [a canvas]({sites[2]}) in view."
    )
    assert validate_editorial("Fine", grouped, project_urls=sites) == ()

    listed = editorial(
        f"[A map]({sites[0]}) showed traces. [A recorder]({sites[1]}) asked gently. "
        f"[A canvas]({sites[2]}) kept versions."
    )
    problems = validate_editorial("Fine", listed, project_urls=sites)
    assert (
        len(problems) == 1 and "3 sentences in the first paragraph point at a build" in problems[0]
    )

    crowded = editorial(
        f"You tried [glasses]({sites[0]}), [a watch]({sites[1]}), [a canvas]({sites[2]}) "
        f"and [a voice]({sites[3]})."
    )
    problems = validate_editorial("Fine", crowded, project_urls=sites)
    assert len(problems) == 1 and "links 4 builds" in problems[0]
    prompt = build_editorial_system_prompt(NewsletterBranding())
    assert "a synthesis of how the class answered the assignment, not a tour of builds" in prompt
    assert "Use at most 3 such links, in at most 2 sentences." in prompt


def test_compose_editorial_is_anonymous_short_constructive_and_link_checked() -> None:
    week = weeks()[0]
    digest = digest_for(week)
    branding = NewsletterBranding()
    scores = (
        ProjectScore(
            project_id="agents2026-ada",
            originality=8,
            execution=7,
            goal_fit=9,
            total=8.2,
            built="Ada built a loop.",
            went_well="Clean loop.",
            struggled="Sparse tests.",
            quotes=("Agents learn best when reality gets a vote.", "My loop ate my homework."),
        ),
        ProjectScore(
            project_id="agents2026-grace", originality=5, execution=5, goal_fit=6, total=5.4
        ),
    )
    lecture = LectureNotes(
        title="Week 1 slides",
        slides_text="What is an agent? Senses, acts, maintains state, learns.",
        learning_goals="1. Build functional AI agents.",
    )

    def link_checker(url: str) -> bool:
        return url.startswith("https://good.example/")

    writer = ScriptedWriter(
        [], editorials=[editorial_json("Agent Loop, There It Is", quote_choice=1)]
    )

    draft = compose_editorial(
        digest, scores, writer, branding=branding, lecture=lecture, link_checker=link_checker
    )

    assert (draft.headline, draft.editorial, draft.quote_choice) == (
        "Agent Loop, There It Is",
        EDITORIAL,
        1,
    )
    prompt = writer.editorial_prompts[0]
    assert "Submission 1: built: Ada built a loop. / went well: Clean loop." in prompt
    assert "students;" not in prompt and "Nothing posted" not in prompt
    assert '1. "Agents learn best when reality gets a vote." \u2014 Ada' in prompt
    assert '2. "My loop ate my homework." \u2014 Ada' in prompt
    assert "## What was taught this week: Week 1 slides\nWhat is an agent?" in prompt
    assert "## Course learning goals (syllabus)\n1. Build functional AI agents." in prompt
    assert prompt == build_editorial_user_prompt(digest, scores, lecture=lecture)
    assert "No slide deck is published" in build_editorial_user_prompt(digest, scores)

    # Names, participation counts, long copy, and dead links are all rejected with feedback.
    names = ["Ada", "Grace", "Hal", "Idle"]
    assert validate_editorial("Fine", EDITORIAL, names=names) == ()
    assert any(
        'name students (found "Grace")' in item
        for item in validate_editorial("Fine", EDITORIAL + " Grace shone.", names=names)
    )
    assert any(
        "count participation" in item
        for item in validate_editorial("Fine", "Twenty-seven of you posted. " + EDITORIAL)
    )
    assert any(
        "count participation" in item
        for item in validate_editorial("Fine", EDITORIAL + " 12 students struggled.")
    )
    # Two paragraphs; the second names no build and keeps sentences light on commas.
    jack = "https://mitmedialab.github.io/agents2026-jack/"
    celebrate = " ".join(["The loop ran and it worked well."] * 7)
    practice = " ".join(["Next week, show each run from start to end."] * 7)
    assert any(
        "exactly two paragraphs" in item
        for item in validate_editorial("Fine", celebrate + " " + practice)
    )
    linked_first = (
        f"A [rolling-ball world]({jack}weeks/week-01.html), a renamer, and a town all ran. "
        + celebrate
        + "\n\n"
        + practice
    )
    assert validate_editorial("Fine", linked_first, project_urls=[jack]) == ()
    pointed = (
        celebrate
        + "\n\n"
        + f"Next week, look at [the ball]({jack}weeks/week-01.html) again. "
        + practice
    )
    assert any(
        "must not point at a particular build" in item
        for item in validate_editorial("Fine", pointed, project_urls=[jack])
    )
    listy = celebrate + "\n\nPractice traces, stopping rules, and user checks. " + practice
    assert any(
        "at most one comma" in item and "Practice traces, stopping rules" in item
        for item in validate_editorial("Fine", listy)
    )
    dense_problems = validate_editorial("Fine", DENSE)
    assert any("sentences average" in item for item in dense_problems)
    assert any("longest sentence" in item for item in dense_problems)
    assert any("reading ease" in item for item in dense_problems)
    assert any("no semicolons" in item for item in dense_problems)
    borrowed = EDITORIAL + " Do not become a horoscope in a trench coat."
    assert any(
        'reuse wording from a candidate quote (found "a horoscope in a trench")' in item
        for item in validate_editorial(
            "Fine", borrowed, quotes=["Otherwise it's a horoscope in a trench coat."]
        )
    )
    assert validate_editorial("Fine", EDITORIAL, quotes=["Otherwise it's a horoscope."]) == ()
    assert any(
        "write between 100 and 165" in item
        for item in validate_editorial("Fine", " ".join(["word"] * 200))
    )
    linked = EDITORIAL + " See [the ReAct paper](https://good.example/react) for more."
    assert validate_editorial("Fine", linked, link_checker=link_checker) == ()
    dead = EDITORIAL + " See [notes](https://bad.example/gone)."
    assert any(
        "does not resolve" in item
        for item in validate_editorial("Fine", dead, link_checker=link_checker)
    )
    many = EDITORIAL + (
        " [a](https://good.example/1) [b](https://good.example/2) [c](https://good.example/3)"
    )
    assert any(
        "3 reference links" in item
        for item in validate_editorial("Fine", many, link_checker=link_checker)
    )
    # Links to students' own sites (first paragraph) are neither counted nor fetched.
    sites = ["https://a.example/", "https://g.example/"]
    site_linked = (
        "[A rolling-ball world](https://a.example/) and [a renamer](https://g.example)"
        " and [a maze](https://a.example/) plus [one paper](https://good.example/paper). "
        + EDITORIAL
    )
    assert (
        validate_editorial(
            "Fine", site_linked, project_urls=sites, link_checker=lambda url: "good" in url
        )
        == ()
    )
    assert "site: https://example.edu/agents2026-ada/" in prompt
    assert any(
        "must not contain links" in item
        for item in validate_editorial("Fine", EDITORIAL + " See https://bare.example/")
    )

    short = ScriptedWriter(
        [], editorials=[editorial_json(editorial="Too short."), editorial_json()]
    )
    retried = compose_editorial(digest, scores, short, branding=branding, link_checker=None)
    assert retried.editorial == EDITORIAL
    assert "editorial has 2 words; write between 100 and 165" in short.editorial_prompts[1]
    with pytest.raises(NewsletterCompositionError, match="editorial broke platform rules"):
        compose_editorial(
            digest,
            scores,
            ScriptedWriter([], editorials=[editorial_json(quote_choice=5)]),
            branding=branding,
            link_checker=None,
        )

    copy, chosen = compose_newsletter(
        digest,
        scores,
        ScriptedWriter([copy_json("agents2026-ada")], editorials=[editorial_json(quote_choice=2)]),
        selected=("agents2026-ada",),
        branding=branding,
        link_checker=None,
    )
    assert copy.headline == "Agent Loop, There It Is" and len(copy.highlights) == 1
    assert chosen == ("agents2026-ada", "Ada", "My loop ate my homework.")


def test_lecture_notes_come_from_the_week_deck_and_syllabus_goals(tmp_path: Path) -> None:
    slides = tmp_path / "slides" / "week-01"
    slides.mkdir(parents=True)
    (slides / "resource.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "resource": {
                    "uri": "course://slides/week-01",
                    "title": "Agents 101",
                    "media_type": "text/markdown",
                    "file": "deck.md",
                },
            }
        )
    )
    (slides / "deck.md").write_text(
        "--- Page 1 ---\nWhat   is an agent?\n\n\n\n--- Page 2 ---\nSenses, acts, learns.\n"
    )
    syllabus = tmp_path / "syllabus.md"
    syllabus.write_text(
        "# Course\n\n## **Learning Goals**\n\n1. Build agents.\n2. Evaluate them.\n\n"
        "## Structure\n\nWeekly.\n"
    )

    notes = load_lecture_notes(tmp_path / "slides", syllabus, weeks()[0])

    assert notes is not None and notes.title == "Agents 101" and notes.truncated is False
    assert notes.slides_text == "What is an agent?\n\nSenses, acts, learns."
    assert notes.learning_goals == "1. Build agents.\n2. Evaluate them."
    assert load_lecture_notes(tmp_path / "slides", syllabus, weeks()[1]) is None
    assert compact_slides_text("a " * 50, limit=20) == ("a a a a a a a a a a", True)
    assert learning_goals_from_syllabus("# No goals here\n") == ""


def test_verify_quote_accepts_only_verbatim_student_prose() -> None:
    project = ProjectEvidence(
        project_id="agents2026-ada",
        label="Ada",
        week_file_count=1,
        site_file_count=1,
        commit_count=1,
        documents=(
            ProjectDocument(
                path="weekly_builds/week01/README.md",
                text="# Loop\n\nI learned that agents   learn best when\nreality gets a vote.",
            ),
        ),
        site_text="Welcome to my site, where \u201cthe loop is the lesson\u201d every week.",
    )
    assert (
        verify_quote("Agents learn best when reality gets a vote.", project)
        == "Agents learn best when reality gets a vote."
    )
    assert verify_quote("\u201cthe loop is the lesson\u201d every week.", project) != ""
    assert verify_quote("Agents learn best when reality votes.", project) == ""
    spiral = ProjectEvidence(
        project_id="agents2026-egemen",
        label="Egemen",
        week_file_count=1,
        site_file_count=1,
        commit_count=1,
        documents=(
            ProjectDocument(
                path="weekly_builds/week01/README.md",
                text=(
                    "## Why\n\nThe agent has to earn its calm with visible reasoning steps. "
                    "Otherwise it's a horoscope in a trench coat. "
                    "Even a happy prompt gets spiraled."
                ),
            ),
        ),
    )
    assert verify_quote("Otherwise it's a horoscope in a trench coat.", spiral) == (
        "The agent has to earn its calm with visible reasoning steps. "
        "Otherwise it's a horoscope in a trench coat."
    )
    assert verify_quote("Even a happy prompt gets spiraled.", spiral) == (
        "Even a happy prompt gets spiraled."
    )
    heading_only = spiral.model_copy(
        update={
            "documents": (
                ProjectDocument(
                    path="weekly_builds/week01/README.md",
                    text="## Why\n\nOtherwise it's a horoscope in a trench coat.",
                ),
            )
        }
    )
    assert verify_quote("Otherwise it's a horoscope in a trench coat.", heading_only) == (
        "Otherwise it's a horoscope in a trench coat."
    )
    assert verify_quote("Short quote here.", project) == ""
    assert verify_quote(" ".join(["word"] * 41), project) == ""


def sample_issue(*, status: str = "draft") -> NewsletterIssue:
    week = weeks()[0]
    return NewsletterIssue(
        issue_id="2026-week01",
        week=week,
        branding=NewsletterBranding(),
        subject="The Class Runtime from MAS.S60",
        body=NewsletterCopy(
            headline="Week one is in the loop.",
            editorial=(
                "The loop ran.\n\nSome looped twice; see "
                "[the ReAct paper](https://arxiv.org/abs/2210.03629?x=1&y=2) for why."
            ),
            highlights=(
                Highlight(
                    project_id="agents2026-ada",
                    headline="Ada <script>alert(1)</script> loops",
                    description=(
                        "A minimal agent loop built from scratch. It is the loop asked for."
                    ),
                ),
            ),
        ),
        roster=(
            ProjectLink(
                project_id="agents2026-ada",
                label="Ada",
                site_url="https://a.example/",
                post_url="https://a.example/week01.html",
            ),
            ProjectLink(
                project_id="agents2026-grace", label="Grace", site_url="https://g.example/?x=1&y=2"
            ),
            ProjectLink(project_id="agents2026-hal", label="Hal", site_url=None, posted=False),
            ProjectLink(project_id="agents2026-ivy", label="Ivy", site_url=None),
        ),
        quote=PioneerQuote(
            text="Agents learn best when reality gets a vote.",
            author="Ada",
            source="from their week 1 post",
            url="https://a.example/",
            kind="student",
        ),
        images=(
            HighlightImage(
                project_id="agents2026-ada",
                filename="agents2026-ada.jpg",
                media_type="image/jpeg",
                width=1200,
                height=750,
                kind="post_image",
                source_url="https://a.example/assets/hero.webp",
                page_url="https://a.example/week01.html",
            ),
        ),
        scores=(
            ProjectScore(
                project_id="agents2026-ada", originality=8, execution=7, goal_fit=9, total=8.2
            ),
            ProjectScore(
                project_id="agents2026-grace",
                originality=5,
                execution=5,
                goal_fit=6,
                total=5.4,
                built="Grace built a tiny tool-calling loop.",
            ),
        ),
        model_id="test-model",
        status="sent" if status == "sent" else "draft",
        created_at=datetime(2026, 9, 22, 13, 0, tzinfo=UTC),
        sent_at=datetime(2026, 9, 22, 14, 0, tzinfo=UTC) if status == "sent" else None,
    )


def test_render_text_and_html_carry_links_lists_quote_footer_and_escaping() -> None:
    issue = sample_issue()

    text = render_text(issue)
    assert text.startswith("THE CLASS RUNTIME · ISSUE 01\nWeek one is in the loop.")
    assert (
        "Week 1 · Sep 15 \u2013 Sep 21, 2026\nTHE ASSIGNMENT: Build a minimal agent loop." in text
    )
    assert "MAS.S60 · AI Agents for Cognitive Augmentation · MIT, Fall 2026" in text
    assert "1. Ada <script>alert(1)</script> loops — Ada" in text
    assert "   A minimal agent loop built from scratch. It is the loop asked for." in text
    assert "THE ASSIGNMENT: Build a minimal agent loop.\n\nThe loop ran." in text
    assert "brief" not in text.casefold() and "scroll" not in text.casefold()
    assert "\n\n— The Course Agent\n\n" in text
    # Colophon: the credit first, then the course line, then the class website last.
    assert text.rstrip().endswith(
        "This newsletter was created by The Course Agent.\n\n"
        "MAS.S60 · AI Agents for Cognitive Augmentation · MIT, Fall 2026\n"
        "Class website: https://cognitive-agents.media.mit.edu"
    )
    # The selection note is a footnote to the section, marked like its heading.
    assert "HIGHLIGHTS*\n" in text
    assert (
        "* How the Course Agent chooses what to highlight: "
        "https://cognitive-agents.media.mit.edu/?q=newslettercriteria\n\n"
        "ALL THE OTHER BUILDS THIS WEEK"
    ) in text
    assert "Open it: https://a.example/week01.html" in text
    assert (
        "ALL THE OTHER BUILDS THIS WEEK\n- Grace: Grace built a tiny tool-calling loop. "
        "https://g.example/?x=1&y=2\n- Ivy: Nothing posted for this week yet."
    ) in text
    assert "Hal" not in text
    assert "Ada — https://a.example/" not in text.split("ALL THE OTHER BUILDS")[1]
    assert '"Agents learn best when reality gets a vote."' in text
    assert "— Ada, from their week 1 post (https://a.example/)" in text
    assert "the ReAct paper (https://arxiv.org/abs/2210.03629?x=1&y=2)" in text
    assert "Class website: https://cognitive-agents.media.mit.edu" in text

    html = render_html(issue)
    assert "<script>" not in html
    assert "Ada &lt;script&gt;alert(1)&lt;/script&gt; loops" in html
    assert "<h1" in html and "Week one is in the loop." in html
    assert "How the week went</p>" in html
    assert "&mdash; The Course Agent</p>" in html
    assert "This newsletter was created by The Course Agent</p>" in html
    assert "Reviewed by" not in html and "Sent by" not in html
    footer = html.split("This newsletter was created by", 1)[1]
    assert footer.index("MAS.S60 · AI Agents") < footer.index(">cognitive-agents.media.mit.edu</a>")
    assert (
        '<a href="https://cognitive-agents.media.mit.edu/?q=newslettercriteria"'
        in html.split("All the other builds this week")[0].split("Open Ada")[1]
    )
    assert "How the Course Agent chooses what to highlight &rarr;</a>" in html
    assert ">Highlights*</p>" in html and ">*&nbsp;<a href=" in html
    assert html.count('bgcolor="#000000"') >= 4 and "supported-color-schemes" in html
    # Mac Mail keeps the dark design: both schemes declared, and its color filter off.
    assert '<meta name="color-scheme" content="light dark">' in html
    assert '<meta name="supported-color-schemes" content="light dark">' in html
    assert ":root{color-scheme:light dark;}" in html
    assert "html,body,*{-apple-color-filter:none !important;}</style>" in html
    assert '<body bgcolor="#000000" style="-apple-color-filter:none;' in html
    assert html.count("The loop ran.</p>") == 1
    assert (
        '<a href="https://arxiv.org/abs/2210.03629?x=1&amp;y=2"' in html
        and ">the ReAct paper</a> for why.</p>" in html
    )
    assert "Grace built a tiny tool-calling loop." in html
    # A blank build (only a starter or welcome site) is left off the list.
    grace_blank = issue.model_copy(
        update={
            "scores": tuple(
                score.model_copy(update={"blank": score.project_id == "agents2026-grace"})
                for score in issue.scores
            )
        }
    )
    assert [link.label for link in grace_blank.other_projects()] == ["Ivy"]
    assert "Grace" not in render_text(grace_blank).split("ALL THE OTHER BUILDS")[1]
    assert "Nothing posted for this week yet." in html
    # The assignment label and sentence are one step greyer than the headline and sections.
    assert 'color:#d6d6d0;">The assignment</p>' in html
    assert 'color:#d6d6d0;">Build a minimal agent loop.</p>' in html
    assert "Week 1 · Sep 15 \u2013 Sep 21, 2026" in html
    assert "Brief" not in html and "Keep scrolling" not in html
    assert 'src="2026-week01/agents2026-ada.jpg"' in html
    assert 'alt="Ada &lt;script&gt;alert(1)&lt;/script&gt; loops"' in html
    assert 'src="cid:agents2026-ada"' in render_html(issue, image_src=cid_image_source)
    assert '<a href="https://a.example/week01.html"' in html
    assert 'href="https://g.example/?x=1&amp;y=2"' in html
    grace = html.split('href="https://g.example/?x=1&amp;y=2" style="', 1)[1].split('"', 1)[0]
    assert "font-weight:600;" in grace and "border-bottom:1px solid #7d7d78" in grace
    assert ">Ivy</span>" in html and "Hal" not in html
    assert 'href="https://cognitive-agents.media.mit.edu"' in html
    assert "Alan Turing" not in html and "<title>The Class Runtime from MAS.S60</title>" in html
    assert "&ldquo;Agents learn best when reality gets a vote.&rdquo;" in html
    assert html.count("linear-gradient(#000000,#000000)") == 2
    assert '<a href="https://a.example/"' in html and "Ada, from their week 1 post</a>" in html
    assert "background-color:#000000" in html and "#f5f5f2" in html
    # Section labels are sentence-case sans, never tracked-out monospace, italic, or webfonts.
    # Section subheadings are real subheadings: 22px bold, between body text and headline.
    for heading in ("How the week went", "Highlights*", "All the other builds this week"):
        style = html.split(f">{heading}</p>", 1)[0].rsplit('style="', 1)[1]
        assert "font-size:22px" in style and "font-weight:700" in style, heading
    assert "monospace" not in html and "uppercase" not in html and "italic" not in html
    assert "fonts.googleapis.com" not in html
    # Secondary text is near-white: the site's faint grey never reaches the email.
    assert "#8b8b86" not in html and "#c9c9c4" not in html and "#f0f0ec" in html
    # Inline blend wrappers cancel the Gmail apps' dark-mode text recoloring; the Gmail iPhone
    # app ignored the stylesheet version. Images and rules stay outside the wrappers.
    wrapper = (
        '<div style="background:#000;mix-blend-mode:screen;">'
        '<div style="background:#000;mix-blend-mode:difference;">'
    )
    assert "u + .body" not in html and "gmail-blend" not in html and "<hr" not in html
    segments = html.split(wrapper)
    assert len(segments) == 7 + len(issue.body.highlights)
    for segment in segments[1:]:
        inner = segment.split("</div></div>", 1)[0]
        assert "<img" not in inner and "<div" not in inner
    assert html.count("linear-gradient(#2a2a28,#2a2a28)") == 4
    assert "border-bottom:1px solid #7d7d78" in html
    assert "\u2019" not in html and "\u201c" not in html


def test_store_round_trips_issues_and_derives_cooldown_and_used_quotes(tmp_path: Path) -> None:
    store = FileNewsletterStore(tmp_path / "newsletter")
    week1 = sample_issue(status="sent")
    week2 = week1.model_copy(
        update={
            "issue_id": "2026-week02",
            "week": weeks()[1],
            "body": week1.body.model_copy(
                update={
                    "highlights": (
                        week1.body.highlights[0].model_copy(
                            update={"project_id": "agents2026-grace"}
                        ),
                    )
                }
            ),
            "quote": PIONEER_QUOTES[1],
        }
    )
    week4_draft = week1.model_copy(
        update={"issue_id": "2026-week04", "week": weeks()[3], "status": "draft", "sent_at": None}
    )
    for issue in (week2, week1, week4_draft):
        store.save(issue)

    assert store.load("2026-week01") == week1
    assert [issue.issue_id for issue in store.list_issues()] == [
        "2026-week01",
        "2026-week02",
        "2026-week04",
    ]
    assert (
        (tmp_path / "newsletter/issues/2026-week01.txt").read_text().startswith("THE CLASS RUNTIME")
    )
    assert (
        (tmp_path / "newsletter/issues/2026-week01.html").read_text().startswith("<!DOCTYPE html>")
    )
    assert store.recently_highlighted(before_week=3, cooldown=1) == {"agents2026-grace"}
    assert store.recently_highlighted(before_week=3, cooldown=2) == {
        "agents2026-ada",
        "agents2026-grace",
    }
    assert store.recently_highlighted(before_week=2, cooldown=2) == {"agents2026-ada"}
    assert store.recently_highlighted(before_week=5, cooldown=0) == frozenset()
    assert store.used_quote_texts() == {
        "Agents learn best when reality gets a vote.",
        PIONEER_QUOTES[1].text,
    }
    assert store.load("2026-week09") is None
    with pytest.raises(NewsletterStoreError):
        store.load("../etc/passwd")

    saved = store.save_image("2026-week01", "agents2026-ada.jpg", b"\xff\xd8jpeg")
    assert saved == tmp_path / "newsletter/issues/2026-week01/agents2026-ada.jpg"
    assert store.load_image("2026-week01", "agents2026-ada.jpg") == b"\xff\xd8jpeg"
    assert (
        'src="2026-week01/agents2026-ada.jpg"'
        in (tmp_path / "newsletter/issues/2026-week01.html").read_text()
    )
    with pytest.raises(NewsletterStoreError):
        store.load_image("2026-week01", "missing.jpg")
    with pytest.raises(NewsletterStoreError):
        store.image_path("2026-week01", "../secret.jpg")
    with pytest.raises(NewsletterStoreError):
        store.image_path("2026-week01", ".hidden")


def test_store_places_an_email_sized_logo_and_the_email_inlines_it(tmp_path: Path) -> None:
    logo_source = tmp_path / "wordmark.png"
    Image.new("RGBA", (2000, 600), (255, 255, 255, 128)).save(logo_source, format="PNG")
    store = FileNewsletterStore(tmp_path / "newsletter", logo_path=logo_source)
    store.save_image("2026-week01", "agents2026-ada.jpg", b"\xff\xd8jpeg")

    store.save(sample_issue())

    placed = tmp_path / "newsletter/issues/2026-week01/newsletter-logo.png"
    assert placed.is_file()
    with Image.open(placed) as image:
        assert image.size == (1000, 300) and image.mode == "RGBA"
    html = (tmp_path / "newsletter/issues/2026-week01.html").read_text()
    assert 'src="2026-week01/newsletter-logo.png"' in html and 'alt="The Class Runtime"' in html
    assert "The Class Runtime &middot; Issue" not in html and ">Issue 01</p>" in html
    assert store.logo_bytes("2026-week01") == placed.read_bytes()

    async def scenario() -> None:
        service = NewsletterService(settings=NewsletterSettings(), weeks=weeks(), store=store)
        adapter = RecordingMailAdapter()
        preview = await service.send(
            "2026-week01", mail=adapter, recipients=["me@mit.edu"], test_only=True
        )
        assert preview.status == "draft"
        logo = [
            image
            for image in adapter.sent[0].inline_images
            if image.content_id == "newsletter-logo"
        ]
        assert len(logo) == 1 and logo[0].filename == "newsletter-logo.png"
        assert (
            adapter.sent[0].html is not None and 'src="cid:newsletter-logo"' in adapter.sent[0].html
        )

    asyncio.run(scenario())

    store.clear_images("2026-week01")
    assert placed.is_file()  # the logo survives image refreshes

    plain_store = FileNewsletterStore(tmp_path / "plain")
    plain_store.save(sample_issue())
    plain_html = (tmp_path / "plain/issues/2026-week01.html").read_text()
    assert (
        "newsletter-logo" not in plain_html and "The Class Runtime &middot; Issue 01" in plain_html
    )


def test_encode_jpeg_downscales_captures_to_email_width() -> None:
    import io

    buffer = io.BytesIO()
    Image.new("RGBA", (2400, 1500), (10, 20, 30, 255)).save(buffer, format="PNG")

    shot = encode_jpeg(buffer.getvalue(), max_width=1200, quality=80)

    assert (shot.width, shot.height, shot.media_type) == (1200, 750, "image/jpeg")
    assert shot.data.startswith(b"\xff\xd8")
    small = io.BytesIO()
    Image.new("RGB", (300, 200)).save(small, format="PNG")
    assert encode_jpeg(small.getvalue(), max_width=1200, quality=80).width == 300


def test_image_finder_reads_fragments_in_their_shell_and_offers_video_posters() -> None:
    # A post a site's script inserts into its styled shell (no document, no styles of its own).
    fragment = (
        '<h1>shape the world</h1><figure><video controls poster="media/week01/still.png">'
        '<source src="media/week01/demo.webm"></video></figure>'
    )
    assert is_html_fragment(fragment)
    assert not is_html_fragment("<!doctype html><html><head></head><body><p>x</p></body></html>")
    assert not is_html_fragment('<link rel="stylesheet" href="style.css"><h1>styled</h1>')
    assert not is_html_fragment("<style>h1{color:red}</style><h1>styled</h1>")
    assert not is_html_fragment("plain text, not markup")
    shell = fragment_shell(fragment, base_url='https://mitmedialab.github.io/agents2026-mo/"x')
    assert shell.startswith("<!DOCTYPE html><html><head>")
    assert '<base href="https://mitmedialab.github.io/agents2026-mo/&quot;x">' in shell
    assert shell.endswith(f"<body>{fragment}</body></html>")

    page = "https://mitmedialab.github.io/agents2026-mo/rooms/week01.html"
    candidates = filter_candidates(
        [
            {
                "index": 0,
                "tag": "video",
                "width": 300,
                "height": 150,
                "alt": "demo",
                "src": "https://mitmedialab.github.io/agents2026-mo/media/week01/demo.webm",
                "poster": "https://mitmedialab.github.io/agents2026-mo/media/week01/still.png",
                "visible": True,
            },
            # A broken image reports itself invisible and is never captured.
            {"index": 1, "tag": "img", "width": 900, "height": 600, "src": "x", "visible": False},
            {"index": 2, "tag": "video", "width": 640, "height": 360, "poster": "data:x"},
        ],
        page_url=page,
    )
    assert [(c.index, c.poster) for c in candidates] == [
        (2, ""),
        (0, "https://mitmedialab.github.io/agents2026-mo/media/week01/still.png"),
    ]

    buffer = io.BytesIO()
    Image.new("RGBA", (1440, 960), (10, 20, 30, 128)).save(buffer, format="PNG")
    png, width, height = still_png(buffer.getvalue(), min_width=280, min_height=140, max_width=1200)
    assert (width, height) == (1200, 800) and png.startswith(b"\x89PNG")
    with Image.open(io.BytesIO(png)) as decoded:
        assert decoded.mode == "RGB"
    tiny = io.BytesIO()
    Image.new("RGB", (100, 100)).save(tiny, format="PNG")
    with pytest.raises(ScreenshotError, match="too small"):
        still_png(tiny.getvalue(), min_width=280, min_height=140, max_width=1200)
    with pytest.raises(ScreenshotError, match="decoded"):
        still_png(b"not an image", min_width=280, min_height=140, max_width=1200)


def test_quotes_rotate_by_week_and_skip_quotes_already_sent() -> None:
    assert choose_quote(week_number=1, used_texts=()) == PIONEER_QUOTES[0]
    assert choose_quote(week_number=2, used_texts=()) == PIONEER_QUOTES[1]
    assert choose_quote(week_number=1, used_texts={PIONEER_QUOTES[0].text}) == PIONEER_QUOTES[1]
    assert choose_quote(week_number=len(PIONEER_QUOTES) + 1, used_texts=()) == PIONEER_QUOTES[0]
    everything = {quote.text for quote in PIONEER_QUOTES}
    assert choose_quote(week_number=3, used_texts=everything) == PIONEER_QUOTES[2]
    assert len(everything) == len(PIONEER_QUOTES)


@dataclass
class RecordingMailAdapter:
    sent: list[OutboundMail] = field(default_factory=list)
    fail_for: set[str] = field(default_factory=set)

    async def send_message(self, message: OutboundMail) -> SentMail:
        if message.to[0] in self.fail_for:
            raise RuntimeError("provider rejected the message")
        self.sent.append(message)
        return SentMail(
            provider_message_id=f"p-{len(self.sent)}", internet_message_id=f"<m{len(self.sent)}@x>"
        )

    async def reply_to_message(
        self, original: object, *, text: str, headers: dict[str, str] | None = None
    ) -> SentMail:
        raise AssertionError("not used")

    async def reply_to_sent_message(
        self,
        original: SentMail,
        *,
        to: tuple[str, ...],
        subject: str,
        text: str,
        headers: dict[str, str] | None = None,
    ) -> SentMail:
        raise AssertionError("not used")

    async def fetch_new_messages(self, *, since: datetime) -> list[InboundMail]:
        return []


@dataclass
class FakeImageFinder:
    calls: list[tuple[str, int, str]] = field(default_factory=list)
    post_urls: dict[str, str | None] = field(default_factory=dict)
    fail_for: set[str] = field(default_factory=set)
    fragment_for: set[str] = field(default_factory=set)

    def find(
        self, *, site_url: str, week: CourseWeek, context: str, post_url: str | None = None
    ) -> FoundImage | None:
        self.calls.append((site_url, week.number, context))
        self.post_urls[site_url] = post_url
        if site_url in self.fail_for:
            raise ScreenshotError("Site inspection failed (Timeout).")
        return FoundImage(
            shot=SiteScreenshot(
                data=b"\xff\xd8jpeg", media_type="image/jpeg", width=1200, height=750
            ),
            kind="post_image",
            page_url=f"{site_url}week01.html",
            source_url=f"{site_url}assets/hero.webp",
            page_is_fragment=site_url in self.fragment_for,
        )


def make_service(
    tmp_path: Path,
    writer: ScriptedWriter,
    *,
    cooldown: int = 2,
    image_finder: FakeImageFinder | None = None,
    find_week_page: WeekPageFinder | None = None,
    assignment: AssignmentBrief | None = None,
) -> tuple[NewsletterService, FileNewsletterStore]:
    store = FileNewsletterStore(tmp_path / "newsletter")
    settings = NewsletterSettings(highlight_count=2, highlight_cooldown_issues=cooldown)
    service = NewsletterService(
        settings=settings,
        weeks=weeks(),
        store=store,
        collector=WeeklyEvidenceCollector(
            fake_catalog(),
            repository_prefix="agents2026-",
            read_site=read_site,
            find_week_page=find_week_page,
            limits=EvidenceLimits(workers=1),
        ),
        writer=writer,
        image_finder=image_finder or FakeImageFinder(),
        link_checker=None,
        lecture_loader=lambda week: None,
        assignment_loader=lambda week: assignment,
        model_id="test-model",
        clock=lambda: datetime(2026, 9, 22, 15, 0, tzinfo=UTC),
    )
    return service, store


def test_the_image_finder_starts_from_the_post_the_collector_found(tmp_path: Path) -> None:
    """A post no link names (found among the site's files) must still supply the image."""

    writer = ScriptedWriter(
        [copy_json("agents2026-ada", "agents2026-hal-9000")],
        scores={
            "agents2026-ada": score_json(goal_fit=9, originality=8, execution=7),
            "agents2026-hal-9000": score_json(goal_fit=7, originality=6, execution=6),
        },
    )
    finder = FakeImageFinder()
    service, _ = make_service(
        tmp_path, writer, image_finder=finder, find_week_page=find_week_page_for_tests
    )

    service.draft(as_of=date(2026, 9, 22))

    ada_site = "https://mitmedialab.github.io/agents2026-ada/"
    assert finder.post_urls == {ada_site: f"{ada_site}week01.html"}  # Hal has no site


def test_the_service_writes_the_issue_against_the_weeks_assignment_record(tmp_path: Path) -> None:
    writer = ScriptedWriter(
        [copy_json("agents2026-ada", "agents2026-hal-9000")],
        scores={
            "agents2026-ada": score_json(goal_fit=9, originality=8, execution=7),
            "agents2026-hal-9000": score_json(goal_fit=7, originality=6, execution=6),
        },
        editorials=[editorial_json("Loop the Loop"), editorial_json("First Agents")],
    )
    brief = AssignmentBrief(
        assignment_id="week-1",
        revision=2,
        title="Week 1: Your Website, Project Ideas, and First Agent",
        text="# Week 1\n\nImplement your first agent from scratch.",
    )
    service, _ = make_service(tmp_path, writer, assignment=brief)

    issue = service.draft(as_of=date(2026, 9, 22))

    # "Loop" is the schedule's word; the record's title is what the headline must reflect.
    assert issue.body.headline == "First Agents"
    assert (
        "Title: Week 1: Your Website, Project Ideas, and First Agent"
        in (writer.editorial_prompts[0])
    )
    assert "Implement your first agent from scratch." in writer.editorial_prompts[0]


def test_highlight_copy_never_makes_the_student_the_tool() -> None:
    selected = ("agents2026-ada",)
    labels = {"agents2026-ada": "Ada"}
    wrong = Highlight(
        project_id="agents2026-ada",
        headline="Loop the loop",
        description="Ada helps you plan a trip. It stops when the plan is done.",
    )
    problems = validate_highlights((wrong,), selected=selected, labels=labels)
    assert len(problems) == 1 and 'opens a sentence with "Ada"' in problems[0]
    # The build as subject, a possessive, and a word that merely starts the same are all fine.
    fine = wrong.model_copy(
        update={
            "description": (
                "Ada's agent helps you plan a trip. Adaptive steps stop it when the plan is done."
            )
        }
    )
    assert validate_highlights((fine,), selected=selected, labels=labels) == ()
    assert validate_highlights((wrong,), selected=selected) == ()


def test_a_fragment_post_found_by_the_browser_never_becomes_the_link(tmp_path: Path) -> None:
    writer = ScriptedWriter(
        [copy_json("agents2026-ada", "agents2026-hal-9000")],
        scores={
            "agents2026-ada": score_json(goal_fit=9, originality=8, execution=7),
            "agents2026-hal-9000": score_json(goal_fit=7, originality=6, execution=6),
        },
    )
    ada_site = "https://mitmedialab.github.io/agents2026-ada/"
    service, _ = make_service(
        tmp_path, writer, image_finder=FakeImageFinder(fragment_for={ada_site})
    )

    issue = service.draft(as_of=date(2026, 9, 22))

    link = issue.link_for("agents2026-ada")
    assert link is not None and link.post_url is None
    assert issue.open_url("agents2026-ada") == ada_site
    assert issue.images[0].page_url == f"{ada_site}week01.html"  # still where the image came from


def test_service_drafts_for_review_and_sends_only_on_explicit_approval(tmp_path: Path) -> None:
    writer = ScriptedWriter(
        [copy_json("agents2026-ada", "agents2026-hal-9000")],
        scores={
            "agents2026-ada": score_json(goal_fit=9, originality=8, execution=7, rationale="Bold."),
            "agents2026-hal-9000": score_json(goal_fit=7, originality=6, execution=6),
        },
    )
    service, store = make_service(tmp_path, writer)

    issue = service.draft(as_of=date(2026, 9, 22))

    assert issue.issue_id == "2026-week01" and issue.status == "draft"
    assert issue.highlighted_project_ids() == ("agents2026-ada", "agents2026-hal-9000")
    assert [score.project_id for score in issue.scores] == [
        "agents2026-ada",
        "agents2026-hal-9000",
    ]
    assert [link.label for link in issue.other_projects()] == []
    assert {link.label: link.posted for link in issue.roster} == {
        "Ada": True,
        "Grace": False,
        "Hal 9000": True,
        "Zed": False,
    }
    assert issue.model_id == "test-model"
    assert issue.quote == PIONEER_QUOTES[0] and issue.quote.kind == "pioneer"
    assert [(image.project_id, image.filename, image.kind) for image in issue.images] == [
        ("agents2026-ada", "agents2026-ada.jpg", "post_image")
    ]
    assert issue.images[0].source_url == (
        "https://mitmedialab.github.io/agents2026-ada/assets/hero.webp"
    )
    # No served link named the week, but the browser reached Ada's post: that is her link.
    ada_link = issue.link_for("agents2026-ada")
    assert ada_link is not None
    assert ada_link.post_url == "https://mitmedialab.github.io/agents2026-ada/week01.html"
    assert (tmp_path / "newsletter/issues/2026-week01/agents2026-ada.jpg").read_bytes() == (
        b"\xff\xd8jpeg"
    )
    assert "Featured projects, in order: agents2026-ada, agents2026-hal-9000" in writer.prompts[0]
    assert issue.body.headline == "Agent Loop, There It Is"
    assert issue.built_for("agents2026-ada") == "A tidy agent loop."
    assert issue.built_for("agents2026-grace") is None
    assert "No candidate quotes were found this week" in writer.editorial_prompts[0]
    assert "students;" not in writer.editorial_prompts[0]
    assert (tmp_path / "newsletter/issues/2026-week01.html").exists()

    async def scenario() -> None:
        adapter = RecordingMailAdapter()
        preview = await service.send(
            "2026-week01", mail=adapter, recipients=["me@mit.edu"], test_only=True
        )
        assert preview.status == "draft" and store.load("2026-week01") == issue
        assert adapter.sent[0].to == ("me@mit.edu",)
        assert adapter.sent[0].subject == "The Class Runtime from MAS.S60 · Issue 01"
        assert adapter.sent[0].html is not None and "<!DOCTYPE html>" in adapter.sent[0].html
        assert 'src="cid:agents2026-ada"' in adapter.sent[0].html
        assert [(image.content_id, image.data) for image in adapter.sent[0].inline_images] == [
            ("agents2026-ada", b"\xff\xd8jpeg")
        ]
        assert "THE CLASS RUNTIME" in adapter.sent[0].text

        with pytest.raises(NewsletterStateError, match="At least one recipient"):
            await service.send("2026-week01", mail=adapter, recipients=[" "])
        with pytest.raises(NewsletterStateError, match="invalid"):
            await service.send("2026-week01", mail=adapter, recipients=["not-an-address"])
        with pytest.raises(NewsletterStateError, match="does not exist"):
            await service.send("2026-week02", mail=adapter, recipients=["a@mit.edu"])

        failing = RecordingMailAdapter(fail_for={"a@mit.edu"})
        with pytest.raises(NewsletterStateError, match="remains a draft"):
            await service.send("2026-week01", mail=failing, recipients=["a@mit.edu"])
        remains = store.load("2026-week01")
        assert remains is not None and remains.status == "draft"
        assert remains.deliveries[0].error == "RuntimeError"

        adapter = RecordingMailAdapter(fail_for={"c@mit.edu"})
        sent = await service.send(
            "2026-week01",
            mail=adapter,
            recipients=["a@mit.edu", " A@mit.edu ", "b@mit.edu", "c@mit.edu"],
        )
        assert sent.status == "sent" and sent.sent_at is not None
        assert [message.to for message in adapter.sent] == [("a@mit.edu",), ("b@mit.edu",)]
        assert [delivery.error for delivery in sent.deliveries] == [None, None, "RuntimeError"]
        assert [delivery.provider_message_id for delivery in sent.deliveries] == [
            "p-1",
            "p-2",
            None,
        ]
        with pytest.raises(NewsletterStateError, match="already sent"):
            await service.send("2026-week01", mail=adapter, recipients=["d@mit.edu"])

    asyncio.run(scenario())

    with pytest.raises(NewsletterStateError, match="already sent"):
        service.draft(week_number=1)

    # The next issue must not feature the students highlighted last week.
    week2_writer = ScriptedWriter(
        [copy_json("agents2026-grace")],
        scores={
            "agents2026-grace": score_json(9, 8, 8).replace(
                '"quotes": []', '"quotes": ["Tools! Tools are how an agent touches the world."]'
            )
        },
        editorials=[editorial_json(quote_choice=1)],
    )
    service2 = NewsletterService(
        settings=NewsletterSettings(highlight_count=2, highlight_cooldown_issues=2),
        weeks=weeks(),
        store=store,
        collector=WeeklyEvidenceCollector(
            fake_catalog(),
            repository_prefix="agents2026-",
            limits=EvidenceLimits(workers=1),
        ),
        writer=week2_writer,
        assignment_loader=lambda week: None,
        clock=lambda: datetime(2026, 9, 29, 15, 0, tzinfo=UTC),
    )
    week2_catalog = fake_catalog()
    week2_catalog.repositories["agents2026-grace"].tree.append("weekly_builds/week02/README.md")
    week2_catalog.repositories["agents2026-grace"].files["weekly_builds/week02/README.md"] = (
        "Tools! Tools are how an agent touches the world."
    )
    week2_catalog.repositories["agents2026-ada"].commits.insert(
        0, ("2026-09-25T12:00:00Z", "week 2")
    )
    service2 = NewsletterService(
        settings=NewsletterSettings(highlight_count=2, highlight_cooldown_issues=2),
        weeks=weeks(),
        store=store,
        collector=WeeklyEvidenceCollector(
            week2_catalog, repository_prefix="agents2026-", limits=EvidenceLimits(workers=1)
        ),
        writer=week2_writer,
        image_finder=FakeImageFinder(fail_for={"https://mitmedialab.github.io/agents2026-grace/"}),
        link_checker=None,
        lecture_loader=lambda week: None,
        assignment_loader=lambda week: None,
        clock=lambda: datetime(2026, 9, 29, 15, 0, tzinfo=UTC),
    )
    week2 = service2.draft()
    assert week2.issue_id == "2026-week02"
    assert week2.images == ()
    assert week2.highlighted_project_ids() == ("agents2026-grace",)
    assert {score.project_id: score.eligible for score in week2.scores} == {
        "agents2026-ada": False,
        "agents2026-grace": True,
    }
    assert week2.quote.kind == "student" and week2.quote.author == "Grace"
    assert week2.quote.text == "Tools! Tools are how an agent touches the world."
    assert week2.quote.url == "https://mitmedialab.github.io/agents2026-grace/"

    # Rewriting keeps the stored selection, scores, and images; only the copy changes.
    fresh = ScriptedWriter(
        [copy_json("agents2026-ada", "agents2026-hal-9000")],
        editorials=[editorial_json("Agents Loop Again", quote_choice=0)],
    )
    rewriter, _ = make_service(tmp_path, fresh)
    tools_store = FileNewsletterStore(tmp_path / "newsletter")
    tools_store.save(issue.model_copy(update={"status": "draft", "approval": None}))
    rewritten = rewriter.rewrite_copy("2026-week01")
    assert rewritten.body.headline == "Agents Loop Again"
    assert rewritten.highlighted_project_ids() == ("agents2026-ada", "agents2026-hal-9000")
    assert rewritten.scores == issue.scores and rewritten.images == issue.images
    assert rewritten.created_at == datetime(2026, 9, 22, 15, 0, tzinfo=UTC)
    assert fresh.score_prompts == []  # no re-scoring
    tools_store.save(issue.model_copy(update={"status": "sent"}))
    with pytest.raises(NewsletterStateError, match="only drafts"):
        rewriter.rewrite_copy("2026-week01")

    forced = ScriptedWriter(
        [copy_json("agents2026-hal-9000", "agents2026-ada")],
        scores={"agents2026-hal-9000": score_json(9, 9, 9)},
    )
    service3, _ = make_service(tmp_path, forced)
    stale = tmp_path / "newsletter/issues/2026-week01/agents2026-stale.jpg"
    stale.write_bytes(b"old")
    assert service3.draft(week_number=1, force=True).status == "draft"
    assert not stale.exists()
    assert (tmp_path / "newsletter/issues/2026-week01/agents2026-ada.jpg").exists()

    sendless = NewsletterService(settings=NewsletterSettings(), weeks=weeks(), store=store)
    with pytest.raises(NewsletterStateError, match="Drafting requires"):
        sendless.draft(week_number=1)


def test_newsletter_settings_read_environment_and_reject_bad_integers() -> None:
    settings = NewsletterSettings.from_environment(
        {
            "NEWSLETTER_RECIPIENTS": " list@mit.edu, staff@mit.edu ,",
            "NEWSLETTER_HIGHLIGHT_COUNT": "3",
            "NEWSLETTER_COURSE_SITE_URL": "https://example.edu/",
            "NEWSLETTER_DATA_PATH": "/tmp/newsletter-data",
        }
    )
    assert settings.recipients == ("list@mit.edu", "staff@mit.edu")
    assert settings.highlight_count == 3 and settings.highlight_cooldown_issues == 1
    assert settings.branding.course_site_url == "https://example.edu/"
    assert settings.branding.course_title == "AI Agents for Cognitive Augmentation"
    assert settings.data_path == Path("/tmp/newsletter-data")
    assert NewsletterSettings.from_environment({}).subject == "The Class Runtime from MAS.S60"
    with pytest.raises(ConfigurationError):
        NewsletterSettings.from_environment({"NEWSLETTER_HIGHLIGHT_COUNT": "four"})


def test_cli_lists_shows_and_refuses_to_send_without_recipients_or_mail(tmp_path: Path) -> None:
    environment = {"NEWSLETTER_DATA_PATH": str(tmp_path / "newsletter")}
    out, err = io.StringIO(), io.StringIO()

    assert newsletter_main(["list"], environment=environment, out=out, err=err) == 0
    assert "No issues yet." in out.getvalue()
    assert newsletter_main(["show", "2026-week01"], environment=environment, out=out, err=err) == 2
    assert "does not exist" in err.getvalue()

    FileNewsletterStore(tmp_path / "newsletter").save(sample_issue())
    out = io.StringIO()
    assert newsletter_main(["show", "2026-week01"], environment=environment, out=out, err=err) == 0
    assert "Issue: 2026-week01 (draft)" in out.getvalue()
    assert "THE CLASS RUNTIME" in out.getvalue()
    out = io.StringIO()
    assert (
        newsletter_main(
            ["show", "2026-week01", "--html"], environment=environment, out=out, err=err
        )
        == 0
    )
    assert "<!DOCTYPE html>" in out.getvalue()
    out = io.StringIO()
    assert newsletter_main(["list"], environment=environment, out=out, err=err) == 0
    assert "2026-week01\t1\tdraft\t2026-09-22\t-\tagents2026-ada" in out.getvalue()

    err = io.StringIO()
    assert newsletter_main(["pdf", "2026-week09"], environment=environment, out=out, err=err) == 2
    out = io.StringIO()
    err = io.StringIO()
    exported = newsletter_main(["pdf", "2026-week01"], environment=environment, out=out, err=err)
    assert exported == 0, err.getvalue()
    pdf_path = Path(out.getvalue().strip())
    assert pdf_path.name == "2026-week01.pdf" and pdf_path.read_bytes().startswith(b"%PDF")
    err = io.StringIO()
    assert newsletter_main(["send", "2026-week01"], environment=environment, out=out, err=err) == 2
    assert "No recipients" in err.getvalue()
    err = io.StringIO()
    assert (
        newsletter_main(
            ["send", "2026-week01", "--to", "a@mit.edu"],
            environment=environment,
            out=out,
            err=err,
            stdin=io.StringIO(""),
        )
        == 2
    )
    assert "MAIL_ENABLED=true" in err.getvalue()
    err = io.StringIO()
    assert (
        newsletter_main(
            ["send", "2026-week09", "--to", "a@mit.edu"], environment=environment, out=out, err=err
        )
        == 2
    )
    assert "does not exist" in err.getvalue()


def staff_principal(role: str) -> PrincipalContext:
    return PrincipalContext(
        authenticated=True,
        user_id=uuid4(),
        username=f"test-{role}",
        roles=["public", role],
        session_id=uuid4(),
    )


def tool_context(principal: PrincipalContext) -> ToolExecutionContext:
    return ToolExecutionContext(
        principal=principal,
        conversation_id=uuid4(),
        permitted_resource_uris=frozenset(),
    )


def make_tools(tmp_path: Path, writer: ScriptedWriter) -> tuple[NewsletterTools, InMemoryAuthStore]:
    store = FileNewsletterStore(tmp_path / "newsletter")
    settings = NewsletterSettings(
        highlight_count=2, highlight_cooldown_issues=2, recipients=("staff@mit.edu",)
    )
    weeks_ = weeks()

    def factory(log: Callable[[str], None]) -> NewsletterService:
        return NewsletterService(
            settings=settings,
            weeks=weeks_,
            store=store,
            collector=WeeklyEvidenceCollector(
                fake_catalog(),
                repository_prefix="agents2026-",
                read_site=read_site,
                limits=EvidenceLimits(workers=1),
            ),
            writer=writer,
            image_finder=FakeImageFinder(),
            link_checker=None,
            lecture_loader=lambda week: None,
            assignment_loader=lambda week: None,
            model_id="test-model",
            clock=lambda: datetime(2026, 9, 22, 15, 0, tzinfo=UTC),
            log=log,
        )

    runner = NewsletterJobRunner(
        store=store,
        service_factory=factory,
        pdf_exporter=lambda issue_id: tmp_path / f"{issue_id}.pdf",
        clock=lambda: datetime(2026, 9, 22, 15, 0, tzinfo=UTC),
        run_in_thread=False,
    )
    auth = InMemoryAuthStore()
    tools = NewsletterTools(
        settings=settings,
        store=store,
        service=NewsletterService(settings=settings, weeks=weeks_, store=store),
        runner=runner,
        auth=auth,
    )
    return tools, auth


def test_course_agent_tools_draft_review_and_prepare_send_for_instructors_only(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        writer = ScriptedWriter(
            [copy_json("agents2026-ada", "agents2026-hal-9000")],
            scores={
                "agents2026-ada": score_json(9, 8, 7, rationale="Bold."),
                "agents2026-hal-9000": score_json(7, 6, 6),
            },
        )
        tools, auth = make_tools(tmp_path, writer)
        admin = UserAdminService(auth)
        await admin.create_user(
            username="alice", display_name="Alice", email="alice@mit.edu", role="student"
        )
        await admin.create_user(
            username="bob", display_name="Bob", email="bob@mit.edu", role="student"
        )
        parked = await admin.create_user(
            username="carl", display_name="Carl", email="carl@mit.edu", role="student"
        )
        await admin.deactivate_user("carl")
        assert parked.user.username == "carl"
        await admin.create_user(username="ta", display_name="TA", email="ta@mit.edu", role="ta")
        draft_tool, status_tool, send_tool = tools.tools()
        instructor = staff_principal("instructor")

        for role in ("student", "ta", "admin"):
            with pytest.raises(ToolValidationError, match="instructor login"):
                await draft_tool.execute({}, tool_context(staff_principal(role)))
            with pytest.raises(ToolValidationError, match="instructor login"):
                await status_tool.execute({}, tool_context(staff_principal(role)))
            with pytest.raises(ToolValidationError, match="instructor login"):
                await send_tool.execute(
                    {"issue_id": "2026-week01", "audience": "test"},
                    tool_context(staff_principal(role)),
                )
        with pytest.raises(ToolValidationError, match="No newsletter"):
            await status_tool.execute({}, tool_context(instructor))

        # While a job runs, a turn may report it once; a second poll is refused so the agent
        # ends its turn instead of spinning.
        running = tools.runner._store
        from course_server.newsletter.models import NewsletterJob

        in_flight = NewsletterJob(
            job_id=uuid4(), status="running", started_at=datetime(2026, 9, 22, 14, 50, tzinfo=UTC)
        )
        running.save_job(in_flight)
        same_turn = tool_context(instructor)
        first = await status_tool.execute({"job_id": str(in_flight.job_id)}, same_turn)
        assert isinstance(first.content, dict) and "Do not check again" in str(
            first.content["message"]
        )
        with pytest.raises(ToolValidationError, match="Do not check again"):
            await status_tool.execute({"job_id": str(in_flight.job_id)}, same_turn)
        running.save_job(in_flight.model_copy(update={"status": "failed", "error": "x"}))

        started = await draft_tool.execute({"week": 1}, tool_context(instructor))
        assert isinstance(started.content, dict)
        job = started.content["job"]
        assert isinstance(job, dict) and job["status"] == "done" and started.content["started"]
        assert job["issue_id"] == "2026-week01" and job["week"] == 1
        assert started.storage_policy == "server_summary"

        status = await status_tool.execute({}, tool_context(instructor))
        assert isinstance(status.content, dict)
        issue = status.content["issue"]
        assert isinstance(issue, dict)
        assert issue["status"] == "draft" and issue["headline"] == "Agent Loop, There It Is"
        highlights = cast(list[dict[str, JsonValue]], issue["highlights"])
        assert [h["student"] for h in highlights] == ["Ada", "Hal 9000"]
        scoreboard = cast(list[dict[str, JsonValue]], issue["scoreboard_top"])
        assert scoreboard[0]["rationale"] == "Bold."
        assert "THE CLASS RUNTIME" in str(issue["plain_text"])
        by_id = await status_tool.execute({"job_id": str(job["job_id"])}, tool_context(instructor))
        assert isinstance(by_id.content, dict) and by_id.content["issue"] is not None
        with pytest.raises(ToolValidationError, match="does not exist"):
            await status_tool.execute({"job_id": str(uuid4())}, tool_context(instructor))

        with pytest.raises(ToolValidationError, match="test recipient"):
            await send_tool.execute(
                {"issue_id": "2026-week01", "audience": "test"}, tool_context(instructor)
            )
        context = tool_context(instructor)
        prepared = await send_tool.execute(
            {"issue_id": "2026-week01", "audience": "all_students"}, context
        )
        assert isinstance(prepared.content, dict)
        assert prepared.content["confirmation_required"] is True
        assert prepared.content["recipient_count"] == 3  # alice, bob, staff list; carl inactive
        event = prepared.emitted_events[0]
        assert event.type == "instructor.newsletter.confirmation_requested"
        assert event.payload["audience"] == "all_students" and event.payload["recipients"] == []
        assert event.payload["headline"] == "Agent Loop, There It Is"
        assert event.metadata == {"visibility": "private"}
        stored = tools.store.load("2026-week01")
        assert stored is not None and stored.status == "awaiting_confirmation"
        assert stored.approval is not None
        assert set(stored.approval.recipients) == {"alice@mit.edu", "bob@mit.edu", "staff@mit.edu"}
        assert stored.approval.conversation_id == context.conversation_id

        # A test audience lists its recipients and replaces the pending snapshot.
        test = await send_tool.execute(
            {
                "issue_id": "2026-week01",
                "audience": "test",
                "test_recipients": ["me@mit.edu", "me@mit.edu"],
            },
            context,
        )
        assert test.emitted_events[0].payload["recipients"] == ["me@mit.edu"]

    asyncio.run(scenario())


def test_send_requires_the_platform_confirmation_and_the_worker_drains_approved_issues(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        writer = ScriptedWriter(
            [copy_json("agents2026-ada", "agents2026-hal-9000")],
            scores={"agents2026-ada": score_json(9, 8, 7)},
        )
        tools, _ = make_tools(tmp_path, writer)
        tools.runner.start(week_number=1, force=False, requested_by_user_id=None)
        service = tools.service
        conversation_id = uuid4()
        instructor_id = uuid4()

        held = service.request_send(
            "2026-week01",
            audience="test",
            recipients=["me@mit.edu"],
            conversation_id=conversation_id,
            requested_by_user_id=instructor_id,
        )
        assert held.status == "awaiting_confirmation" and held.approval is not None
        confirmation_id = held.approval.confirmation_id

        # The CLI's direct send refuses while the Course Agent holds the issue.
        adapter = RecordingMailAdapter()
        with pytest.raises(NewsletterStateError, match="resolve it in the Course Agent"):
            await service.send("2026-week01", mail=adapter, recipients=["x@mit.edu"])
        assert await service.deliver_approved(adapter) == ()

        # Only the same instructor, conversation, and confirmation id may decide.
        with pytest.raises(NewsletterStateError, match="no longer awaiting"):
            service.confirm_send(
                "2026-week01",
                confirmation_id=uuid4(),
                conversation_id=conversation_id,
                user_id=instructor_id,
            )
        with pytest.raises(NewsletterStateError, match="no longer awaiting"):
            service.confirm_send(
                "2026-week01",
                confirmation_id=confirmation_id,
                conversation_id=uuid4(),
                user_id=instructor_id,
            )
        with pytest.raises(NewsletterStateError, match="no longer awaiting"):
            service.cancel_send(
                "2026-week01",
                confirmation_id=confirmation_id,
                conversation_id=conversation_id,
                user_id=uuid4(),
            )

        cancelled = service.cancel_send(
            "2026-week01",
            confirmation_id=confirmation_id,
            conversation_id=conversation_id,
            user_id=instructor_id,
        )
        assert cancelled.status == "draft" and cancelled.approval is None
        with pytest.raises(NewsletterStateError, match="no longer awaiting"):
            service.confirm_send(
                "2026-week01",
                confirmation_id=confirmation_id,
                conversation_id=conversation_id,
                user_id=instructor_id,
            )

        # An approved test copy is delivered but leaves the issue a draft for the real send.
        trial = service.request_send(
            "2026-week01",
            audience="test",
            recipients=["me@mit.edu"],
            conversation_id=conversation_id,
            requested_by_user_id=instructor_id,
        )
        assert trial.approval is not None
        service.confirm_send(
            "2026-week01",
            confirmation_id=trial.approval.confirmation_id,
            conversation_id=conversation_id,
            user_id=instructor_id,
        )
        tested = await service.deliver_approved(adapter)
        assert [issue.status for issue in tested] == ["draft"]
        assert [message.to for message in adapter.sent] == [("me@mit.edu",)]
        assert tested[0].approval is None and tested[0].deliveries[0].recipient == "me@mit.edu"
        adapter.sent.clear()

        held = service.request_send(
            "2026-week01",
            audience="all_students",
            recipients=["a@mit.edu", "b@mit.edu"],
            conversation_id=conversation_id,
            requested_by_user_id=instructor_id,
        )
        assert held.approval is not None
        approved = service.confirm_send(
            "2026-week01",
            confirmation_id=held.approval.confirmation_id,
            conversation_id=conversation_id,
            user_id=instructor_id,
        )
        assert approved.status == "approved"
        assert approved.approval is not None and approved.approval.decided_at is not None
        assert adapter.sent == []

        delivered = await service.deliver_approved(adapter)
        assert [issue.status for issue in delivered] == ["sent"]
        assert [message.to for message in adapter.sent] == [("a@mit.edu",), ("b@mit.edu",)]
        assert adapter.sent[0].inline_images[0].content_id == "agents2026-ada"
        assert await service.deliver_approved(adapter) == ()
        final = tools.store.load("2026-week01")
        assert final is not None and final.status == "sent" and len(final.deliveries) == 2
        with pytest.raises(NewsletterStateError, match="cannot be resent"):
            service.request_send(
                "2026-week01",
                audience="test",
                recipients=["me@mit.edu"],
                conversation_id=conversation_id,
                requested_by_user_id=instructor_id,
            )

    asyncio.run(scenario())


def test_job_runner_records_failures_and_refuses_concurrent_drafts(tmp_path: Path) -> None:
    store = FileNewsletterStore(tmp_path / "newsletter")

    def failing(log: Callable[[str], None]) -> NewsletterService:
        log("collecting")
        raise RuntimeError("GitHub is down")

    runner = NewsletterJobRunner(store=store, service_factory=failing, run_in_thread=False)
    job, started = runner.start(week_number=None, force=False, requested_by_user_id=None)
    assert started
    failed = runner.status(job.job_id)
    assert failed is not None and failed.status == "failed"
    assert failed.error == "RuntimeError: GitHub is down" and failed.log == ("collecting",)
    assert runner.latest() == failed

    running = failed.model_copy(update={"status": "running", "finished_at": None})
    store.save_job(running)
    runner._current_id = running.job_id  # simulate a job still in flight
    again, started_again = runner.start(week_number=2, force=False, requested_by_user_id=None)
    assert not started_again and again.job_id == running.job_id

    # A job left "running" by a process that died is reported as failed after the stale window.
    stale = running.model_copy(update={"started_at": datetime(2026, 9, 22, 14, 0, tzinfo=UTC)})
    store.save_job(stale)
    later = NewsletterJobRunner(
        store=store,
        service_factory=failing,
        clock=lambda: datetime(2026, 9, 22, 15, 0, tzinfo=UTC),
        run_in_thread=False,
    )
    reported = later.latest()
    assert reported is not None and reported.status == "failed"
    assert reported.error is not None and "restarted" in reported.error


def test_capability_policy_exposes_newsletter_tools_only_to_instructors() -> None:
    from course_server.agent import CourseCapabilityPolicy
    from course_server.newsletter_tool_ids import NEWSLETTER_TOOL_IDS

    enabled = CourseCapabilityPolicy(newsletter_enabled=True)
    disabled = CourseCapabilityPolicy(newsletter_enabled=False)
    assert set(NEWSLETTER_TOOL_IDS) <= set(
        enabled.authorize(staff_principal("instructor")).tool_ids
    )
    for role in ("student", "ta", "admin"):
        assert not set(NEWSLETTER_TOOL_IDS) & set(enabled.authorize(staff_principal(role)).tool_ids)
    assert not set(NEWSLETTER_TOOL_IDS) & set(
        disabled.authorize(staff_principal("instructor")).tool_ids
    )


def test_newsletter_confirmation_endpoint_checks_instructor_ownership_and_state(
    tmp_path: Path,
) -> None:
    from fastapi.testclient import TestClient

    from agent_core import AgentRuntime
    from course_server.agent import CourseAgentService, InMemoryConversationStore
    from course_server.api import API_PREFIX, AppServices, create_app
    from course_server.auth import AuthenticationService

    auth = InMemoryAuthStore()
    admin = UserAdminService(auth)

    async def create_users() -> tuple[str, str, UUID]:
        student = await admin.create_user(
            username="student", display_name="Student", email="s@mit.edu", role="student"
        )
        instructor = await admin.create_user(
            username="prof", display_name="Prof", email="p@mit.edu", role="instructor"
        )
        return student.access_code, instructor.access_code, instructor.user.id

    student_code, instructor_code, instructor_id = asyncio.run(create_users())
    store = FileNewsletterStore(tmp_path / "newsletter")
    store.save(sample_issue())
    service = NewsletterService(settings=NewsletterSettings(), weeks=weeks(), store=store)
    conversations = InMemoryConversationStore()
    app = create_app(
        services=AppServices(
            authentication=AuthenticationService(auth),
            agent=CourseAgentService(
                runtime=cast(AgentRuntime, object()), conversations=conversations
            ),
            conversations=conversations,
            newsletter=service,
        )
    )
    instructor_client = TestClient(app, base_url="https://testserver")
    student_client = TestClient(app, base_url="https://testserver")
    assert (
        instructor_client.post(
            f"{API_PREFIX}/auth/login", json={"username": "prof", "access_code": instructor_code}
        ).status_code
        == 200
    )
    assert (
        student_client.post(
            f"{API_PREFIX}/auth/login", json={"username": "student", "access_code": student_code}
        ).status_code
        == 200
    )
    conversation_id = UUID(
        instructor_client.post(f"{API_PREFIX}/conversations", json={}).json()["id"]
    )
    held = service.request_send(
        "2026-week01",
        audience="test",
        recipients=["me@mit.edu"],
        conversation_id=conversation_id,
        requested_by_user_id=instructor_id,
    )
    assert held.approval is not None
    url = f"{API_PREFIX}/conversations/{conversation_id}/newsletter/2026-week01/confirmation"
    body = {"action": "send", "confirmation_id": str(held.approval.confirmation_id)}

    assert student_client.post(url, json=body).status_code == 404
    wrong = instructor_client.post(url, json={**body, "confirmation_id": str(uuid4())})
    assert wrong.status_code == 409
    approved = instructor_client.post(url, json=body)
    assert approved.status_code == 200
    assert approved.json()["type"] == "instructor.newsletter.approved"
    assert approved.json()["payload"] == {
        "issue_id": "2026-week01",
        "confirmation_id": str(held.approval.confirmation_id),
        "subject": "The Class Runtime from MAS.S60",
        "recipient_count": 1,
        "status": "approved",
    }
    stored = store.load("2026-week01")
    assert stored is not None and stored.status == "approved"
    assert instructor_client.post(url, json=body).status_code == 409
    assert instructor_client.post(url, json={**body, "action": "cancel"}).status_code == 409


def test_render_markdown_carries_sections_images_links_and_escaping() -> None:
    issue = sample_issue()

    markdown = render_markdown(issue, index_uri=NEWSLETTER_URI)

    assert markdown.startswith(
        "# Week one is in the loop.\n\n"
        "**Issue:** The Class Runtime · Issue 01\n"
        "**Week:** Week 1 · Sep 15 \u2013 Sep 21, 2026\n"
        "**The assignment:** Build a minimal agent loop.\n\n"
        "## How the week went\n\n"
        "The loop ran.\n\n"
        "Some looped twice; see [the ReAct paper](https://arxiv.org/abs/2210.03629?x=1&y=2) "
        "for why.\n\n"
        "\u2014 The Course Agent\n\n"
        "## Highlights\n\n"
    )
    # Model and repository strings never become Markdown structure; links come from code.
    assert re.search(r"(?<!\\)<", markdown) is None
    assert "### Ada \\<script>alert(1)\\</script> loops\n\n01 · Ada\n\n" in markdown
    # The image is referenced by its registered asset id and links to the student's post.
    assert (
        "[![Ada \\<script>alert(1)\\</script> loops](agents2026_ada)]"
        "(https://a.example/week01.html)\n\n"
        "A minimal agent loop built from scratch. It is the loop asked for.\n\n"
        "[Open Ada\u2019s build \u2192](https://a.example/week01.html)\n\n"
        "\\* [How the Course Agent chooses what to highlight \u2192]"
        "(https://cognitive-agents.media.mit.edu/?q=newslettercriteria)\n\n"
        "## All the other builds this week\n\n"
        "**[Grace](https://g.example/?x=1&y=2):** Grace built a tiny tool-calling loop.\n"
        "**Ivy:** Nothing posted for this week yet.\n\n"
        "## Last word\n\n"
        "> \u201cAgents learn best when reality gets a vote.\u201d\n>\n"
        "> \u2014 [Ada, from their week 1 post](https://a.example/)\n\n"
        "---\n\n"
        "This newsletter was created by The Course Agent.\n\n"
        "MAS.S60 · AI Agents for Cognitive Augmentation · MIT, Fall 2026 · Class website: "
        "[cognitive-agents.media.mit.edu](https://cognitive-agents.media.mit.edu)\n\n"
        "[All issues of The Class Runtime \u2192](course://newsletter)\n"
    ) in markdown
    assert markdown.endswith("(course://newsletter)\n")
    with_logo = render_markdown(issue, logo_src="logo")
    assert with_logo.startswith("![The Class Runtime](logo)\n\n# Week one is in the loop.\n")
    assert "Hal" not in markdown and "Alan Turing" not in markdown
    assert "All issues" not in render_markdown(issue)

    # Block starters and emphasis in copy are escaped, so a headline cannot become a heading.
    spiky = issue.model_copy(
        update={
            "body": issue.body.model_copy(
                update={
                    "headline": "# 1. Loop - *fast*",
                    "highlights": (
                        issue.body.highlights[0].model_copy(
                            update={"description": "- not a list\n> not a quote [x](y)"}
                        ),
                    ),
                }
            )
        }
    )
    spiky_markdown = render_markdown(spiky)
    assert spiky_markdown.startswith("# \\# 1. Loop - \\*fast\\*\n")
    assert "\n\\- not a list\n\\> not a quote \\[x\\](y)\n" in spiky_markdown
    # A blank build is left off the list, as in the other renderings.
    grace_blank = issue.model_copy(
        update={
            "scores": tuple(
                score.model_copy(update={"blank": score.project_id == "agents2026-grace"})
                for score in issue.scores
            )
        }
    )
    assert "Grace" not in render_markdown(grace_blank).split("All the other builds")[1]


def test_sent_issues_are_public_resources_and_drafts_stay_private(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    from agent_core import AgentRuntime
    from course_server.agent import CourseAgentService, InMemoryConversationStore
    from course_server.agent.capabilities import FileResourceProvider, ResourceNotFound
    from course_server.api import API_PREFIX, AppServices, create_app
    from course_server.auth import AuthenticationService

    logo_path = tmp_path / "wordmark.png"
    Image.new("RGBA", (1200, 400), (245, 245, 242, 255)).save(logo_path)
    store = FileNewsletterStore(tmp_path / "newsletter", logo_path=logo_path)
    store.save(sample_issue(status="sent"))
    store.save_image("2026-week01", "agents2026-ada.jpg", b"\xff\xd8\xff-ada-jpeg")
    store.pdf_path("2026-week01").write_bytes(b"%PDF-1.7 issue one")
    store.save(sample_issue().model_copy(update={"issue_id": "2026-week02", "week": weeks()[1]}))
    catalog = NewsletterResourceCatalog(
        FileResourceProvider.with_sample_syllabus(), store, branding=NewsletterBranding()
    )
    session_id = uuid4()
    anonymous = PrincipalContext(
        authenticated=False,
        anonymous_session_id=session_id,
        roles=["public"],
        session_id=session_id,
    )
    issue_uri = "course://newsletter/2026-week01"
    draft_uri = "course://newsletter/2026-week02"

    async def scenario() -> None:
        # Only the sent issue is listed, for everyone; the draft is not a resource at all.
        listed = catalog.list_public()
        assert [summary.uri for summary in listed] == [
            "course://syllabus",
            NEWSLETTER_URI,
            issue_uri,
        ]
        assert listed[1].title == "The Class Runtime (the weekly newsletter)"
        assert "(1 so far)" in listed[1].description
        assert listed[2].title == "The Class Runtime · Issue 01: Week one is in the loop."
        assert listed[2].description == (
            "Week 1 · Sep 15 \u2013 Sep 21, 2026. The assignment: Build a minimal agent loop. "
            "Featured: Ada."
        )
        assert listed[2].media_type == "text/markdown" and listed[2].status == "published"
        assert catalog.list_authorized(anonymous) == listed
        assert catalog.authorized_resource_uris(anonymous) == (
            "course://syllabus",
            NEWSLETTER_URI,
            issue_uri,
        )
        assert catalog.is_public(issue_uri) and catalog.is_public(NEWSLETTER_URI)
        with pytest.raises(ResourceNotFound):
            catalog.is_public(draft_uri)
        with pytest.raises(ResourceNotFound):
            await catalog.read(draft_uri)
        with pytest.raises(ResourceNotFound):
            await catalog.read_asset(draft_uri, "agents2026_ada")

        # The index links every sent issue; each issue is Markdown with its images as assets.
        index = await catalog.read(NEWSLETTER_URI)
        assert index.media_type == "text/markdown" and index.assets == {"logo": "image/png"}
        # The wordmark is the first block, before the title; the site shows it as the masthead.
        assert index.text.startswith(
            "![The Class Runtime](logo)\n\n# The Class Runtime\n\n"
            "**What it is:** The weekly newsletter"
        )
        assert "**Issues:** 1\n" in index.text
        # Each issue's facts are labelled lines, shown as a facts block on the site.
        assert (
            "## [Issue 01 · Week one is in the loop.](course://newsletter/2026-week01)\n\n"
            "**Week:** Week 1 · Sep 15 \u2013 Sep 21, 2026\n"
            "**Sent:** Sep 22, 2026\n"
            "**The assignment:** Build a minimal agent loop.\n"
            "**Featured:** Ada\n\n"
            "[Read Issue 01 \u2192](course://newsletter/2026-week01)\n"
        ) in index.text
        assert "2026-week02" not in index.text
        assert catalog.asset_ids(NEWSLETTER_URI) == ("logo",)
        logo = await catalog.read_asset(NEWSLETTER_URI, "logo")
        assert logo.media_type == "image/png" and logo.data.startswith(b"\x89PNG")
        assert Image.open(io.BytesIO(logo.data)).size == (1000, 333)
        contents = await catalog.read(issue_uri)
        assert contents.title == "The Class Runtime · Issue 01: Week one is in the loop."
        assert contents.text == render_markdown(
            sample_issue(status="sent"), index_uri=NEWSLETTER_URI, logo_src="logo"
        )
        assert contents.text.startswith("![The Class Runtime](logo)\n\n# Week one is in the loop.")
        assert contents.assets == {
            "agents2026_ada": "image/jpeg",
            "logo": "image/png",
            "pdf": "application/pdf",
        }
        assert catalog.asset_ids(issue_uri) == ("agents2026_ada", "logo", "pdf")
        assert (await catalog.read_asset(issue_uri, "logo")).data == logo.data
        resource_file = await catalog.read_file(issue_uri)
        assert resource_file.data == contents.text.encode("utf-8")
        image = await catalog.read_asset(issue_uri, "agents2026_ada")
        assert (image.media_type, image.data) == ("image/jpeg", b"\xff\xd8\xff-ada-jpeg")
        pdf = await catalog.read_asset(issue_uri, "pdf")
        assert (pdf.media_type, pdf.data) == ("application/pdf", b"%PDF-1.7 issue one")
        with pytest.raises(ResourceNotFound):
            await catalog.read_asset(issue_uri, "agents2026_grace")
        for not_an_asset in ("agents2026-ada", "agents2026-ada.jpg"):
            with pytest.raises(ResourceNotFound):
                await catalog.read_asset(issue_uri, not_an_asset)

        # Course search reaches the sent issue, only when it is among the searched resources.
        everything = frozenset(catalog.authorized_resource_uris(anonymous))
        matches = await catalog.search("reality vote", limit=5, resource_uris=everything)
        assert matches and matches[0].uri == issue_uri
        assert "reality gets a vote" in matches[0].excerpt
        assert matches[0].title == contents.title
        without = await catalog.search(
            "reality vote", limit=5, resource_uris=frozenset({"course://syllabus"})
        )
        assert all(match.uri != issue_uri for match in without)

        # The registered base is untouched.
        syllabus = await catalog.read("course://syllabus")
        assert syllabus.uri == "course://syllabus"
        assert catalog.list_feed_metadata(anonymous) == []

        # An unreadable issue file hides the issues instead of failing requests.
        (tmp_path / "newsletter" / "issues" / "2026-week03.json").write_text("{not json")
        assert [summary.uri for summary in catalog.list_public()] == [
            "course://syllabus",
            NEWSLETTER_URI,
        ]

    asyncio.run(scenario())

    # Over HTTP, anonymous visitors read the issue, its images, and its PDF; a draft is 404.
    (tmp_path / "newsletter" / "issues" / "2026-week03.json").unlink()
    conversations = InMemoryConversationStore()
    app = create_app(
        services=AppServices(
            authentication=AuthenticationService(InMemoryAuthStore()),
            agent=CourseAgentService(
                runtime=cast(AgentRuntime, object()), conversations=conversations
            ),
            conversations=conversations,
            course_resources=catalog,
        )
    )
    client = TestClient(app, base_url="https://testserver")
    assert [item["uri"] for item in client.get(f"{API_PREFIX}/course/resources").json()] == [
        "course://syllabus",
        NEWSLETTER_URI,
        issue_uri,
    ]
    content = client.get(f"{API_PREFIX}/course/resources/content", params={"uri": issue_uri})
    assert content.status_code == 200
    assert content.headers["content-type"].startswith("text/markdown")
    assert content.headers["x-class-agent-pdf-asset"] == "pdf"
    assert content.headers["cache-control"] == "private, max-age=60"
    assert content.text.startswith("![The Class Runtime](logo)\n\n# Week one is in the loop.")
    wordmark = client.get(
        f"{API_PREFIX}/course/resources/asset", params={"uri": NEWSLETTER_URI, "asset_id": "logo"}
    )
    assert wordmark.status_code == 200 and wordmark.headers["content-type"] == "image/png"
    assert "newsletter/issues" not in content.text
    index_page = client.get(
        f"{API_PREFIX}/course/resources/content", params={"uri": NEWSLETTER_URI}
    )
    assert index_page.status_code == 200 and "(course://newsletter/2026-week01)" in index_page.text
    assert "X-Class-Agent-Pdf-Asset" not in index_page.headers
    image = client.get(
        f"{API_PREFIX}/course/resources/asset",
        params={"uri": issue_uri, "asset_id": "agents2026_ada"},
    )
    assert image.status_code == 200 and image.headers["content-type"] == "image/jpeg"
    assert image.content == b"\xff\xd8\xff-ada-jpeg"
    pdf = client.get(
        f"{API_PREFIX}/course/resources/asset", params={"uri": issue_uri, "asset_id": "pdf"}
    )
    assert pdf.status_code == 200 and pdf.headers["content-type"] == "application/pdf"
    assert (
        client.get(f"{API_PREFIX}/course/resources/content", params={"uri": draft_uri}).status_code
        == 404
    )
    assert (
        client.get(
            f"{API_PREFIX}/course/resources/asset",
            params={"uri": draft_uri, "asset_id": "agents2026_ada"},
        ).status_code
        == 404
    )
