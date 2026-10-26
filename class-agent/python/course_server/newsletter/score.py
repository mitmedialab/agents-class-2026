"""Score every active project against a fixed rubric, then rank and select in code.

The model judges one project at a time from bounded evidence. Platform code owns the
weights, the goal-fit gate, the cooldown, tie-breaking, and the final selection.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import TYPE_CHECKING

from pydantic import ValidationError

from .models import CourseWeek, NewsletterBranding, ProjectEvidence, ProjectScore, WeeklyDigest

if TYPE_CHECKING:
    from .compose import NewsletterWriter


@dataclass(frozen=True)
class RubricCriterion:
    """One scored dimension: `guidance` instructs the scorer, `question` explains it to students.

    The public page course://newsletter-highlights restates these; a test keeps them in step.
    """

    key: str
    name: str
    weight: float
    question: str
    guidance: str


# Instructor-set rubric, in display order. Out-of-the-box thinking lives in originality, which
# absorbed the earlier "interest" criterion; cognitive augmentation is scored on its own because
# a build can be original and polished while helping no one think better.
RUBRIC: tuple[RubricCriterion, ...] = (
    RubricCriterion(
        key="originality",
        name="Originality",
        weight=0.30,
        question=(
            "How far outside the box is it? An unexpected idea, subject, or mechanism scores "
            "higher than the tutorial's default path, and ambition counts."
        ),
        guidance=(
            "how far outside the box the idea and the approach are. Reward an unexpected "
            "problem, domain, or mechanism, a playful or ambitious take, and surprising "
            "findings. The tutorial's default example with a new coat of paint scores 4 or "
            "below."
        ),
    ),
    RubricCriterion(
        key="goal_fit",
        name="Assignment fit",
        weight=0.25,
        question=("Did it do what this week's assignment asked, rather than something next to it?"),
        guidance=(
            "whether the student properly did what this week's assignment asked, not "
            "something adjacent. Missing the core of the assignment scores 3 or below."
        ),
    ),
    RubricCriterion(
        key="augmentation",
        name="Cognitive augmentation",
        weight=0.25,
        question=(
            "How directly does it help a person think, remember, learn, focus, or decide, "
            "while that person stays in charge?"
        ),
        guidance=(
            "how directly the build helps a person think, remember, learn, focus, decide, or "
            "create, with that person still in charge. Automating a chore without changing "
            "how anyone thinks scores low, and a build with no person it helps scores 2 or "
            "below, however clever."
        ),
    ),
    RubricCriterion(
        key="execution",
        name="Execution",
        weight=0.20,
        question=(
            "Does it work, and does the post show it with a demo, a trace, or an honest "
            "account of what failed?"
        ),
        guidance=(
            "how complete and working the build is and how well the post shows it with a "
            "demo, a trace, or a write-up. An honest analysis of what failed counts in its "
            "favor; a bare template, an empty folder, or plans without a build score low."
        ),
    ),
)
SCORE_WEIGHTS: dict[str, float] = {criterion.key: criterion.weight for criterion in RUBRIC}
# A blank submission is left off the issue's list of builds and is never featured. The rule is
# about this week: a site full of earlier weeks' work is still blank for a week with nothing new.
BLANK_RULE = (
    "true only when the evidence shows nothing made for this week's assignment: an untouched "
    "or lightly edited starter site, a welcome or about page, an empty folder, a placeholder "
    "post, or only work from earlier weeks and final-project ideas. Anything made for this "
    "week, even a plan, a concept page, or a partial or broken build, is false."
)
if abs(sum(SCORE_WEIGHTS.values()) - 1.0) > 1e-9:
    raise RuntimeError("Newsletter rubric weights must sum to 1.")

SCORE_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        **{
            criterion.key: {
                "type": "integer",
                "description": f"0-10: {criterion.question}",
            }
            for criterion in RUBRIC
        },
        "blank": {
            "type": "boolean",
            "description": BLANK_RULE,
        },
        "rationale": {
            "type": "string",
            "description": "At most 40 words explaining the scores, for the instructor.",
        },
        "built": {
            "type": "string",
            "description": (
                "One plain sentence, at most 18 words, telling a classmate who has never seen "
                "this week's build what it does for a person (name it if it has a name). "
                "Everyday words only: no acronyms, code names, or jargon. Do not include the "
                "student's name; no mention of evidence, assessment, or what is missing. "
                "Describe only what was made for this week's assignment, never the website "
                "that holds it or work from an earlier week. If nothing was made for this "
                "week, say so plainly."
            ),
        },
        "went_well": {
            "type": "string",
            "description": "At most 25 words: what went well in this submission.",
        },
        "struggled": {
            "type": "string",
            "description": "At most 25 words: what the student struggled with or left missing.",
        },
        "quotes": {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                "Up to three passages copied exactly, character for character, from the "
                "student's own prose (not code, headings, or assignment text) that would make "
                "a memorable closing line: surprising, funny, candid about a failure, or a vivid "
                "way of seeing agents. It must be about agents, AI, or human cognition (thinking, "
                "attention, memory, learning, judgment) or how the build helps a person; skip "
                "witty lines about unrelated things such as file names, visual style, or names. "
                "Each passage must stand on its own: one to two consecutive sentences, at most "
                "40 words, including any sentence a punchline depends on. Never a definition or "
                "a restatement of the assignment. Empty list if nothing qualifies."
            ),
        },
    },
    "required": [
        *(criterion.key for criterion in RUBRIC),
        "blank",
        "rationale",
        "built",
        "went_well",
        "struggled",
        "quotes",
    ],
    "additionalProperties": False,
}
# Projects below this goal-fit score are featured only when nothing better exists.
MIN_GOAL_FIT = 5
SCORING_MARKER = "You are scoring one student project"


class NewsletterScoringError(RuntimeError):
    """A project could not be scored; it is excluded from selection."""


def build_score_system_prompt(branding: NewsletterBranding) -> str:
    return (
        f"{SCORING_MARKER} for {branding.course_code} {branding.course_title} "
        f"({branding.institution}, {branding.course_term}) so course staff can choose which "
        "builds to feature in the weekly newsletter.\n\n"
        f"Score {len(RUBRIC)} things from 0 to 10 using only the evidence provided:\n"
        + "".join(f"- {criterion.key}: {criterion.guidance}\n" for criterion in RUBRIC)
        + f"Set `blank` {BLANK_RULE} Blank submissions are left off the newsletter's list of "
        "builds.\n"
        + "Be strict and consistent: 5 is an ordinary complete submission, 8 or more is "
        "exceptional, and evidence-free claims do not count.\n"
        "Also write, in plain language for the class: `built`, one sentence (at most 18 words) "
        "saying what the student built for this week's assignment, naming the build if it has "
        "a name. A course site usually holds several weeks; describe this week's build, not "
        "the site and not an earlier week's work. Then `went_well` and "
        "`struggled`, each at most 25 words, describing what worked and where the student had "
        "difficulty or left gaps, so an editor can summarize the week. Refer to the student by "
        "the label. Finally, `quotes`: up to three passages from the student's own prose that "
        "have personality (a surprising observation, a candid failure, a joke that lands, a vivid "
        "metaphor) and are about agents, AI, or human cognition, or about how the build helps a "
        "person think, remember, learn, or decide. Copy them exactly as written because each is "
        "checked verbatim against the source. A passage must make sense on its own: if the line "
        "you like is a punchline, include the consecutive sentence before it that sets it up, "
        "within 40 words in total. Skip definitions, assignment restatements, and witty lines "
        "about unrelated subjects, and return an empty list rather than something bland. "
        "Respond with JSON matching the schema and nothing else."
    )


def build_score_user_prompt(week: CourseWeek, project: ProjectEvidence) -> str:
    from .compose import describe_project

    return "\n\n".join(
        [
            f"Week {week.number} assignment goal: {week.tutorial}",
            f"Lecture topic: {week.topic}",
            f"Project id: {project.project_id}",
            describe_project(project, status="candidate"),
        ]
    )


_QUOTE_MAX_WORDS = 40
_QUOTE_MIN_CHARS = 25
_NORMALIZE = str.maketrans({"\u2019": "'", "\u2018": "'", "\u201c": '"', "\u201d": '"'})


def _normalize(value: str) -> str:
    return " ".join(value.translate(_NORMALIZE).split()).casefold()


# A quote opening with one of these leans on the sentence before it; that sentence is added.
_DEPENDENT_OPENERS = frozenset(
    {
        "otherwise",
        "but",
        "so",
        "and",
        "because",
        "which",
        "that",
        "this",
        "it",
        "then",
        "still",
        "yet",
        "instead",
        "also",
        "hence",
        "thus",
        "therefore",
        "unfortunately",
        "except",
    }
)
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


def _corpus(project: ProjectEvidence) -> str:
    return "\n".join([*(document.text for document in project.documents), project.site_text or ""])


def complete_quote(quote: str, project: ProjectEvidence) -> str:
    """Prepend the sentence a dependent opener relies on, when it is a real sentence."""

    words = quote.split()
    if (
        not words
        or words[0].strip("\"'\u201c\u201d(").casefold().rstrip(",") not in _DEPENDENT_OPENERS
    ):
        return quote
    sentences = [part.strip() for part in _SENTENCE_SPLIT.split(_corpus(project)) if part.strip()]
    target = _normalize(quote)
    for index, sentence in enumerate(sentences):
        if index == 0 or not target.startswith(_normalize(sentence)[: len(target)]):
            continue
        # Only the last paragraph before the quote counts; headings and lists are not setup.
        previous = " ".join(re.split(r"\n\s*\n", sentences[index - 1])[-1].split())
        if not previous.endswith((".", "!", "?")) or len(previous.split()) < 4:
            return quote
        combined = f"{previous} {quote}"
        return combined if len(combined.split()) <= _QUOTE_MAX_WORDS else quote
    return quote


def verify_quote(quote: str, project: ProjectEvidence) -> str:
    """Return the quote only if it appears verbatim in the student's collected prose."""

    candidate = " ".join(quote.split()).strip().strip('"\u201c\u201d')
    if len(candidate) < _QUOTE_MIN_CHARS or len(candidate.split()) > _QUOTE_MAX_WORDS:
        return ""
    if _normalize(candidate) not in _normalize(_corpus(project)):
        return ""
    completed = complete_quote(candidate, project)
    return completed if _normalize(completed) in _normalize(_corpus(project)) else candidate


