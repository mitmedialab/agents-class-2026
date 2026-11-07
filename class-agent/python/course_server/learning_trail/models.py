"""Validated learning-trail records. Pure data: no I/O, identity, or transport."""

from __future__ import annotations

from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

MAX_ENTRIES_PER_STUDENT = 64
MAX_FEEDBACK_PER_ENTRY = 16
MAX_WEEK = 20

FeedbackRole = Literal["instructor", "ta"]
FeedbackSource = Literal["pasted_by_student", "staff"]


def _require_https(value: str) -> str:
    # The panel renders this as a link, so only a plain https URL is an acceptable value.
    if not value.startswith("https://") or any(character.isspace() for character in value):
        raise ValueError("build_url must be an https URL")
    return value


Week = Annotated[int, Field(ge=1, le=MAX_WEEK)]
BuildTitle = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
BuildUrl = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=2_048),
    AfterValidator(_require_https),
]
Reflection = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20_000)
]
FeedbackBody = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=10_000)
]
PersonName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


class TrailModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class TrailFeedback(TrailModel):
    """Staff feedback attached to an entry.

    `source` records provenance for the agent and the reader. `staff` means a logged-in TA or
    instructor wrote it here. `pasted_by_student` means the student copied it from an email, so
    the platform has not verified that staff wrote it.
    """

    id: UUID
    from_role: FeedbackRole
    from_name: PersonName | None = None
    body: FeedbackBody
    received_at: AwareDatetime | None = None
    source: FeedbackSource
    added_at: AwareDatetime


class TrailEntry(TrailModel):
    """One reflection on one weekly build."""

    id: UUID
    week: Week
    build_title: BuildTitle
    build_url: BuildUrl | None = None
    reflection: Reflection
    still_relevant: bool = True
    shared_with_staff: bool = False
    feedback: list[TrailFeedback] = Field(default_factory=list, max_length=MAX_FEEDBACK_PER_ENTRY)
    created_at: AwareDatetime
    updated_at: AwareDatetime


class TrailEntryDraft(TrailModel):
    week: Week
    build_title: BuildTitle
    build_url: BuildUrl | None = None
    reflection: Reflection
    shared_with_staff: bool = False


class TrailEntryPatch(TrailModel):
    """Only fields the client actually sent are applied; see `model_fields_set`."""

    week: Week | None = None
    build_title: BuildTitle | None = None
    build_url: BuildUrl | None = None
    reflection: Reflection | None = None
    still_relevant: bool | None = None
    shared_with_staff: bool | None = None

    @model_validator(mode="after")
    def validate_patch(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("a patch must change at least one field")
        # Only build_url can be cleared; every other field always has a value.
        for name in self.model_fields_set - {"build_url"}:
            if getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        return self


class TrailFeedbackDraft(TrailModel):
    from_role: FeedbackRole
    from_name: PersonName | None = None
    body: FeedbackBody
    received_at: AwareDatetime | None = None


class StaffFeedbackDraft(TrailModel):
    """The author and role come from the staff member's session, never from the request."""

    body: FeedbackBody


class SharedTrailSummary(TrailModel):
    """What staff see in the list of students who have shared at least one entry."""

    student_id: UUID
    student_name: str
    shared_entries: int
    latest_week: int


class TrailDocument(TrailModel):
    """The durable per-student file. `user_id` is checked against the owner on every read."""

    schema_version: Literal[1] = 1
    user_id: UUID
    entries: list[TrailEntry] = Field(default_factory=list, max_length=MAX_ENTRIES_PER_STUDENT)
