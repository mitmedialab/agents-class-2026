"""Student-scoped MCP wrappers around the existing project inspection tools."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import uuid4

from agent_core import PrincipalContext
from course_server.agent.capabilities import ToolExecutionContext, WebVisitRunner
from course_server.student_projects import (
    InspectMyStudentRepositoryTool,
    InspectMyStudentSiteTool,
    InspectStudentSiteTool,
    ListStudentProjectsTool,
    StudentProjectCatalog,
)


class CourseMcpProjectService:
    def __init__(
        self,
        projects: StudentProjectCatalog,
        visit: WebVisitRunner,
        *,
        repository_prefix: str,
        student_project_aliases: Mapping[str, str] | None = None,
    ) -> None:
        self._list = ListStudentProjectsTool(projects)
        self._site = InspectStudentSiteTool(projects, visit)
        self._my_site = InspectMyStudentSiteTool(
            projects, visit, repository_prefix, student_project_aliases
        )
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

    async def inspect_site(self, principal: PrincipalContext, project_id: str) -> Any:
        return (
            await self._site.execute({"project_id": project_id}, self._context(principal))
        ).content

    async def inspect_my_site(self, principal: PrincipalContext) -> Any:
        return (await self._my_site.execute({}, self._context(principal))).content

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