def parse_score(raw: str, *, project_id: str, eligible: bool) -> ProjectScore:
    try:
        payload = json.loads(raw)
    except ValueError as error:
        raise NewsletterScoringError(f"{project_id}: the model returned invalid JSON.") from error
    if not isinstance(payload, dict):
        raise NewsletterScoringError(f"{project_id}: the model returned no score object.")
    try:
        values = {criterion.key: int(payload.get(criterion.key, -1)) for criterion in RUBRIC}
        rationale = str(payload.get("rationale", ""))[:600]
        return ProjectScore(
            project_id=project_id,
            **values,
            total=round(sum(criterion.weight * values[criterion.key] for criterion in RUBRIC), 2),
            rationale=rationale,
            blank=payload.get("blank") is True,
            built=str(payload.get("built", ""))[:300],
            went_well=str(payload.get("went_well", ""))[:400],
            struggled=str(payload.get("struggled", ""))[:400],
            quotes=tuple(
                str(item)[:400]
                for item in (payload.get("quotes") or [])
                if isinstance(item, str) and item.strip()
            )[:3],
            eligible=eligible,
        )
    except (TypeError, ValueError, ValidationError) as error:
        raise NewsletterScoringError(
            f"{project_id}: the score did not match the rubric."
        ) from error


def score_projects(
    digest: WeeklyDigest,
    writer: NewsletterWriter,
    *,
    branding: NewsletterBranding,
    workers: int = 4,
    log: Callable[[str], None] | None = None,
) -> tuple[ProjectScore, ...]:
    """Score every active project; cooldown projects are scored but marked ineligible."""

    say = log or (lambda message: None)
    system_prompt = build_score_system_prompt(branding)
    eligible = set(digest.eligible_project_ids())
    active = [project for project in digest.projects if project.active]

    def score_one(project: ProjectEvidence) -> ProjectScore | None:
        try:
            raw = writer.write(
                system_prompt=system_prompt,
                user_prompt=build_score_user_prompt(digest.week, project),
                schema=SCORE_SCHEMA,
            )
            score = parse_score(
                raw, project_id=project.project_id, eligible=project.project_id in eligible
            )
            verified: list[str] = []
            for quote in score.quotes:
                kept = verify_quote(quote, project)
                if kept and kept not in verified:
                    verified.append(kept)
                elif not kept:
                    say(f"  {project.project_id}: quote was not verbatim; dropped")
            score = score.model_copy(update={"quotes": tuple(verified)})
        except NewsletterScoringError as error:
            say(f"  {project.project_id}: not scored ({error})")
            return None
        except Exception as error:  # a provider failure for one project must not stop the rest
            say(f"  {project.project_id}: not scored ({type(error).__name__})")
            return None
        flag = "; blank" if score.blank else ""
        say(f"  {project.project_id}: total {score.total:.1f} ({score_breakdown(score)}{flag})")
        return score

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        results = list(pool.map(score_one, active))
    scored = [score for score in results if score is not None]
    return tuple(sorted(scored, key=_ranking_key))


def score_breakdown(score: ProjectScore) -> str:
    """Each criterion's score in rubric order, for logs and the instructor scoreboard."""

    return ", ".join(
        f"{criterion.name.lower()} {_criterion_value(score, criterion.key)}" for criterion in RUBRIC
    )


def _criterion_value(score: ProjectScore, key: str) -> int | str:
    value = getattr(score, key)
    return value if isinstance(value, int) else "-"


def _ranking_key(score: ProjectScore) -> tuple[int, float, int, int, int, str]:
    return (
        0 if score.goal_fit >= MIN_GOAL_FIT else 1,
        -score.total,
        -score.goal_fit,
        -score.originality,
        -(score.augmentation or 0),
        score.project_id,
    )


def select_highlights(scores: Sequence[ProjectScore], *, count: int) -> tuple[str, ...]:
    """Top eligible projects by weighted total; goal-fit failures rank last."""

    ranked = sorted(
        (score for score in scores if score.eligible and not score.blank), key=_ranking_key
    )
    return tuple(score.project_id for score in ranked[: max(0, count)])
