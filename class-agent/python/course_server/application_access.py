"""Trusted, deployment-owned application sharing policy; never match submitted names."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID

from agent_core import PrincipalContext


class ApplicationAccessPolicy:
    """Instructors see all records; students see only explicitly shared immutable IDs."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path

    def scope(
        self, principal: PrincipalContext, *, accepted_only: bool = False
    ) -> frozenset[UUID] | None:
        if not principal.authenticated or not {"student", "instructor"}.intersection(
            principal.roles
        ):
            raise PermissionError("Instructor access or student access is required.")
        if "instructor" in principal.roles and not accepted_only:
            return None
        if self.path is None or not self.path.exists():
            return frozenset()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if (
                not isinstance(data, dict)
                or set(data) != {"schema_version", "application_ids"}
                or data["schema_version"] != 1
                or not isinstance(data["application_ids"], list)
                or any(not isinstance(value, str) for value in data["application_ids"])
            ):
                raise ValueError("invalid access registry")
            return frozenset(UUID(value) for value in data["application_ids"])
        except (OSError, UnicodeError, ValueError, TypeError) as error:
            raise PermissionError("Student application access is unavailable.") from error

    def require(
        self, principal: PrincipalContext, application_id: UUID, *, accepted_only: bool = False
    ) -> None:
        scope = self.scope(principal, accepted_only=accepted_only)
        if scope is not None and application_id not in scope:
            raise PermissionError("Application is not available to this account.")
