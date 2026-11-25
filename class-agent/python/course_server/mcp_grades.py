"""Student-scoped MCP reads of released weekly build feedback."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from agent_core import PrincipalContext
from course_server.assignments import AssignmentStore
from course_server.grades import FileGradeBook


class CourseMcpGradeService:
    def __init__(self, grades: FileGradeBook, assignments: AssignmentStore) -> None:
        self._grades = grades
        self._assignments = assignments

    async def list_feedback(self, principal: PrincipalContext) -> list[dict[str, Any]]:
        graded_ids, feedback_weeks = self._grades.weekly_build_summary(principal)
        released = await self._assignments.list_for_principal(principal, now=datetime.now(UTC))
        allowed = set(graded_ids)
        entries = [
            {
                "assignment_id": assignment.assignment_id,
                "title": assignment.title,
                "has_feedback": int(assignment.assignment_id[5:]) in feedback_weeks,
            }
            for assignment in released
            if assignment.assignment_id in allowed
        ]
        return sorted(entries, key=lambda item: int(str(item["assignment_id"])[5:]))

    async def read_feedback(
        self, principal: PrincipalContext, assignment_id: str
    ) -> dict[str, Any]:
        try:
            feedback = self._grades.feedback_for_assignment(principal, assignment_id)
        except KeyError as error:
            raise ValueError("Feedback is unavailable for this assignment.") from error
        assignment = await self._assignments.get_for_principal(
            assignment_id, principal, now=datetime.now(UTC)
        )
        if assignment is None:
            raise ValueError("Feedback is unavailable for this assignment.")
        return {
            "assignment_id": assignment_id,
            "title": assignment.title,
            "feedback": feedback.model_dump(mode="json") if feedback else None,
        }
