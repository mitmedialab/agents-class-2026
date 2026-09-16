"""Read-only GitHub adapter for the bounded course-repository collection."""

from __future__ import annotations

import base64
import re
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Literal, Protocol, cast
from urllib.parse import quote, urlsplit

import httpx
from pydantic import JsonValue

_GITHUB_API_URL = "https://api.github.com"
_RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
_MAX_FILE_BYTES = 50_000
_MAX_ITEMS = 100
_MAX_REPOSITORY_PAGES = 20
_SAFE_REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]{1,100}$")
_SENSITIVE_FILE_NAMES = frozenset(
    {
        ".npmrc",
        ".pypirc",
        "credentials",
        "credentials.json",
        "id_dsa",
        "id_ed25519",
        "id_rsa",
    }
)
_SENSITIVE_FILE_SUFFIXES = (".key", ".p12", ".pem", ".pfx")
RepositoryView = Literal[
    "summary",
    "tree",
    "file",
    "commits",
    "branches",
    "pulls",
    "issues",
    "workflows",
]


class StudentProjectProviderError(RuntimeError):
    """A safe provider failure that does not include credentials or response bodies."""

    def __init__(
        self,
        message: str,
        *,
        category: Literal["invalid_request", "permission_denied", "temporary_failure"],
    ) -> None:
        super().__init__(message)
        self.category = category


class StudentProjectNotFound(RuntimeError):
    """The requested repository is outside the configured course collection."""


@dataclass(frozen=True)
class StudentProject:
    """Safe project metadata shared with authenticated course members."""

    id: str
    site_url: str | None


class StudentProjectCatalog(Protocol):
    """Application-owned read boundary for course GitHub repositories."""

    def list_projects(self) -> list[StudentProject]: ...

    def inspect_repository(
        self,
        project_id: str,
        view: RepositoryView,
        *,
        path: str | None = None,
        ref: str | None = None,
    ) -> dict[str, JsonValue]: ...


