"""Build the newsletter pipeline from validated settings, for the API, worker, and CLI."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from course_server.auth.store import AuthStore
from course_server.config import AgentSettings, ConfigurationError
from course_server.student_projects import GitHubStudentProjectCatalog
from course_server.web_search import fetch_public_webpage

from .collect import WeeklyEvidenceCollector, find_week_page, week_page_is_fragment
from .compose import OpenAINewsletterWriter
from .images import PlaywrightImageFinder
from .jobs import NewsletterJobRunner
from .models import CourseWeek, NewsletterSettings
from .pdf import export_pdf
from .schedule import load_schedule
from .service import NewsletterService
from .store import FileNewsletterStore
from .tools import NewsletterTools


def browser_executable(agent_settings: AgentSettings) -> Path | None:
    """The deployment's Chromium when it exists here; otherwise Playwright's bundled one."""

    candidate = agent_settings.browser_executable_path
    return candidate if candidate is not None and candidate.is_file() else None


def newsletter_weeks(settings: NewsletterSettings) -> tuple[CourseWeek, ...]:
    return load_schedule(settings.schedule_path, timezone=settings.timezone)


def drafting_service_factory(
    agent_settings: AgentSettings,
    settings: NewsletterSettings,
    *,
    store: FileNewsletterStore,
    weeks: tuple[CourseWeek, ...],
) -> Callable[[Callable[[str], None]], NewsletterService]:
    """A factory so each background job gets its own log sink and fresh adapters."""

    if not agent_settings.github_student_projects_enabled or agent_settings.github_token is None:
        raise ConfigurationError(
            "GITHUB_STUDENT_PROJECTS_ENABLED=true and a read-only GITHUB_TOKEN are required"
        )
    token = agent_settings.github_token.get_secret_value()
    executable = browser_executable(agent_settings)

    def build(log: Callable[[str], None]) -> NewsletterService:
        catalog = GitHubStudentProjectCatalog(
            token,
            organization=agent_settings.github_organization,
            repository_prefix=agent_settings.github_repository_prefix,
            excluded_repositories=agent_settings.github_excluded_repositories,
            roster_cache_ttl_seconds=agent_settings.github_roster_cache_ttl_seconds,
        )
        writer = OpenAINewsletterWriter(
            model_id=agent_settings.model_id, api_key=agent_settings.model_api_key
        )
        return NewsletterService(
            settings=settings,
            weeks=weeks,
            store=store,
            collector=WeeklyEvidenceCollector(
                catalog,
                repository_prefix=agent_settings.github_repository_prefix,
                read_site=fetch_public_webpage,
                find_week_page=find_week_page,
                is_fragment=week_page_is_fragment,
                log=log,
            ),
            writer=writer,
            image_finder=PlaywrightImageFinder(
                judge=writer.judge_images, executable_path=executable, log=log
            ),
            model_id=agent_settings.model_id,
            log=log,
        )

    return build


def build_newsletter_tools(
    agent_settings: AgentSettings,
    settings: NewsletterSettings,
    *,
    auth: AuthStore,
) -> NewsletterTools:
    """Everything the Course Agent's newsletter tools need, built once per process."""

    store = FileNewsletterStore(settings.data_path, logo_path=settings.logo_path)
    weeks = newsletter_weeks(settings)
    factory = drafting_service_factory(agent_settings, settings, store=store, weeks=weeks)
    executable = browser_executable(agent_settings)
    runner = NewsletterJobRunner(
        store=store,
        service_factory=factory,
        pdf_exporter=lambda issue_id: export_pdf(store, issue_id, executable_path=executable),
    )
    return NewsletterTools(
        settings=settings,
        store=store,
        service=NewsletterService(settings=settings, weeks=weeks, store=store),
        runner=runner,
        auth=auth,
    )
