"""Typed configuration and portable records for the weekly course newsletter."""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import date
from pathlib import Path, PurePosixPath
from typing import Annotated, Literal
from urllib.parse import urldefrag, urlsplit
from uuid import UUID

from pydantic import AliasChoices, BaseModel, ConfigDict, EmailStr, Field, StringConstraints

from course_server.auth.models import AwareDatetime
from course_server.config import ConfigurationError

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_NEWSLETTER_DATA_PATH = PROJECT_ROOT / "var/newsletter"
DEFAULT_SCHEDULE_PATH = PROJECT_ROOT / "shared/course/schedule/schedule.md"
DEFAULT_SLIDES_PATH = PROJECT_ROOT / "shared/course/slides"
DEFAULT_SYLLABUS_PATH = PROJECT_ROOT / "shared/course/syllabus/syllabus.md"
DEFAULT_LOGO_PATH = PROJECT_ROOT / "shared/course/newsletter/newsletter-logo.png"
# The deployment's assignment records (see docs/ASSIGNMENTS.md); the same default the API uses.
DEFAULT_ASSIGNMENTS_PATH = PROJECT_ROOT / "var/assignments"
ISSUE_ID_PATTERN = r"^[0-9]{4}-week[0-9]{2}$"
# Validation bounds for the two sections that point students at each other: the list of
# other builds is grouped under at most this many approach headings, and at most this many
# blockers each name at most this many classmates to ask.
MAX_BUILD_GROUPS = 6
MAX_ASK_AROUND = 3
MAX_ASK_AROUND_NAMES = 2

ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
ProjectId = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_.-]{1,100}$")]


class NewsletterModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class NewsletterBranding(NewsletterModel):
    """Course identity printed in every issue; stored with the issue so renders stay stable."""

    newsletter_name: ShortText = "The Class Runtime"
    course_code: ShortText = "MAS.S60"
    course_title: ShortText = "AI Agents for Cognitive Augmentation"
    course_term: ShortText = "Fall 2026"
    institution: ShortText = "MIT"
    course_site_url: Annotated[str, StringConstraints(pattern=r"^https://[^\s]+$")] = (
        "https://cognitive-agents.media.mit.edu"
    )
    # No longer printed; kept so issues stored with it still load.
    sender_name: ShortText = "The MAS.S60 teaching team"
    # Signs the editorial and is credited in the footer as the newsletter's creator.
    editor_name: ShortText = "The Course Agent"