class GitHubStudentProjectCatalog:
    """Connect directly to GitHub while confining reads to one repository prefix."""

    def __init__(
        self,
        token: str,
        *,
        organization: str,
        repository_prefix: str,
        excluded_repositories: tuple[str, ...] = (),
        timeout_seconds: float = 10.0,
        roster_cache_ttl_seconds: float = 300.0,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if not token.strip() or "\n" in token or "\r" in token:
            raise ValueError("GitHub token must be a non-empty single line")
        if not _SAFE_REPOSITORY.fullmatch(organization):
            raise ValueError("GitHub organization is invalid")
        if not _SAFE_REPOSITORY.fullmatch(repository_prefix):
            raise ValueError("GitHub repository prefix is invalid")
        self._token = token
        self._organization = organization
        self._repository_prefix = repository_prefix
        self._excluded_repositories = frozenset(excluded_repositories)
        self._timeout_seconds = timeout_seconds
        if roster_cache_ttl_seconds < 0:
            raise ValueError("Roster cache TTL cannot be negative")
        self._roster_cache_ttl_seconds = roster_cache_ttl_seconds
        self._transport = transport
        self._sleep = sleep
        self._monotonic = monotonic
        self._roster_cache: tuple[StudentProject, ...] | None = None
        self._roster_cache_expires_at = 0.0
        self._roster_cache_lock = threading.Lock()

    def list_projects(self) -> list[StudentProject]:
        with self._roster_cache_lock:
            now = self._monotonic()
            if self._roster_cache is not None and now < self._roster_cache_expires_at:
                return list(self._roster_cache)
            projects = self._fetch_projects()
            if self._roster_cache_ttl_seconds > 0:
                self._roster_cache = tuple(projects)
                self._roster_cache_expires_at = self._monotonic() + self._roster_cache_ttl_seconds
            return list(projects)

    def _fetch_projects(self) -> list[StudentProject]:
        repositories: list[object] = []
        for page in range(1, _MAX_REPOSITORY_PAGES + 1):
            raw_repositories = self._request_json(
                f"/orgs/{quote(self._organization, safe='')}/repos",
                params={
                    "type": "all",
                    "per_page": str(_MAX_ITEMS),
                    "page": str(page),
                },
            )
            if not isinstance(raw_repositories, list):
                raise StudentProjectProviderError(
                    "GitHub returned an invalid repository list.",
                    category="temporary_failure",
                )
            repositories.extend(raw_repositories)
            if len(raw_repositories) < _MAX_ITEMS:
                break
        projects: list[StudentProject] = []
        for raw in repositories:
            if not isinstance(raw, Mapping):
                continue
            name = raw.get("name")
            if not isinstance(name, str) or not self._is_allowed_name(name):
                continue
            projects.append(
                StudentProject(
                    id=name,
                    site_url=self._site_url(raw, name),
                )
            )
        return sorted(projects, key=lambda project: project.id.casefold())

    def inspect_repository(
        self,
        project_id: str,
        view: RepositoryView,
        *,
        path: str | None = None,
        ref: str | None = None,
    ) -> dict[str, JsonValue]:
        repository = self._repository(project_id)
        default_branch = _optional_string(repository.get("default_branch")) or "main"
        selected_ref = ref or default_branch
        base = f"/repos/{quote(self._organization, safe='')}/{quote(project_id, safe='')}"
        if view == "summary":
            result = self._repository_summary(repository)
        elif view == "tree":
            payload = self._request_json(
                f"{base}/git/trees/{quote(selected_ref, safe='')}",
                params={"recursive": "1"},
            )
            result = self._tree_summary(payload, selected_ref)
        elif view == "file":
            if not path:
                raise StudentProjectNotFound("A repository-relative path is required.")
            safe_path = _repository_path(path)
            payload = self._request_json(
                f"{base}/contents/{quote(safe_path, safe='/')}",
                params={"ref": selected_ref},
            )
            result = self._file_summary(payload, selected_ref)
        elif view == "commits":
            payload = self._request_json(
                f"{base}/commits",
                params={"sha": selected_ref, "per_page": "30"},
            )
            result = {"ref": selected_ref, "commits": _commit_summaries(payload)}
        elif view == "branches":
            payload = self._request_json(f"{base}/branches", params={"per_page": "100"})
            result = {"branches": _branch_summaries(payload)}
        elif view == "pulls":
            payload = self._request_json(
                f"{base}/pulls",
                params={"state": "all", "per_page": "50"},
            )
            result = {"pull_requests": _pull_summaries(payload)}
        elif view == "issues":
            payload = self._request_json(
                f"{base}/issues",
                params={"state": "all", "per_page": "50"},
            )
            result = {"issues": _issue_summaries(payload)}
        else:
            payload = self._request_json(
                f"{base}/actions/runs",
                params={"per_page": "50"},
            )
            result = {"workflow_runs": _workflow_summaries(payload)}
        result["project_id"] = project_id
        result["view"] = view
        result["provider"] = "github"
        return result

    def _repository(self, project_id: str) -> Mapping[str, object]:
        if not self._is_allowed_name(project_id):
            raise StudentProjectNotFound("Student project was not found.")
        payload = self._request_json(
            f"/repos/{quote(self._organization, safe='')}/{quote(project_id, safe='')}"
        )
        if not isinstance(payload, Mapping) or payload.get("name") != project_id:
            raise StudentProjectProviderError(
                "GitHub returned invalid repository metadata.",
                category="temporary_failure",
            )
        return cast(Mapping[str, object], payload)

    def _is_allowed_name(self, name: str) -> bool:
        return (
            bool(_SAFE_REPOSITORY.fullmatch(name))
            and name.startswith(self._repository_prefix)
            and len(name) > len(self._repository_prefix)
            and name not in self._excluded_repositories
        )

    def _site_url(self, repository: Mapping[str, object], name: str) -> str | None:
        homepage = _public_https_url(repository.get("homepage"))
        if homepage:
            return homepage
        if repository.get("has_pages") is not True:
            return None
        try:
            pages = self._request_json(
                f"/repos/{quote(self._organization, safe='')}/{quote(name, safe='')}/pages"
            )
        except StudentProjectNotFound:
            return None
        if not isinstance(pages, Mapping):
            return None
        return _public_https_url(pages.get("html_url"))

    def _request_json(
        self,
        path: str,
        *,
        params: Mapping[str, str] | None = None,
    ) -> object:
        with httpx.Client(
            base_url=_GITHUB_API_URL,
            timeout=self._timeout_seconds,
            transport=self._transport,
            trust_env=False,
        ) as client:
            for attempt in range(3):
                try:
                    response = client.get(
                        path,
                        params=params,
                        headers={
                            "Accept": "application/vnd.github+json",
                            "Authorization": f"Bearer {self._token}",
                            "X-GitHub-Api-Version": "2022-11-28",
                            "User-Agent": "mit-course-agent",
                        },
                    )
                except httpx.TransportError as error:
                    if attempt == 2:
                        raise StudentProjectProviderError(
                            "GitHub is temporarily unavailable.",
                            category="temporary_failure",
                        ) from error
                    self._sleep(0.25 * (2**attempt))
                    continue
                if response.status_code in _RETRYABLE_STATUS_CODES and attempt < 2:
                    self._sleep(0.25 * (2**attempt))
                    continue
                if response.status_code in {401, 403}:
                    raise StudentProjectProviderError(
                        "GitHub rejected the configured read-only credential.",
                        category="permission_denied",
                    )
                if response.status_code == 404:
                    raise StudentProjectNotFound("Student project data was not found.")
                if response.status_code >= 500:
                    raise StudentProjectProviderError(
                        "GitHub is temporarily unavailable.",
                        category="temporary_failure",
                    )
                if response.status_code >= 400:
                    raise StudentProjectProviderError(
                        "GitHub rejected the read request.",
                        category="invalid_request",
                    )
                try:
                    return response.json()
                except ValueError as error:
                    raise StudentProjectProviderError(
                        "GitHub returned an invalid response.",
                        category="temporary_failure",
                    ) from error
        raise StudentProjectProviderError(
            "GitHub is temporarily unavailable.",
            category="temporary_failure",
        )

    @staticmethod
    def _repository_summary(repository: Mapping[str, object]) -> dict[str, JsonValue]:
        return {
            "description": _optional_string(repository.get("description")),
            "default_branch": _optional_string(repository.get("default_branch")),
            "homepage": _public_https_url(repository.get("homepage")),
            "language": _optional_string(repository.get("language")),
            "topics": cast(list[JsonValue], _string_list(repository.get("topics"), maximum=30)),
            "pushed_at": _optional_string(repository.get("pushed_at")),
            "updated_at": _optional_string(repository.get("updated_at")),
            "archived": repository.get("archived") is True,
        }

    @staticmethod
    def _tree_summary(payload: object, ref: str) -> dict[str, JsonValue]:
        if not isinstance(payload, Mapping):
            raise StudentProjectProviderError(
                "GitHub returned an invalid repository tree.",
                category="temporary_failure",
            )
        entries: list[JsonValue] = []
        raw_tree = payload.get("tree")
        if isinstance(raw_tree, list):
            for raw in raw_tree[:500]:
                if not isinstance(raw, Mapping):
                    continue
                entries.append(
                    {
                        "path": _optional_string(raw.get("path")),
                        "type": _optional_string(raw.get("type")),
                        "size": raw.get("size") if isinstance(raw.get("size"), int) else None,
                    }
                )
        return {"ref": ref, "entries": entries, "truncated": payload.get("truncated") is True}

    @staticmethod
    def _file_summary(payload: object, ref: str) -> dict[str, JsonValue]:
        if isinstance(payload, list):
            return {
                "ref": ref,
                "entries": [
                    {
                        "name": _optional_string(raw.get("name")),
                        "path": _optional_string(raw.get("path")),
                        "type": _optional_string(raw.get("type")),
                        "size": raw.get("size") if isinstance(raw.get("size"), int) else None,
                    }
                    for raw in payload[:_MAX_ITEMS]
                    if isinstance(raw, Mapping)
                ],
            }
        if not isinstance(payload, Mapping):
            raise StudentProjectProviderError(
                "GitHub returned invalid file metadata.",
                category="temporary_failure",
            )
        raw_content = payload.get("content")
        encoding = payload.get("encoding")
        if not isinstance(raw_content, str) or encoding != "base64":
            raise StudentProjectNotFound("The selected path is not a readable text file.")
        try:
            decoded = base64.b64decode(raw_content, validate=False)
        except ValueError as error:
            raise StudentProjectProviderError(
                "GitHub returned invalid file content.",
                category="temporary_failure",
            ) from error
        clipped = decoded[:_MAX_FILE_BYTES]
        try:
            text = clipped.decode("utf-8")
        except UnicodeDecodeError as error:
            raise StudentProjectNotFound("The selected path is not a UTF-8 text file.") from error
        return {
            "ref": ref,
            "path": _optional_string(payload.get("path")),
            "size": payload.get("size") if isinstance(payload.get("size"), int) else len(decoded),
            "text": text,
            "truncated": len(decoded) > _MAX_FILE_BYTES,
        }


def _repository_path(path: str) -> str:
    normalized = path.strip().strip("/")
    if (
        not normalized
        or len(normalized) > 500
        or "\\" in normalized
        or any(part in {"", ".", ".."} for part in normalized.split("/"))
    ):
        raise StudentProjectNotFound("Repository path is invalid.")
    filename = normalized.rsplit("/", 1)[-1].casefold()
    if (
        (filename == ".env" or (filename.startswith(".env.") and filename != ".env.example"))
        or filename in _SENSITIVE_FILE_NAMES
        or filename.endswith(_SENSITIVE_FILE_SUFFIXES)
    ):
        raise StudentProjectNotFound("Credential and private-key files cannot be inspected.")
    return normalized


def _public_https_url(value: object) -> str | None:
    if not isinstance(value, str) or len(value) > 2_048:
        return None
    parsed = urlsplit(value.strip())
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        return None
    return value.strip()


def _optional_string(value: object, *, maximum: int = 4_000) -> str | None:
    return value[:maximum] if isinstance(value, str) else None


def _string_list(value: object, *, maximum: int) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item[:500] for item in value[:maximum] if isinstance(item, str)]


