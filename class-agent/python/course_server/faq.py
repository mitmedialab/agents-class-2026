"""Durable, staff-approved FAQ publication and student notifications."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Literal, Protocol
from uuid import UUID, uuid4

from psycopg_pool import AsyncConnectionPool
from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    StringConstraints,
    ValidationError,
    model_validator,
)

from agent_core import PrincipalContext
from course_server.agent.capabilities import (
    COURSE_FAQ_URI,
    CourseResourceCatalog,
    CourseSearchResult,
    ResourceContents,
    ResourceFile,
    ResourceSummary,
)
from course_server.auth.store import AuthStore


def _clock() -> datetime:
    return datetime.now(UTC)


class FaqModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PublishedFaqEntry(FaqModel):
    id: UUID
    question: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    answer: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    source_question_id: UUID | None
    published_by_user_id: UUID | None = None
    created_at: datetime
    updated_at: datetime
    active: bool = True


class CourseNotification(FaqModel):
    id: UUID
    faq_entry_id: UUID
    question: str
    answer: str
    published_at: datetime


class FaqPublisher(Protocol):
    async def publish(
        self,
        *,
        source_question_id: UUID,
        question: str,
        answer: str,
        published_by_user_id: UUID | None,
        published_at: datetime,
    ) -> PublishedFaqEntry: ...


class FaqKnowledgeStore(Protocol):
    async def list_active(self) -> list[PublishedFaqEntry]: ...


class FaqNotificationStore(Protocol):
    async def list_unread(self, user_id: UUID) -> list[CourseNotification]: ...

    async def mark_read(
        self,
        *,
        user_id: UUID,
        notification_id: UUID,
        read_at: datetime,
    ) -> bool: ...


class FaqStore(FaqPublisher, FaqKnowledgeStore, FaqNotificationStore, Protocol):
    """Combined protocol retained for simple in-memory and PostgreSQL adapters."""


class InMemoryFaqStore:
    """Deterministic publication store for domain and API tests."""

    def __init__(self) -> None:
        self.entries: dict[UUID, PublishedFaqEntry] = {}
        self.notifications: dict[UUID, CourseNotification] = {}
        self.reads: set[tuple[UUID, UUID]] = set()

    async def publish(
        self,
        *,
        source_question_id: UUID,
        question: str,
        answer: str,
        published_by_user_id: UUID | None,
        published_at: datetime,
    ) -> PublishedFaqEntry:
        existing = next(
            (
                entry
                for entry in self.entries.values()
                if entry.source_question_id == source_question_id
            ),
            None,
        )
        if existing is not None:
            return existing
        entry = PublishedFaqEntry(
            id=uuid4(),
            question=question,
            answer=answer,
            source_question_id=source_question_id,
            published_by_user_id=published_by_user_id,
            created_at=published_at,
            updated_at=published_at,
        )
        notification = CourseNotification(
            id=uuid4(),
            faq_entry_id=entry.id,
            question=entry.question,
            answer=entry.answer,
            published_at=published_at,
        )
        self.entries[entry.id] = entry
        self.notifications[notification.id] = notification
        return entry

    async def list_active(self) -> list[PublishedFaqEntry]:
        return sorted(
            (entry for entry in self.entries.values() if entry.active),
            key=lambda entry: entry.created_at,
        )

    async def list_unread(self, user_id: UUID) -> list[CourseNotification]:
        return sorted(
            (
                notification
                for notification in self.notifications.values()
                if (notification.id, user_id) not in self.reads
            ),
            key=lambda notification: notification.published_at,
            reverse=True,
        )

    async def mark_read(
        self,
        *,
        user_id: UUID,
        notification_id: UUID,
        read_at: datetime,
    ) -> bool:
        del read_at
        if notification_id not in self.notifications:
            return False
        self.reads.add((notification_id, user_id))
        return True


class LocalFaqRecord(FaqModel):
    """Public fields persisted in the Course Agent's local knowledge file."""

    id: UUID
    question: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    answer: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    created_at: AwareDatetime
    updated_at: AwareDatetime
    active: bool = True

    @model_validator(mode="after")
    def validate_timestamp_order(self) -> LocalFaqRecord:
        if self.updated_at < self.created_at:
            raise ValueError("updated_at must not precede created_at")
        return self


