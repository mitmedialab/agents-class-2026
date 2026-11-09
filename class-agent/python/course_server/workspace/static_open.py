"""Deterministic workspace presentations for explicit course-site controls."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID, uuid4

from agent_core import PrincipalContext
from course_server.agent import COURSE_SCHEDULE_URI, COURSE_SYLLABUS_URI, CourseResourceCatalog
from course_server.assignments import AssignmentStore, assignment_workspace_command
from course_server.notifications import (
    NotificationCenterAccessDenied,
    NotificationCenterItem,
    NotificationCenterService,
)

from .models import OpenWorkspaceCommand, WorkspacePanel

StaticOpenTarget = Literal["schedule", "grading", "notification", "assignment", "people"]
_DOCUMENT_MEDIA_TYPES = frozenset({"text/markdown", "text/plain", "application/pdf"})


class StaticWorkspaceUnavailable(ValueError):
    """The requested item is absent or unavailable to this principal."""


def _panel_title(value: str) -> str:
    return value if len(value) <= 200 else value[:199] + "…"


def _resource_command(
    resources: CourseResourceCatalog,
    principal: PrincipalContext,
    uri: str,
    *,
    grading: bool = False,
) -> OpenWorkspaceCommand:
    resource = next(
        (item for item in resources.list_authorized(principal) if item.uri == uri),
        None,
    )
    if resource is None:
        raise StaticWorkspaceUnavailable("resource not available")
    if grading and (uri != COURSE_SYLLABUS_URI or resource.media_type != "text/markdown"):
        raise StaticWorkspaceUnavailable("grading source not available")
    if uri == COURSE_SCHEDULE_URI:
        if resource.media_type not in {"text/markdown", "application/json"}:
            raise StaticWorkspaceUnavailable("schedule source has no calendar viewer")
        component_id = "calendar"
        props: dict[str, str | int] = {"view": "agenda"}
    elif resource.media_type in _DOCUMENT_MEDIA_TYPES:
        component_id = "document-viewer"
        props = {"page": 1} if resource.media_type == "application/pdf" else {}
        if grading:
            props["find_text"] = "Assignments and Evaluation"
    else:
        raise StaticWorkspaceUnavailable("resource has no static viewer")
    return OpenWorkspaceCommand(
        panel=WorkspacePanel(
            id=uuid4(),
            component_id=component_id,
            title="Grading" if grading else _panel_title(resource.title),
            resource_uri=uri,
            props=props,
            state={"document_kind": "grading-overview"} if grading else {},
        )
    )


def _notification_detail_command(item: NotificationCenterItem) -> OpenWorkspaceCommand:
    title = _panel_title(item.title)
    content = item.detail if title == item.title else f"## {item.title}\n\n{item.detail}"
    return OpenWorkspaceCommand(
        panel=WorkspacePanel(
            id=uuid4(),
            component_id="draft-document",
            title=title,
            props={"title": title, "content": content},
            state={"document_kind": "course-notification", "notification_id": str(item.id)},
        )
    )


async def static_open_command(
    *,
    target: StaticOpenTarget,
    notification_id: UUID | None,
    assignment_id: str | None = None,
    principal: PrincipalContext,
    resources: CourseResourceCatalog,
    notifications: NotificationCenterService | None,
    assignments: AssignmentStore | None,
) -> OpenWorkspaceCommand:
    if target == "schedule":
        return _resource_command(resources, principal, COURSE_SCHEDULE_URI)
    if target == "grading":
        return _resource_command(resources, principal, COURSE_SYLLABUS_URI, grading=True)
    if target == "assignment":
        if assignment_id is None or assignments is None:
            raise StaticWorkspaceUnavailable("assignment not available")
        assignment = await assignments.get_for_principal(
            assignment_id, principal, now=datetime.now(UTC)
        )
        if assignment is None:
            raise StaticWorkspaceUnavailable("assignment not available")
        return assignment_workspace_command(assignment)
    if target == "people":
        # The People panel is owner-scoped and opened by the API adapter, which holds the service.
        raise StaticWorkspaceUnavailable("people panel is opened by the API adapter")
    if notification_id is None or notifications is None:
        raise StaticWorkspaceUnavailable("notification not available")
    try:
        center = await notifications.get(principal)
    except NotificationCenterAccessDenied as error:
        raise StaticWorkspaceUnavailable("notification not available") from error
    item = next(
        (candidate for candidate in center.history_items if candidate.id == notification_id),
        None,
    )
    if item is None or item.section == "communications":
        raise StaticWorkspaceUnavailable("notification not available")
    if item.assignment_id is not None:
        if assignments is None:
            raise StaticWorkspaceUnavailable("assignment not available")
        assignment = await assignments.get_for_principal(
            item.assignment_id, principal, now=datetime.now(UTC)
        )
        if assignment is None:
            raise StaticWorkspaceUnavailable("assignment not available")
        return assignment_workspace_command(assignment)
    if item.resource_uri is not None:
        try:
            return _resource_command(resources, principal, item.resource_uri)
        except StaticWorkspaceUnavailable:
            pass
    return _notification_detail_command(item)
