"""Canonical course-application workspace state."""

from __future__ import annotations

from typing import cast

from pydantic import JsonValue

from course_server.course_application import (
    APPLICATION_FIELD_SPECS,
    application_field_validation_error,
)
from course_server.workspace.models import WorkspacePanel, WorkspaceState

COURSE_APPLICATION_URI = "course://application"


class ApplicationDraftValidationError(ValueError):
    """A populated application draft field does not satisfy its final contract."""


class ApplicationDraftEditError(ValueError):
    """A user draft edit cannot be represented safely."""

    def __init__(self, code: str, message: str, *, field_id: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.field_id = field_id
        self.message = message


APPLICATION_DRAFT_FIELDS: tuple[tuple[str, str], ...] = tuple(
    (field.id, field.label) for field in APPLICATION_FIELD_SPECS
)

_LEGACY_APPLICATION_FIELD_IDS: dict[str, tuple[str, ...]] = {
    "department": ("department_research_group_year_of_study_mit", "background"),
    "personal_webpage": ("webpage",),
    "why_take_this_class": ("why", "motivation"),
    "skill_set": ("skills",),
    "registration_status": ("registration",),
    "listener_willing_to_do_weekly_builds": ("listener_builds",),
    "questions_or_comments_for_instructors": ("questions",),
    "photo_upload_id": ("photo",),
}

_LEGACY_REGISTRATION_VALUES: dict[str, str] = {
    "MAS student for credit": "for credit",
    "MIT student for credit": "for credit",
    "Other student for credit": "for credit",
    "MAS student listener": "listener",
    "MIT student listener": "listener",
    "Other student listener": "listener",
}

_LEGACY_SCHOOL_VALUES: dict[str, str] = {
    "MAS student for credit": "MIT Media Lab",
    "MAS student listener": "MIT Media Lab",
    "MIT student for credit": "MIT",
    "MIT student listener": "MIT",
    "Other student for credit": "Other",
    "Other student listener": "Other",
}

_APPLICATION_FIELD_OPTIONS = {
    field.id: field.options for field in APPLICATION_FIELD_SPECS if field.options
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
            {
                "id": field.id,
                "label": field.label,
                "value": "",
                "status": "missing",
                **({"options": list(field.options)} if field.options else {}),
                "input_type": field.input_type,
                **({"help_text": field.help_text} if field.help_text else {}),
            }
            for field in APPLICATION_FIELD_SPECS
        ],
    }


def _draft_fields(props: dict[str, JsonValue]) -> list[dict[str, JsonValue]]:
    fields = props.get("fields")
    if not isinstance(fields, list) or not all(isinstance(field, dict) for field in fields):
        return []
    return cast(list[dict[str, JsonValue]], fields)


