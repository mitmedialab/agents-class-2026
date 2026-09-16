"""Role-scoped tools for student project repositories and deployed sites."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import ClassVar, cast

from pydantic import JsonValue

from agent_core import PrincipalContext
from course_server.agent.capabilities import (
    ToolExecutionContext,
    ToolExecutionResult,
    ToolProviderError,
    ToolValidationError,
    WebVisitRunner,
)
from course_server.student_project_tool_ids import (
    INSPECT_STUDENT_REPOSITORY_TOOL_ID,
    INSPECT_STUDENT_SITE_TOOL_ID,
    LIST_STUDENT_PROJECTS_TOOL_ID,
)

from .client import (
    RepositoryView,
    StudentProjectCatalog,
    StudentProjectNotFound,
    StudentProjectProviderError,
)

_PROJECT_ID_PATTERN = "^agents2026-[A-Za-z0-9_.-]{1,80}$"
_REPOSITORY_VIEWS = (
    "summary",
    "tree",
    "file",
    "commits",
    "branches",
    "pulls",
    "issues",
    "workflows",
)


def _require_course_member(principal: PrincipalContext) -> None:
    if not principal.authenticated or not (
        {"student", "ta", "instructor", "admin"} & set(principal.roles)
    ):
        raise ToolValidationError("An active course-member login is required.")


def _require_course_staff(principal: PrincipalContext) -> None:
    if not principal.authenticated or not ({"ta", "instructor", "admin"} & set(principal.roles)):
        raise ToolValidationError("An active TA, instructor, or admin login is required.")


def _project_id(arguments: Mapping[str, JsonValue], allowed: frozenset[str]) -> str:
    unknown = set(arguments) - allowed
    if unknown:
        raise ToolValidationError(f"unexpected arguments: {', '.join(sorted(unknown))}")
    value = arguments.get("project_id")
    if not isinstance(value, str) or not value.strip() or len(value) > 100:
        raise ToolValidationError("project_id must be a student project identifier.")
    return value.strip()


def _translate_provider_error(error: StudentProjectProviderError) -> ToolProviderError:
    return ToolProviderError(str(error), category=error.category)


class ListStudentProjectsTool:
    id = LIST_STUDENT_PROJECTS_TOOL_ID
    description = (
        "List the real course student projects and their deployed public website URLs. "
        "Use this first when a course member asks about a student or project by name and "
        "the exact agents2026-* project identifier or deployed URL is not yet known. Once "
        "the project is identified, continue with the appropriate site or repository "
        "inspection tool instead of searching general course resources. "
        "Available only to authenticated course members. This does not expose "
        "repository source or GitHub development metadata."
    )
    input_schema: ClassVar[dict[str, JsonValue]] = {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    }

    def __init__(self, projects: StudentProjectCatalog) -> None:
        self._projects = projects

    async def execute(
        self,
        arguments: Mapping[str, JsonValue],
        context: ToolExecutionContext,
    ) -> ToolExecutionResult:
        _require_course_member(context.principal)
        if arguments:
            raise ToolValidationError("This tool accepts no arguments.")
        try:
            projects = await asyncio.to_thread(self._projects.list_projects)
        except StudentProjectProviderError as error:
            raise _translate_provider_error(error) from error
        return ToolExecutionResult(
            content={
                "projects": [
                    {"project_id": project.id, "site_url": project.site_url} for project in projects
                ],
                "count": len(projects),
                "provider": "github",
                "retrieved_at": datetime.now(UTC).isoformat(),
            },
            summary=f"Listed {len(projects)} student project websites.",
            storage_policy="server_summary",
        )


class InspectStudentSiteTool:
    id = INSPECT_STUDENT_SITE_TOOL_ID
    description = (
        "Read what one student's deployed public website currently displays. Authenticated "
        "students, TAs, instructors, and admins may inspect any listed student site. Use the "
        "exact project identifier returned by course.list_student_projects, and call this "
        "directly for questions about what a student's live website shows. Use the "
        "returned site URL "
        "with browser.open when a live visual rendering is useful. This tool never returns "
        "repository source, commits, issues, or workflow metadata."
    )
    input_schema: ClassVar[dict[str, JsonValue]] = {
        "type": "object",
        "properties": {
            "project_id": {
                "type": "string",
                "pattern": _PROJECT_ID_PATTERN,
                "maxLength": 100,
            }
        },
        "required": ["project_id"],
        "additionalProperties": False,
    }

    def __init__(self, projects: StudentProjectCatalog, visit: WebVisitRunner) -> None:
        self._projects = projects
        self._visit = visit

    async def execute(
        self,
        arguments: Mapping[str, JsonValue],
        context: ToolExecutionContext,
    ) -> ToolExecutionResult:
        _require_course_member(context.principal)
        project_id = _project_id(arguments, frozenset({"project_id"}))
        try:
            projects = await asyncio.to_thread(self._projects.list_projects)
        except StudentProjectProviderError as error:
            raise _translate_provider_error(error) from error
        project = next((item for item in projects if item.id == project_id), None)
        if project is None:
            raise ToolValidationError("Student project was not found.")
        if project.site_url is None:
            raise ToolValidationError("This student project has no deployed website URL.")
        try:
            raw_page = await asyncio.to_thread(self._visit, project.site_url)
        except Exception as error:
            raise ToolValidationError("The deployed student website could not be read.") from error
        if isinstance(raw_page, str):
            page: JsonValue = {"url": project.site_url, "text": raw_page[:20_000]}
        elif isinstance(raw_page, Mapping):
            text = raw_page.get("text")
            images = raw_page.get("images")
            page = {
                "url": str(raw_page.get("url", project.site_url)),
                "text": text[:20_000] if isinstance(text, str) else "",
                "images": cast(list[JsonValue], images[:20]) if isinstance(images, list) else [],
            }
        else:
            raise ToolValidationError("The deployed student website returned invalid content.")
        return ToolExecutionResult(
            content={
                "project_id": project.id,
                "site_url": project.site_url,
                "page": page,
                "retrieved_at": datetime.now(UTC).isoformat(),
            },
            summary=f"Inspected the deployed website for {project.id}.",
            storage_policy="server_summary",
        )


class InspectStudentRepositoryTool:
    id = INSPECT_STUDENT_REPOSITORY_TOOL_ID
    description = (
        "Inspect one real student GitHub repository as authorized course staff. Read summary, "
        "tree, one "
        "UTF-8 file, commits, branches, pull requests, issues, or workflow runs. Use several "
        "focused calls when assessing current work or debugging evidence. For requests to tell "
        "course staff about a named student's work, use the exact agents2026-* "
        "project identifier and inspect the repository directly; begin with summary or tree, "
        "then read only relevant files. Do not substitute general course-resource searches for "
        "repository inspection. This read-only tool "
        "cannot access secrets, settings, collaborators, or perform GitHub writes."
    )
    input_schema: ClassVar[dict[str, JsonValue]] = {
        "type": "object",
        "properties": {
            "project_id": {
                "type": "string",
                "pattern": _PROJECT_ID_PATTERN,
                "maxLength": 100,
            },
            "view": {"type": "string", "enum": list(_REPOSITORY_VIEWS)},
            "path": {
                "type": "string",
                "minLength": 1,
                "maxLength": 500,
                "description": "Repository-relative path, required only for the file view.",
            },
            "ref": {
                "type": "string",
                "minLength": 1,
                "maxLength": 200,
                "description": "Optional branch, tag, or commit for tree, file, and commits.",
            },
        },
        "required": ["project_id", "view"],
        "additionalProperties": False,
    }

    def __init__(self, projects: StudentProjectCatalog) -> None:
        self._projects = projects

    async def execute(
        self,
        arguments: Mapping[str, JsonValue],
        context: ToolExecutionContext,
    ) -> ToolExecutionResult:
        _require_course_staff(context.principal)
        project_id = _project_id(
            arguments,
            frozenset({"project_id", "view", "path", "ref"}),
        )
        view = arguments.get("view")
        if not isinstance(view, str) or view not in _REPOSITORY_VIEWS:
            raise ToolValidationError("view must be one of the supported repository sections.")
        path = arguments.get("path")
        ref = arguments.get("ref")
        if path is not None and not isinstance(path, str):
            raise ToolValidationError("path must be text.")
        if ref is not None and not isinstance(ref, str):
            raise ToolValidationError("ref must be text.")
        if view == "file" and (not isinstance(path, str) or not path.strip()):
            raise ToolValidationError("path is required for the file view.")
        if view != "file" and path is not None:
            raise ToolValidationError("path is accepted only for the file view.")
        if ref is not None and view not in {"tree", "file", "commits"}:
            raise ToolValidationError("ref is accepted only for tree, file, and commits.")
        try:
            result = await asyncio.to_thread(
                self._projects.inspect_repository,
                project_id,
                cast(RepositoryView, view),
                path=path.strip() if isinstance(path, str) else None,
                ref=ref.strip() if isinstance(ref, str) else None,
            )
        except StudentProjectNotFound as error:
            raise ToolValidationError(str(error)) from error
        except StudentProjectProviderError as error:
            raise _translate_provider_error(error) from error
        result["retrieved_at"] = datetime.now(UTC).isoformat()
        return ToolExecutionResult(
            content=result,
            summary=f"Inspected {view} for {project_id}.",
            storage_policy="server_summary",
        )
