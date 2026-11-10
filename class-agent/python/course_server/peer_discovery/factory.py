"""Deployment-owned wiring; no credentials or alternate identity reach the model."""

from functools import partial

from course_server.config import AgentSettings
from course_server.course_roster import CourseRoster
from course_server.student_projects import GitHubStudentProjectCatalog
from course_server.web_search import fetch_public_webpage

from .service import PeerDiscovery
from .store import PeerStore


def build_peer_discovery(
    settings: AgentSettings, roster: CourseRoster | None
) -> PeerDiscovery | None:
    if not settings.github_student_projects_enabled or settings.github_token is None:
        return None
    aliases = roster.active_student_project_aliases.copy() if roster is not None else {}
    aliases.update(dict(settings.github_student_project_aliases))
    catalog = GitHubStudentProjectCatalog(
        settings.github_token.get_secret_value(),
        organization=settings.github_organization,
        repository_prefix=settings.github_repository_prefix,
        excluded_repositories=settings.github_excluded_repositories,
        allowed_repositories=roster.active_weekly_project_ids if roster is not None else None,
        roster_cache_ttl_seconds=settings.github_roster_cache_ttl_seconds,
    )
    return PeerDiscovery(
        PeerStore(settings.peer_discovery_path),
        catalog,
        partial(fetch_public_webpage, peer_preview=True),
        aliases,
        settings.github_repository_prefix,
    )
