"""What was taught the week an assignment was given, from the maintained course resources.

The slide deck for the week (`shared/course/slides/week-NN/`) and the syllabus learning goals
give the editorial something to compare the submissions against, so it can name blind spots.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from course_server.resource_text import ResourceTextExtractionError, extract_resource_text

from .models import CourseWeek

MAX_SLIDES_CHARS = 14_000
MAX_GOALS_CHARS = 2_000
_PAGE_MARKER = re.compile(r"^--- Page \d+ ---$", re.MULTILINE)
_SPACES = re.compile(r"[ \t\f\v]+")
_BLANK_LINES = re.compile(r"\n{3,}")
_GOALS_HEADING = re.compile(r"^##\s*\**\s*Learning Goals\s*\**\s*$", re.IGNORECASE | re.MULTILINE)
_NEXT_HEADING = re.compile(r"^##\s", re.MULTILINE)


@dataclass(frozen=True)
class LectureNotes:
    title: str
    slides_text: str
    learning_goals: str
    truncated: bool = False


def compact_slides_text(text: str, *, limit: int = MAX_SLIDES_CHARS) -> tuple[str, bool]:
    without_markers = _PAGE_MARKER.sub("", text)
    compact = _BLANK_LINES.sub("\n\n", _SPACES.sub(" ", without_markers)).strip()
    if len(compact) <= limit:
        return compact, False
    return compact[:limit].rstrip(), True


def learning_goals_from_syllabus(markdown: str, *, limit: int = MAX_GOALS_CHARS) -> str:
    match = _GOALS_HEADING.search(markdown)
    if match is None:
        return ""
    rest = markdown[match.end() :]
    following = _NEXT_HEADING.search(rest)
    section = rest[: following.start()] if following else rest
    return _SPACES.sub(" ", section).strip()[:limit]


def load_lecture_notes(
    slides_root: Path, syllabus_path: Path, week: CourseWeek
) -> LectureNotes | None:
    """Slides for the week plus the syllabus goals; None when no deck was published."""

    directory = slides_root / f"week-{week.number:02d}"
    manifest_path = directory / "resource.json"
    if not manifest_path.is_file():
        return None
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        resource = manifest["resource"]
        file_name = str(resource["file"])
        media_type = str(resource.get("media_type", "text/plain"))
        title = str(resource.get("title", f"Week {week.number} slides"))
        data = (directory / file_name).read_bytes()
        text = extract_resource_text(data, media_type)
    except (OSError, ValueError, KeyError, TypeError, ResourceTextExtractionError):
        return None
    slides_text, truncated = compact_slides_text(text)
    if not slides_text:
        return None
    try:
        goals = learning_goals_from_syllabus(syllabus_path.read_text(encoding="utf-8"))
    except OSError:
        goals = ""
    return LectureNotes(
        title=title, slides_text=slides_text, learning_goals=goals, truncated=truncated
    )
