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
FeedbackSource = Literal["pasted_by_student"]


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

    `source` records provenance for the agent and the reader: the text was pasted by the
    student from an email, so the platform has not verified that staff wrote it.
    """

    id: UUID
    from_role: FeedbackRole
    from_name: PersonName | None = None
    body: FeedbackBody
    received_at: AwareDatetime | None = None
    source: FeedbackSource = "pasted_by_student"
    added_at: AwareDatetime


class TrailEntry(TrailModel):
    """One reflection on one weekly build."""

    id: UUID
    week: Week
    build_title: BuildTitle
    build_url: BuildUrl | None = None
    reflection: Reflection
    still_relevant: bool = True
    feedback: list[TrailFeedback] = Field(default_factory=list, max_length=MAX_FEEDBACK_PER_ENTRY)
    created_at: AwareDatetime
    updated_at: AwareDatetime


class TrailEntryDraft(TrailModel):
    week: Week
    build_title: BuildTitle
    build_url: BuildUrl | None = None
    reflection: Reflection


class TrailEntryPatch(TrailModel):
    """Only fields the client actually sent are applied; see `model_fields_set`."""

    week: Week | None = None
    build_title: BuildTitle | None = None
    build_url: BuildUrl | None = None
    reflection: Reflection | None = None
    still_relevant: bool | None = None

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


class TrailDocument(TrailModel):
    """The durable per-student file. `user_id` is checked against the owner on every read."""

    schema_version: Literal[1] = 1
    user_id: UUID
    entries: list[TrailEntry] = Field(default_factory=list, max_length=MAX_ENTRIES_PER_STUDENT)
