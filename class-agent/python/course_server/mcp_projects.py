"""Student-scoped MCP project links and own-repository inspection."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import uuid4

from agent_core import PrincipalContext
from course_server.agent.capabilities import ToolExecutionContext
from course_server.student_projects import (
    InspectMyStudentRepositoryTool,
    ListStudentProjectsTool,
    StudentProjectCatalog,
)
from course_server.student_projects.tools import resolve_own_project


class CourseMcpProjectService:
    def __init__(
        self,
        projects: StudentProjectCatalog,
        *,
        repository_prefix: str,
        student_project_aliases: Mapping[str, str] | None = None,
    ) -> None:
        self._projects = projects
        self._repository_prefix = repository_prefix
        self._student_project_aliases = dict(student_project_aliases or {})
        self._list = ListStudentProjectsTool(projects)
        self._my_repository = InspectMyStudentRepositoryTool(
            projects, repository_prefix, student_project_aliases
        )

    @staticmethod
    def _context(principal: PrincipalContext) -> ToolExecutionContext:
        if not principal.authenticated or "student" not in principal.roles:
            raise PermissionError("Active student access is required.")
        return ToolExecutionContext(
            principal=principal,
            conversation_id=uuid4(),
            permitted_resource_uris=frozenset(),
        )

    async def list_projects(self, principal: PrincipalContext) -> Any:
        return (await self._list.execute({}, self._context(principal))).content

    async def get_my_project(self, principal: PrincipalContext) -> dict[str, str | bool | None]:
        self._context(principal)
        project = await resolve_own_project(
            self._projects,
            principal,
            self._repository_prefix,
            self._student_project_aliases,
        )
        return {
            "project_id": project.id,
            "site_url": project.site_url,
            "site_content_inspected": False,
        }

    async def inspect_my_repository(
        self,
        principal: PrincipalContext,
        view: str,
        *,
        path: str | None = None,
        ref: str | None = None,
    ) -> Any:
        arguments = {"view": view}
        if path is not None:
            arguments["path"] = path
        if ref is not None:
            arguments["ref"] = ref
        return (await self._my_repository.execute(arguments, self._context(principal))).content
