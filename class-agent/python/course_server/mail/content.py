"""Provider-neutral helpers for extracting a staff reply from email content."""

from __future__ import annotations

import re
from html.parser import HTMLParser

_QUOTED_REPLY_MARKERS = (
    re.compile(r"^On .+ wrote:\s*$", re.IGNORECASE),
    re.compile(r"^-{2,}\s*Original Message\s*-{2,}$", re.IGNORECASE),
    re.compile(r"^From:\s+.+$", re.IGNORECASE),
)


class _HTMLTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._ignored_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        normalized = tag.casefold()
        if normalized in {"script", "style"}:
            self._ignored_depth += 1
        elif normalized in {"br", "div", "li", "p", "tr"} and self._ignored_depth == 0:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() in {"script", "style"} and self._ignored_depth > 0:
            self._ignored_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._ignored_depth == 0:
            self.parts.append(data)


def html_to_text(content: str) -> str:
    """Convert a small email HTML body to plain text without executing content."""

    parser = _HTMLTextExtractor()
    parser.feed(content)
    parser.close()
    return "".join(parser.parts)


def strip_quoted_reply(content: str) -> str:
    """Return the newly-authored portion of a conventional plain-text reply."""

    kept: list[str] = []
    for line in content.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        stripped = line.strip()
        if stripped.startswith(">") or any(
            marker.match(stripped) for marker in _QUOTED_REPLY_MARKERS
        ):
            break
        kept.append(line)
    return "\n".join(kept).strip()