class LocalFaqDocument(FaqModel):
    schema_version: Literal[1] = 1
    entries: tuple[LocalFaqRecord, ...] = ()

    @model_validator(mode="after")
    def validate_unique_entries(self) -> LocalFaqDocument:
        entry_ids = [entry.id for entry in self.entries]
        if len(entry_ids) != len(set(entry_ids)):
            raise ValueError("local FAQ entry IDs must be unique")
        return self


class FaqKnowledgeError(RuntimeError):
    """The local public FAQ file is malformed or conflicts with publication state."""


class LocalFaqKnowledgeStore:
    """Atomic JSON storage used by the agent's public FAQ resource."""

    def __init__(self, path: Path) -> None:
        self._path = path

    async def list_active(self) -> list[PublishedFaqEntry]:
        document = self._read()
        return [
            PublishedFaqEntry(
                id=entry.id,
                question=entry.question,
                answer=entry.answer,
                source_question_id=None,
                created_at=entry.created_at,
                updated_at=entry.updated_at,
                active=entry.active,
            )
            for entry in document.entries
            if entry.active
        ]

    async def upsert(self, entry: PublishedFaqEntry) -> PublishedFaqEntry:
        document = self._read()
        public_entry = LocalFaqRecord(
            id=entry.id,
            question=entry.question,
            answer=entry.answer,
            created_at=entry.created_at,
            updated_at=entry.updated_at,
            active=entry.active,
        )
        existing = next((item for item in document.entries if item.id == entry.id), None)
        if existing is not None:
            if existing != public_entry:
                raise FaqKnowledgeError(f"local FAQ entry conflicts with publication: {entry.id}")
            return entry
        entries = tuple(
            sorted(
                (*document.entries, public_entry),
                key=lambda item: (item.created_at, str(item.id)),
            )
        )
        self._write(LocalFaqDocument(entries=entries))
        return entry

    def _read(self) -> LocalFaqDocument:
        try:
            contents = self._path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return LocalFaqDocument()
        except OSError as error:
            raise FaqKnowledgeError(f"cannot read local FAQ knowledge: {self._path}") from error
        try:
            return LocalFaqDocument.model_validate_json(contents)
        except ValidationError as error:
            raise FaqKnowledgeError(f"invalid local FAQ knowledge: {self._path}") from error

    def _write(self, document: LocalFaqDocument) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self._path.with_name(f".{self._path.name}.{uuid4().hex}.tmp")
        try:
            temporary_path.write_text(document.model_dump_json(indent=2) + "\n", encoding="utf-8")
            temporary_path.replace(self._path)
        except OSError as error:
            temporary_path.unlink(missing_ok=True)
            raise FaqKnowledgeError(f"cannot write local FAQ knowledge: {self._path}") from error


class CoordinatedFaqPublisher:
    """Completes database bookkeeping, then updates agent-readable local knowledge."""

    def __init__(self, workflow: FaqPublisher, knowledge: LocalFaqKnowledgeStore) -> None:
        self._workflow = workflow
        self._knowledge = knowledge

    async def publish(
        self,
        *,
        source_question_id: UUID,
        question: str,
        answer: str,
        published_by_user_id: UUID | None,
        published_at: datetime,
    ) -> PublishedFaqEntry:
        entry = await self._workflow.publish(
            source_question_id=source_question_id,
            question=question,
            answer=answer,
            published_by_user_id=published_by_user_id,
            published_at=published_at,
        )
        return await self._knowledge.upsert(entry)