def _mapping_list(payload: object) -> list[Mapping[str, Any]]:
    if not isinstance(payload, list):
        return []
    return [cast(Mapping[str, Any], item) for item in payload if isinstance(item, Mapping)]


def _commit_summaries(payload: object) -> list[JsonValue]:
    summaries: list[JsonValue] = []
    for raw in _mapping_list(payload)[:30]:
        raw_commit = raw.get("commit")
        commit = cast(Mapping[str, Any], raw_commit) if isinstance(raw_commit, Mapping) else {}
        raw_author = commit.get("author")
        author = cast(Mapping[str, Any], raw_author) if isinstance(raw_author, Mapping) else {}
        raw_account = raw.get("author")
        account = cast(Mapping[str, Any], raw_account) if isinstance(raw_account, Mapping) else {}
        summaries.append(
            {
                "sha": _optional_string(raw.get("sha"), maximum=40),
                "message": _optional_string(commit.get("message")),
                "author": _optional_string(author.get("name"), maximum=200),
                "author_login": _optional_string(account.get("login"), maximum=100),
                "date": _optional_string(author.get("date"), maximum=100),
                "url": _public_https_url(raw.get("html_url")),
            }
        )
    return summaries


def _branch_summaries(payload: object) -> list[JsonValue]:
    return [
        {
            "name": _optional_string(raw.get("name"), maximum=200),
            "sha": _optional_string(
                raw.get("commit", {}).get("sha")
                if isinstance(raw.get("commit"), Mapping)
                else None,
                maximum=40,
            ),
            "protected": raw.get("protected") is True,
        }
        for raw in _mapping_list(payload)[:_MAX_ITEMS]
    ]