class NewsletterSettings(NewsletterModel):
    """Deployment-owned newsletter configuration read from the environment."""

    branding: NewsletterBranding = NewsletterBranding()
    subject: ShortText = "The Class Runtime from MAS.S60"
    timezone: ShortText = "America/New_York"
    highlight_count: int = Field(default=4, ge=1, le=8)
    # Only the previous issue's featured students sit out, so strong builders return quickly.
    highlight_cooldown_issues: int = Field(default=1, ge=0, le=12)
    recipients: tuple[EmailStr, ...] = ()
    data_path: Path = DEFAULT_NEWSLETTER_DATA_PATH
    schedule_path: Path = DEFAULT_SCHEDULE_PATH
    slides_path: Path = DEFAULT_SLIDES_PATH
    syllabus_path: Path = DEFAULT_SYLLABUS_PATH
    # The masthead wordmark; rendered at the top of the HTML and inlined in email.
    logo_path: Path = DEFAULT_LOGO_PATH
    # Where the week's assignment record is read from, for the headline and editorial.
    assignments_path: Path = DEFAULT_ASSIGNMENTS_PATH

    @classmethod
    def from_environment(cls, values: Mapping[str, str]) -> NewsletterSettings:
        def text(name: str, default: str) -> str:
            raw = values.get(name)
            return raw.strip() if raw and raw.strip() else default

        def integer(name: str, default: int) -> int:
            raw = values.get(name)
            if raw is None or not raw.strip():
                return default
            try:
                return int(raw.strip())
            except ValueError as error:
                raise ConfigurationError(f"{name} must be an integer") from error

        def path(name: str, default: Path) -> Path:
            raw = values.get(name)
            return Path(raw.strip()).expanduser() if raw and raw.strip() else default

        defaults = NewsletterBranding()
        branding = NewsletterBranding(
            newsletter_name=text("NEWSLETTER_NAME", defaults.newsletter_name),
            course_code=text("NEWSLETTER_COURSE_CODE", defaults.course_code),
            course_title=text("NEWSLETTER_COURSE_TITLE", defaults.course_title),
            course_term=text("NEWSLETTER_COURSE_TERM", defaults.course_term),
            institution=text("NEWSLETTER_INSTITUTION", defaults.institution),
            course_site_url=text("NEWSLETTER_COURSE_SITE_URL", defaults.course_site_url),
            sender_name=text("NEWSLETTER_SENDER_NAME", defaults.sender_name),
            editor_name=text("NEWSLETTER_EDITOR_NAME", defaults.editor_name),
        )
        recipients = tuple(
            address.strip()
            for address in values.get("NEWSLETTER_RECIPIENTS", "").split(",")
            if address.strip()
        )
        return cls(
            branding=branding,
            subject=text("NEWSLETTER_SUBJECT", "The Class Runtime from MAS.S60"),
            timezone=text("NEWSLETTER_TIMEZONE", "America/New_York"),
            highlight_count=integer("NEWSLETTER_HIGHLIGHT_COUNT", 4),
            highlight_cooldown_issues=integer("NEWSLETTER_HIGHLIGHT_COOLDOWN_ISSUES", 1),
            recipients=recipients,
            data_path=path("NEWSLETTER_DATA_PATH", DEFAULT_NEWSLETTER_DATA_PATH),
            schedule_path=path("NEWSLETTER_SCHEDULE_PATH", DEFAULT_SCHEDULE_PATH),
            slides_path=path("NEWSLETTER_SLIDES_PATH", DEFAULT_SLIDES_PATH),
            syllabus_path=path("NEWSLETTER_SYLLABUS_PATH", DEFAULT_SYLLABUS_PATH),
            logo_path=path("NEWSLETTER_LOGO_PATH", DEFAULT_LOGO_PATH),
            assignments_path=path("ASSIGNMENT_DATA_PATH", DEFAULT_ASSIGNMENTS_PATH),
        )


class CourseWeek(NewsletterModel):
    """One scheduled class week and the build window that follows it."""

    number: int = Field(ge=1, le=52)
    class_date: date
    topic: ShortText
    tutorial: ShortText
    starts_at: AwareDatetime
    ends_at: AwareDatetime
    has_class: bool = True


class CommitSummary(NewsletterModel):
    committed_at: AwareDatetime
    subject: Annotated[str, StringConstraints(max_length=200)]


class ProjectDocument(NewsletterModel):
    path: Annotated[str, StringConstraints(min_length=1, max_length=500)]
    text: str
    truncated: bool = False


# A post's file name that is safe to use as a `#section` address on its site.
_SITE_SECTION_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,60}")


class ProjectEvidence(NewsletterModel):
    """Bounded, read-only evidence of one student's work during a course week."""

    project_id: ProjectId
    label: ShortText
    site_url: str | None = None
    week_file_count: int = Field(ge=0)
    site_file_count: int = Field(ge=0)
    # Site files whose path names this week, such as a post the home page does not link.
    week_site_file_count: int = Field(default=0, ge=0)
    commit_count: int = Field(ge=0)
    commits: tuple[CommitSummary, ...] = ()
    documents: tuple[ProjectDocument, ...] = ()
    site_text: str | None = None
    # The student's post for this week on their site, when a link naming the week exists.
    week_page_url: str | None = None
    week_page_text: str | None = None
    # The post is an HTML fragment that only renders inside the site's own shell.
    week_page_fragment: bool = False
    notes: tuple[str, ...] = ()

    @property
    def visitor_url(self) -> str | None:
        """Where a reader should land: the week's post, or the site when it only renders there.

        A fragment post is addressed on the site as `#<its file name>`. A shell that loads its
        posts by name opens the post from that address; any other site shows its home page,
        which is where the reader would have been sent anyway.
        """

        if self.week_page_url is None or not self.week_page_fragment:
            return self.week_page_url or self.site_url
        if self.site_url is None:
            return None
        name = PurePosixPath(urlsplit(self.week_page_url).path).stem
        site = urldefrag(self.site_url).url
        return f"{site}#{name}" if _SITE_SECTION_NAME.fullmatch(name) else site

    @property
    def active(self) -> bool:
        """Whether anything points at work for this week.

        A site that exists but was not touched this week does not count: it would put a
        student on the week's list for work from an earlier week.
        """

        return self.week_file_count > 0 or self.commit_count > 0 or self.week_site_file_count > 0