class PostgresFaqStore:
    """PostgreSQL publication projection and per-student notification state."""

    def __init__(self, pool: AsyncConnectionPool[Any]) -> None:
        self._pool = pool

    async def publish(
        self,
        *,
        source_question_id: UUID,
        question: str,
        answer: str,
        published_by_user_id: UUID | None,
        published_at: datetime,
    ) -> PublishedFaqEntry:
        entry_id = uuid4()
        async with self._pool.connection() as connection, connection.transaction():
            await connection.execute(
                """
                INSERT INTO faq_entries (
                    id, question, answer, source_question_id,
                    published_by_user_id, created_at, updated_at, active
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, true)
                ON CONFLICT (source_question_id) WHERE source_question_id IS NOT NULL
                DO NOTHING
                """,
                (
                    entry_id,
                    question,
                    answer,
                    source_question_id,
                    published_by_user_id,
                    published_at,
                    published_at,
                ),
            )
            row = await (
                await connection.execute(
                    """
                    SELECT id, question, answer, source_question_id,
                           published_by_user_id, created_at, updated_at, active
                    FROM faq_entries WHERE source_question_id = %s
                    """,
                    (source_question_id,),
                )
            ).fetchone()
            assert row is not None
            await connection.execute(
                """
                INSERT INTO course_notifications (id, faq_entry_id, published_at)
                VALUES (%s, %s, %s)
                ON CONFLICT (faq_entry_id) DO NOTHING
                """,
                (uuid4(), row["id"], published_at),
            )
        return PublishedFaqEntry.model_validate(row)

    async def list_active(self) -> list[PublishedFaqEntry]:
        async with self._pool.connection() as connection:
            rows = await (
                await connection.execute(
                    """
                    SELECT id, question, answer, source_question_id,
                           published_by_user_id, created_at, updated_at, active
                    FROM faq_entries
                    WHERE active AND source_question_id IS NOT NULL
                    ORDER BY created_at, id
                    """
                )
            ).fetchall()
        return [PublishedFaqEntry.model_validate(row) for row in rows]

    async def list_unread(self, user_id: UUID) -> list[CourseNotification]:
        async with self._pool.connection() as connection:
            rows = await (
                await connection.execute(
                    """
                    SELECT n.id, n.faq_entry_id, f.question, f.answer, n.published_at
                    FROM course_notifications AS n
                    JOIN faq_entries AS f ON f.id = n.faq_entry_id AND f.active
                    LEFT JOIN course_notification_reads AS r
                      ON r.notification_id = n.id AND r.user_id = %s
                    WHERE r.notification_id IS NULL
                    ORDER BY n.published_at DESC, n.id
                    """,
                    (user_id,),
                )
            ).fetchall()
        return [CourseNotification.model_validate(row) for row in rows]

    async def mark_read(
        self,
        *,
        user_id: UUID,
        notification_id: UUID,
        read_at: datetime,
    ) -> bool:
        async with self._pool.connection() as connection:
            cursor = await connection.execute(
                """
                INSERT INTO course_notification_reads (notification_id, user_id, read_at)
                SELECT id, %s, %s FROM course_notifications WHERE id = %s
                ON CONFLICT (notification_id, user_id) DO NOTHING
                RETURNING notification_id
                """,
                (user_id, read_at, notification_id),
            )
            if await cursor.fetchone() is not None:
                return True
            row = await (
                await connection.execute(
                    """
                    SELECT 1 FROM course_notification_reads
                    WHERE notification_id = %s AND user_id = %s
                    """,
                    (notification_id, user_id),
                )
            ).fetchone()
        return row is not None


class NotificationAccessDenied(RuntimeError):
    """Only the exact active student account may access its notification state."""


