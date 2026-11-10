"""Choose which trail entries the agent sees on each run. Pure, so it is easy to change.

The whole course produces roughly one entry a week, so these bounds fit a full semester.
Selection is therefore recency plus the student's own relevance mark; deciding which entry
bears on the current question stays with the Course Agent.
"""

from __future__ import annotations

from collections.abc import Mapping
from uuid import UUID

from pydantic import JsonValue

from agent_core import Memory

from .models import TrailEntry, TrailFeedback

LEARNING_TRAIL_MEMORY_KIND = "learning_trail.reflection"
MAX_SELECTED_ENTRIES = 16
MAX_SELECTED_CHARACTERS = 16_000
MAX_REFLECTION_CHARACTERS = 1_500
MAX_FEEDBACK_CHARACTERS = 600
MAX_FEEDBACK_PER_MEMORY = 3


def _bounded(text: str, limit: int) -> tuple[str, bool]:
    if len(text) <= limit:
        return text, False
    return text[:limit].rstrip() + "…", True


def _feedback_metadata(feedback: TrailFeedback) -> dict[str, JsonValue]:
    body, _ = _bounded(feedback.body, MAX_FEEDBACK_CHARACTERS)
    return {
        "from_role": feedback.from_role,
        "from_name": feedback.from_name,
        "body": body,
        "source": feedback.source,
    }


def _as_memory(
    entry: TrailEntry, user_id: UUID, topic_titles: Mapping[str, str] | None = None
) -> Memory:
    content, truncated = _bounded(entry.reflection, MAX_REFLECTION_CHARACTERS)
    recent_feedback = entry.feedback[-MAX_FEEDBACK_PER_MEMORY:]
    return Memory(
        id=entry.id,
        user_id=user_id,
        created_at=entry.created_at,
        updated_at=entry.updated_at,
        kind=LEARNING_TRAIL_MEMORY_KIND,
        content=content,
        privacy="personal",
        metadata={
            "week": entry.week,
            "build_title": entry.build_title,
            "build_url": entry.build_url,
            "topics": [(topic_titles or {}).get(topic, topic) for topic in entry.topics],
            "feedback": [_feedback_metadata(feedback) for feedback in recent_feedback],
            "truncated": truncated
            or len(recent_feedback) < len(entry.feedback)
            or any(len(item.body) > MAX_FEEDBACK_CHARACTERS for item in recent_feedback),
        },
    )


def select_trail_memories(
    entries: list[TrailEntry],
    user_id: UUID,
    *,
    topic_titles: Mapping[str, str] | None = None,
) -> list[Memory]:
    """Return still-relevant entries, newest week first, within the context budget."""

    relevant = sorted(
        (entry for entry in entries if entry.still_relevant),
        key=lambda entry: (entry.week, entry.updated_at),
        reverse=True,
    )
    selected: list[Memory] = []
    characters = 0
    for entry in relevant[:MAX_SELECTED_ENTRIES]:
        memory = _as_memory(entry, user_id, topic_titles)
        characters += len(memory.content) + sum(
            len(item.body) for item in entry.feedback[-MAX_FEEDBACK_PER_MEMORY:]
        )
        if selected and characters > MAX_SELECTED_CHARACTERS:
            break
        selected.append(memory)
    return selected
