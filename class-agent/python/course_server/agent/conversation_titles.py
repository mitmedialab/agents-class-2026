"""Readable conversation titles, projected from what the person actually asked."""

from __future__ import annotations

import re

from agent_core import Conversation

# The web client creates this title before anyone has said anything.
_PLACEHOLDER_TITLES = frozenset({"Course Agent welcome"})
_MAX_TITLE_CHARACTERS = 56
_USER_REQUEST = re.compile(r"<user_request>\s*([\s\S]*?)\s*</user_request>", re.IGNORECASE)
_TEMPORARY_UPLOAD = re.compile(r"\n*\[Temporary upload:[^\]]+]")


def _title_from_message(message: str) -> str:
    request = _USER_REQUEST.search(message)
    visible = _TEMPORARY_UPLOAD.sub("", request.group(1) if request else message)
    single_line = " ".join(visible.split())
    if len(single_line) <= _MAX_TITLE_CHARACTERS:
        return single_line
    return f"{single_line[: _MAX_TITLE_CHARACTERS - 1].rstrip()}…"


def with_readable_title(conversation: Conversation, first_message: str | None) -> Conversation:
    """Replace a missing or placeholder title. A title someone chose is left alone."""

    current = (conversation.title or "").strip()
    if first_message is None or (current and current not in _PLACEHOLDER_TITLES):
        return conversation
    title = _title_from_message(first_message)
    return conversation.model_copy(update={"title": title}) if title else conversation
