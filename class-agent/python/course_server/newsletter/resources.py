"""Sent issues of the newsletter as public course resources, for the site and the Course Agent.

A draft is the instructor's until it is delivered, so only sent issues are exposed. The catalog
wraps the registered resources the way the published FAQ does: the index and each issue are
read from the newsletter store at request time, so an issue appears as soon as it is sent,
without a restart, and the same Markdown serves the site's Newsletters pages, the agent's reads,
and course search. Model-controlled input never selects a file: an issue is addressed only by
its validated issue id inside a `course://newsletter/<issue_id>` URI.
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import date

from agent_core import PrincipalContext
from course_server.agent.capabilities import (
    CourseResourceCatalog,
    CourseSearchResult,
    ResourceContents,
    ResourceFeedMetadata,
    ResourceFile,
    ResourceNotFound,
    ResourceSummary,
)

from .models import NewsletterBranding, NewsletterIssue
from .render import image_asset_id, masthead_markdown, render_markdown, window_label
from .store import FileNewsletterStore, NewsletterStoreError

logger = logging.getLogger(__name__)

NEWSLETTER_URI = "course://newsletter"
# The single-page PDF export, offered as the issue's download the way the syllabus offers its PDF.
PDF_ASSET_ID = "pdf"
# The masthead wordmark, shown at the top of the list and of every issue.
LOGO_ASSET_ID = "logo"
MARKDOWN_MEDIA_TYPE = "text/markdown"
_ISSUE_URI = re.compile(r"^course://newsletter/([0-9]{4}-week[0-9]{2})$")
_SEARCH_TERM = re.compile(r"[a-z0-9]+")
_EXCERPT_CHARS = 480


def issue_uri(issue_id: str) -> str:
    return f"{NEWSLETTER_URI}/{issue_id}"


def issue_id_from_uri(uri: str) -> str | None:
    match = _ISSUE_URI.fullmatch(uri)
    return match.group(1) if match else None


def issue_title(issue: NewsletterIssue) -> str:
    return (
        f"{issue.branding.newsletter_name} · Issue {issue.week.number:02d}: {issue.body.headline}"
    )


def _long_date(value: date) -> str:
    return f"{value.strftime('%b')} {value.day}, {value.year}"


def _highlighted_names(issue: NewsletterIssue) -> str:
    names = [
        link.label if (link := issue.link_for(project_id)) else project_id
        for project_id in issue.highlighted_project_ids()
    ]
    if not names:
        return ""
    if len(names) == 1:
        return names[0]
    return ", ".join(names[:-1]) + f", and {names[-1]}"


def issue_description(issue: NewsletterIssue) -> str:
    featured = _highlighted_names(issue)
    return f"{window_label(issue)}. The assignment: {issue.week.tutorial}" + (
        f" Featured: {featured}." if featured else ""
    )


def render_index_markdown(
    issues: tuple[NewsletterIssue, ...],
    *,
    branding: NewsletterBranding,
    logo_src: str | None = None,
) -> str:
    """Every sent issue, newest first, with a link to each; what the Newsletters page shows."""

    course = (
        f"{branding.course_code} · {branding.course_title} · "
        f"{branding.institution}, {branding.course_term}"
    )
    lines = [
        *([masthead_markdown(branding.newsletter_name, logo_src), ""] if logo_src else []),
        f"# {branding.newsletter_name}",
        "",
        f"**What it is:** The weekly newsletter of {course}: the best student builds of each "
        f"week, chosen and written by {branding.editor_name}.",
        f"**Issues:** {len(issues)}",
        "",
    ]
    if not issues:
        lines.append("No issue has been sent yet. The first follows the first finished class week.")
    for issue in issues:
        featured = _highlighted_names(issue)
        # Labelled lines, the same form as the facts under a page title, so the site shows
        # them as a facts block rather than three loose paragraphs.
        lines.extend(
            [
                f"## [Issue {issue.week.number:02d} · {issue.body.headline}]"
                f"({issue_uri(issue.issue_id)})",
                "",
                f"**Week:** {window_label(issue)}",
                *(
                    [
                        "**Sent:** "
                        + _long_date(issue.sent_at.astimezone(issue.week.starts_at.tzinfo).date())
                    ]
                    if issue.sent_at is not None
                    else []
                ),
                f"**The assignment:** {issue.week.tutorial}",
                *([f"**Featured:** {featured}"] if featured else []),
                "",
                f"[Read Issue {issue.week.number:02d} \u2192]({issue_uri(issue.issue_id)})",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


class NewsletterResourceCatalog:
    """Adds `course://newsletter` and one `course://newsletter/<issue_id>` per sent issue."""

    def __init__(
        self,
        base: CourseResourceCatalog,
        store: FileNewsletterStore,
        *,
        branding: NewsletterBranding,
    ) -> None:
        self._base = base
        self._store = store
        self._branding = branding

    # -- what exists ------------------------------------------------------------------------

    def _sent_issues(self) -> tuple[NewsletterIssue, ...]:
        """Sent issues newest first; an unreadable store hides the newsletter, never fails."""

        try:
            return tuple(reversed(self._store.sent_issues()))
        except NewsletterStoreError:
            logger.warning("Newsletter issues are unreadable; hiding them from the catalog")
            return ()

    def _sent_issue(self, uri: str) -> NewsletterIssue | None:
        issue_id = issue_id_from_uri(uri)
        if issue_id is None:
            return None
        try:
            issue = self._store.load(issue_id)
        except NewsletterStoreError:
            return None
        return issue if issue is not None and issue.status == "sent" else None

    def _summaries(self) -> list[ResourceSummary]:
        issues = self._sent_issues()
        index = ResourceSummary(
            uri=NEWSLETTER_URI,
            title=f"{self._branding.newsletter_name} (the weekly newsletter)",
            description=(
                f"Every sent issue of the class newsletter, newest first ({len(issues)} so far): "
                "the week's assignment, how the week went, the highlighted student builds, and "
                "every other build. Read an issue's own resource for its full text."
            ),
            media_type=MARKDOWN_MEDIA_TYPE,
            status="published",
        )
        return [
            index,
            *(
                ResourceSummary(
                    uri=issue_uri(issue.issue_id),
                    title=issue_title(issue),
                    description=issue_description(issue),
                    media_type=MARKDOWN_MEDIA_TYPE,
                    status="published",
                )
                for issue in issues
            ),
        ]

    def _has_logo(self) -> bool:
        return self._store.wordmark_bytes() is not None

    def _assets(self, issue: NewsletterIssue) -> dict[str, str]:
        assets: dict[str, str] = {image_asset_id(image): image.media_type for image in issue.images}
        if self._store.pdf_path(issue.issue_id).is_file():
            assets[PDF_ASSET_ID] = "application/pdf"
        if self._has_logo():
            assets[LOGO_ASSET_ID] = "image/png"
        return dict(sorted(assets.items()))

    def _index_assets(self) -> dict[str, str]:
        return {LOGO_ASSET_ID: "image/png"} if self._has_logo() else {}

    async def _logo_asset(self, uri: str) -> ResourceFile:
        data = await asyncio.to_thread(self._store.wordmark_bytes)
        if data is None:
            raise ResourceNotFound(f"{uri} asset {LOGO_ASSET_ID}")
        return ResourceFile(uri=uri, title=LOGO_ASSET_ID, media_type="image/png", data=data)

    # -- CourseResourceCatalog --------------------------------------------------------------

    def list_public(self) -> list[ResourceSummary]:
        return [*self._base.list_public(), *self._summaries()]

    def list_authorized(self, principal: PrincipalContext) -> list[ResourceSummary]:
        return [*self._base.list_authorized(principal), *self._summaries()]

    def authorized_resource_uris(self, principal: PrincipalContext) -> tuple[str, ...]:
        return (
            *self._base.authorized_resource_uris(principal),
            *(summary.uri for summary in self._summaries()),
        )

    def list_feed_metadata(self, principal: PrincipalContext) -> list[ResourceFeedMetadata]:
        return self._base.list_feed_metadata(principal)

    def is_public(self, uri: str) -> bool:
        if uri == NEWSLETTER_URI or self._sent_issue(uri) is not None:
            return True
        return self._base.is_public(uri)

    def asset_ids(self, uri: str) -> tuple[str, ...]:
        if uri == NEWSLETTER_URI:
            return tuple(self._index_assets())
        issue = self._sent_issue(uri)
        if issue is None:
            return self._base.asset_ids(uri)
        return tuple(self._assets(issue))

    async def read(self, uri: str) -> ResourceContents:
        logo = LOGO_ASSET_ID if self._has_logo() else None
        if uri == NEWSLETTER_URI:
            return ResourceContents(
                uri=uri,
                title=self._branding.newsletter_name,
                media_type=MARKDOWN_MEDIA_TYPE,
                text=render_index_markdown(
                    self._sent_issues(), branding=self._branding, logo_src=logo
                ),
                assets=self._index_assets(),
            )
        issue = self._sent_issue(uri)
        if issue is None:
            return await self._base.read(uri)
        return ResourceContents(
            uri=uri,
            title=issue_title(issue),
            media_type=MARKDOWN_MEDIA_TYPE,
            text=render_markdown(issue, index_uri=NEWSLETTER_URI, logo_src=logo),
            assets=self._assets(issue),
        )

    async def read_file(self, uri: str) -> ResourceFile:
        if uri == NEWSLETTER_URI or self._sent_issue(uri) is not None:
            contents = await self.read(uri)
            return ResourceFile(
                uri=contents.uri,
                title=contents.title,
                media_type=contents.media_type,
                data=contents.text.encode("utf-8"),
            )
        return await self._base.read_file(uri)

    async def read_asset(self, uri: str, asset_id: str) -> ResourceFile:
        if uri == NEWSLETTER_URI and asset_id == LOGO_ASSET_ID:
            return await self._logo_asset(uri)
        issue = self._sent_issue(uri)
        if issue is None:
            return await self._base.read_asset(uri, asset_id)
        if asset_id == LOGO_ASSET_ID:
            return await self._logo_asset(uri)
        try:
            if asset_id == PDF_ASSET_ID:
                path = self._store.pdf_path(issue.issue_id)
                if not path.is_file() or path.is_symlink():
                    raise ResourceNotFound(f"{uri} asset {asset_id}")
                data = await asyncio.to_thread(path.read_bytes)
                media_type = "application/pdf"
            else:
                image = next(
                    (image for image in issue.images if image_asset_id(image) == asset_id), None
                )
                if image is None:
                    raise ResourceNotFound(f"{uri} asset {asset_id}")
                data = await asyncio.to_thread(
                    self._store.load_image, issue.issue_id, image.filename
                )
                media_type = image.media_type
        except (NewsletterStoreError, OSError) as error:
            raise ResourceNotFound(f"{uri} asset {asset_id}") from error
        return ResourceFile(uri=uri, title=asset_id, media_type=media_type, data=data)

    async def search(
        self,
        query: str,
        *,
        limit: int,
        resource_uris: frozenset[str],
    ) -> list[CourseSearchResult]:
        base_matches = await self._base.search(query, limit=limit, resource_uris=resource_uris)
        terms = tuple(dict.fromkeys(_SEARCH_TERM.findall(query.casefold())))
        dynamic: list[CourseSearchResult] = []
        for issue in self._sent_issues():
            uri = issue_uri(issue.issue_id)
            if uri not in resource_uris or not terms:
                continue
            for block in re.split(r"\n\s*\n", render_markdown(issue)):
                haystack = block.casefold()
                score = sum(haystack.count(term) for term in terms)
                if score:
                    dynamic.append(
                        CourseSearchResult(
                            uri=uri,
                            title=issue_title(issue),
                            excerpt=block.strip()[:_EXCERPT_CHARS],
                            score=score,
                            status="published",
                        )
                    )
        matches = [*base_matches, *dynamic]
        matches.sort(key=lambda match: (-match.score, match.uri, match.excerpt))
        return matches[:limit]
