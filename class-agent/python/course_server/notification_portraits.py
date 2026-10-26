"""Deployment-owned student portrait assignments for staff notifications."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError


class _PortraitAssignment(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    user_id: UUID
    asset_id: str = Field(
        min_length=1,
        max_length=200,
        pattern=r"^[a-z0-9][a-z0-9_-]*$",
    )


class _PortraitRegistryDocument(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1]
    portraits: tuple[_PortraitAssignment, ...]


class StudentNotificationPortraitRegistry:
    """Resolve explicit user IDs to registered course portrait asset IDs."""

    def __init__(self, assignments: dict[UUID, str] | None = None) -> None:
        self._assignments = assignments or {}

    @classmethod
    def from_path(cls, path: Path) -> StudentNotificationPortraitRegistry:
        if not path.exists():
            return cls()
        try:
            document = _PortraitRegistryDocument.model_validate_json(
                path.read_text(encoding="utf-8")
            )
        except (OSError, UnicodeError, json.JSONDecodeError, ValidationError) as error:
            raise ValueError("Invalid student notification portrait registry.") from error

        assignments: dict[UUID, str] = {}
        for portrait in document.portraits:
            if portrait.user_id in assignments:
                raise ValueError(
                    "Student notification portrait registry contains duplicate user IDs."
                )
            assignments[portrait.user_id] = portrait.asset_id
        return cls(assignments)

    def asset_id_for(self, user_id: UUID) -> str | None:
        return self._assignments.get(user_id)
