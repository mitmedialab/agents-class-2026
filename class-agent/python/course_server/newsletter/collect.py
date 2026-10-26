"""Gather bounded, read-only evidence of each student's weekly build from GitHub."""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from urllib.parse import quote, urljoin

from course_server.student_projects import (
    StudentProject,
    StudentProjectCatalog,
    StudentProjectNotFound,
    StudentProjectProviderError,
)

from .images import (
    RenderedPost,
    discover_week_anchor,
    discover_week_pages,
    is_html_fragment,
    static_anchors,
    static_html,
    week_page_pattern,
)
from .models import CommitSummary, CourseWeek, ProjectDocument, ProjectEvidence

WEEKLY_BUILDS_DIRECTORY = "weekly_builds"
SITE_DIRECTORY = "website/"
_DOCUMENT_SUFFIXES = (".md", ".txt", ".rst")
_NOTEBOOK_SUFFIX = ".ipynb"
_PAGE_SUFFIXES = (".html", ".htm")
_INDEX_PAGE = "index.html"
_NOTEBOOK_CELL = re.compile(r'"cell_type"\s*:\s*"(markdown|code|raw)"')
_NOTEBOOK_SOURCE = re.compile(r'"source"\s*:\s*')
_IGNORED_PATH_PARTS = frozenset({"node_modules", ".git", "__pycache__", "venv", ".venv"})
_WHITESPACE = re.compile(r"[ \t\f\v]+")
_BLANK_LINES = re.compile(r"\n{3,}")


class SiteReader(Protocol):
    """Reads one deployed public site; matches `fetch_public_webpage`'s return shape."""

    def __call__(self, url: str) -> str | dict[str, object]: ...


class WeekPageFinder(Protocol):
    """Finds the student's post for the week from their site root, or None."""

    def __call__(self, site_url: str, week: CourseWeek) -> str | None: ...


class WeekPageRenderer(Protocol):
    """Finds and reads the week's post in a browser, for sites whose scripts build links."""

    def __call__(self, site_url: str, week: CourseWeek) -> RenderedPost | None: ...


class FragmentCheck(Protocol):
    """Whether a post is an HTML fragment that only renders inside its site's shell."""

    def __call__(self, url: str) -> bool: ...


def week_page_is_fragment(url: str) -> bool:
    html = static_html(url)
    return html is not None and is_html_fragment(html)


def find_week_page(site_url: str, week: CourseWeek) -> str | None:
    """The first same-site link naming the week in the served HTML, else a week section."""

    anchors = static_anchors(site_url)
    pages = discover_week_pages(anchors, site_url=site_url, week=week)
    if pages:
        return pages[0]
    return discover_week_anchor(anchors, site_url=site_url, week=week)


@dataclass(frozen=True)
class EvidenceLimits:
    """Bounds that keep the model input and GitHub usage predictable."""

    max_documents: int = 6
    max_document_chars: int = 4_000
    max_project_document_chars: int = 9_000
    max_site_chars: int = 2_500
    max_week_page_chars: int = 5_000
    max_commits: int = 15
    workers: int = 4


def week_directory(week: CourseWeek) -> str:
    return f"{WEEKLY_BUILDS_DIRECTORY}/week{week.number:02d}/"


def project_label(project_id: str, *, repository_prefix: str) -> str:
    """Human label derived only from the repository name, never from model output."""

    suffix = (
        project_id[len(repository_prefix) :] if project_id.startswith(repository_prefix) else ""
    )
    words = [part for part in re.split(r"[-_]+", suffix) if part]
    return " ".join(word.capitalize() for word in words) or project_id


def compact_text(value: str, *, limit: int) -> tuple[str, bool]:
    collapsed = _BLANK_LINES.sub("\n\n", _WHITESPACE.sub(" ", value.replace("\r\n", "\n"))).strip()
    if len(collapsed) <= limit:
        return collapsed, False
    return collapsed[:limit].rstrip(), True


def _document_priority(path: str) -> tuple[int, int, str]:
    name = path.rsplit("/", 1)[-1].casefold()
    return (path.count("/"), 0 if name.startswith("readme") else 1, path)


