"""Canonical course-application fields and validated submission model."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    TypeAdapter,
    ValidationInfo,
    field_validator,
)

School = Literal["MIT Media Lab", "MIT", "Harvard", "Wellesley", "Other"]
RegistrationStatus = Literal["for credit", "listener"]
ListenerBuildCommitment = Literal["yes", "no", "not applicable"]

SCHOOL_OPTIONS: tuple[School, ...] = (
    "MIT Media Lab",
    "MIT",
    "Harvard",
    "Wellesley",
    "Other",
)
REGISTRATION_STATUS_OPTIONS: tuple[RegistrationStatus, ...] = (
    "for credit",
    "listener",
)
LISTENER_BUILD_OPTIONS: tuple[ListenerBuildCommitment, ...] = (
    "yes",
    "no",
    "not applicable",
)

_GITHUB_ID = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9]|-(?=[A-Za-z0-9])){0,38}\Z")
_DEGREE_START_YEAR = re.compile(r"\d{4}\Z")
_EMAIL = TypeAdapter(EmailStr)

_FIELD_LENGTH_BOUNDS: dict[str, tuple[int, int]] = {
    "name": (2, 200),
    "github_id": (1, 39),
    "department": (1, 1_000),
    "research_group": (1, 1_000),
    "degree": (1, 500),
    "personal_webpage": (1, 2_000),
    "interests": (1, 4_000),
    "why_take_this_class": (1, 4_000),
    "knowledgeable_about": (1, 4_000),
    "skill_set": (1, 4_000),
    "questions_or_comments_for_instructors": (1, 4_000),
}

_FIELD_OPTIONS: dict[str, tuple[str, ...]] = {
    "school": SCHOOL_OPTIONS,
    "registration_status": REGISTRATION_STATUS_OPTIONS,
    "listener_willing_to_do_weekly_builds": LISTENER_BUILD_OPTIONS,
}


@dataclass(frozen=True)
class ApplicationFieldSpec:
    """One canonical field displayed in the application draft."""

    id: str
    label: str
    options: tuple[str, ...] = ()


APPLICATION_FIELD_SPECS: tuple[ApplicationFieldSpec, ...] = (
    ApplicationFieldSpec("name", "Name"),
    ApplicationFieldSpec("email", "Email"),
    ApplicationFieldSpec(
        "github_id",
        "GitHub ID (username only; create an account first if needed)",
    ),
    ApplicationFieldSpec("school", "School", SCHOOL_OPTIONS),
    ApplicationFieldSpec("department", "Department"),
    ApplicationFieldSpec(
        "research_group",
        "Research group (if applicable; otherwise enter Not applicable)",
    ),
    ApplicationFieldSpec("degree", "Degree"),
    ApplicationFieldSpec("degree_start_year", "Year degree started (YYYY)"),
    ApplicationFieldSpec("personal_webpage", "Personal Webpage"),
    ApplicationFieldSpec("interests", "Interests"),
    ApplicationFieldSpec(
        "why_take_this_class",
        "Motivation: why this course; what you have built and want to build; "
        "your past project roles",
    ),
    ApplicationFieldSpec("knowledgeable_about", "Knowledgeable about"),
    ApplicationFieldSpec("skill_set", "Skill-set (practical knowledge and builder experience)"),
    ApplicationFieldSpec(
        "registration_status",
        "Registration",
        REGISTRATION_STATUS_OPTIONS,
    ),
    ApplicationFieldSpec(
        "listener_willing_to_do_weekly_builds",
        "For listeners: willing to do weekly builds",
        LISTENER_BUILD_OPTIONS,
    ),
    ApplicationFieldSpec("questions_or_comments_for_instructors", "Questions or comments"),
    ApplicationFieldSpec(
        "photo_upload_id",
        "Class-only picture that represents you (JPG/JPEG, PNG, or WebP)",
    ),
)


def application_field_validation_error(
    field_id: str,
    value: str,
    *,
    registration_status: str | None = None,
) -> str | None:
    """Validate one populated draft value against its final field contract."""

    stripped = value.strip()
    if not stripped:
        return None
    bounds = _FIELD_LENGTH_BOUNDS.get(field_id)
    if bounds is not None:
        minimum, maximum = bounds
        if len(stripped) < minimum:
            return f"must contain at least {minimum} characters"
        if len(stripped) > maximum:
            return f"must contain at most {maximum} characters"
    if field_id in {
        "name",
        "department",
        "research_group",
        "degree",
        "personal_webpage",
        "interests",
        "why_take_this_class",
        "knowledgeable_about",
        "skill_set",
        "questions_or_comments_for_instructors",
    } and stripped.casefold() in {"-", "tbd", "unknown"}:
        return "placeholder answers are not accepted"
    if field_id == "email":
        try:
            _EMAIL.validate_python(stripped)
        except ValueError:
            return "must be a valid email address"
    if field_id == "github_id":
        if stripped.casefold() in {"none", "n/a", "not applicable", "tbd", "unknown"}:
            return "requires a GitHub account; create one before submitting"
        if not _GITHUB_ID.fullmatch(stripped):
            return (
                "must be a GitHub username with 1-39 letters, numbers, or single hyphens; "
                "no @, URL, leading or trailing hyphen, or consecutive hyphens"
            )
    if field_id == "degree_start_year" and not _DEGREE_START_YEAR.fullmatch(stripped):
        return "must be the four-digit year when the applicant started the degree"
    options = _FIELD_OPTIONS.get(field_id)
    if options is not None and stripped not in options:
        return "must be one of: " + ", ".join(options)
    if field_id == "listener_willing_to_do_weekly_builds":
        if registration_status == "listener" and stripped not in {"yes", "no"}:
            return "must be 'yes' or 'no' when registration is 'listener'"
        if registration_status == "for credit" and stripped != "not applicable":
            return "must be 'not applicable' when registration is 'for credit'"
    if field_id == "photo_upload_id":
        try:
            UUID(stripped)
        except ValueError:
            return "must be a valid upload UUID"
    return None


class CourseApplication(BaseModel):
    """Complete structured application accepted by the submission boundary."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
        validate_default=True,
    )

    name: str = Field(min_length=2, max_length=200)
    email: EmailStr
    github_id: str = Field(min_length=1, max_length=39)
    school: School
    department: str = Field(min_length=1, max_length=1_000)
    research_group: str = Field(min_length=1, max_length=1_000)
    degree: str = Field(min_length=1, max_length=500)
    degree_start_year: str = Field(pattern=r"^\d{4}$")
    personal_webpage: str = Field(min_length=1, max_length=2_000)
    interests: str = Field(min_length=1, max_length=4_000)
    why_take_this_class: str = Field(min_length=1, max_length=4_000)
    knowledgeable_about: str = Field(min_length=1, max_length=4_000)
    skill_set: str = Field(min_length=1, max_length=4_000)
    registration_status: RegistrationStatus
    listener_willing_to_do_weekly_builds: ListenerBuildCommitment
    questions_or_comments_for_instructors: str = Field(min_length=1, max_length=4_000)
    photo_upload_id: UUID

    @field_validator(
        "name",
        "department",
        "research_group",
        "degree",
        "personal_webpage",
        "interests",
        "why_take_this_class",
        "knowledgeable_about",
        "skill_set",
        "questions_or_comments_for_instructors",
    )
    @classmethod
    def reject_placeholders(cls, value: str) -> str:
        if value.strip().casefold() in {"-", "tbd", "unknown"}:
            raise ValueError("placeholder answers are not accepted")
        return value

    @field_validator("github_id")
    @classmethod
    def validate_github_id(cls, value: str) -> str:
        if value.casefold() in {"none", "n/a", "not applicable", "tbd", "unknown"}:
            raise ValueError("a GitHub account is required; create one before submitting")
        if not _GITHUB_ID.fullmatch(value):
            raise ValueError(
                "must be a GitHub username (1-39 letters, numbers, or single hyphens; "
                "no @, URL, leading or trailing hyphen, or consecutive hyphens)"
            )
        return value

    @field_validator("degree_start_year")
    @classmethod
    def validate_degree_start_year(cls, value: str) -> str:
        if not _DEGREE_START_YEAR.fullmatch(value):
            raise ValueError("must be the four-digit year when the applicant started the degree")
        return value

    @field_validator("listener_willing_to_do_weekly_builds")
    @classmethod
    def validate_listener_commitment(
        cls,
        value: ListenerBuildCommitment,
        info: ValidationInfo,
    ) -> ListenerBuildCommitment:
        registration_status = info.data.get("registration_status")
        if registration_status == "listener" and value not in {"yes", "no"}:
            raise ValueError("must be 'yes' or 'no' when registration_status is 'listener'")
        if registration_status == "for credit" and value != "not applicable":
            raise ValueError("must be 'not applicable' when registration_status is 'for credit'")
        return value
