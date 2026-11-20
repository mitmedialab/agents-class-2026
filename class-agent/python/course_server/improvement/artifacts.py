"""Deterministic checks and review exports for the deliverable attached to a proposal.

A deliverable is model-authored and untrusted. It is validated here, shown only to the
reviewing instructor, and never rendered by the course site or loaded by the Course Agent.
Installing an approved deliverable remains a reviewed repository change.
"""

from __future__ import annotations

import html
import re
from html.parser import HTMLParser
from pathlib import Path

from course_server.agent.skills import SkillCatalogError, parse_skill_text

from .models import Proposal, ProposalArtifact

# Trusted denylist: elements that execute code, load remote content, or submit data.
_FORBIDDEN_ELEMENTS = frozenset(
    {
        "script",
        "iframe",
        "frame",
        "object",
        "embed",
        "link",
        "meta",
        "base",
        "applet",
        "form",
        "input",
        "textarea",
        "select",
    }
)
_URL_ATTRIBUTES = frozenset({"href", "src", "srcset", "action", "formaction", "poster", "data"})
_FORBIDDEN_STYLE_TOKENS = ("url(", "@import", "expression(", "javascript:")
# The only link targets a static mock-up may use: nowhere, or another part of itself.
_INERT_LINK = re.compile(r"#[A-Za-z][\w-]*|#")
# A mock-up is a storyboard: one full screen for each part of the proposal's single flow, in
# order. The attribute is checked here so a reviewer always gets the whole flow.
MOCKUP_STEP_ATTRIBUTE = "data-step"
MOCKUP_STEPS = ("trigger", "agent", "student")
# Styles the platform puts around every mock-up, so mock-ups share the site's look and the
# author spends its characters on the feature. Staff-maintained; see the file's header.
MOCKUP_SHELL_CSS = (Path(__file__).parent / "mockup_shell.css").read_text(encoding="utf-8")
# Stated once and given to both the author and the critics.
MOCKUP_RULES = (
    "An html_mockup is a full-screen storyboard of the feature inside the Course Agent "
    "interface, not a single panel. It has exactly three screens, in this order: "
    '<section class="mk-screen" data-step="trigger"> (the moment before, as the student '
    'sees it), data-step="agent" (what the Course Agent then shows), and '
    'data-step="student" (the student partway through their action, with realistic '
    "content they would have entered or selected). Each screen shows the whole interface: "
    "the conversation in .mk-chat and the workspace in .mk-workspace. Put a one-line "
    '<p class="mk-step"> caption above each screen. Use the mk- classes from the shell '
    "stylesheet in the brief, which the platform supplies; add an inline <style> only for "
    "what the feature needs beyond them. Content is realistic but invented: never a real "
    "student, repository, or link. Static HTML only: no scripts, event handlers, forms, "
    'inputs, images, or URLs; a link may only be href="#" or point at an id in the same '
    "mock-up."
)
# Review documents get no network, script, or plugin access even if a check above is bypassed.
_REVIEW_CONTENT_SECURITY_POLICY = "default-src 'none'; style-src 'unsafe-inline'"


class ArtifactError(ValueError):
    """A deliverable is unsafe or malformed; the message is safe to return to the model."""


class _MockupChecker(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.problems: list[str] = []
        self.steps: list[str] = []
        self._in_style = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _FORBIDDEN_ELEMENTS:
            self.problems.append(f"<{tag}> is not allowed")
        self._in_style = tag == "style"
        for name, value in attrs:
            text = (value or "").strip()
            if name.startswith("on"):
                self.problems.append(f"event handler attribute {name} is not allowed")
            elif name in _URL_ATTRIBUTES and not _INERT_LINK.fullmatch(text):
                self.problems.append(f'{name} may only be "#" or an id in the mock-up')
            elif name == MOCKUP_STEP_ATTRIBUTE:
                self.steps.append(text)
            elif name == "style":
                self._check_style(text)

    def handle_endtag(self, tag: str) -> None:
        if tag == "style":
            self._in_style = False

    def handle_data(self, data: str) -> None:
        if self._in_style:
            self._check_style(data)

    def _check_style(self, text: str) -> None:
        lowered = text.casefold()
        for token in _FORBIDDEN_STYLE_TOKENS:
            if token in lowered:
                self.problems.append(f"styles may not contain {token}")


def validate_artifact(artifact: ProposalArtifact) -> None:
    """Reject a deliverable that could execute, load remote content, or is not well formed."""

    if artifact.format == "html_mockup":
        checker = _MockupChecker()
        checker.feed(artifact.content)
        checker.close()
        if tuple(checker.steps) != MOCKUP_STEPS:
            checker.problems.append(
                f"it needs exactly one screen for each {MOCKUP_STEP_ATTRIBUTE}, in the order "
                + ", ".join(MOCKUP_STEPS)
            )
        if checker.problems:
            raise ArtifactError(
                "the mock-up must be static, self-contained HTML: "
                + "; ".join(dict.fromkeys(checker.problems))
            )
    elif artifact.format == "skill":
        try:
            parse_skill_text(artifact.content)
        except SkillCatalogError as error:
            raise ArtifactError(
                "the skill must be a SKILL.md with name and description frontmatter "
                "and a non-empty body"
            ) from error


def review_file(proposal: Proposal) -> tuple[str, str] | None:
    """Return a file name and text an instructor can open to inspect the deliverable."""

    artifact = proposal.draft.artifact
    if artifact is None:
        return None
    stem = f"{proposal.draft.kind}-{str(proposal.id)[:8]}-r{proposal.revision}"
    if artifact.format != "html_mockup":
        return f"{stem}.md", artifact.content
    title = html.escape(proposal.draft.title)
    document = (
        "<!doctype html>\n"
        '<html lang="en"><head><meta charset="utf-8">\n'
        f'<meta http-equiv="Content-Security-Policy" content="{_REVIEW_CONTENT_SECURITY_POLICY}">\n'
        f"<title>Proposed mock-up · {title}</title>\n"
        f"<style>\n{MOCKUP_SHELL_CSS}</style></head>\n"
        f"<body>\n{artifact.content}\n</body></html>\n"
    )
    return f"{stem}.html", document
