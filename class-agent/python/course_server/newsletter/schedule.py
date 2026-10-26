"""Derive weekly build windows and assignment goals from the maintained course schedule."""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from .models import CourseWeek

# The date, topic, and tutorial cells; any further columns (suggested readings) are ignored.
_WEEK_ROW = re.compile(
    r"^\|\s*Week\s+(?P<number>\d+)\s*\(\s*(?P<month>\d{1,2})/(?P<day>\d{1,2})\s*\)\s*\|"
    r"(?P<topic>[^|]*)\|(?P<tutorial>[^|]*)\|(?:.*\|)?\s*$"
)
_YEAR = re.compile(r"\b(20\d{2})\b")
# The schedule marks speakers in *italics*; they are not part of the topic or the brief.
_ITALIC_SPAN = re.compile(r"(?<!\*)\*(?!\*)([^*\n]+?)\*(?!\*)")
_MARKDOWN_NOISE = re.compile(r"\*\*|\\(?=[+*_])")
_WHITESPACE = re.compile(r"\s+")


class NewsletterScheduleError(RuntimeError):
    """The schedule resource does not describe the requested week."""


def _clean_cell(value: str) -> str:
    without_speakers = _ITALIC_SPAN.sub("", value)
    return (
        _WHITESPACE.sub(" ", _MARKDOWN_NOISE.sub("", without_speakers)).strip() or "(unspecified)"
    )


def parse_schedule(markdown: str, *, timezone: str) -> tuple[CourseWeek, ...]:
    """Parse `Week N (M/D)` table rows into ordered weeks with build windows."""

    zone = ZoneInfo(timezone)
    year_match = _YEAR.search(markdown)
    if year_match is None:
        raise NewsletterScheduleError("The schedule does not state a year.")
    year = int(year_match.group(1))
    rows: list[tuple[int, date, str, str]] = []
    previous_month: int | None = None
    for line in markdown.splitlines():
        match = _WEEK_ROW.match(line.strip())
        if match is None:
            continue
        month = int(match.group("month"))
        if previous_month is not None and month < previous_month:
            year += 1
        previous_month = month
        rows.append(
            (
                int(match.group("number")),
                date(year, month, int(match.group("day"))),
                _clean_cell(match.group("topic")),
                _clean_cell(match.group("tutorial")),
            )
        )
    if not rows:
        raise NewsletterScheduleError("The schedule contains no dated `Week N (M/D)` rows.")
    weeks: list[CourseWeek] = []
    for index, (number, class_date, topic, tutorial) in enumerate(rows):
        starts_at = datetime(class_date.year, class_date.month, class_date.day, tzinfo=zone)
        if index + 1 < len(rows):
            next_date = rows[index + 1][1]
            ends_at = datetime(next_date.year, next_date.month, next_date.day, tzinfo=zone)
        else:
            ends_at = starts_at + timedelta(days=7)
        if ends_at <= starts_at:
            raise NewsletterScheduleError(f"Week {number} does not precede the following week.")
        weeks.append(
            CourseWeek(
                number=number,
                class_date=class_date,
                topic=topic,
                tutorial=tutorial,
                starts_at=starts_at,
                ends_at=ends_at,
                has_class=not topic.casefold().startswith("no class"),
            )
        )
    return tuple(weeks)


def load_schedule(path: Path, *, timezone: str) -> tuple[CourseWeek, ...]:
    try:
        markdown = path.read_text(encoding="utf-8")
    except OSError as error:
        raise NewsletterScheduleError(f"Cannot read the schedule at {path}.") from error
    return parse_schedule(markdown, timezone=timezone)


def select_week(
    weeks: Sequence[CourseWeek],
    *,
    week_number: int | None = None,
    as_of: date,
) -> CourseWeek:
    """Pick an explicit week, or the latest class week whose build window has closed."""

    if week_number is not None:
        for week in weeks:
            if week.number == week_number:
                return week
        raise NewsletterScheduleError(f"Week {week_number} is not on the schedule.")
    completed = [week for week in weeks if week.has_class and week.ends_at.date() <= as_of]
    if not completed:
        raise NewsletterScheduleError(f"No class week has finished its build window by {as_of}.")
    return completed[-1]