def _is_document(path: str) -> bool:
    name = path.rsplit("/", 1)[-1]
    return name.casefold().endswith((*_DOCUMENT_SUFFIXES, _NOTEBOOK_SUFFIX)) and not (
        name.startswith(".")
    )


def notebook_prose(raw: str) -> str:
    """The Markdown cells of a Jupyter notebook, in order.

    Read by scanning rather than parsing the whole file, because the catalog caps file size
    and a notebook cut off mid-cell is no longer valid JSON. A cell that was cut off is dropped.
    """

    decoder = json.JSONDecoder()
    cells = list(_NOTEBOOK_CELL.finditer(raw))
    prose: list[str] = []
    for position, cell in enumerate(cells):
        if cell.group(1) != "markdown":
            continue
        end = cells[position + 1].start() if position + 1 < len(cells) else len(raw)
        source = _NOTEBOOK_SOURCE.search(raw, cell.end(), end)
        if source is None:
            continue
        try:
            value, _ = decoder.raw_decode(raw, source.end())
        except ValueError:
            break  # the file ends inside this cell
        text = "".join(str(line) for line in value) if isinstance(value, list) else value
        if isinstance(text, str) and text.strip():
            prose.append(text.strip())
    return "\n\n".join(prose)


def week_site_pages(relative_paths: Sequence[str], *, site_url: str) -> list[str]:
    """Published pages named for the week, as site URLs, the post itself first.

    A site's home page may not link the post in its served HTML (a script builds the menu, or
    the post opens inside the page), but the page is still a file in the site folder. A week
    folder's own index, then the shallowest and shortest path, is taken to be the post.
    """

    pages = [path for path in relative_paths if path.casefold().endswith(_PAGE_SUFFIXES)]
    pages.sort(
        key=lambda path: (
            path.count("/"),
            0 if path.rsplit("/", 1)[-1].casefold() == _INDEX_PAGE else 1,
            len(path),
            path,
        )
    )
    root = site_url if site_url.endswith("/") else f"{site_url}/"
    urls: list[str] = []
    for path in pages:
        directory, _, name = path.rpartition("/")
        visible = f"{directory}/" if name.casefold() == _INDEX_PAGE and directory else path
        urls.append(urljoin(root, quote(visible)))
    return urls


def _parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


