"""Background draft runs started from the Course Agent.

A draft takes several minutes, longer than one agent turn, so the tool starts a thread and
the instructor asks for status. Job records are portable JSON in the newsletter store.
"""

from __future__ import annotations

import threading
from collections import deque
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

from .models import NewsletterJob
from .service import NewsletterService
from .store import FileNewsletterStore

MAX_LOG_LINES = 40
# A job still "running" this long after it started belongs to a process that died.
STALE_AFTER = timedelta(minutes=20)
ServiceFactory = Callable[[Callable[[str], None]], NewsletterService]


class NewsletterJobRunner:
    def __init__(
        self,
        *,
        store: FileNewsletterStore,
        service_factory: ServiceFactory,
        pdf_exporter: Callable[[str], Path] | None = None,
        clock: Callable[[], datetime] | None = None,
        run_in_thread: bool = True,
    ) -> None:
        self._store = store
        self._service_factory = service_factory
        self._pdf_exporter = pdf_exporter
        self._clock = clock or (lambda: datetime.now(UTC))
        self._run_in_thread = run_in_thread
        self._lock = threading.Lock()
        self._current_id: UUID | None = None

    def start(
        self,
        *,
        week_number: int | None,
        force: bool,
        requested_by_user_id: UUID | None,
    ) -> tuple[NewsletterJob, bool]:
        """Start a draft, or return the job already running; the bool says which."""

        with self._lock:
            current = self.current()
            if current is not None and current.status == "running":
                return current, False
            job = NewsletterJob(
                job_id=uuid4(),
                status="running",
                requested_by_user_id=requested_by_user_id,
                week_number=week_number,
                started_at=self._clock(),
            )
            self._store.save_job(job)
            self._current_id = job.job_id
        if self._run_in_thread:
            threading.Thread(
                target=self._run,
                args=(job.job_id, week_number, force),
                name=f"newsletter-draft-{job.job_id}",
                daemon=True,
            ).start()
        else:
            self._run(job.job_id, week_number, force)
            job = self._store.load_job(job.job_id) or job
        return job, True

    def current(self) -> NewsletterJob | None:
        if self._current_id is None:
            return None
        return self._reconcile(self._store.load_job(self._current_id))

    def status(self, job_id: UUID) -> NewsletterJob | None:
        return self._reconcile(self._store.load_job(job_id))

    def latest(self) -> NewsletterJob | None:
        jobs = self._store.list_jobs()
        return self._reconcile(jobs[-1]) if jobs else None

    def _reconcile(self, job: NewsletterJob | None) -> NewsletterJob | None:
        """Mark a job abandoned by a restarted process as failed instead of running forever."""

        if job is None or job.status != "running":
            return job
        if self._clock() - job.started_at < STALE_AFTER:
            return job
        return self._update(
            job.job_id,
            status="failed",
            error="The draft did not finish; the server restarted while it was running.",
            finished_at=self._clock(),
        )

    def _update(self, job_id: UUID, **changes: object) -> NewsletterJob:
        with self._lock:
            job = self._store.load_job(job_id)
            if job is None:
                raise RuntimeError(f"newsletter job {job_id} vanished")
            updated = job.model_copy(update=changes)
            self._store.save_job(updated)
            return updated

    def _run(self, job_id: UUID, week_number: int | None, force: bool) -> None:
        lines: deque[str] = deque(maxlen=MAX_LOG_LINES)

        def log(message: str) -> None:
            lines.append(message.strip())
            self._update(job_id, log=tuple(lines))

        try:
            service = self._service_factory(log)
            issue = service.draft(week_number=week_number, force=force)
            if self._pdf_exporter is not None:
                try:
                    self._pdf_exporter(issue.issue_id)
                except Exception as error:  # the PDF is a convenience, not the deliverable
                    log(f"PDF export skipped ({type(error).__name__})")
            self._update(
                job_id,
                status="done",
                issue_id=issue.issue_id,
                week_number=issue.week.number,
                finished_at=self._clock(),
                log=tuple(lines),
            )
        except Exception as error:  # the job record is the only place a failure can surface
            self._update(
                job_id,
                status="failed",
                error=f"{type(error).__name__}: {error}"[:500],
                finished_at=self._clock(),
                log=tuple(lines),
            )