class WeeklyDigest(NewsletterModel):
    week: CourseWeek
    projects: tuple[ProjectEvidence, ...]
    cooldown_project_ids: frozenset[str] = frozenset()
    highlight_count: int = Field(ge=1, le=8)

    def eligible_project_ids(self) -> tuple[str, ...]:
        return tuple(
            project.project_id
            for project in self.projects
            if project.active and project.project_id not in self.cooldown_project_ids
        )

    def target_highlight_count(self) -> int:
        return min(self.highlight_count, len(self.eligible_project_ids()))


class Highlight(NewsletterModel):
    project_id: ProjectId
    headline: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
    description: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=700)
    ]


class BuildGroup(NewsletterModel):
    """Builds that took one approach, under the heading the editorial gave that approach."""

    heading: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
    project_ids: tuple[ProjectId, ...] = Field(min_length=1)


class AskAround(NewsletterModel):
    """One blocker from the editorial, and the classmates whose notes say they got past it."""

    question: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
    project_ids: tuple[ProjectId, ...] = Field(min_length=1, max_length=MAX_ASK_AROUND_NAMES)


class NewsletterCopy(NewsletterModel):
    """Model-authored prose; platform code owns selection, links, ordering, quote, and footer."""

    headline: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    editorial: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2_500)
    ]
    highlights: tuple[Highlight, ...] = Field(max_length=8)
    # The approaches the editorial found, each with the builds that took it; the list of other
    # builds is grouped under them. Empty on issues drafted before grouping existed.
    groups: tuple[BuildGroup, ...] = Field(default=(), max_length=MAX_BUILD_GROUPS)
    # Blockers from the editorial's second paragraph, each pointing at classmates who got past it.
    ask_around: tuple[AskAround, ...] = Field(default=(), max_length=MAX_ASK_AROUND)


class ProjectScore(NewsletterModel):
    """Rubric scores for one project's week, produced by the model and ranked in code."""

    project_id: ProjectId
    # Out-of-the-box thinking; issues scored before the rename stored it as `interest`.
    originality: int = Field(ge=0, le=10, validation_alias=AliasChoices("originality", "interest"))
    execution: int = Field(ge=0, le=10)
    goal_fit: int = Field(ge=0, le=10)
    # How directly the build helps a person think; absent from issues scored before it existed.
    augmentation: int | None = Field(default=None, ge=0, le=10)
    total: float = Field(ge=0, le=10)
    # Nothing beyond a starter or welcome site: left off the list of builds and never featured.
    blank: bool = False
    rationale: Annotated[str, StringConstraints(strip_whitespace=True, max_length=600)] = ""
    built: Annotated[str, StringConstraints(strip_whitespace=True, max_length=300)] = ""
    went_well: Annotated[str, StringConstraints(strip_whitespace=True, max_length=400)] = ""
    struggled: Annotated[str, StringConstraints(strip_whitespace=True, max_length=400)] = ""
    # Verbatim, platform-verified sentences from the student's own writing.
    quotes: tuple[
        Annotated[str, StringConstraints(strip_whitespace=True, max_length=400)], ...
    ] = ()
    eligible: bool = True


class PioneerQuote(NewsletterModel):
    """The closing quote: a verified line from a student's post, or a curated pioneer quote."""

    text: ShortText
    author: ShortText
    source: ShortText
    url: str | None = None
    kind: Literal["pioneer", "student"] = "pioneer"


class ProjectLink(NewsletterModel):
    project_id: ProjectId
    label: ShortText
    site_url: str | None = None
    # The week's post when the site has one; links prefer it over the site root.
    post_url: str | None = None
    # Whether the student posted anything in the week's window; quiet students stay off the list.
    posted: bool = True


class HighlightImage(NewsletterModel):
    """A screenshot of a highlighted build, stored next to the issue and inlined in email."""

    project_id: ProjectId
    filename: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9._-]{1,120}$")]
    media_type: Literal["image/jpeg", "image/png"]
    width: int = Field(ge=1)
    height: int = Field(ge=1)
    kind: Literal["post_image", "screenshot"] = "screenshot"
    source_url: str | None = None
    page_url: str | None = None

    @property
    def content_id(self) -> str:
        return self.project_id


