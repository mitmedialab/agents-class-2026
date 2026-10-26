"""Local JSON storage for newsletter issues plus reviewable text/HTML renderings."""

from __future__ import annotations

import io
import re
from pathlib import Path
from uuid import UUID

from PIL import Image
from pydantic import ValidationError

from .models import ISSUE_ID_PATTERN, NewsletterIssue, NewsletterJob
from .render import render_html, render_text

_ISSUE_ID = re.compile(ISSUE_ID_PATTERN)
_IMAGE_FILENAME = re.compile(r"^[A-Za-z0-9._-]{1,120}$")
LOGO_FILENAME = "newsletter-logo.png"
LOGO_CONTENT_ID = "newsletter-logo"
_LOGO_MAX_WIDTH = 1000


class NewsletterStoreError(RuntimeError):
    """A stored issue is unreadable or an identifier is unsafe."""


class FileNewsletterStore:
    """One `<issue_id>.json` per issue under `<root>/issues/`, ignored by Git."""

    def __init__(self, root: Path, *, logo_path: Path | None = None) -> None:
        self._root = root
        self._logo_path = logo_path

    @property
    def issues_directory(self) -> Path:
        return self._root / "issues"

    def paths_for(self, issue_id: str) -> tuple[Path, Path, Path]:
        if not _ISSUE_ID.fullmatch(issue_id):
            raise NewsletterStoreError(f"Invalid issue id: {issue_id!r}")
        base = self.issues_directory / issue_id
        return base.with_suffix(".json"), base.with_suffix(".txt"), base.with_suffix(".html")

    def pdf_path(self, issue_id: str) -> Path:
        """Where `pdf` exports the single-page rendering; it exists only after an export."""

        _, _, html_path = self.paths_for(issue_id)
        return html_path.with_suffix(".pdf")

    def save(self, issue: NewsletterIssue) -> Path:
        json_path, text_path, html_path = self.paths_for(issue.issue_id)
        self.issues_directory.mkdir(parents=True, exist_ok=True)
        temporary = json_path.with_suffix(".json.tmp")
        temporary.write_text(issue.model_dump_json(indent=2) + "\n", encoding="utf-8")
        temporary.replace(json_path)
        text_path.write_text(render_text(issue), encoding="utf-8")
        logo = self._place_logo(issue.issue_id)
        html_path.write_text(
            render_html(issue, logo_src=f"{issue.issue_id}/{LOGO_FILENAME}" if logo else None),
            encoding="utf-8",
        )
        return json_path

    def _place_logo(self, issue_id: str) -> Path | None:
        """Write an email-sized copy of the wordmark beside the issue, if one is configured."""

        if self._logo_path is None or not self._logo_path.is_file():
            return None
        target = self.image_path(issue_id, LOGO_FILENAME)
        if target.is_file():
            return target
        encoded = self.wordmark_bytes()
        if encoded is None:
            return None
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(encoded)
        return target

    def wordmark_bytes(self) -> bytes | None:
        """The configured wordmark at email width, re-encoded; None when none is configured."""

        if self._logo_path is None or not self._logo_path.is_file():
            return None
        try:
            with Image.open(self._logo_path) as image:
                rgba = image.convert("RGBA")
                if rgba.width > _LOGO_MAX_WIDTH:
                    height = max(1, round(rgba.height * _LOGO_MAX_WIDTH / rgba.width))
                    rgba = rgba.resize((_LOGO_MAX_WIDTH, height), Image.Resampling.LANCZOS)
                buffer = io.BytesIO()
                rgba.save(buffer, format="PNG", optimize=True)
        except (OSError, ValueError) as error:
            raise NewsletterStoreError("The newsletter logo could not be read.") from error
        return buffer.getvalue()

    def logo_bytes(self, issue_id: str) -> bytes | None:
        target = self._place_logo(issue_id)
        return target.read_bytes() if target is not None else None

    def image_path(self, issue_id: str, filename: str) -> Path:
        self.paths_for(issue_id)
        if not _IMAGE_FILENAME.fullmatch(filename) or filename.startswith("."):
            raise NewsletterStoreError(f"Invalid image filename: {filename!r}")
        return self.issues_directory / issue_id / filename

    def save_image(self, issue_id: str, filename: str, data: bytes) -> Path:
        path = self.image_path(issue_id, filename)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def clear_images(self, issue_id: str) -> None:
        """Remove a previous draft's images so a redraft leaves no stale files behind."""

        self.paths_for(issue_id)
        directory = self.issues_directory / issue_id
        if not directory.is_dir() or directory.is_symlink():
            return
        for path in directory.iterdir():
            if (
                path.is_file()
                and not path.is_symlink()
                and _IMAGE_FILENAME.fullmatch(path.name)
                and path.name != LOGO_FILENAME
            ):
                path.unlink()

    def load_image(self, issue_id: str, filename: str) -> bytes:
        path = self.image_path(issue_id, filename)
        if not path.is_file() or path.is_symlink():
            raise NewsletterStoreError(f"Image {filename} for {issue_id} is missing.")
        return path.read_bytes()

    @property
    def jobs_directory(self) -> Path:
        return self._root / "jobs"

    def save_job(self, job: NewsletterJob) -> Path:
        self.jobs_directory.mkdir(parents=True, exist_ok=True)
        path = self.jobs_directory / f"{job.job_id}.json"
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(job.model_dump_json(indent=2) + "\n", encoding="utf-8")
        temporary.replace(path)
        return path

    def load_job(self, job_id: UUID) -> NewsletterJob | None:
        path = self.jobs_directory / f"{job_id}.json"
        if not path.is_file() or path.is_symlink():
            return None
        try:
            return NewsletterJob.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValidationError, ValueError) as error:
            raise NewsletterStoreError(f"Stored job {job_id} is unreadable.") from error

    def list_jobs(self) -> tuple[NewsletterJob, ...]:
        if not self.jobs_directory.is_dir():
            return ()
        jobs: list[NewsletterJob] = []
        for path in sorted(self.jobs_directory.glob("*.json")):
            try:
                jobs.append(self.load_job(UUID(path.stem)) or None)  # type: ignore[arg-type]
            except (ValueError, NewsletterStoreError):
                continue
        return tuple(sorted((job for job in jobs if job is not None), key=lambda j: j.started_at))

    def load(self, issue_id: str) -> NewsletterIssue | None:
        json_path, _, _ = self.paths_for(issue_id)
        if not json_path.is_file() or json_path.is_symlink():
            return None
        try:
            return NewsletterIssue.model_validate_json(json_path.read_text(encoding="utf-8"))
        except (OSError, ValidationError, ValueError) as error:
            raise NewsletterStoreError(f"Stored issue {issue_id} is unreadable.") from error

    def list_issues(self) -> tuple[NewsletterIssue, ...]:
        if not self.issues_directory.is_dir():
            return ()
        issues: list[NewsletterIssue] = []
        for path in sorted(self.issues_directory.glob("*.json")):
            if _ISSUE_ID.fullmatch(path.stem) and (issue := self.load(path.stem)) is not None:
                issues.append(issue)
        return tuple(sorted(issues, key=lambda issue: (issue.week.class_date, issue.issue_id)))

    def sent_issues(self) -> tuple[NewsletterIssue, ...]:
        return tuple(issue for issue in self.list_issues() if issue.status == "sent")

    def recently_highlighted(self, *, before_week: int, cooldown: int) -> frozenset[str]:
        """Project ids featured in the last `cooldown` sent issues before `before_week`."""

        if cooldown <= 0:
            return frozenset()
        earlier = [issue for issue in self.sent_issues() if issue.week.number < before_week]
        recent = earlier[-cooldown:]
        return frozenset(
            project_id for issue in recent for project_id in issue.highlighted_project_ids()
        )

    def used_quote_texts(self) -> frozenset[str]:
        return frozenset(issue.quote.text for issue in self.sent_issues())
