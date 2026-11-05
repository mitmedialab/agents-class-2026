"""Offline GitHub-shaped project evidence for the fictional student starter."""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any
from urllib.parse import unquote

import httpx
from pydantic import JsonValue

from course_server.course_roster import CourseRoster

from .client import GitHubStudentProjectCatalog, RepositoryView, StudentProjectNotFound

FIXTURE_ROOT = Path(__file__).resolve().parents[3] / "examples/memory_starter/projects"
_ORGANIZATION = "memory-starter"


class FixtureStudentProjectCatalog(GitHubStudentProjectCatalog):
    """Run the production GitHub adapter against checked-in, offline API responses."""

    provider_name = "fixture"

    def __init__(self, roster: CourseRoster, root: Path = FIXTURE_ROOT) -> None:
        self._root = root
        self._fixtures: dict[str, dict[str, Any]] = {}
        self._sites: dict[str, Path] = {}
        for manifest in sorted(root.glob("*/api.json")):
            directory = manifest.parent
            if directory.is_symlink() or manifest.is_symlink():
                raise ValueError("Project fixture paths cannot be symbolic links")
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            if not isinstance(payload, dict) or payload.get("name") != directory.name:
                raise ValueError(f"Invalid project fixture: {manifest}")
            site_url = payload.get("homepage")
            site_file = directory / "site.md"
            expected_site = "https://student-fixtures.invalid/" + directory.name.removeprefix(
                "agents2026-"
            )
            if (
                site_url != expected_site
                or site_url in self._sites
                or site_file.is_symlink()
                or not site_file.is_file()
            ):
                raise ValueError(f"Invalid fixture site: {directory}")
            self._fixtures[directory.name] = payload
            self._sites[site_url] = site_file
        if not self._fixtures:
            raise ValueError("No fictional project fixtures were found")
        expected = {member.project_id for member in roster.members if member.project_id is not None}
        if set(self._fixtures) != expected:
            raise ValueError("Fictional projects must match the fictional course roster")
        for member in roster.members:
            if (
                member.project_id is not None
                and str(member.website) != self._fixtures[member.project_id]["homepage"]
            ):
                raise ValueError("Fictional project sites must match the fictional course roster")
        super().__init__(
            "offline-fixture",
            organization=_ORGANIZATION,
            repository_prefix="agents2026-",
            allowed_repositories=roster.active_weekly_project_ids,
            transport=httpx.MockTransport(self._respond),
            sleep=lambda _: None,
        )

    def inspect_repository(
        self,
        project_id: str,
        view: RepositoryView,
        *,
        path: str | None = None,
        ref: str | None = None,
    ) -> dict[str, JsonValue]:
        result = super().inspect_repository(project_id, view, path=path, ref=ref)
        result["provider"] = "fixture"
        return result

    def visit_site(self, url: str) -> dict[str, object]:
        """Read only exact fictional site URLs; never access the public network."""
        source = self._sites.get(url)
        if source is None:
            raise StudentProjectNotFound("Fictional student site was not found")
        return {"url": url, "text": source.read_text(encoding="utf-8"), "images": []}

    def _respond(self, request: httpx.Request) -> httpx.Response:
        parts = request.url.path.strip("/").split("/")
        if parts == ["orgs", _ORGANIZATION, "repos"]:
            return httpx.Response(200, json=list(self._fixtures.values()))
        if len(parts) < 3 or parts[:2] != ["repos", _ORGANIZATION]:
            return httpx.Response(404)
        project_id = parts[2]
        fixture = self._fixtures.get(project_id)
        if fixture is None:
            return httpx.Response(404)
        tail = parts[3:]
        if not tail:
            return httpx.Response(200, json=fixture)
        if tail[:2] == ["git", "trees"] and len(tail) == 3:
            if tail[2] != "main":
                return httpx.Response(404)
            files = self._files(project_id)
            return httpx.Response(
                200,
                json={
                    "tree": [
                        {"path": path, "type": "blob", "size": file.stat().st_size}
                        for path, file in files.items()
                    ],
                    "truncated": False,
                },
            )
        if tail and tail[0] == "contents":
            if request.url.params.get("ref", "main") != "main":
                return httpx.Response(404)
            relative = unquote("/".join(tail[1:]))
            files = self._files(project_id)
            file = files.get(relative)
            if file is not None:
                content = file.read_bytes()
                return httpx.Response(
                    200,
                    json={
                        "path": relative,
                        "size": len(content),
                        "encoding": "base64",
                        "content": base64.b64encode(content).decode("ascii"),
                    },
                )
            directory_prefix = relative.rstrip("/") + "/"
            children = [
                {
                    "name": path[len(directory_prefix) :],
                    "path": path,
                    "type": "file",
                    "size": source.stat().st_size,
                }
                for path, source in files.items()
                if path.startswith(directory_prefix) and "/" not in path[len(directory_prefix) :]
            ]
            return httpx.Response(200, json=children) if children else httpx.Response(404)
        if tail == ["actions", "runs"]:
            return httpx.Response(200, json={"workflow_runs": fixture.get("workflow_runs", [])})
        if tail == ["commits"] and request.url.params.get("sha", "main") != "main":
            return httpx.Response(404)
        if len(tail) == 1 and tail[0] in {"commits", "branches", "pulls", "issues"}:
            return httpx.Response(200, json=fixture.get(tail[0], []))
        return httpx.Response(404)

    def _files(self, project_id: str) -> dict[str, Path]:
        files_root = self._root / project_id / "files"
        return {
            file.relative_to(files_root).as_posix(): file
            for file in sorted(files_root.rglob("*"))
            if file.is_file() and not file.is_symlink()
        }
