"""Instructor command line for drafting, reviewing, and sending the weekly newsletter."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from collections.abc import Mapping, Sequence
from datetime import date
from pathlib import Path
from typing import TextIO

from dotenv import load_dotenv

from course_server.config import AgentSettings, ConfigurationError, MailSettings
from course_server.mail.adapters import create_mail_adapter
from course_server.postgres.auth_store import PostgresAuthStore, create_auth_pool
from course_server.student_projects import GitHubStudentProjectCatalog
from course_server.web_search import fetch_public_webpage

from .collect import WeeklyEvidenceCollector, find_week_page, week_page_is_fragment
from .compose import NewsletterCompositionError, OpenAINewsletterWriter
from .images import PlaywrightImageFinder, read_rendered_week_post
from .models import NewsletterIssue, NewsletterSettings
from .pdf import export_pdf
from .render import render_html, render_text
from .schedule import NewsletterScheduleError, load_schedule
from .score import RUBRIC
from .service import NewsletterService, NewsletterStateError
from .store import FileNewsletterStore, NewsletterStoreError

MODULE = "course_server.newsletter"
# Writers created for this command, so token usage can be reported after a draft.
_WRITERS: list[OpenAINewsletterWriter] = []


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=f"python -m {MODULE}",
        description="Draft the weekly class newsletter from student repositories, then send it.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    draft = commands.add_parser("draft", help="collect last week's builds and write a draft")
    draft.add_argument("--week", type=int, help="schedule week number (default: last finished)")
    draft.add_argument(
        "--as-of",
        type=date.fromisoformat,
        help="pretend today is this date (YYYY-MM-DD) when choosing the week",
    )
    draft.add_argument("--force", action="store_true", help="redraft a week already sent")
    draft.add_argument("--quiet", action="store_true", help="do not print the draft body")

    rewrite = commands.add_parser(
        "rewrite", help="rewrite a draft's copy while keeping its highlights and images"
    )
    rewrite.add_argument("issue_id")
    rewrite.add_argument(
        "--quiet", dest="quiet_rewrite", action="store_true", help="do not print the body"
    )

    show = commands.add_parser("show", help="print a stored issue")
    show.add_argument("issue_id")
    show.add_argument("--html", action="store_true", help="print the HTML rendering")

    commands.add_parser("list", help="list stored issues and their status")

    pdf = commands.add_parser("pdf", help="export a stored issue as a single-page PDF")
    pdf.add_argument("issue_id")

    send = commands.add_parser("send", help="email an approved draft")
    send.add_argument("issue_id")
    send.add_argument("--to", help="comma-separated recipients (adds to NEWSLETTER_RECIPIENTS)")
    send.add_argument(
        "--to-active-students",
        action="store_true",
        help="also send to every active student account in the database",
    )
    send.add_argument(
        "--test-to",
        help="comma-separated addresses for a test copy; the issue stays a draft",
    )
    send.add_argument("--yes", action="store_true", help="skip the interactive confirmation")
    return parser


def _split(value: str | None) -> tuple[str, ...]:
    return tuple(item.strip() for item in (value or "").split(",") if item.strip())


def _browser(values: Mapping[str, str]) -> Path | None:
    """The deployment's Chromium when it exists locally; otherwise Playwright's bundled one."""

    raw = values.get("BROWSER_EXECUTABLE_PATH", "").strip()
    candidate = Path(raw).expanduser() if raw else None
    return candidate if candidate is not None and candidate.is_file() else None


def _store(values: Mapping[str, str]) -> tuple[NewsletterSettings, FileNewsletterStore]:
    settings = NewsletterSettings.from_environment(values)
    return settings, FileNewsletterStore(settings.data_path, logo_path=settings.logo_path)


def _drafting_service(values: Mapping[str, str], *, log: TextIO) -> NewsletterService:
    settings, store = _store(values)
    agent_settings = AgentSettings.from_environment(values)
    if not agent_settings.github_student_projects_enabled or agent_settings.github_token is None:
        raise ConfigurationError(
            "GITHUB_STUDENT_PROJECTS_ENABLED=true and a read-only GITHUB_TOKEN are required"
        )
    catalog = GitHubStudentProjectCatalog(
        agent_settings.github_token.get_secret_value(),
        organization=agent_settings.github_organization,
        repository_prefix=agent_settings.github_repository_prefix,
        excluded_repositories=agent_settings.github_excluded_repositories,
        roster_cache_ttl_seconds=agent_settings.github_roster_cache_ttl_seconds,
    )
    configured = agent_settings.browser_executable_path
    executable = configured if configured is not None and configured.is_file() else None
    collector = WeeklyEvidenceCollector(
        catalog,
        repository_prefix=agent_settings.github_repository_prefix,
        read_site=fetch_public_webpage,
        find_week_page=find_week_page,
        render_week_page=lambda site_url, week: read_rendered_week_post(
            site_url, week, executable_path=executable
        ),
        is_fragment=week_page_is_fragment,
        log=lambda message: print(message, file=log),
    )
    writer = OpenAINewsletterWriter(
        model_id=agent_settings.model_id,
        api_key=agent_settings.model_api_key,
    )
    _WRITERS.append(writer)
    image_finder = PlaywrightImageFinder(
        judge=writer.judge_images,
        executable_path=executable,
        log=lambda message: print(message, file=log),
    )
    return NewsletterService(
        settings=settings,
        weeks=load_schedule(settings.schedule_path, timezone=settings.timezone),
        collector=collector,
        writer=writer,
        image_finder=image_finder,
        store=store,
        model_id=agent_settings.model_id,
        log=lambda message: print(message, file=log),
    )


def _sending_service(values: Mapping[str, str], *, log: TextIO) -> NewsletterService:
    settings, store = _store(values)
    return NewsletterService(
        settings=settings,
        weeks=load_schedule(settings.schedule_path, timezone=settings.timezone),
        store=store,
        log=lambda message: print(message, file=log),
    )


async def _active_student_addresses(database_url: str) -> tuple[str, ...]:
    pool = create_auth_pool(database_url)
    await pool.open()
    try:
        users = await PostgresAuthStore(pool).list_users()
    finally:
        await pool.close()
    return tuple(str(user.email) for user in users if user.active and user.role == "student")


def _print_issue(issue: NewsletterIssue, store: FileNewsletterStore, *, out: TextIO) -> None:
    json_path, text_path, html_path = store.paths_for(issue.issue_id)
    print(f"Issue: {issue.issue_id} ({issue.status})", file=out)
    print(f"Subject: {issue.subject}", file=out)
    print(f"Files: {json_path}\n       {text_path}\n       {html_path}", file=out)
    print("", file=out)


_COLUMN = {"originality": "ORIG", "goal_fit": "FIT", "augmentation": "AUG", "execution": "EXEC"}


def _print_scores(issue: NewsletterIssue, *, out: TextIO) -> None:
    if not issue.scores:
        return
    featured = set(issue.highlighted_project_ids())
    weights = " · ".join(
        f"{criterion.name.lower()} {round(criterion.weight * 100)}%" for criterion in RUBRIC
    )
    print(f"Scoreboard ({weights}):", file=out)
    print("  TOTAL  " + "".join(f"{_COLUMN[c.key]:>5}" for c in RUBRIC) + "  PROJECT", file=out)
    for score in issue.scores:
        marker = "*" if score.project_id in featured else " "
        flag = "  (blank: left off the list)" if score.blank else ""
        flag += "" if score.eligible else "  (featured recently)"
        cells = "".join(
            f"{value if isinstance(value, int) else '-':>5}"
            for value in (getattr(score, criterion.key) for criterion in RUBRIC)
        )
        print(f"{marker} {score.total:5.2f}  {cells}  {score.project_id}{flag}", file=out)
        if score.built:
            print(f"           built: {score.built}", file=out)
        if score.rationale:
            print(f"           {score.rationale}", file=out)
    print("", file=out)


def _confirm(prompt: str, *, stdin: TextIO) -> bool:
    if not stdin.isatty():
        return False
    print(prompt, end="", flush=True)
    return stdin.readline().strip() == "SEND"


async def _send(
    arguments: argparse.Namespace,
    values: Mapping[str, str],
    *,
    out: TextIO,
    err: TextIO,
    stdin: TextIO,
) -> int:
    service = _sending_service(values, log=err)
    settings, store = _store(values)
    issue = service.load(arguments.issue_id)
    test_only = bool(arguments.test_to)
    if test_only:
        recipients: list[str] = list(_split(arguments.test_to))
    else:
        recipients = [*settings.recipients, *_split(arguments.to)]
        if arguments.to_active_students:
            database_url = values.get("DATABASE_URL", "").strip()
            if not database_url:
                raise ConfigurationError("DATABASE_URL is required for --to-active-students")
            recipients.extend(await _active_student_addresses(database_url))
    if not recipients:
        print(
            "No recipients. Use --to, --to-active-students, --test-to, or NEWSLETTER_RECIPIENTS.",
            file=err,
        )
        return 2
    mail_settings = MailSettings.optional_from_environment(values)
    if mail_settings is None:
        raise ConfigurationError("MAIL_ENABLED=true with mailbox credentials is required to send")

    _print_issue(issue, store, out=out)
    print(render_text(issue), file=out)
    unique = sorted({address.strip().casefold() for address in recipients})
    kind = "TEST copy" if test_only else "newsletter"
    print(f"About to send the {kind} to {len(unique)} recipient(s):", file=out)
    for address in unique:
        print(f"  {address}", file=out)
    if not arguments.yes and not _confirm(
        'Type "SEND" to deliver, anything else to abort: ', stdin=stdin
    ):
        print("Aborted; nothing was sent.", file=err)
        return 1

    adapter = create_mail_adapter(mail_settings)
    try:
        result = await service.send(
            issue.issue_id,
            mail=adapter,
            recipients=recipients,
            test_only=test_only,
        )
    finally:
        await adapter.close()
    sent = [delivery for delivery in result.deliveries if delivery.error is None]
    failed = [delivery for delivery in result.deliveries if delivery.error is not None]
    print(f"Delivered {len(sent)} message(s); {len(failed)} failed.", file=out)
    for delivery in failed:
        print(f"  {delivery.recipient}: {delivery.error}", file=err)
    if not test_only:
        print(f"Issue {result.issue_id} is now marked {result.status}.", file=out)
    return 0 if not failed else 1


def _run(
    arguments: argparse.Namespace,
    values: Mapping[str, str],
    *,
    out: TextIO,
    err: TextIO,
    stdin: TextIO,
) -> int:
    if arguments.command == "draft":
        service = _drafting_service(values, log=err)
        _, store = _store(values)
        issue = service.draft(
            week_number=arguments.week, as_of=arguments.as_of, force=arguments.force
        )
        _print_issue(issue, store, out=out)
        try:
            print(
                f"PDF:   {export_pdf(store, issue.issue_id, executable_path=_browser(values))}",
                file=out,
            )
        except NewsletterStoreError as error:
            print(f"PDF export skipped: {error}", file=err)
        print("", file=out)
        _print_scores(issue, out=out)
        for writer in _WRITERS:
            usage = writer.usage
            print(
                f"Model usage ({writer.model_id}): {usage.requests} requests, "
                f"{usage.input_tokens:,} input tokens, {usage.output_tokens:,} output tokens.\n",
                file=out,
            )
        if not arguments.quiet:
            print(render_text(issue), file=out)
        print(
            "Review the draft above; open the .html file in a browser to see the designed "
            "version with images. To send it:\n"
            f"  python -m {MODULE} send {issue.issue_id} --to you@example.edu\n"
            f"  python -m {MODULE} send {issue.issue_id} --to-active-students\n"
            f"To try a test copy first:  python -m {MODULE} send {issue.issue_id} "
            "--test-to you@example.edu\n"
            f"To regenerate:  python -m {MODULE} draft --week {issue.week.number}",
            file=out,
        )
        return 0
    if arguments.command == "rewrite":
        service = _drafting_service(values, log=err)
        _, store = _store(values)
        issue = service.rewrite_copy(arguments.issue_id)
        _print_issue(issue, store, out=out)
        try:
            print(
                f"PDF:   {export_pdf(store, issue.issue_id, executable_path=_browser(values))}",
                file=out,
            )
        except NewsletterStoreError as error:
            print(f"PDF export skipped: {error}", file=err)
        for writer in _WRITERS:
            usage = writer.usage
            print(
                f"Model usage ({writer.model_id}): {usage.requests} requests, "
                f"{usage.input_tokens:,} input tokens, {usage.output_tokens:,} output tokens.\n",
                file=out,
            )
        if not arguments.quiet_rewrite:
            print(render_text(issue), file=out)
        return 0
    if arguments.command == "show":
        _, store = _store(values)
        stored = store.load(arguments.issue_id)
        if stored is None:
            print(f"Issue {arguments.issue_id} does not exist.", file=err)
            return 2
        _print_issue(stored, store, out=out)
        if not arguments.html:
            _print_scores(stored, out=out)
        print(render_html(stored) if arguments.html else render_text(stored), file=out)
        return 0
    if arguments.command == "pdf":
        _, store = _store(values)
        if store.load(arguments.issue_id) is None:
            print(f"Issue {arguments.issue_id} does not exist.", file=err)
            return 2
        print(export_pdf(store, arguments.issue_id, executable_path=_browser(values)), file=out)
        return 0
    if arguments.command == "list":
        _, store = _store(values)
        issues = store.list_issues()
        if not issues:
            print("No issues yet.", file=out)
            return 0
        print("ISSUE\tWEEK\tSTATUS\tCREATED\tSENT\tHIGHLIGHTS", file=out)
        for issue in issues:
            print(
                f"{issue.issue_id}\t{issue.week.number}\t{issue.status}\t"
                f"{issue.created_at.date().isoformat()}\t"
                f"{issue.sent_at.date().isoformat() if issue.sent_at else '-'}\t"
                f"{', '.join(issue.highlighted_project_ids())}",
                file=out,
            )
        return 0
    return asyncio.run(_send(arguments, values, out=out, err=err, stdin=stdin))


def main(
    argv: Sequence[str] | None = None,
    *,
    environment: Mapping[str, str] | None = None,
    out: TextIO | None = None,
    err: TextIO | None = None,
    stdin: TextIO | None = None,
) -> int:
    arguments = _parser().parse_args(argv)
    if environment is None:
        load_dotenv(override=False)
        environment = dict(os.environ)
    out = out or sys.stdout
    err = err or sys.stderr
    stdin = stdin or sys.stdin
    try:
        return _run(arguments, environment, out=out, err=err, stdin=stdin)
    except (
        ConfigurationError,
        NewsletterCompositionError,
        NewsletterScheduleError,
        NewsletterStateError,
        NewsletterStoreError,
    ) as error:
        print(f"Error: {error}", file=err)
        return 2