def _refresh_application_validation(fields: list[dict[str, JsonValue]]) -> None:
    registration_field = next(
        (field for field in fields if field.get("id") == "registration_status"),
        None,
    )
    registration_value = registration_field.get("value") if registration_field is not None else None
    registration_status = registration_value if isinstance(registration_value, str) else None
    for field in fields:
        field_id = field.get("id")
        value = field.get("value")
        if not isinstance(field_id, str) or not isinstance(value, str):
            field.pop("validation_error", None)
            continue
        validation_error = application_field_validation_error(
            field_id,
            value,
            registration_status=registration_status,
        )
        if validation_error is None:
            field.pop("validation_error", None)
            continue
        field["validation_error"] = validation_error
        if field.get("status") == "confirmed":
            field["status"] = "candidate"


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
        prior_match = next(
            (
                (candidate_id, fields_by_id[candidate_id])
                for candidate_id in (
                    field_id,
                    *_LEGACY_APPLICATION_FIELD_IDS.get(field_id, ()),
                )
                if candidate_id in fields_by_id
            ),
            (None, None),
        )
        prior_id, prior = prior_match
        if prior is None and field_id == "school":
            legacy_registration = fields_by_id.get("registration_status")
            legacy_value = (
                legacy_registration.get("value") if isinstance(legacy_registration, dict) else None
            )
            if isinstance(legacy_value, str) and legacy_value in _LEGACY_SCHOOL_VALUES:
                field["value"] = _LEGACY_SCHOOL_VALUES[legacy_value]
                field["status"] = "candidate"
                field["source"] = "Migrated from the previous registration response"
            continue
        if prior is None:
            continue
        value = prior.get("value")
        field["value"] = value if isinstance(value, str) else ""
        if field_id == "registration_status" and field["value"] in _LEGACY_REGISTRATION_VALUES:
            field["value"] = _LEGACY_REGISTRATION_VALUES[cast(str, field["value"])]
        if field_id == "listener_willing_to_do_weekly_builds":
            normalized_listener_value = cast(str, field["value"]).strip().casefold()
            if "not applicable" in normalized_listener_value:
                field["value"] = "not applicable"
            elif normalized_listener_value.startswith("yes"):
                field["value"] = "yes"
            elif normalized_listener_value.startswith("no"):
                field["value"] = "no"
        status = prior.get("status")
        field["status"] = (
            status
            if status in {"missing", "candidate", "inferred", "confirmed"}
            else ("candidate" if field["value"] else "missing")
        )
        allowed_options = _APPLICATION_FIELD_OPTIONS.get(field_id)
        if allowed_options is not None and field["value"] not in allowed_options:
            field["status"] = "candidate" if field["value"] else "missing"
        if prior_id == "department_research_group_year_of_study_mit":
            field["status"] = "candidate"
            field["source"] = "Migrated from the previous combined background field"
        source = prior.get("source")
        if isinstance(source, str) and source and "source" not in field:
            field["source"] = source
    _refresh_application_validation(normalized_fields)
    return normalized


def updated_application_draft_from_user(
    existing_props: dict[str, JsonValue],
    field_id: object,
    value: object,
) -> dict[str, JsonValue]:
    """Save a bounded user edit and annotate any final-submission validation problem."""

    if not isinstance(field_id, str) or not isinstance(value, str):
        raise ApplicationDraftEditError(
            "invalid_draft_change",
            "The draft change must identify a field and provide text.",
        )
    if len(value) > 4_000:
        raise ApplicationDraftEditError(
            "draft_field_too_long",
            "This field cannot contain more than 4,000 characters.",
            field_id=field_id,
        )
    normalized = normalized_application_draft_props(existing_props)
    fields = _draft_fields(normalized)
    target = next((field for field in fields if field.get("id") == field_id), None)
    if target is None:
        raise ApplicationDraftEditError(
            "unknown_draft_field",
            "This field is not part of the current draft.",
            field_id=field_id,
        )
    target["value"] = value
    if value.strip():
        target["status"] = "confirmed"
        target["source"] = "Confirmed by applicant"
    else:
        target["status"] = "missing"
        target["source"] = ""
    _refresh_application_validation(fields)
    if target.get("validation_error") is not None:
        target["status"] = "candidate"
        target["source"] = "Entered by applicant"
    return {"fields": cast(list[JsonValue], fields)}


def merged_application_draft_props(
    existing_props: dict[str, JsonValue],
    changes: dict[str, JsonValue],
) -> dict[str, JsonValue]:
    """Merge a model update without dropping canonical or previously populated fields."""

    merged = normalized_application_draft_props(existing_props)
    merged_fields = cast(list[dict[str, JsonValue]], merged["fields"])
    fields_by_id = {cast(str, field["id"]): field for field in merged_fields}
    changed_fields = _draft_fields(changes)
    proposed_registration = next(
        (
            changed.get("value")
            for changed in changed_fields
            if changed.get("id") == "registration_status" and isinstance(changed.get("value"), str)
        ),
        fields_by_id["registration_status"].get("value"),
    )
    registration_status = proposed_registration if isinstance(proposed_registration, str) else None
    for changed in changed_fields:
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
        if isinstance(changed_value, str):
            validation_error = application_field_validation_error(
                field_id,
                changed_value,
                registration_status=registration_status,
            )
            if validation_error is not None:
                raise ApplicationDraftValidationError(f"{field_id} {validation_error}")
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
