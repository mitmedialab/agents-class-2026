"""Role-scoped assignment reads with an attached educational instruction."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from agent_core import PrincipalContext
from course_server.assignments import AssignmentStore

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_INSTRUCTION_PATH = _PROJECT_ROOT / "mcp/learning-contract.md"


class CourseMcpAssignmentService:
    def __init__(
        self,
        assignments: AssignmentStore,
        *,
        public_base_url: str,
        instruction_path: Path = _INSTRUCTION_PATH,
    ) -> None:
        self._assignments = assignments
        self._public_base_url = public_base_url.rstrip("/")
        self._instruction = instruction_path.read_text(encoding="utf-8").strip()
        if not self._instruction:
            raise ValueError("Course MCP assignment instruction is empty")

    def _open_in_course_agent_url(self, assignment_id: str) -> str:
        query = f"open_{assignment_id.replace('-', '_')}_assignment"
        return f"{self._public_base_url}/?{urlencode({'q': query})}"

    async def list_assignments(self, principal: PrincipalContext) -> list[dict[str, Any]]:
        if not principal.authenticated or "student" not in principal.roles:
            raise PermissionError("Active student access is required.")
        assignments = await self._assignments.list_for_principal(principal, now=datetime.now(UTC))
        return [
            {
                "assignment_id": item.assignment_id,
                "title": item.title,
                "summary": item.summary,
                "due_at": item.due_at.isoformat(),
                "revision": item.revision,
                "open_in_course_agent_url": self._open_in_course_agent_url(item.assignment_id),
            }
            for item in assignments
        ]

    async def get_assignment(
        self, principal: PrincipalContext, assignment_id: str
    ) -> dict[str, Any]:
        if not principal.authenticated or "student" not in principal.roles:
            raise PermissionError("Active student access is required.")
        assignment = await self._assignments.get_for_principal(
            assignment_id, principal, now=datetime.now(UTC)
        )
        if assignment is None:
            raise ValueError("The assignment is not available to this student.")
        return {
            "assistant_instruction": self._instruction,
            "assignment_id": assignment.assignment_id,
            "title": assignment.title,
            "revision": assignment.revision,
            "due_at": assignment.due_at.isoformat(),
            "content_markdown": assignment.content_markdown,
            "open_in_course_agent_url": self._open_in_course_agent_url(assignment.assignment_id),
        }