class WeeklyEvidenceCollector:
    """Read each course repository through the existing bounded GitHub catalog."""

    def __init__(
        self,
        catalog: StudentProjectCatalog,
        *,
        repository_prefix: str,
        read_site: SiteReader | None = None,
        find_week_page: WeekPageFinder | None = None,
        render_week_page: WeekPageRenderer | None = None,
        is_fragment: FragmentCheck | None = None,
        limits: EvidenceLimits | None = None,
        log: Callable[[str], None] | None = None,
    ) -> None:
        self._catalog = catalog
        self._repository_prefix = repository_prefix
        self._read_site = read_site
        self._find_week_page = find_week_page
        self._render_week_page = render_week_page
        self._is_fragment = is_fragment
        self._limits = limits or EvidenceLimits()
        self._log = log or (lambda message: None)

    def collect(self, week: CourseWeek) -> tuple[ProjectEvidence, ...]:
        projects = self._catalog.list_projects()
        self._log(f"Collecting week {week.number} evidence from {len(projects)} repositories.")
        with ThreadPoolExecutor(max_workers=max(1, self._limits.workers)) as pool:
            evidence = list(
                pool.map(lambda project: self._collect_project(project, week), projects)
            )
        return tuple(sorted(evidence, key=lambda item: (item.label.casefold(), item.project_id)))

    def _collect_project(self, project: StudentProject, week: CourseWeek) -> ProjectEvidence:
        notes: list[str] = []
        prefix = week_directory(week)
        names_week = week_page_pattern(week.number)
        document_paths: list[str] = []
        site_document_paths: list[str] = []
        week_site_paths: list[str] = []
        week_file_count = 0
        site_file_count = 0
        try:
            tree = self._catalog.inspect_repository(project.id, "tree")
            entries = tree.get("entries")
            for entry in entries if isinstance(entries, list) else []:
                if not isinstance(entry, Mapping) or entry.get("type") != "blob":
                    continue
                path = entry.get("path")
                if not isinstance(path, str):
                    continue
                if any(part in _IGNORED_PATH_PARTS for part in path.split("/")):
                    continue
                if path.startswith(prefix) and not path.endswith(".gitkeep"):
                    week_file_count += 1
                    if _is_document(path):
                        document_paths.append(path)
                elif path.startswith(SITE_DIRECTORY):
                    site_file_count += 1
                    relative = path[len(SITE_DIRECTORY) :]
                    # A site file named for the week is this week's work even when the home
                    # page's served HTML does not link it.
                    if names_week.search(relative):
                        week_site_paths.append(relative)
                        if _is_document(path):
                            site_document_paths.append(path)
            if tree.get("truncated") is True:
                notes.append("repository tree was truncated; counts are lower bounds")
        except (StudentProjectNotFound, StudentProjectProviderError) as error:
            notes.append(f"repository tree unavailable: {error}")

        documents = self._read_documents(
            project.id,
            [
                *sorted(document_paths, key=_document_priority),
                *sorted(site_document_paths, key=_document_priority),
            ],
        )
        commits, commit_count = self._read_commits(project.id, week, notes)
        site_text = self._read_site_text(project, notes)
        week_page_url, week_page_text = self._read_week_page(
            project, week, notes, week_site_paths=week_site_paths
        )
        week_page_fragment = self._fragment(project, week_page_url, notes)
        self._log(
            f"  {project.id}: {week_file_count} week files, {len(documents)} documents, "
            f"{commit_count} commits in window"
        )
        return ProjectEvidence(
            project_id=project.id,
            label=project_label(project.id, repository_prefix=self._repository_prefix),
            site_url=project.site_url,
            week_file_count=week_file_count,
            site_file_count=site_file_count,
            week_site_file_count=len(week_site_paths),
            commit_count=commit_count,
            commits=commits,
            documents=documents,
            site_text=site_text,
            week_page_url=week_page_url,
            week_page_text=week_page_text,
            week_page_fragment=week_page_fragment,
            notes=tuple(notes),
        )

    def _read_documents(self, project_id: str, paths: list[str]) -> tuple[ProjectDocument, ...]:
        documents: list[ProjectDocument] = []
        remaining = self._limits.max_project_document_chars
        for path in paths:
            if len(documents) >= self._limits.max_documents or remaining <= 0:
                break
            try:
                result = self._catalog.inspect_repository(project_id, "file", path=path)
            except (StudentProjectNotFound, StudentProjectProviderError):
                continue
            raw_text = result.get("text")
            if isinstance(raw_text, str) and path.casefold().endswith(_NOTEBOOK_SUFFIX):
                raw_text = notebook_prose(raw_text)
            if not isinstance(raw_text, str) or not raw_text.strip():
                continue
            text, truncated = compact_text(
                raw_text, limit=min(self._limits.max_document_chars, remaining)
            )
            remaining -= len(text)
            documents.append(
                ProjectDocument(
                    path=path,
                    text=text,
                    truncated=truncated or result.get("truncated") is True,
                )
            )
        return tuple(documents)

    def _read_commits(
        self, project_id: str, week: CourseWeek, notes: list[str]
    ) -> tuple[tuple[CommitSummary, ...], int]:
        try:
            result = self._catalog.inspect_repository(project_id, "commits")
        except (StudentProjectNotFound, StudentProjectProviderError) as error:
            notes.append(f"commit history unavailable: {error}")
            return (), 0
        raw_commits = result.get("commits")
        in_window: list[CommitSummary] = []
        for raw in raw_commits if isinstance(raw_commits, list) else []:
            if not isinstance(raw, Mapping):
                continue
            committed_at = _parse_timestamp(raw.get("date"))
            if committed_at is None or not (week.starts_at <= committed_at < week.ends_at):
                continue
            message = raw.get("message")
            subject = message.splitlines()[0] if isinstance(message, str) and message else ""
            in_window.append(CommitSummary(committed_at=committed_at, subject=subject[:200]))
        if isinstance(raw_commits, list) and len(raw_commits) >= 30 and in_window:
            notes.append("only the 30 most recent commits were inspected")
        return tuple(in_window[: self._limits.max_commits]), len(in_window)

    def _read_week_page(
        self,
        project: StudentProject,
        week: CourseWeek,
        notes: list[str],
        *,
        week_site_paths: Sequence[str] = (),
    ) -> tuple[str | None, str | None]:
        if self._find_week_page is None or project.site_url is None:
            return None, None
        try:
            page_url = self._find_week_page(project.site_url, week)
        except Exception as error:  # discovery is best effort
            notes.append(f"week page discovery failed: {type(error).__name__}")
            return None, None
        if page_url is None:
            published = self._published_week_page(project.site_url, week_site_paths, notes)
            if published is not None:
                return published
            return self._render_week_post(project.site_url, week, notes)
        if page_url.split("#", 1)[0].rstrip("/") == project.site_url.rstrip("/"):
            return page_url, None  # a section of the root page; its text is site_text
        if self._read_site is None:
            return page_url, None
        try:
            text = self._page_text(page_url)
        except Exception as error:  # an unreadable post must not stop the digest
            notes.append(f"week page unreadable: {type(error).__name__}")
            return page_url, None
        return page_url, text

    def _page_text(self, page_url: str) -> str | None:
        if self._read_site is None:
            return None
        page = self._read_site(page_url)
        text = page if isinstance(page, str) else page.get("text")
        if not isinstance(text, str) or not text.strip():
            return None
        compacted, _ = compact_text(text, limit=self._limits.max_week_page_chars)
        return compacted or None

    def _published_week_page(
        self, site_url: str, week_site_paths: Sequence[str], notes: list[str]
    ) -> tuple[str, str | None] | None:
        """The home page links no post for the week; the site folder may still hold one."""

        if self._read_site is None:
            return None
        for page_url in week_site_pages(week_site_paths, site_url=site_url)[:2]:
            try:
                text = self._page_text(page_url)
            except Exception:  # not deployed at this address; try the next candidate
                continue
            notes.append("the week's post was found among the site's files, not its links")
            return page_url, text
        return None

    def _render_week_post(
        self, site_url: str, week: CourseWeek, notes: list[str]
    ) -> tuple[str | None, str | None]:
        """The served HTML named no week post; a script may build the site's links."""

        if self._render_week_page is None:
            return None, None
        try:
            post = self._render_week_page(site_url, week)
        except Exception as error:  # the browser pass is best effort, like static discovery
            notes.append(f"week page browser discovery failed: {type(error).__name__}")
            return None, None
        if post is None:
            return None, None
        notes.append("the week's post was found by opening the site in a browser")
        compacted, _ = compact_text(post.text, limit=self._limits.max_week_page_chars)
        return post.url, compacted or None

    def _fragment(self, project: StudentProject, page_url: str | None, notes: list[str]) -> bool:
        if self._is_fragment is None or page_url is None or project.site_url is None:
            return False
        if page_url.split("#", 1)[0].rstrip("/") == project.site_url.rstrip("/"):
            return False
        try:
            fragment = self._is_fragment(page_url)
        except Exception as error:  # the flag only redirects links; failure keeps the post link
            notes.append(f"week page type unknown: {type(error).__name__}")
            return False
        if fragment:
            notes.append("the week's post is a fragment shown inside the site; links open the site")
        return fragment

    def _read_site_text(self, project: StudentProject, notes: list[str]) -> str | None:
        if self._read_site is None or project.site_url is None:
            return None
        try:
            page = self._read_site(project.site_url)
        except Exception as error:  # one unreadable site must not stop the digest
            notes.append(f"deployed site unreadable: {type(error).__name__}")
            return None
        text = page if isinstance(page, str) else page.get("text")
        if not isinstance(text, str) or not text.strip():
            return None
        compacted, _ = compact_text(text, limit=self._limits.max_site_chars)
        return compacted or None
