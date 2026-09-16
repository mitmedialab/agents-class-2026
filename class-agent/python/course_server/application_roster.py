"""Resolve the instructor-approved deployment roster once, before accepting requests."""

from __future__ import annotations

import json
import logging
import os
import tempfile
import unicodedata
from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from course_server.agent.capabilities import ApplicantStore

logger = logging.getLogger(__name__)


class AcceptedApplicant(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1)
    institution: str = Field(min_length=1)
    department: str = Field(min_length=1)
    aliases: list[str] = Field(default_factory=list)


class AcceptedRoster(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1]
    applicants: list[AcceptedApplicant] = Field(min_length=1)


def _name_key(name: str) -> str:
    # Case, whitespace and conventional name ordering do not change the roster identity.
    normalized = unicodedata.normalize("NFKC", name).casefold()
    return " ".join(sorted(normalized.replace("(", " ").replace(")", " ").split()))


def _write_once(path: Path, payload: object) -> None:
    """Publish a complete private snapshot without replacing an operator's existing file."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, temporary = tempfile.mkstemp(prefix=".roster-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        with suppress(FileExistsError):
            os.link(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


async def initialize_student_application_access(
    applicants: ApplicantStore,
    directory: Path,
    roster_path: Path | None = None,
) -> None:
    """Freeze unique matches from existing records; never extend access on later submissions."""
    access_path = directory / "student-access.json"
    if access_path.exists():
        return
    roster_path = roster_path or directory / "accepted-applicants.json"
    if not roster_path.exists():
        logger.info("No local accepted-applicant roster; student application access stays closed.")
        return
    roster = AcceptedRoster.model_validate_json(roster_path.read_text(encoding="utf-8"))
    keys: set[str] = set()
    for entry in roster.applicants:
        entry_keys = {_name_key(name) for name in [entry.name, *entry.aliases]}
        if "" in entry_keys or keys.intersection(entry_keys):
            raise ValueError("Accepted applicant roster contains conflicting names.")
        keys.update(entry_keys)

    summaries = await applicants.list_applications()
    approved: set[UUID] = set()
    resolutions: list[dict[str, object]] = []
    for entry in roster.applicants:
        entry_keys = {_name_key(name) for name in [entry.name, *entry.aliases]}
        matches = [item for item in summaries if _name_key(item.name) in entry_keys]
        status = "missing" if not matches else "ambiguous"
        if len(matches) == 1:
            candidate = matches[0]
            record = await applicants.read_application(candidate.application_id)
            fields = record.get("application")
            # v1 records may lack school. When supplied, require the institution to agree.
            school = fields.get("school") if isinstance(fields, dict) else None
            institution = "MIT" if school == "MIT Media Lab" else school
            if institution is not None and institution != entry.institution:
                status = "institution_mismatch"
            else:
                approved.add(candidate.application_id)
                status = "matched"
        resolutions.append(
            {
                "name": entry.name,
                "status": status,
                "application_ids": [str(item.application_id) for item in matches],
            }
        )

    # The report is private deployment state, not model-visible course content.
    _write_once(
        directory / "student-access-resolution.json",
        {
            "schema_version": 1,
            "applicants": resolutions,
        },
    )
    _write_once(
        access_path,
        {
            "schema_version": 1,
            "application_ids": sorted(str(value) for value in approved),
        },
    )
    logger.warning(
        "Accepted application access initialized: %d matched, %d unresolved; "
        "inspect private student-access-resolution.json for details.",
        len(approved),
        len(roster.applicants) - len(approved),
    )