class StudentNotificationService:
    def __init__(self, *, faqs: FaqNotificationStore, auth: AuthStore) -> None:
        self._faqs = faqs
        self._auth = auth

    async def list_unread(self, principal: PrincipalContext) -> list[CourseNotification]:
        user_id = await self._student_user_id(principal)
        return await self._faqs.list_unread(user_id)

    async def mark_read(
        self,
        principal: PrincipalContext,
        notification_id: UUID,
    ) -> bool:
        user_id = await self._student_user_id(principal)
        return await self._faqs.mark_read(
            user_id=user_id,
            notification_id=notification_id,
            read_at=_clock(),
        )

    async def _student_user_id(self, principal: PrincipalContext) -> UUID:
        if (
            not principal.authenticated
            or principal.user_id is None
            or "student" not in principal.roles
        ):
            raise NotificationAccessDenied("student login required")
        user = await self._auth.get_user_by_id(principal.user_id)
        if user is None or not user.active or user.role != "student":
            raise NotificationAccessDenied("student login required")
        return user.id


class PublishedFaqResourceCatalog:
    """Adds approved local FAQs to the registered public FAQ resource."""

    def __init__(self, base: CourseResourceCatalog, faqs: FaqKnowledgeStore) -> None:
        self._base = base
        self._faqs = faqs

    def list_public(self) -> list[ResourceSummary]:
        return self._base.list_public()

    def list_authorized(self, principal: PrincipalContext) -> list[ResourceSummary]:
        return self._base.list_authorized(principal)

    def authorized_resource_uris(self, principal: PrincipalContext) -> tuple[str, ...]:
        return self._base.authorized_resource_uris(principal)

    def is_public(self, uri: str) -> bool:
        return self._base.is_public(uri)

    def asset_ids(self, uri: str) -> tuple[str, ...]:
        return self._base.asset_ids(uri)

    async def read_asset(self, uri: str, asset_id: str) -> ResourceFile:
        return await self._base.read_asset(uri, asset_id)

    async def read(self, uri: str) -> ResourceContents:
        contents = await self._base.read(uri)
        if uri != COURSE_FAQ_URI:
            return contents
        appendix = await self._approved_markdown()
        return contents.model_copy(update={"text": f"{contents.text.rstrip()}{appendix}\n"})

    async def read_file(self, uri: str) -> ResourceFile:
        resource_file = await self._base.read_file(uri)
        if uri != COURSE_FAQ_URI:
            return resource_file
        appendix = await self._approved_markdown()
        return ResourceFile(
            uri=resource_file.uri,
            title=resource_file.title,
            media_type=resource_file.media_type,
            data=resource_file.data.rstrip() + appendix.encode("utf-8") + b"\n",
        )

    async def search(
        self,
        query: str,
        *,
        limit: int,
        resource_uris: frozenset[str],
    ) -> list[CourseSearchResult]:
        base_matches = await self._base.search(
            query,
            limit=limit,
            resource_uris=resource_uris,
        )
        if COURSE_FAQ_URI not in resource_uris:
            return base_matches
        terms = tuple(dict.fromkeys(re.findall(r"[a-z0-9]+", query.casefold())))
        dynamic: list[CourseSearchResult] = []
        for entry in await self._faqs.list_active():
            text = f"Question: {entry.question}\nAnswer: {entry.answer}"
            haystack = text.casefold()
            score = sum(haystack.count(term) for term in terms)
            if score:
                dynamic.append(
                    CourseSearchResult(
                        uri=COURSE_FAQ_URI,
                        title="Course FAQ",
                        excerpt=text[:480],
                        score=score,
                        status="published",
                    )
                )
        matches = [*base_matches, *dynamic]
        matches.sort(key=lambda match: (-match.score, match.uri, match.excerpt))
        return matches[:limit]

    async def _approved_markdown(self) -> str:
        entries = await self._faqs.list_active()
        if not entries:
            return ""
        sections = ["\n\n## Staff-approved updates"]
        for entry in entries:
            sections.append(f"\n### {entry.question}\n\n{entry.answer}")
        return "".join(sections)
