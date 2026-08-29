"""Canonical course-application workspace state."""

from __future__ import annotations

from typing import cast

from pydantic import JsonValue

from course_server.workspace.models import WorkspacePanel, WorkspaceState

COURSE_APPLICATION_URI = "course://application"

APPLICATION_DRAFT_FIELDS: tuple[tuple[str, str], ...] = (
    ("name", "Name"),
    ("email", "Email"),
    ("github_id", "GitHub ID (username only; no @ or URL)"),
    (
        "department_research_group_year_of_study_mit",
        "Department / Research Group / Year of Study MIT",
    ),
    ("personal_webpage", "Personal Webpage"),
    ("interests", "Interests"),
    (
        "why_take_this_class",
        "Motivation: why this course; what you have built and want to build; "
        "your past project roles",
    ),
    ("knowledgeable_about", "Knowledgeable about"),
    ("skill_set", "Skill-set (practical knowledge and builder experience)"),
    ("registration_status", "Registration Status"),
    ("listener_willing_to_do_weekly_builds", "For listeners: willing to do weekly builds"),
    ("questions_or_comments_for_instructors", "Questions or comments for instructors"),
    ("photo_upload_id", "Class-only picture that represents you (JPEG, PNG, or WebP)"),
)

_LEGACY_APPLICATION_FIELD_IDS: dict[str, tuple[str, ...]] = {
    "department_research_group_year_of_study_mit": ("background", "department"),
    "personal_webpage": ("webpage",),
    "why_take_this_class": ("why", "motivation"),
    "skill_set": ("skills",),
    "registration_status": ("registration",),
    "listener_willing_to_do_weekly_builds": ("listener_builds",),
    "questions_or_comments_for_instructors": ("questions",),
    "photo_upload_id": ("photo",),
}


def application_draft_props() -> dict[str, JsonValue]:
    """Return a fresh, complete application form for the workspace."""

    return {
        "title": "Course Application Draft",
        "description": (
            "Enrollment is limited to 20 students. Apply by September 4 at midnight; "
            "notifications are sent September 9 at midnight. Expect to build a technical "
            "implementation every week, document each build in a GitHub repository, and show "
            "and present it in class. Complete every field below; changes are saved when you "
            "leave a field."
        ),
        "status": "draft",
        "fields": [
            {"id": field_id, "label": label, "value": "", "status": "missing"}
            for field_id, label in APPLICATION_DRAFT_FIELDS
        ],
    }


def _draft_fields(props: dict[str, JsonValue]) -> list[dict[str, JsonValue]]:
    fields = props.get("fields")
    if not isinstance(fields, list) or not all(isinstance(field, dict) for field in fields):
        return []
    return cast(list[dict[str, JsonValue]], fields)


def normalized_application_draft_props(
    existing_props: dict[str, JsonValue],
) -> dict[str, JsonValue]:
    """Restore canonical fields while preserving trustworthy draft values."""

    normalized = application_draft_props()
    fields_by_id = {
        field_id: field
        for field in _draft_fields(existing_props)
        if isinstance((field_id := field.get("id")), str)
    }
    normalized_fields = cast(list[dict[str, JsonValue]], normalized["fields"])
    for field in normalized_fields:
        field_id = cast(str, field["id"])
        prior = next(
            (
                fields_by_id[candidate_id]
                for candidate_id in (
                    field_id,
                    *_LEGACY_APPLICATION_FIELD_IDS.get(field_id, ()),
                )
                if candidate_id in fields_by_id
            ),
            None,
        )
        if prior is None:
            continue
        value = prior.get("value")
        field["value"] = value if isinstance(value, str) else ""
        status = prior.get("status")
        field["status"] = (
            status
            if status in {"missing", "candidate", "inferred", "confirmed"}
            else ("candidate" if field["value"] else "missing")
        )
        source = prior.get("source")
        if isinstance(source, str) and source:
            field["source"] = source
    return normalized


def merged_application_draft_props(
    existing_props: dict[str, JsonValue],
    changes: dict[str, JsonValue],
) -> dict[str, JsonValue]:
    """Merge a model update without dropping canonical or previously populated fields."""

    merged = normalized_application_draft_props(existing_props)
    merged_fields = cast(list[dict[str, JsonValue]], merged["fields"])
    fields_by_id = {cast(str, field["id"]): field for field in merged_fields}
    for changed in _draft_fields(changes):
        field_id = changed.get("id")
        if not isinstance(field_id, str) or field_id not in fields_by_id:
            continue
        current = fields_by_id[field_id]
        changed_value = changed.get("value")
        current_value = current.get("value")
        if (
            isinstance(changed_value, str)
            and not changed_value.strip()
            and isinstance(current_value, str)
            and current_value.strip()
        ):
            continue
        for key in ("value", "status", "source"):
            if key in changed:
                current[key] = changed[key]
    status = changes.get("status")
    if status in {"draft", "ready", "final", "submitted"}:
        merged["status"] = status
    return merged


def application_draft_panel(workspace: WorkspaceState) -> WorkspacePanel | None:
    """Find canonical or legacy model-created application drafts."""

    for panel in workspace.panels:
        if panel.component_id != "draft-document":
            continue
        if (
            panel.state.get("document_kind") == "course-application"
            or panel.resource_uri == COURSE_APPLICATION_URI
        ):
            return panel
        prop_title = panel.props.get("title")
        titles = [panel.title, prop_title if isinstance(prop_title, str) else None]
        if any(
            isinstance(title, str) and "course application" in title.casefold() for title in titles
        ):
            return panel
    return None
