"""The week's assignment as the course posted it, from the server-owned assignment records.

The schedule gives each week one line. The assignment record students receive says far more,
so the issue's title and editorial are written against the record, not the schedule.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from course_server.assignments import MAX_ASSIGNMENT_BYTES, Assignment

from .models import CourseWeek

MAX_ASSIGNMENT_CHARS = 14_000


@dataclass(frozen=True)
class AssignmentBrief:
    assignment_id: str
    revision: int
    title: str
    text: str
    truncated: bool = False


def load_assignment_brief(
    directory: Path, week: CourseWeek, *, limit: int = MAX_ASSIGNMENT_CHARS
) -> AssignmentBrief | None:
    """The published assignment due inside the week's window; None when no record covers it.

    Records sit one per file, directly in the directory or one folder down, the two layouts
    deployments use. A file that is not a current assignment record is skipped, never guessed
    at. When two published records are due in the same week, the later deadline wins.
    """

    if not directory.is_dir():
        return None
    due_this_week: list[Assignment] = []
    for path in sorted([*directory.glob("*.json"), *directory.glob("*/*.json")]):
        try:
            if path.is_symlink() or path.stat().st_size > MAX_ASSIGNMENT_BYTES:
                continue
            record = Assignment.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, ValidationError, ValueError):
            continue
        if record.status == "published" and week.starts_at <= record.due_at < week.ends_at:
            due_this_week.append(record)
    if not due_this_week:
        return None
    record = max(due_this_week, key=lambda item: (item.due_at, item.updated_at))
    text = record.content_markdown.strip()
    return AssignmentBrief(
        assignment_id=record.assignment_id,
        revision=record.revision,
        title=record.title.strip(),
        text=text[:limit].rstrip(),
        truncated=len(text) > limit,
    )
