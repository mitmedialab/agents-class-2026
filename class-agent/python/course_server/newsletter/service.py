"""Instructor-run newsletter workflow: score, select, illustrate, draft, then send on approval."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, date, datetime
from urllib.parse import urlsplit
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from pydantic import EmailStr, ValidationError

from course_server.mail.models import InlineImage, MailAdapter, OutboundMail

from .assignment import AssignmentBrief, load_assignment_brief
from .collect import WeeklyEvidenceCollector
from .compose import (
    LinkChecker,
    NewsletterCompositionError,
    NewsletterWriter,
    compose_newsletter,
    link_resolves,
)
from .images import HighlightImageFinder
from .lecture import LectureNotes, load_lecture_notes
from .models import (
    CourseWeek,
    Delivery,
    HighlightImage,
    NewsletterApproval,
    NewsletterIssue,
    NewsletterModel,
    NewsletterSettings,
    PioneerQuote,
    ProjectEvidence,
    ProjectLink,
    ProjectScore,
    WeeklyDigest,
    issue_id_for,
    issue_subject,
)
from .quotes import PIONEER_QUOTES, choose_quote
from .render import cid_image_source, render_html, render_text
from .schedule import select_week
from .score import score_projects, select_highlights
from .screenshots import ScreenshotError
from .store import LOGO_CONTENT_ID, LOGO_FILENAME, FileNewsletterStore


class NewsletterStateError(RuntimeError):
    """The requested transition is not allowed for the issue's current state."""


class _Recipients(NewsletterModel):
    addresses: tuple[EmailStr, ...]


def normalize_recipients(values: Sequence[str]) -> tuple[str, ...]:
    """Validate, trim, and de-duplicate addresses while preserving order."""

    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        address = value.strip()
        if address and address.casefold() not in seen:
            seen.add(address.casefold())
            ordered.append(address)
    try:
        return tuple(str(item) for item in _Recipients(addresses=tuple(ordered)).addresses)
    except ValidationError as error:
        raise NewsletterStateError("One or more recipient addresses are invalid.") from error


def adopt_browser_pages(
    evidence: Sequence[ProjectEvidence], pages: Mapping[str, str]
) -> tuple[ProjectEvidence, ...]:
    """A highlight's week post that only the browser found (a script-built site) becomes its link.

    Static discovery reads served HTML, so it misses links a site's script renders. The image
    finder opens the site in a browser; the post page it captured from is the better link.
    """

    adopted: list[ProjectEvidence] = []
    for item in evidence:
        page = pages.get(item.project_id)
        if (
            item.week_page_url is None
            and page is not None
            and item.site_url is not None
            and _is_site_subpage(page, item.site_url)
        ):
            item = item.model_copy(update={"week_page_url": page})
        adopted.append(item)
    return tuple(adopted)


def _is_site_subpage(page: str, site_url: str) -> bool:
    page_parts, site_parts = urlsplit(page), urlsplit(site_url)
    return (
        (page_parts.scheme, page_parts.netloc) == (site_parts.scheme, site_parts.netloc)
        and page_parts.path.startswith(site_parts.path.rstrip("/"))
        and page.rstrip("/") != site_url.rstrip("/")
    )


