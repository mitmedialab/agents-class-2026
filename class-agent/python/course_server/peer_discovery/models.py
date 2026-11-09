"""Additive application models; stable agent/workspace contracts remain unchanged."""

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


def now() -> str:
    return datetime.now(UTC).isoformat()


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LearningProfile(StrictModel):
    long_term_focus: str = Field(default="", max_length=1200)
    goal: str = Field(default="", max_length=1200)
    challenges: list[str] = Field(default_factory=list, max_length=10)
    interests: list[str] = Field(default_factory=list, max_length=10)


class ProfileUpdate(LearningProfile):
    confirmed: Literal[True]


class Build(StrictModel):
    id: str
    project_id: str
    week: int | None = None
    title: str
    source_url: str
    content: str
    reviewed_title: str | None = None
    image_url: str | None = None
    source_hash: str
    observed_at: str
    truncated: bool = False


class ReviewedMessage(StrictModel):
    build_id: str = Field(min_length=1, max_length=100)
    request_id: UUID
    body: str = Field(min_length=1, max_length=10_000)
    confirmed: Literal[True]


class Feedback(StrictModel):
    build_id: str = Field(min_length=1, max_length=100)
    rating: Literal["helpful", "not_relevant", "already_seen", "saved", "unsaved", "opened"]
    note: str = Field(default="", max_length=1200)


class Recommendation(StrictModel):
    build_id: str = Field(min_length=1, max_length=100)
    reason: str = Field(min_length=10, max_length=1500)
    borrow: str = Field(min_length=10, max_length=1500)
    evidence_quote: str = Field(min_length=12, max_length=800)


class SavedRecommendation(Recommendation):
    profile: LearningProfile
    created_at: str = Field(default_factory=now)


class StudentMemory(StrictModel):
    schema_version: Literal[1] = 1
    profile: LearningProfile = Field(default_factory=LearningProfile)
    profile_origin: str = "Not provided"
    updated_at: str | None = None
    recommendations: list[SavedRecommendation] = Field(default_factory=list)
    feedback: list[Feedback] = Field(default_factory=list)


class Catalog(StrictModel):
    sites: dict[str, str] = Field(default_factory=dict)
    schema_version: Literal[1] = 1
    builds: list[Build] = Field(default_factory=list)
    coverage: dict[str, dict[str, str]] = Field(default_factory=dict)
