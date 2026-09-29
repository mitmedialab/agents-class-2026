"""Bounded site and repository discovery; the agent decides weekly eligibility."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from pathlib import Path
from typing import ClassVar

from pydantic import JsonValue

from course_server.agent.capabilities import (
    ToolExecutionContext,
    ToolExecutionResult,
    ToolProviderError,
    ToolValidationError,
    WebVisitRunner,
)
from course_server.student_project_tool_ids import SCREEN_SHOWCASE_TOOL_ID

from .client import StudentProject, StudentProjectCatalog, StudentProjectProviderError
from .showcase import read_history
from .tools import (
    InspectStudentRepositoryTool,
    InspectStudentSiteTool,
    _require_course_staff,
    _translate_provider_error,
)

# Bounds limit network load and model context for one class-wide screening call.
_SITE_CONCURRENCY = 4
_MAX_ROSTER = 100
_SCREEN_TEXT_LIMIT = 4000


class ScreenShowcaseTool:
    id = SCREEN_SHOWCASE_TOOL_ID
    description = (
        "Screen all registered student sites in one bounded concurrent call for a weekly "
        "showcase, excluding the last two issues' presenters. Returns public homepage text "
        "and repository file listings with independent failure statuses. Homepage text alone "
        "cannot establish absence of a weekly build. Follow links or read the relevant weekly "
        "repository documentation/files and commits with staff.inspect_student_repository "
        "before excluding unclear sites. Repository documentation may establish eligibility "
        "when site navigation hides the weekly post. A listing alone is not build evidence. "
        "Then review a ranked shortlist's repositories and use staff.select_weekly_showcase "
        "with the full eligible_projects pool for the random draw. Continue to selection "
        "and display in the same turn; screening is not task completion."
    )
    input_schema: ClassVar[dict[str, JsonValue]] = {
        "type": "object",
        "properties": {"week": {"type": "integer", "minimum": 1, "maximum": 100}},
        "required": ["week"],
        "additionalProperties": False,
    }

    def __init__(
        self, projects: StudentProjectCatalog, visit: WebVisitRunner, history_path: Path
    ) -> None:
        self._projects = projects
        self._site_tool = InspectStudentSiteTool(projects, visit)
        self._repository_tool = InspectStudentRepositoryTool(projects)
        self._history_path = history_path

    async def execute(
        self, arguments: Mapping[str, JsonValue], context: ToolExecutionContext
    ) -> ToolExecutionResult:
        _require_course_staff(context.principal)
        week = arguments.get("week")
        if set(arguments) != {"week"} or type(week) is not int or not 1 <= week <= 100:
            raise ToolValidationError("Supply only an integer week from 1 to 100.")
        history = read_history(self._history_path)
        if any(issue.week == week for issue in history.issues):
            raise ToolValidationError("This week's issue is already recorded.")
        previous = sorted(
            (issue for issue in history.issues if issue.week < week), key=lambda issue: issue.week
        )
        excluded = {project for issue in previous[-2:] for project in issue.project_ids}
        try:
            projects = await asyncio.to_thread(self._projects.list_projects)
        except StudentProjectProviderError as error:
            raise _translate_provider_error(error) from error
        if len(projects) > _MAX_ROSTER:
            raise ToolValidationError("Roster exceeds the 100-project screening bound.")
        semaphore = asyncio.Semaphore(_SITE_CONCURRENCY)

        async def inspect(project: StudentProject) -> JsonValue:
            base: dict[str, JsonValue] = {
                "project_id": project.id,
                "site_url": project.site_url,
            }
            if project.id in excluded:
                return {**base, "status": "cooldown"}
            if not project.site_url:
                return {**base, "status": "no_site"}
            async with semaphore:
                try:
                    result = await self._site_tool.execute({"project_id": project.id}, context)
                except (ToolValidationError, ToolProviderError):
                    base["status"] = "unreadable"
                else:
                    content = result.content
                    page = content.get("page") if isinstance(content, dict) else None
                    text = page.get("text") if isinstance(page, dict) else ""
                    text = text if isinstance(text, str) else ""
                    base.update(
                        {
                            "status": "read",
                            "text": text[:_SCREEN_TEXT_LIMIT],
                            "truncated": len(text) > _SCREEN_TEXT_LIMIT,
                            "images": page.get("images", []) if isinstance(page, dict) else [],
                        }
                    )
                # A successful homepage fetch says nothing about hidden weekly work.
                # Discover files for every deployed project; semantic path choice stays agent-owned.
                try:
                    repository = await self._repository_tool.execute(
                        {"project_id": project.id, "view": "tree"}, context
                    )
                except (ToolValidationError, ToolProviderError):
                    base["repository_status"] = "unreadable"
                else:
                    base["repository_status"] = "read"
                    base["repository_tree"] = repository.content
            base["eligibility_status"] = "needs_review"
            return base

        results = await asyncio.gather(*(inspect(project) for project in projects))
        return ToolExecutionResult(
            content={
                "week": week,
                "projects": list(results),
                "note": "Discovery only, not eligibility decisions. If the weekly build is hidden, "
                "read relevant repository documentation and implementation, check commits, and "
                "follow documented site routes. Repository documentation may verify the weekly "
                "build without an accessible weekly post. Failed reads remain unresolved; a "
                "filename or commit message alone is insufficient evidence.",
            },
            summary=f"Screened {len(projects)} roster entries for Week {week}.",
            storage_policy="server_summary",
        )
