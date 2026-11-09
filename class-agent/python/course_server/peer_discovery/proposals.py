"""Reviewed public proposal metadata, keyed by an indexed portfolio page."""

import json
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel

from .models import Build
from .pair_reason import terms


class Proposal(BaseModel):
    title: str
    members: dict[str, str]
    pages: list[str]
    source: str
    summary: str
    offers: dict[str, str]
    applications: dict[str, str]


@lru_cache(maxsize=1)
def _directory() -> dict[str, Proposal]:
    path = Path(__file__).with_name("proposal_groups.json")
    groups = [Proposal.model_validate(row) for row in json.loads(path.read_text())]
    return {url: group for group in groups for url in group.pages}


def proposal_for(build: Build) -> Proposal | None:
    group = _directory().get(build.source_url)
    return group if group and build.week == 7 and build.project_id in group.members else None


def belongs_to(build: Build, student_project: str) -> bool:
    if build.project_id == student_project:
        return True
    group = proposal_for(build)
    return bool(group and student_project in group.members)


def transfer(mine: Proposal, peer: Proposal, focus: set[str]) -> tuple[float, str] | None:
    options = []
    for theme, application in mine.applications.items():
        if theme in peer.offers:
            reason = f"{peer.offers[theme]} {application}"
            options.append((len(terms(reason) & focus), reason))
    if not options:
        return None
    relevance, reason = max(options)
    return 10.0 + relevance, reason
