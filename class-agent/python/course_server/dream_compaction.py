"""Context-only summarization: never delete or rewrite canonical dream history."""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING

from agent_core import PrincipalContext
from course_server.dream_learning import DreamIntelligence

if TYPE_CHECKING:
    from course_server.weekly_dreams import DreamMemory


async def compact_history(
    principal: PrincipalContext,
    memory: DreamMemory,
    intelligence: DreamIntelligence | None,
    budget_chars: int,
) -> str | None:
    entries = [
        {
            "id": str(d.id),
            "text": json.dumps(
                {
                    "dream": d.draft.model_dump(mode="json"),
                    "feedback": [
                        f.model_dump(mode="json") for f in memory.feedback if f.dream_id == d.id
                    ],
                }
            ),
        }
        for d in memory.dreams
    ]
    entries.append({"id": "student-profile", "text": memory.profile.model_dump_json()})
    # Split a single long record into labeled pieces before any model request.
    # This is representation splitting only, never durable truncation.
    entries = [
        {
            "id": entry["id"] + f"/part-{offset // (budget_chars // 2)}",
            "text": entry["text"][offset : offset + budget_chars // 2],
        }
        for entry in entries
        for offset in range(0, len(entry["text"]), budget_chars // 2)
    ]
    if len(json.dumps(entries)) <= budget_chars:
        return None
    if intelligence is None:
        raise ValueError(
            "Dream context needs summarization; configure the model before generating."
        )
    # Hierarchical summarization also bounds individual summarizer requests. All saved
    # dream/feedback records remain on disk; only their model-context representation changes.
    for _ in range(12):
        batches: list[list[dict[str, str]]] = [[]]
        size = 0
        for entry in entries:
            length = len(json.dumps(entry))
            if batches[-1] and size + length > budget_chars:
                batches.append([])
                size = 0
            batches[-1].append(entry)
            size += length
        summaries: list[dict[str, str]] = []
        for batch in batches:
            summary = await intelligence.summarize(principal, batch)
            expected = {item["id"] for item in batch}
            if set(summary.covered_ids) != expected or len(summary.covered_ids) != len(expected):
                raise ValueError("Compaction must account for every supplied history entry.")
            summaries.append(
                {
                    "id": "summary:"
                    + hashlib.sha256(",".join(item["id"] for item in batch).encode()).hexdigest()[
                        :16
                    ],
                    "text": summary.text,
                }
            )
        text = json.dumps(summaries)
        if len(text) <= budget_chars:
            return text
        if len(text) >= len(json.dumps(entries)):
            raise ValueError("Summarization did not reduce context; full history remains saved.")
        entries = summaries
    raise ValueError("History exceeds the compaction budget; no saved history was discarded.")