def _pull_summaries(payload: object) -> list[JsonValue]:
    return [_issue_like_summary(raw, include_merge=True) for raw in _mapping_list(payload)[:50]]


def _issue_summaries(payload: object) -> list[JsonValue]:
    return [
        _issue_like_summary(raw, include_merge=False)
        for raw in _mapping_list(payload)[:50]
        if "pull_request" not in raw
    ]


def _issue_like_summary(raw: Mapping[str, Any], *, include_merge: bool) -> JsonValue:
    raw_user = raw.get("user")
    user = cast(Mapping[str, Any], raw_user) if isinstance(raw_user, Mapping) else {}
    result: dict[str, JsonValue] = {
        "number": raw.get("number") if isinstance(raw.get("number"), int) else None,
        "title": _optional_string(raw.get("title"), maximum=500),
        "state": _optional_string(raw.get("state"), maximum=30),
        "draft": raw.get("draft") is True,
        "author_login": _optional_string(user.get("login"), maximum=100),
        "body": _optional_string(raw.get("body")),
        "labels": [
            name[:200]
            for label in raw.get("labels", [])[:30]
            if isinstance(label, Mapping) and isinstance((name := label.get("name")), str)
        ]
        if isinstance(raw.get("labels"), list)
        else [],
        "created_at": _optional_string(raw.get("created_at"), maximum=100),
        "updated_at": _optional_string(raw.get("updated_at"), maximum=100),
        "url": _public_https_url(raw.get("html_url")),
    }
    if include_merge:
        result["merged_at"] = _optional_string(raw.get("merged_at"), maximum=100)
    return result


def _workflow_summaries(payload: object) -> list[JsonValue]:
    if not isinstance(payload, Mapping):
        return []
    runs = payload.get("workflow_runs")
    return [
        {
            "name": _optional_string(raw.get("name"), maximum=300),
            "branch": _optional_string(raw.get("head_branch"), maximum=200),
            "event": _optional_string(raw.get("event"), maximum=100),
            "status": _optional_string(raw.get("status"), maximum=100),
            "conclusion": _optional_string(raw.get("conclusion"), maximum=100),
            "created_at": _optional_string(raw.get("created_at"), maximum=100),
            "updated_at": _optional_string(raw.get("updated_at"), maximum=100),
            "url": _public_https_url(raw.get("html_url")),
        }
        for raw in _mapping_list(runs)[:50]
    ]
