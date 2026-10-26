"""Model boundary for the newsletter: editorial, highlight copy, and image choice.

Platform code decides who is featured (see `score.py`), the order, every link, the quote,
and the footer. The model writes the prose from the per-project read the scoring pass
produced, scores projects one at a time, and picks among measured image captures.
"""

from __future__ import annotations

import base64
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol, cast

import httpx
from openai import OpenAI, OpenAIError
from pydantic import SecretStr, ValidationError

from .assignment import AssignmentBrief
from .lecture import LectureNotes
from .models import (
    MAX_ASK_AROUND,
    MAX_ASK_AROUND_NAMES,
    MAX_BUILD_GROUPS,
    AskAround,
    BuildGroup,
    Highlight,
    NewsletterBranding,
    NewsletterCopy,
    ProjectEvidence,
    ProjectScore,
    WeeklyDigest,
)

EDITORIAL_MARKER = "You are the editor of"
HIGHLIGHTS_MARKER = "You write the highlights of"
EDITORIAL_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "headline": {
            "type": "string",
            "description": "A punny headline about this week's assignment, at most 12 words.",
        },
        "editorial": {
            "type": "string",
            "description": (
                "Up to 150 words on how the class did against what was taught, in two short "
                "paragraphs. Reference links, if any, use Markdown [text](https://url) syntax."
            ),
        },
        "quote_choice": {
            "type": "integer",
            "description": (
                "1-based index of the most inspiring candidate quote from a student post, "
                "or 0 if none is good enough to close the issue."
            ),
        },
        "groups": {
            "type": "array",
            "description": (
                "The approaches the first paragraph found, in the order it mentions them: a "
                "heading of two to five plain words naming the approach, and the numbers of "
                "the submissions that took it. Every submission appears under exactly one "
                "heading; a last heading takes the ones that fit nowhere else."
            ),
            "items": {
                "type": "object",
                "properties": {
                    "heading": {"type": "string"},
                    "submissions": {"type": "array", "items": {"type": "integer"}},
                },
                "required": ["heading", "submissions"],
                "additionalProperties": False,
            },
        },
        "ask_around": {
            "type": "array",
            "description": (
                "Up to three blockers from the second paragraph that some submission clearly "
                "got past: each a short question a stuck classmate would ask, ending in a "
                "question mark, and the numbers of one or two submissions whose went-well "
                "notes show they got past exactly that. Empty when none did."
            ),
            "items": {
                "type": "object",
                "properties": {
                    "question": {"type": "string"},
                    "submissions": {"type": "array", "items": {"type": "integer"}},
                },
                "required": ["question", "submissions"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["headline", "editorial", "quote_choice", "groups", "ask_around"],
    "additionalProperties": False,
}
HIGHLIGHTS_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "highlights": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "project_id": {"type": "string"},
                    "headline": {"type": "string"},
                    "description": {"type": "string"},
                },
                "required": ["project_id", "headline", "description"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["highlights"],
    "additionalProperties": False,
}
_LINK_LIKE = re.compile(r"https?://|www\.|@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", re.IGNORECASE)
MARKDOWN_LINK = re.compile(r"\[([^\]\n]{1,120})\]\((https://[^\s)]+)\)")
_PARTICIPATION_COUNT = re.compile(
    r"\b(\d+|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|"
    r"fifteen|sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|dozen|dozens|half|most|"
    r"majority)\s+(of\s+you|students?|submissions?|projects?|people|builds?|posts?|"
    r"of\s+the\s+class)\b",
    re.IGNORECASE,
)
MAX_EDITORIAL_LINKS = 2
# The editorial's second paragraph (what to practice next) is read by students who have not
# seen the other builds: no build references, and no sentence dense with commas or lists.
MAX_NEXT_STEP_COMMAS = 1
# Plain-language bounds for the editorial, enforced in code and fed back to the model.
MAX_AVERAGE_SENTENCE_WORDS = 18
MAX_SENTENCE_WORDS = 26
MIN_READING_EASE = 50.0
MIN_HIGHLIGHT_READING_EASE = 50.0
# ALL_CAPS tokens, snake_case, and file names read as code to a classmate.
# The first paragraph is a synthesis; builds may appear only as a few examples of an approach.
MAX_EXAMPLE_LINKS = 3
MAX_EXAMPLE_SENTENCES = 2
# A headline is tied to its week by sharing a term with the assignment's title. Terms are the
# title's own words of at least four letters, minus words that carry no subject.
_TOPIC_TERM_MIN = 4
_TOPIC_STEM = 6
_TOPIC_EXAMPLES = 6
_TOPIC_FILLER = frozenset(
    {"about", "course", "from", "into", "that", "their", "this", "week", "what", "with", "your"}
)
_CODE_LIKE = re.compile(r"\b(?:[A-Z]{2,}_[A-Z_]+|[a-z]+_[a-z_]+|\w+\.(?:py|md|json|html|js|txt))\b")
# Staff vocabulary that must not leak into student-facing copy. Kept narrow: words like
# "score" are legitimate when describing a build that scores things.
_BANNED_WORDS = re.compile(r"\b(brief|rubric)\b", re.IGNORECASE)
# Brevity is part of the format; the model is re-prompted with the exact overrun.
WORD_LIMITS: dict[str, int] = {"headline": 12, "description": 48}
# An approach heading is a label over a few names; a blocker question is one short line.
MAX_GROUP_HEADING_WORDS = 5
MAX_ASK_AROUND_WORDS = 10
EDITORIAL_WORDS = (100, 165)


class LinkChecker(Protocol):
    """Confirms a reference URL actually resolves before it goes into the issue."""

    def __call__(self, url: str) -> bool: ...


def link_resolves(url: str, *, timeout_seconds: float = 10.0) -> bool:
    try:
        with httpx.Client(
            follow_redirects=True, max_redirects=5, timeout=timeout_seconds
        ) as client:
            response = client.head(url)
            if response.status_code in {403, 405}:
                response = client.get(url)
            return response.status_code < 400
    except httpx.HTTPError:
        return False


@dataclass(frozen=True)
class EditorialDraft:
    headline: str
    editorial: str
    quote_choice: int
    groups: tuple[BuildGroup, ...] = ()
    ask_around: tuple[AskAround, ...] = ()


_CHOICE = re.compile(r'"choice"\s*:\s*(\d+)')
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


class NewsletterCompositionError(RuntimeError):
    """The model could not produce copy that satisfies the platform's rules."""


class NewsletterWriter(Protocol):
    """Text and image-choice calls; the platform parses and validates every response."""

    def write(self, *, system_prompt: str, user_prompt: str, schema: dict[str, object]) -> str: ...

    def judge_images(self, *, prompt: str, images: Sequence[bytes]) -> int: ...


@dataclass
class ModelUsage:
    """Token totals across one command, for the instructor's cost awareness."""

    requests: int = 0
    input_tokens: int = 0
    output_tokens: int = 0

    def add(self, *, input_tokens: int | None, output_tokens: int | None) -> None:
        self.requests += 1
        self.input_tokens += input_tokens or 0
        self.output_tokens += output_tokens or 0


class OpenAINewsletterWriter:
    """OpenAI writer that keeps the API key inside this process."""

    def __init__(
        self,
        *,
        model_id: str,
        api_key: SecretStr,
        api_base: str = "https://api.openai.com/v1",
    ) -> None:
        self.model_id = model_id
        self.usage = ModelUsage()
        self._client = OpenAI(api_key=api_key.get_secret_value(), base_url=api_base)

    def write(self, *, system_prompt: str, user_prompt: str, schema: dict[str, object]) -> str:
        try:
            completion = self._client.chat.completions.create(
                model=self.model_id,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                response_format={
                    "type": "json_schema",
                    "json_schema": {"name": "newsletter_copy", "strict": True, "schema": schema},
                },
            )
        except OpenAIError as error:
            raise NewsletterCompositionError(
                f"The model request failed ({type(error).__name__})."
            ) from error
        if completion.usage is not None:
            self.usage.add(
                input_tokens=completion.usage.prompt_tokens,
                output_tokens=completion.usage.completion_tokens,
            )
        content = completion.choices[0].message.content if completion.choices else None
        if not content:
            raise NewsletterCompositionError("The model returned no newsletter copy.")
        return content

    def judge_images(self, *, prompt: str, images: Sequence[bytes]) -> int:
        content: list[dict[str, object]] = [{"type": "input_text", "text": prompt}]
        for index, png in enumerate(images, start=1):
            encoded = base64.b64encode(png).decode("ascii")
            content.append({"type": "input_text", "text": f"Image {index}:"})
            content.append(
                {
                    "type": "input_image",
                    "image_url": f"data:image/png;base64,{encoded}",
                    "detail": "low",
                }
            )
        try:
            response = self._client.responses.create(
                model=self.model_id,
                input=cast(Any, [{"role": "user", "content": content}]),
                store=False,
            )
        except OpenAIError as error:
            raise NewsletterCompositionError(
                f"The image choice request failed ({type(error).__name__})."
            ) from error
        if response.usage is not None:
            self.usage.add(
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
            )
        match = _CHOICE.search(response.output_text)
        if match is None:
            raise NewsletterCompositionError("The model returned no image choice.")
        return int(match.group(1))


def _voice(branding: NewsletterBranding) -> str:
    return (
        f'"{branding.newsletter_name}", the weekly newsletter of {branding.course_code} '
        f"{branding.course_title} at {branding.institution}, {branding.course_term}. Readers are "
        "the students and staff of the class, who skim it on their phones.\n\n"
        "Voice: warm, witty, and quick. Use clever puns and playful phrasing, but keep every "
        "factual claim grounded in the notes you are given. Never invent features, results, or "
        "names. Refer to each student by the label provided. Call the week's task \"the "
        'assignment"; never say "brief" or "rubric".\n'
        "Write plain text only: no Markdown, no bullet characters, no URLs, no email addresses, "
        "no emoji. Respond with JSON that matches the provided schema and nothing else."
    )


def build_editorial_system_prompt(branding: NewsletterBranding) -> str:
    return (
        f"{EDITORIAL_MARKER} {_voice(branding)}\n\n"
        "Task: from the staff notes on every student's submission, write the issue's headline "
        "and editorial, and pick the closing quote.\n"
        "- headline: at most 12 words, a pun or playful turn on the main topic of this week's "
        'assignment as the class received it (the section "The assignment as given to the '
        'class"; its title names the topic), so that someone who reads only the headline knows '
        "what the class was asked to explore. It uses at least one of that title's own terms. "
        "Never a generic line about highlights.\n"
        "- editorial: at most 150 words (count them; between 110 and 150), exactly two short "
        "paragraphs separated by a blank line, speaking to the class directly. Read the lecture "
        "slides for the week the assignment was given and judge the submissions against them.\n"
        "  First paragraph: a synthesis of how the class answered the assignment, not a tour of "
        "builds. Read every submission's notes, find the two or three approaches that recurred, "
        "and say what they were. In a week on interfaces, for example: which form factors "
        "people chose (a phone, a watch, glasses), what they let the agent notice, and when it "
        "speaks up or stays quiet. Group builds by what they share, and say which ideas from "
        "the assignment and lecture the class clearly absorbed. Never give a build a sentence "
        "of its own: the highlights and the full list below already describe each one. To make "
        "an approach concrete you may name builds as examples inside a sentence about that "
        "approach, each wrapped in a Markdown link to that submission's site URL from the "
        "notes, for example: several of you moved the agent off the screen, into [smart "
        f"glasses](https://...) and [a bedside voice](https://...). Use at most "
        f"{MAX_EXAMPLE_LINKS} such links, in at most {MAX_EXAMPLE_SENTENCES} sentences.\n"
        "  Second paragraph: what to practice next. Name the blind spots, meaning ideas the "
        "lecture emphasized that the submissions largely missed, skipped, or misapplied, and the "
        "common blockers, framed constructively in terms of the learning goals: what the gap "
        "teaches and one or two concrete things to try, not a complaint. Readers have not seen "
        "the other builds yet, so this paragraph never mentions, links, or hints at a particular "
        "build or its details (no 'the ball', no 'one agent'); describe the general pattern "
        "instead. Every sentence in it has at most one comma, and it contains no lists.\n"
        "  Keep it simple: write for a tired student reading on a phone. Plain everyday words, "
        "no jargon, no semicolons, at most one metaphor per paragraph, and no clever "
        "compression. Short sentences of at most 20 words, one idea each, and never more than "
        "three items in a comma-separated run. If a sentence needs a second read, split it. "
        "Never name a student. Never state how "
        "many people submitted, posted, or struggled; no counts or proportions of the class at "
        "all. "
        "Do not single out the featured projects as such; the highlights and the full list "
        "follow separately. Do not reuse wording from the candidate closing quotes; the chosen "
        "quote closes the issue on its own. When a specific reference genuinely helps (a paper, "
        "documentation, or tutorial you are certain exists), add at most two links using "
        "Markdown [text](https://url) syntax; otherwise add none. Never invent a URL.\n"
        "- quote_choice: from the candidate quotes taken from students' own posts, choose the "
        "one with the most personality as a closing line: surprising, funny, candid, or vivid, "
        "complete enough to make sense to someone who has not read the post, and clearly about "
        "agents, AI, or human cognition and how agents augment it (the course's theme). A witty "
        "line about an unrelated subject loses to a plainer line about agents. Reject "
        "definitions, restatements of the assignment, fragments that depend on missing context, "
        "and anything a textbook could have said; answer 0 rather than pick a bland or "
        "off-topic one.\n"
        "- groups: the issue ends with a list of every build, grouped under the approaches "
        "your first paragraph found, so that classmates who took the same path find each "
        'other. Give each approach a heading of two to five plain words ("Maps and traces", '
        '"Approval before changes", "Voice and wearables"), no jargon, and put every '
        'submission number under exactly one heading. A last heading such as "Other paths" '
        "takes the ones that fit nowhere else. Use between two and five headings.\n"
        "- ask_around: under the second paragraph the issue points a stuck classmate to people "
        "who got past a blocker (code fills in their names). For up to three of the blockers "
        "that paragraph names, write the question a stuck classmate would ask, at most ten "
        'words ending in a question mark ("Stuck on when the agent should speak?"), and list '
        "the one or two submissions whose went-well notes show they got past exactly that. "
        "Point at a submission only when its notes say so; otherwise leave the list empty."
    )


def build_highlights_system_prompt(branding: NewsletterBranding) -> str:
    return (
        f"{HIGHLIGHTS_MARKER} {_voice(branding)}\n\n"
        "Rules:\n"
        "- Course staff already chose the featured builds and their order. Write one highlight "
        "per listed project, in the given order, using the given project ids.\n"
        "- Each highlight has a pun-friendly headline of at most six words and a description "
        "of exactly two sentences (at most 40 words in total; count them). Write for a "
        "classmate who is still learning these concepts and has never seen this project: plain "
        "everyday words, "
        "as if explaining it to a friend. The first sentence says what the build does for a "
        "person and what makes it interesting. The second sentence says specifically how this "
        "particular build does what the assignment asked, in concrete terms (what it looks at, "
        "what it chooses between, how it knows when to stop), so that the sentence could only be "
        "about this build. Explain any technical term in a few words the first time; never use "
        "an acronym, a code identifier, a file name, or a project-internal label as if the "
        "reader already knows it. Never restate the assignment's wording and never reuse a "
        "sentence across highlights. An image of the build appears above the text, so do not "
        "describe what it looks like.\n"
        "- The student's name is printed beside the headline, so a sentence never opens with it "
        'as if the student were the tool ("Ada helps you..."). The subject is the build: its '
        'own name when it has a plain one, otherwise "this build" or a plain phrase for what '
        'it is. A possessive ("Ada\'s agent") is fine.'
    )


def describe_project(project: ProjectEvidence, *, status: str) -> str:
    lines = [f"### {project.project_id} (label: {project.label}) — {status}"]
    lines.append(f"deployed site: {project.site_url or 'none'}")
    lines.append(
        f"activity: {project.week_file_count} files in this week's build folder, "
        f"{project.commit_count} commits in the window, {project.site_file_count} website files "
        f"({project.week_site_file_count} named for this week)"
    )
    if project.commits:
        lines.append("commit subjects:")
        lines.extend(
            f"- {commit.committed_at.date().isoformat()} {commit.subject}"
            for commit in project.commits
        )
    for document in project.documents:
        suffix = " (truncated)" if document.truncated else ""
        lines.append(f"document {document.path}{suffix}:")
        lines.append(document.text)
    if project.week_page_url:
        lines.append(f"this week's post on the site: {project.visitor_url}")
    if project.week_page_text:
        lines.append("text of this week's post:")
        lines.append(project.week_page_text)
    if project.site_text:
        lines.append("deployed site home page text:")
        lines.append(project.site_text)
    if project.notes:
        lines.append("collection notes: " + "; ".join(project.notes))
    return "\n".join(lines)


def _week_header(digest: WeeklyDigest) -> list[str]:
    week = digest.week
    return [
        f"# Week {week.number} (class on {week.class_date.isoformat()})",
        f"Lecture topic: {week.topic}",
        f"This week's assignment: {week.tutorial}",
        f"Build window: {week.starts_at.date().isoformat()} to {week.ends_at.date().isoformat()}",
    ]


def editorial_submissions(
    digest: WeeklyDigest, scores: Sequence[ProjectScore]
) -> tuple[tuple[int, ProjectEvidence, ProjectScore], ...]:
    """The numbered, anonymous submissions the editorial reads: active projects with a score.

    Numbers follow the active list (a blank project keeps its number but is left out), and
    the same numbers map the model's groups and ask-around picks back to projects.
    """

    scored = {score.project_id: score for score in scores}
    numbered: list[tuple[int, ProjectEvidence, ProjectScore]] = []
    for index, project in enumerate(
        (project for project in digest.projects if project.active), start=1
    ):
        score = scored.get(project.project_id)
        if score is not None and not score.blank:
            numbered.append((index, project, score))
    return tuple(numbered)


def quote_candidates(
    digest: WeeklyDigest, scores: Sequence[ProjectScore]
) -> tuple[tuple[str, str, str], ...]:
    """(project_id, label, verified quote) for every line a student's post offered."""

    labels = {project.project_id: project.label for project in digest.projects}
    return tuple(
        (score.project_id, labels.get(score.project_id, score.project_id), quote)
        for score in scores
        for quote in score.quotes
    )


def build_editorial_user_prompt(
    digest: WeeklyDigest,
    scores: Sequence[ProjectScore],
    *,
    lecture: LectureNotes | None = None,
    assignment: AssignmentBrief | None = None,
    feedback: tuple[str, ...] = (),
) -> str:
    """Notes are anonymized and uncounted so the editorial cannot name or tally students."""

    sections = _week_header(digest)
    if assignment is not None:
        suffix = " (excerpt)" if assignment.truncated else ""
        sections.append(
            f"## The assignment as given to the class{suffix}\n"
            f"Title: {assignment.title}\n\n{assignment.text}"
        )
    else:
        sections.append(
            "## The assignment as given to the class\n"
            "No assignment record covers this week; go by the assignment line above."
        )
    if lecture is not None:
        suffix = " (excerpt)" if lecture.truncated else ""
        sections.append(
            f"## What was taught this week: {lecture.title}{suffix}\n{lecture.slides_text}"
        )
        if lecture.learning_goals:
            sections.append(f"## Course learning goals (syllabus)\n{lecture.learning_goals}")
    else:
        sections.append("## What was taught this week\nNo slide deck is published for this week.")
    if feedback:
        sections.append(
            "Your previous attempt was rejected for these reasons; fix all of them:\n"
            + "\n".join(f"- {item}" for item in feedback)
        )
    sections.append(
        "## Staff notes per submission (anonymous: what was built / went well / struggled)"
    )
    for index, project, score in editorial_submissions(digest, scores):
        link = project.visitor_url
        site = f" / site: {link}" if link else ""
        sections.append(
            f"- Submission {index}: built: {score.built or 'unclear'} / "
            f"went well: {score.went_well or 'n/a'} / struggled: {score.struggled or 'n/a'}{site}"
        )
    candidates = quote_candidates(digest, scores)
    if candidates:
        sections.append(
            "## Candidate closing quotes, verbatim from students' own posts\n"
            + "\n".join(
                f'{index}. "{text}" \u2014 {label}'
                for index, (_, label, text) in enumerate(candidates, start=1)
            )
        )
    else:
        sections.append("No candidate quotes were found this week; answer quote_choice 0.")
    return "\n\n".join(sections)


def build_highlights_user_prompt(
    digest: WeeklyDigest,
    *,
    selected: Sequence[str],
    feedback: tuple[str, ...] = (),
) -> str:
    by_id = {project.project_id: project for project in digest.projects}
    sections = _week_header(digest)
    sections.append("Featured projects, in order: " + ", ".join(selected))
    if feedback:
        sections.append(
            "Your previous attempt was rejected for these reasons; fix all of them:\n"
            + "\n".join(f"- {item}" for item in feedback)
        )
    sections.append("## Evidence for the featured projects")
    for position, project_id in enumerate(selected, start=1):
        project = by_id.get(project_id)
        if project is not None:
            sections.append(describe_project(project, status=f"FEATURED #{position}"))
    return "\n\n".join(sections)


def _parse(raw: str) -> dict[str, object]:
    try:
        payload = json.loads(raw)
    except ValueError as error:
        raise NewsletterCompositionError("The model returned invalid JSON.") from error
    if not isinstance(payload, dict):
        raise NewsletterCompositionError("The model returned no JSON object.")
    return cast(dict[str, object], payload)


def _word_count(value: str) -> int:
    return len(value.split())


def _text_problems(value: str, *, field_name: str, owner: str = "") -> list[str]:
    prefix = f"{owner} {field_name}" if owner else field_name
    problems: list[str] = []
    if _LINK_LIKE.search(value):
        problems.append(f"{prefix} must not contain links or addresses")
    banned = _BANNED_WORDS.search(value)
    if banned is not None:
        problems.append(f'{prefix} must not use the word "{banned.group(0)}"')
    return problems


def _reused_phrase(editorial: str, quote: str, *, window: int = 5) -> str | None:
    """A run of `window` consecutive quote words that also appears in the editorial."""

    prose = " ".join(re.sub(r"[^\w\s]", " ", editorial).split()).casefold()
    words = re.sub(r"[^\w\s]", " ", quote).split()
    for start in range(0, max(0, len(words) - window + 1)):
        phrase = " ".join(words[start : start + window]).casefold()
        if phrase in prose:
            return " ".join(words[start : start + window])
    return None


_VOWEL_GROUPS = re.compile(r"[aeiouy]+")


def _syllables(word: str) -> int:
    stripped = re.sub(r"[^a-z]", "", word.casefold())
    if not stripped:
        return 0
    count = len(_VOWEL_GROUPS.findall(stripped))
    if stripped.endswith("e") and not stripped.endswith(("le", "ee")) and count > 1:
        count -= 1
    return max(1, count)


def reading_ease(prose: str) -> float:
    """Flesch reading ease from a heuristic syllable count; higher is easier."""

    sentences = [part for part in _SENTENCE_SPLIT.split(prose) if part.strip()]
    words = [word for word in re.sub(r"[^\w\s'-]", " ", prose).split() if word.strip("'-")]
    if not sentences or not words:
        return 100.0
    syllables = sum(_syllables(word) for word in words)
    return 206.835 - 1.015 * (len(words) / len(sentences)) - 84.6 * (syllables / len(words))


def readability_problems(prose: str) -> list[str]:
    sentences = [part.strip() for part in _SENTENCE_SPLIT.split(prose) if part.strip()]
    if not sentences:
        return []
    lengths = [len(sentence.split()) for sentence in sentences]
    problems: list[str] = []
    average = sum(lengths) / len(lengths)
    if average > MAX_AVERAGE_SENTENCE_WORDS:
        problems.append(
            f"sentences average {average:.0f} words; keep the average under "
            f"{MAX_AVERAGE_SENTENCE_WORDS}"
        )
    longest = max(lengths)
    if longest > MAX_SENTENCE_WORDS:
        problems.append(
            f"the longest sentence has {longest} words; split anything over {MAX_SENTENCE_WORDS}"
        )
    ease = reading_ease(prose)
    if ease < MIN_READING_EASE:
        problems.append(
            f"reading ease is {ease:.0f} (needs at least {MIN_READING_EASE:.0f}); use shorter, "
            "plainer words and simpler sentences"
        )
    if ";" in prose:
        problems.append("no semicolons; use two sentences instead")
    return problems


def _is_project_link(url: str, project_urls: Sequence[str]) -> bool:
    target = url.rstrip("/")
    for known in project_urls:
        root = known.rstrip("/")
        if target == root or target.startswith(f"{root}/"):
            return True
    return False


def _synthesis_problems(paragraph: str, *, project_urls: Sequence[str]) -> list[str]:
    """The first paragraph synthesizes approaches; builds appear only as a few examples."""

    def build_links(text: str) -> int:
        return sum(
            1 for _, url in MARKDOWN_LINK.findall(text) if _is_project_link(url, project_urls)
        )

    problems: list[str] = []
    total = build_links(paragraph)
    if total > MAX_EXAMPLE_LINKS:
        problems.append(
            f"the first paragraph links {total} builds; describe the approaches the class "
            f"shared and link at most {MAX_EXAMPLE_LINKS} builds as examples"
        )
    pointed = sum(1 for sentence in _sentences(paragraph) if build_links(sentence))
    if pointed > MAX_EXAMPLE_SENTENCES:
        problems.append(
            f"{pointed} sentences in the first paragraph point at a build; that reads as a "
            "list of builds. Write about approaches shared across builds and keep examples to "
            f"at most {MAX_EXAMPLE_SENTENCES} sentences"
        )
    return problems


def _next_steps_problems(paragraph: str, *, project_urls: Sequence[str]) -> list[str]:
    """The second paragraph speaks to everyone: no particular build, no comma-dense sentences."""

    problems = [
        f'the second paragraph must not point at a particular build (found "[{text}]"); readers '
        "have not seen the builds yet, so describe the general pattern instead"
        for text, url in MARKDOWN_LINK.findall(paragraph)
        if _is_project_link(url, project_urls)
    ]
    prose = MARKDOWN_LINK.sub(r"\1", paragraph)
    for sentence in (part.strip() for part in _SENTENCE_SPLIT.split(prose) if part.strip()):
        if sentence.count(",") > MAX_NEXT_STEP_COMMAS:
            problems.append(
                "in the second paragraph, give each sentence at most one comma and no lists; "
                f'rewrite: "{sentence}"'
            )
    return problems


def topic_terms(topic: str) -> tuple[str, ...]:
    """The subject-bearing words of an assignment title (or topic line), in order."""

    terms: list[str] = []
    for word in re.findall(r"[a-z]+", topic.casefold()):
        if len(word) >= _TOPIC_TERM_MIN and word not in _TOPIC_FILLER and word not in terms:
            terms.append(word)
    return tuple(terms)


def _root(word: str) -> str:
    """A word without its plural or "-ing" ending: "memories" and "learning" become roots."""

    if word.endswith("ies") and len(word) > 4:
        word = f"{word[:-3]}y"
    elif word.endswith("s") and not word.endswith("ss"):
        word = word[:-1]
    return word[:-3] if word.endswith("ing") and len(word) > 6 else word


def _same_term(left: str, right: str) -> bool:
    """Equal, or forms of one word ("delegation" and "delegate"), judged by a shared opening.

    A short word never matches a longer one it merely begins ("over" and "overreliance").
    """

    left, right = _root(left), _root(right)
    shared = next(
        (index for index, (a, b) in enumerate(zip(left, right, strict=False)) if a != b),
        min(len(left), len(right)),
    )
    return shared >= min(_TOPIC_STEM, max(len(left), len(right)))


def headline_names_topic(headline: str, topic: str) -> bool:
    """Whether the headline uses one of the subject's terms; true when the subject has none."""

    terms = topic_terms(topic)
    words = [word for word in re.findall(r"[a-z]+", headline.casefold()) if len(word) >= 4]
    return not terms or any(_same_term(word, term) for word in words for term in terms)


def validate_editorial(
    headline: str,
    editorial: str,
    *,
    names: Sequence[str] = (),
    quotes: Sequence[str] = (),
    project_urls: Sequence[str] = (),
    link_checker: LinkChecker | None = None,
    topic: str = "",
) -> tuple[str, ...]:
    """Project links (to roster sites) are unlimited; external references stay bounded."""

    problems = _text_problems(headline, field_name="headline")
    if _word_count(headline) > WORD_LIMITS["headline"]:
        problems.append(
            f"headline has {_word_count(headline)} words; the limit is {WORD_LIMITS['headline']}"
        )
    if not headline_names_topic(headline, topic):
        problems.append(
            "headline must reflect the main topic of this week's assignment and use one of "
            f"its own terms (for example: {', '.join(topic_terms(topic)[:_TOPIC_EXAMPLES])})"
        )
    links = MARKDOWN_LINK.findall(editorial)
    prose = MARKDOWN_LINK.sub(r"\1", editorial)
    problems += _text_problems(prose, field_name="editorial")
    low, high = EDITORIAL_WORDS
    count = _word_count(prose)
    if not low <= count <= high:
        problems.append(f"editorial has {count} words; write between {low} and {high}")
    for name in names:
        if len(name) >= 4 and re.search(rf"\b{re.escape(name)}\b", prose, re.IGNORECASE):
            problems.append(f'editorial must not name students (found "{name}")')
    tally = _PARTICIPATION_COUNT.search(prose)
    if tally is not None:
        problems.append(f'editorial must not count participation (found "{tally.group(0)}")')
    problems += readability_problems(prose)
    for quote in quotes:
        reused = _reused_phrase(prose, quote)
        if reused is not None:
            problems.append(
                f'editorial must not reuse wording from a candidate quote (found "{reused}")'
            )
            break
    known = {url.rstrip("/") for url in project_urls}
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n|\n", editorial) if part.strip()]
    if len(paragraphs) != 2:
        problems.append(
            f"write exactly two paragraphs separated by a blank line (found {len(paragraphs)})"
        )
    else:
        problems += _synthesis_problems(paragraphs[0], project_urls=project_urls)
        problems += _next_steps_problems(paragraphs[1], project_urls=project_urls)
    external = [url for _, url in links if url.rstrip("/") not in known]
    if len(external) > MAX_EDITORIAL_LINKS:
        problems.append(
            f"editorial has {len(external)} reference links; the limit is {MAX_EDITORIAL_LINKS} "
            "(links to students' own sites do not count)"
        )
    for url in external:
        if link_checker is not None and not link_checker(url):
            problems.append(f"the link {url} does not resolve; remove it or use a real one")
    return tuple(problems)


def _names_student(value: str, names: Sequence[str]) -> str | None:
    """The first student name a run of model copy mentions, if any."""

    for name in names:
        if len(name) >= 4 and re.search(rf"\b{re.escape(name)}\b", value, re.IGNORECASE):
            return name
    return None


def _submission_numbers(raw: object, *, owner: str) -> tuple[list[int], list[str]]:
    """The submission numbers a group or ask-around entry lists, or why they are unusable."""

    if not isinstance(raw, list) or not all(isinstance(item, int) for item in raw):
        return [], [f"{owner} must list submission numbers"]
    return list(cast(list[int], raw)), []


def parse_groups(
    raw: object,
    *,
    submissions: Mapping[int, str],
    names: Sequence[str] = (),
) -> tuple[tuple[BuildGroup, ...], tuple[str, ...]]:
    """Map the model's approach groups to project ids; every submission lands in exactly one."""

    if not submissions:
        return (), ()
    if not isinstance(raw, list) or not all(isinstance(item, dict) for item in raw):
        return (), ("groups must be a list of headings with submission numbers",)
    items = cast(list[dict[str, object]], raw)
    problems: list[str] = []
    if not items:
        problems.append("groups: put every submission under an approach heading")
    if len(items) > MAX_BUILD_GROUPS:
        problems.append(f"groups has {len(items)} headings; the limit is {MAX_BUILD_GROUPS}")
    groups: list[BuildGroup] = []
    seen_headings: set[str] = set()
    placed: dict[int, str] = {}
    for item in items:
        heading = str(item.get("heading", "")).strip()
        if not heading:
            problems.append("every group needs a heading")
            continue
        problems += _text_problems(heading, field_name="heading", owner=f'group "{heading}"')
        if _word_count(heading) > MAX_GROUP_HEADING_WORDS:
            problems.append(
                f'group heading "{heading}" has {_word_count(heading)} words; the limit is '
                f"{MAX_GROUP_HEADING_WORDS}"
            )
        name = _names_student(heading, names)
        if name is not None:
            problems.append(f'group heading "{heading}" must not name a student ("{name}")')
        if heading.casefold() in seen_headings:
            problems.append(f'group heading "{heading}" is used twice')
        seen_headings.add(heading.casefold())
        numbers, number_problems = _submission_numbers(
            item.get("submissions"), owner=f'group "{heading}"'
        )
        problems += number_problems
        if not numbers and not number_problems:
            problems.append(f'group "{heading}" lists no submissions; drop it or fill it')
        for number in numbers:
            if number not in submissions:
                problems.append(
                    f'group "{heading}" lists submission {number}, which does not exist'
                )
            elif number in placed:
                problems.append(
                    f'submission {number} is under both "{placed[number]}" and "{heading}"; '
                    "put each submission under exactly one heading"
                )
            else:
                placed[number] = heading
        members = tuple(submissions[number] for number in numbers if submissions.get(number))
        if members:
            groups.append(BuildGroup(heading=heading, project_ids=members))
    missing = sorted(number for number in submissions if number not in placed)
    if items and missing:
        problems.append(
            "every submission must be under a heading; missing: "
            + ", ".join(str(number) for number in missing)
        )
    return tuple(groups), tuple(problems)


def parse_ask_around(
    raw: object,
    *,
    submissions: Mapping[int, str],
    names: Sequence[str] = (),
) -> tuple[tuple[AskAround, ...], tuple[str, ...]]:
    """Map the model's blocker questions to the project ids of those who got past them."""

    if not isinstance(raw, list) or not all(isinstance(item, dict) for item in raw):
        return (), ("ask_around must be a list of questions with submission numbers",)
    items = cast(list[dict[str, object]], raw)
    problems: list[str] = []
    if len(items) > MAX_ASK_AROUND:
        problems.append(f"ask_around has {len(items)} entries; the limit is {MAX_ASK_AROUND}")
    entries: list[AskAround] = []
    seen: set[str] = set()
    for item in items:
        question = str(item.get("question", "")).strip()
        if not question:
            problems.append("every ask_around entry needs a question")
            continue
        owner = f'ask_around "{question}"'
        problems += _text_problems(question, field_name="question", owner=owner)
        if not question.endswith("?"):
            problems.append(f"{owner} must be a question ending in a question mark")
        if _word_count(question) > MAX_ASK_AROUND_WORDS:
            problems.append(
                f"{owner} has {_word_count(question)} words; the limit is {MAX_ASK_AROUND_WORDS}"
            )
        name = _names_student(question, names)
        if name is not None:
            problems.append(f'{owner} must not name a student ("{name}")')
        if question.casefold() in seen:
            problems.append(f"{owner} is asked twice")
        seen.add(question.casefold())
        numbers, number_problems = _submission_numbers(item.get("submissions"), owner=owner)
        problems += number_problems
        unique = list(dict.fromkeys(numbers))
        if not 1 <= len(unique) <= MAX_ASK_AROUND_NAMES:
            problems.append(f"{owner} must point at one or two submissions (got {len(unique)})")
        for number in unique:
            if number not in submissions:
                problems.append(f"{owner} lists submission {number}, which does not exist")
        members = tuple(submissions[number] for number in unique if number in submissions)
        if members:
            entries.append(AskAround(question=question, project_ids=members[:MAX_ASK_AROUND_NAMES]))
    return tuple(entries), tuple(problems)


def _opens_with_student(description: str, label: str) -> bool:
    """Whether a sentence makes the student its subject ("Ada helps you..."), not the build."""

    opener = re.compile(rf"{re.escape(label)}(?!['\u2019\w])", re.IGNORECASE)
    return any(opener.match(sentence) for sentence in _sentences(description))


def validate_highlights(
    highlights: Sequence[Highlight],
    *,
    selected: Sequence[str],
    labels: Mapping[str, str] | None = None,
) -> tuple[str, ...]:
    """Deterministic checks the model cannot override; returns problems to fix."""

    problems: list[str] = []
    written = [highlight.project_id for highlight in highlights]
    if written != list(selected):
        problems.append(
            "highlights must cover exactly these project ids in this order: "
            + ", ".join(selected)
            + f" (got: {', '.join(written) or 'none'})"
        )
    seen_sentences: dict[str, str] = {}
    for highlight in highlights:
        for field_name in ("headline", "description"):
            value = getattr(highlight, field_name)
            problems += _text_problems(value, field_name=field_name, owner=highlight.project_id)
            if _word_count(value) > WORD_LIMITS[field_name]:
                problems.append(
                    f"{highlight.project_id} {field_name} has {_word_count(value)} words; "
                    f"the limit is {WORD_LIMITS[field_name]}"
                )
        for sentence in _sentences(highlight.description):
            owner = seen_sentences.setdefault(sentence.casefold(), highlight.project_id)
            if owner != highlight.project_id:
                problems.append(
                    f'{highlight.project_id} repeats a sentence from {owner}: "{sentence}"; '
                    "each description must be specific to its own build"
                )
        ease = reading_ease(highlight.description)
        if ease < MIN_HIGHLIGHT_READING_EASE:
            problems.append(
                f"{highlight.project_id} description reading ease is {ease:.0f} (needs at least "
                f"{MIN_HIGHLIGHT_READING_EASE:.0f}); use shorter, plainer words a classmate who "
                "has not seen the project would understand"
            )
        code_like = _CODE_LIKE.search(highlight.description)
        if code_like is not None:
            problems.append(
                f"{highlight.project_id} description uses the internal name "
                f'"{code_like.group(0)}"; say it in plain words instead'
            )
        label = (labels or {}).get(highlight.project_id)
        if label and _opens_with_student(highlight.description, label):
            problems.append(
                f'{highlight.project_id} description opens a sentence with "{label}" as if the '
                'student were the tool; name the build or write "this build" instead'
            )
    return tuple(problems)


def _sentences(value: str) -> list[str]:
    return [part.strip() for part in _SENTENCE_SPLIT.split(value) if part.strip()]


def compose_editorial(
    digest: WeeklyDigest,
    scores: Sequence[ProjectScore],
    writer: NewsletterWriter,
    *,
    branding: NewsletterBranding,
    lecture: LectureNotes | None = None,
    assignment: AssignmentBrief | None = None,
    link_checker: LinkChecker | None = link_resolves,
    max_attempts: int = 4,
) -> EditorialDraft:
    """Headline, editorial, and quote choice from the class's notes; re-prompted on rule breaks."""

    system_prompt = build_editorial_system_prompt(branding)
    names = [project.label for project in digest.projects]
    candidate_count = len(quote_candidates(digest, scores))
    feedback: tuple[str, ...] = ()
    for _ in range(max(1, max_attempts)):
        payload = _parse(
            writer.write(
                system_prompt=system_prompt,
                user_prompt=build_editorial_user_prompt(
                    digest, scores, lecture=lecture, assignment=assignment, feedback=feedback
                ),
                schema=EDITORIAL_SCHEMA,
            )
        )
        headline = str(payload.get("headline", "")).strip()
        editorial = str(payload.get("editorial", "")).strip()
        raw_choice = payload.get("quote_choice", 0)
        choice = raw_choice if isinstance(raw_choice, int) else 0
        if not headline or not editorial:
            raise NewsletterCompositionError("The model returned an empty headline or editorial.")
        submissions = {
            number: project.project_id
            for number, project, _ in editorial_submissions(digest, scores)
        }
        groups, group_problems = parse_groups(
            payload.get("groups", []), submissions=submissions, names=names
        )
        ask_around, ask_problems = parse_ask_around(
            payload.get("ask_around", []), submissions=submissions, names=names
        )
        feedback = validate_editorial(
            headline,
            editorial,
            names=names,
            quotes=[text for _, _, text in quote_candidates(digest, scores)],
            project_urls=[
                url
                for project in digest.projects
                for url in (project.site_url, project.visitor_url)
                if url is not None
            ],
            link_checker=link_checker,
            # The assignment's own title names its main topic; without a record, the
            # schedule's assignment line and topic stand in.
            topic=(
                assignment.title
                if assignment is not None
                else f"{digest.week.tutorial} {digest.week.topic}"
            ),
        )
        feedback += group_problems + ask_problems
        if not 0 <= choice <= candidate_count:
            feedback += (f"quote_choice must be between 0 and {candidate_count}",)
        if not feedback:
            return EditorialDraft(
                headline=headline,
                editorial=editorial,
                quote_choice=choice,
                groups=groups,
                ask_around=ask_around,
            )
    raise NewsletterCompositionError("The editorial broke platform rules: " + "; ".join(feedback))


def compose_highlights(
    digest: WeeklyDigest,
    writer: NewsletterWriter,
    *,
    selected: Sequence[str],
    branding: NewsletterBranding,
    max_attempts: int = 4,
) -> tuple[Highlight, ...]:
    """Highlight copy for exactly the selected projects; re-prompted once on rule breaks."""

    if not selected:
        raise NewsletterCompositionError("No project was selected for highlights.")
    system_prompt = build_highlights_system_prompt(branding)
    feedback: tuple[str, ...] = ()
    for _ in range(max(1, max_attempts)):
        payload = _parse(
            writer.write(
                system_prompt=system_prompt,
                user_prompt=build_highlights_user_prompt(
                    digest, selected=selected, feedback=feedback
                ),
                schema=HIGHLIGHTS_SCHEMA,
            )
        )
        try:
            highlights = tuple(
                Highlight.model_validate(item)
                for item in cast(list[object], payload.get("highlights", []))
            )
        except (ValidationError, TypeError) as error:
            raise NewsletterCompositionError("The highlights did not match the schema.") from error
        feedback = validate_highlights(
            highlights,
            selected=selected,
            labels={project.project_id: project.label for project in digest.projects},
        )
        if not feedback:
            return highlights
    raise NewsletterCompositionError(
        "The highlight copy broke platform rules: " + "; ".join(feedback)
    )


def compose_newsletter(
    digest: WeeklyDigest,
    scores: Sequence[ProjectScore],
    writer: NewsletterWriter,
    *,
    selected: Sequence[str],
    branding: NewsletterBranding,
    lecture: LectureNotes | None = None,
    assignment: AssignmentBrief | None = None,
    link_checker: LinkChecker | None = link_resolves,
) -> tuple[NewsletterCopy, tuple[str, str, str] | None]:
    """The issue's copy plus the chosen student quote as (project_id, label, text), if any."""

    draft = compose_editorial(
        digest,
        scores,
        writer,
        branding=branding,
        lecture=lecture,
        assignment=assignment,
        link_checker=link_checker,
    )
    highlights = compose_highlights(digest, writer, selected=selected, branding=branding)
    candidates = quote_candidates(digest, scores)
    chosen = candidates[draft.quote_choice - 1] if draft.quote_choice > 0 else None
    return (
        NewsletterCopy(
            headline=draft.headline,
            editorial=draft.editorial,
            highlights=highlights,
            groups=draft.groups,
            ask_around=draft.ask_around,
        ),
        chosen,
    )