IssueStatus = Literal["draft", "awaiting_confirmation", "approved", "sent"]


class NewsletterApproval(NewsletterModel):
    """The instructor's send request: a fixed recipient snapshot awaiting or holding approval."""

    confirmation_id: UUID
    conversation_id: UUID
    requested_by_user_id: UUID
    audience: Literal["all_students", "test"]
    recipients: tuple[EmailStr, ...] = Field(min_length=1, max_length=500)
    requested_at: AwareDatetime
    decided_at: AwareDatetime | None = None


JobStatus = Literal["running", "done", "failed"]


class NewsletterJob(NewsletterModel):
    """A background draft run started from the Course Agent; persisted for status queries."""

    job_id: UUID
    status: JobStatus
    requested_by_user_id: UUID | None = None
    week_number: int | None = None
    issue_id: str | None = None
    error: str | None = None
    started_at: AwareDatetime
    finished_at: AwareDatetime | None = None
    log: tuple[str, ...] = ()


class Delivery(NewsletterModel):
    recipient: EmailStr
    provider_message_id: str | None = None
    error: str | None = None
    attempted_at: AwareDatetime


class NewsletterIssue(NewsletterModel):
    """One portable newsletter issue: draft until an instructor explicitly sends it."""

    schema_version: Literal[1] = 1
    issue_id: Annotated[str, StringConstraints(pattern=ISSUE_ID_PATTERN)]
    week: CourseWeek
    branding: NewsletterBranding
    subject: ShortText
    body: NewsletterCopy
    roster: tuple[ProjectLink, ...]
    quote: PioneerQuote
    scores: tuple[ProjectScore, ...] = ()
    images: tuple[HighlightImage, ...] = ()
    model_id: str | None = None
    status: IssueStatus = "draft"
    approval: NewsletterApproval | None = None
    created_at: AwareDatetime
    sent_at: AwareDatetime | None = None
    deliveries: tuple[Delivery, ...] = ()

    def highlighted_project_ids(self) -> tuple[str, ...]:
        return tuple(highlight.project_id for highlight in self.body.highlights)

    def link_for(self, project_id: str) -> ProjectLink | None:
        return next((link for link in self.roster if link.project_id == project_id), None)

    def image_for(self, project_id: str) -> HighlightImage | None:
        return next((image for image in self.images if image.project_id == project_id), None)

    def open_url(self, project_id: str) -> str | None:
        link = self.link_for(project_id)
        return (link.post_url or link.site_url) if link is not None else None

    def built_for(self, project_id: str) -> str | None:
        score = next((item for item in self.scores if item.project_id == project_id), None)
        return score.built or None if score is not None else None

    def other_projects(self) -> tuple[ProjectLink, ...]:
        """Students who posted a real build this week and were not featured."""

        hidden = set(self.highlighted_project_ids()) | {
            score.project_id for score in self.scores if score.blank
        }
        return tuple(link for link in self.roster if link.posted and link.project_id not in hidden)

    def grouped_other_projects(self) -> tuple[tuple[str | None, tuple[ProjectLink, ...]], ...]:
        """The other builds under their approach headings, in the editorial's order.

        Builds placed under no heading come last under `None`; an issue without groups is one
        unnamed section, so the renderers print the plain list they always did.
        """

        others = self.other_projects()
        if not self.body.groups:
            return ((None, others),) if others else ()
        placed: set[str] = set()
        sections: list[tuple[str | None, tuple[ProjectLink, ...]]] = []
        for group in self.body.groups:
            members = tuple(
                link
                for link in others
                if link.project_id in group.project_ids and link.project_id not in placed
            )
            placed.update(link.project_id for link in members)
            if members:
                sections.append((group.heading, members))
        rest = tuple(link for link in others if link.project_id not in placed)
        if rest:
            sections.append((None, rest))
        return tuple(sections)


def issue_id_for(week: CourseWeek) -> str:
    return f"{week.class_date.year}-week{week.number:02d}"


def issue_subject(subject: str, week: CourseWeek) -> str:
    """The configured subject with the issue number the masthead prints, e.g. "· Issue 02"."""

    return f"{subject} · Issue {week.number:02d}"