class NewsletterService:
    def __init__(
        self,
        *,
        settings: NewsletterSettings,
        weeks: Sequence[CourseWeek],
        store: FileNewsletterStore,
        collector: WeeklyEvidenceCollector | None = None,
        writer: NewsletterWriter | None = None,
        image_finder: HighlightImageFinder | None = None,
        link_checker: LinkChecker | None = link_resolves,
        lecture_loader: Callable[[CourseWeek], LectureNotes | None] | None = None,
        assignment_loader: Callable[[CourseWeek], AssignmentBrief | None] | None = None,
        quotes: tuple[PioneerQuote, ...] = PIONEER_QUOTES,
        model_id: str | None = None,
        clock: Callable[[], datetime] | None = None,
        log: Callable[[str], None] | None = None,
    ) -> None:
        self._settings = settings
        self._weeks = tuple(weeks)
        self._collector = collector
        self._writer = writer
        self._image_finder = image_finder
        self._link_checker = link_checker
        self._lecture_loader = lecture_loader or (
            lambda week: load_lecture_notes(settings.slides_path, settings.syllabus_path, week)
        )
        self._assignment_loader = assignment_loader or (
            lambda week: load_assignment_brief(settings.assignments_path, week)
        )
        self._store = store
        self._quotes = quotes
        self._model_id = model_id
        self._clock = clock or (lambda: datetime.now(UTC))
        self._log = log or (lambda message: None)

    def resolve_week(
        self, *, week_number: int | None = None, as_of: date | None = None
    ) -> CourseWeek:
        today = as_of or self._clock().astimezone(ZoneInfo(self._settings.timezone)).date()
        return select_week(self._weeks, week_number=week_number, as_of=today)

    def draft(
        self,
        *,
        week_number: int | None = None,
        as_of: date | None = None,
        force: bool = False,
    ) -> NewsletterIssue:
        if self._collector is None or self._writer is None:
            raise NewsletterStateError("Drafting requires the repository collector and a writer.")
        week = self.resolve_week(week_number=week_number, as_of=as_of)
        issue_id = issue_id_for(week)
        existing = self._store.load(issue_id)
        if existing is not None and existing.status == "sent" and not force:
            raise NewsletterStateError(
                f"Issue {issue_id} was already sent on {existing.sent_at}; pass force to redraft."
            )
        cooldown = self._store.recently_highlighted(
            before_week=week.number,
            cooldown=self._settings.highlight_cooldown_issues,
        )
        evidence = self._collector.collect(week)
        digest = WeeklyDigest(
            week=week,
            projects=evidence,
            cooldown_project_ids=cooldown,
            highlight_count=self._settings.highlight_count,
        )
        self._log(
            f"Scoring {sum(1 for item in evidence if item.active)} active projects "
            f"({len(digest.eligible_project_ids())} eligible for highlights)."
        )
        scores = score_projects(
            digest, self._writer, branding=self._settings.branding, log=self._log
        )
        selected = select_highlights(scores, count=digest.highlight_count)
        if not selected:
            raise NewsletterCompositionError("No eligible project could be scored this week.")
        self._log("Selected: " + ", ".join(selected))
        images, browser_pages = self._find_images(issue_id, selected, evidence, week, scores)
        evidence = adopt_browser_pages(evidence, browser_pages)
        digest = digest.model_copy(update={"projects": evidence})
        lecture = self._lecture_loader(week)
        self._log(
            f"Lecture notes: {lecture.title} ({len(lecture.slides_text)} chars)"
            if lecture is not None
            else "Lecture notes: none published for this week."
        )
        copy, student_quote = compose_newsletter(
            digest,
            scores,
            self._writer,
            selected=selected,
            branding=self._settings.branding,
            lecture=lecture,
            assignment=self._assignment_for(week),
            link_checker=self._link_checker,
        )
        sites = {item.project_id: item.site_url for item in evidence}
        if student_quote is not None:
            project_id, label, text = student_quote
            quote = PioneerQuote(
                text=text,
                author=label,
                source=f"from their week {week.number} post",
                url=sites.get(project_id),
                kind="student",
            )
            self._log(f"Closing quote: {label}'s own words.")
        else:
            quote = choose_quote(
                week_number=week.number,
                used_texts=self._store.used_quote_texts(),
                quotes=self._quotes,
            )
            self._log("Closing quote: no student quote qualified; using the pioneer rotation.")
        issue = NewsletterIssue(
            issue_id=issue_id,
            week=week,
            branding=self._settings.branding,
            subject=issue_subject(self._settings.subject, week),
            body=copy,
            roster=tuple(
                ProjectLink(
                    project_id=item.project_id,
                    label=item.label,
                    site_url=item.site_url,
                    # A fragment post only renders inside the site, so readers go to the
                    # site, at the address its shell would open the post from.
                    post_url=item.visitor_url if item.week_page_url is not None else None,
                    posted=item.active,
                )
                for item in evidence
            ),
            quote=quote,
            scores=scores,
            images=images,
            model_id=self._model_id,
            created_at=self._clock(),
        )
        self._store.save(issue)
        return issue

    def _assignment_for(self, week: CourseWeek) -> AssignmentBrief | None:
        """The week's assignment record, logged so a missing or stale copy is visible."""

        assignment = self._assignment_loader(week)
        self._log(
            f"Assignment: {assignment.title} (record {assignment.assignment_id}, "
            f"revision {assignment.revision})"
            if assignment is not None
            else "Assignment: no published record is due this week in "
            f"{self._settings.assignments_path}; the title follows the schedule's line instead."
        )
        return assignment

    def rewrite_copy(self, issue_id: str) -> NewsletterIssue:
        """Regenerate headline, editorial, highlights, and quote; keep selection and images."""

        if self._collector is None or self._writer is None:
            raise NewsletterStateError("Rewriting requires the repository collector and a writer.")
        issue = self.load(issue_id)
        if issue.status != "draft":
            raise NewsletterStateError(
                f"Issue {issue_id} is {issue.status}; only drafts are rewritten."
            )
        selected = issue.highlighted_project_ids()
        if not selected or not issue.scores:
            raise NewsletterStateError("This issue has no stored selection to rewrite from.")
        evidence = self._collector.collect(issue.week)
        digest = WeeklyDigest(
            week=issue.week,
            projects=evidence,
            cooldown_project_ids=frozenset(
                score.project_id for score in issue.scores if not score.eligible
            ),
            highlight_count=self._settings.highlight_count,
        )
        lecture = self._lecture_loader(issue.week)
        copy, student_quote = compose_newsletter(
            digest,
            issue.scores,
            self._writer,
            selected=selected,
            branding=self._settings.branding,
            lecture=lecture,
            assignment=self._assignment_for(issue.week),
            link_checker=self._link_checker,
        )
        sites = {item.project_id: item.site_url for item in evidence}
        quote = issue.quote
        if student_quote is not None:
            project_id, label, text = student_quote
            quote = PioneerQuote(
                text=text,
                author=label,
                source=f"from their week {issue.week.number} post",
                url=sites.get(project_id),
                kind="student",
            )
        updated = issue.model_copy(
            update={"body": copy, "quote": quote, "created_at": self._clock()}
        )
        self._store.save(updated)
        return updated

    def _find_images(
        self,
        issue_id: str,
        selected: Sequence[str],
        evidence: Sequence[ProjectEvidence],
        week: CourseWeek,
        scores: Sequence[ProjectScore],
    ) -> tuple[tuple[HighlightImage, ...], dict[str, str]]:
        """Each highlight's image, plus the week posts only the browser could reach."""

        self._store.clear_images(issue_id)
        if self._image_finder is None:
            return (), {}
        projects = {item.project_id: item for item in evidence}
        rationale = {score.project_id: score.rationale for score in scores}
        images: list[HighlightImage] = []
        browser_pages: dict[str, str] = {}
        for project_id in selected:
            project = projects.get(project_id)
            if project is None or project.site_url is None:
                continue
            context = f"{project.label}: {rationale.get(project_id, '')}".strip(": ")
            found = None
            for attempt in (1, 2):  # one retry: site inspection can time out transiently
                try:
                    found = self._image_finder.find(
                        site_url=project.site_url,
                        week=week,
                        context=context,
                        post_url=project.week_page_url,
                    )
                    break
                except ScreenshotError as error:
                    self._log(f"  {project_id}: attempt {attempt} failed ({error})")
            if found is None and attempt == 2:
                self._log(f"  {project_id}: no image after two attempts")
                continue
            if found is None:
                self._log(f"  {project_id}: no image found")
                continue
            extension = "png" if found.shot.media_type == "image/png" else "jpg"
            filename = f"{project_id}.{extension}"
            self._store.save_image(issue_id, filename, found.shot.data)
            self._log(
                f"  {project_id}: {found.kind.replace('_', ' ')} from {found.page_url} "
                f"({len(found.shot.data)} bytes)"
            )
            images.append(
                HighlightImage(
                    project_id=project_id,
                    filename=filename,
                    media_type=found.shot.media_type,
                    width=found.shot.width,
                    height=found.shot.height,
                    kind=found.kind,
                    source_url=found.source_url,
                    page_url=found.page_url,
                )
            )
            if found.kind == "post_image" and not found.page_is_fragment:
                browser_pages[project_id] = found.page_url
        return tuple(images), browser_pages

    def load(self, issue_id: str) -> NewsletterIssue:
        issue = self._store.load(issue_id)
        if issue is None:
            raise NewsletterStateError(f"Issue {issue_id} does not exist; draft it first.")
        return issue

    def request_send(
        self,
        issue_id: str,
        *,
        audience: str,
        recipients: Sequence[str],
        conversation_id: UUID,
        requested_by_user_id: UUID,
    ) -> NewsletterIssue:
        """Freeze a recipient snapshot and hold the issue until the instructor confirms."""

        issue = self.load(issue_id)
        if issue.status not in {"draft", "awaiting_confirmation"}:
            raise NewsletterStateError(f"Issue {issue_id} is {issue.status}; it cannot be resent.")
        addresses = normalize_recipients(recipients)
        if not addresses:
            raise NewsletterStateError("At least one recipient is required.")
        if audience not in {"all_students", "test"}:
            raise NewsletterStateError("Audience must be all_students or test.")
        approval = NewsletterApproval(
            confirmation_id=uuid4(),
            conversation_id=conversation_id,
            requested_by_user_id=requested_by_user_id,
            audience="all_students" if audience == "all_students" else "test",
            recipients=addresses,
            requested_at=self._clock(),
        )
        updated = issue.model_copy(update={"status": "awaiting_confirmation", "approval": approval})
        self._store.save(updated)
        return updated

    def _awaiting(
        self,
        issue_id: str,
        *,
        confirmation_id: UUID,
        conversation_id: UUID,
        user_id: UUID,
    ) -> NewsletterIssue:
        issue = self.load(issue_id)
        approval = issue.approval
        if (
            issue.status != "awaiting_confirmation"
            or approval is None
            or approval.confirmation_id != confirmation_id
            or approval.conversation_id != conversation_id
            or approval.requested_by_user_id != user_id
        ):
            raise NewsletterStateError("The newsletter is no longer awaiting confirmation.")
        return issue

    def confirm_send(
        self,
        issue_id: str,
        *,
        confirmation_id: UUID,
        conversation_id: UUID,
        user_id: UUID,
    ) -> NewsletterIssue:
        """Approve delivery; the mail worker sends to the frozen recipients on its next cycle."""

        issue = self._awaiting(
            issue_id,
            confirmation_id=confirmation_id,
            conversation_id=conversation_id,
            user_id=user_id,
        )
        assert issue.approval is not None
        updated = issue.model_copy(
            update={
                "status": "approved",
                "approval": issue.approval.model_copy(update={"decided_at": self._clock()}),
            }
        )
        self._store.save(updated)
        return updated

    def cancel_send(
        self,
        issue_id: str,
        *,
        confirmation_id: UUID,
        conversation_id: UUID,
        user_id: UUID,
    ) -> NewsletterIssue:
        issue = self._awaiting(
            issue_id,
            confirmation_id=confirmation_id,
            conversation_id=conversation_id,
            user_id=user_id,
        )
        updated = issue.model_copy(update={"status": "draft", "approval": None})
        self._store.save(updated)
        return updated

    async def deliver_approved(self, mail: MailAdapter) -> tuple[NewsletterIssue, ...]:
        """Outbox step for the mail worker: send every approved issue to its snapshot."""

        delivered: list[NewsletterIssue] = []
        for issue in self._store.list_issues():
            if issue.status != "approved" or issue.approval is None:
                continue
            self._log(
                f"Delivering {issue.issue_id} to {len(issue.approval.recipients)} recipients."
            )
            if issue.approval.audience == "test":
                # A test copy never counts as the class send: record it and return to draft.
                tested = await self._deliver(issue, mail, issue.approval.recipients, test_only=True)
                reverted = tested.model_copy(update={"status": "draft", "approval": None})
                self._store.save(reverted)
                delivered.append(reverted)
                continue
            delivered.append(
                await self._deliver(issue, mail, issue.approval.recipients, test_only=False)
            )
        return tuple(delivered)

    async def send(
        self,
        issue_id: str,
        *,
        mail: MailAdapter,
        recipients: Sequence[str],
        test_only: bool = False,
    ) -> NewsletterIssue:
        """Direct send from the command line. A test send never changes the stored issue."""

        issue = self.load(issue_id)
        if issue.status == "sent" and not test_only:
            raise NewsletterStateError(f"Issue {issue_id} was already sent on {issue.sent_at}.")
        if issue.status != "draft" and not test_only:
            raise NewsletterStateError(
                f"Issue {issue_id} is {issue.status}; resolve it in the Course Agent first."
            )
        addresses = normalize_recipients(recipients)
        if not addresses:
            raise NewsletterStateError("At least one recipient is required.")
        updated = await self._deliver(issue, mail, addresses, test_only=test_only)
        if not test_only and updated.status != "sent":
            raise NewsletterStateError("No recipient accepted the newsletter; it remains a draft.")
        return updated

    async def _deliver(
        self,
        issue: NewsletterIssue,
        mail: MailAdapter,
        addresses: Sequence[str],
        *,
        test_only: bool,
    ) -> NewsletterIssue:
        text = render_text(issue)
        logo = self._store.logo_bytes(issue.issue_id)
        html = render_html(
            issue,
            image_src=cid_image_source,
            logo_src=f"cid:{LOGO_CONTENT_ID}" if logo is not None else None,
        )
        inline_images = tuple(
            InlineImage(
                content_id=image.content_id,
                media_type=image.media_type,
                data=self._store.load_image(issue.issue_id, image.filename),
                filename=f"{issue.issue_id}-{image.filename}",
            )
            for image in issue.images
        )
        if logo is not None:
            inline_images += (
                InlineImage(
                    content_id=LOGO_CONTENT_ID,
                    media_type="image/png",
                    data=logo,
                    filename=LOGO_FILENAME,
                ),
            )
        deliveries: list[Delivery] = []
        for address in addresses:
            attempted_at = self._clock()
            try:
                sent = await mail.send_message(
                    OutboundMail(
                        to=(address,),
                        subject=issue.subject,
                        text=text,
                        html=html,
                        inline_images=inline_images,
                    )
                )
            except Exception as error:  # record the class, keep sending
                self._log(f"  {address}: failed ({type(error).__name__})")
                deliveries.append(
                    Delivery(
                        recipient=address,
                        error=type(error).__name__,
                        attempted_at=attempted_at,
                    )
                )
                continue
            self._log(f"  {address}: sent")
            deliveries.append(
                Delivery(
                    recipient=address,
                    provider_message_id=sent.provider_message_id,
                    attempted_at=attempted_at,
                )
            )
        succeeded = any(delivery.error is None for delivery in deliveries)
        if test_only:
            return issue.model_copy(update={"deliveries": tuple(deliveries)})
        updated = issue.model_copy(
            update={
                "status": "sent" if succeeded else issue.status,
                "sent_at": self._clock() if succeeded else None,
                "deliveries": tuple(deliveries),
            }
        )
        self._store.save(updated)
        return updated
