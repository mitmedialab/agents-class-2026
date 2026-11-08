"""Storage boundary for learning trails. Replace `FileTrailStore` to change the backend."""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
from collections.abc import Callable
from pathlib import Path
from threading import Lock
from typing import Protocol, TypeVar
from uuid import UUID

from pydantic import ValidationError

from course_server.agent.store import MemoryUnavailable

from .models import PendingDraft, TrailDocument, TrailEntry

MAX_TRAIL_FILE_BYTES = 2 * 1024 * 1024

Result = TypeVar("Result")


class TrailStoreError(MemoryUnavailable):
    """Stored trail data is invalid or unavailable."""


class TrailStore(Protocol):
    async def read(self, user_id: UUID) -> list[TrailEntry]: ...

    async def owners(self) -> list[UUID]:
        """Every student who has a saved trail."""
        ...

    async def update(
        self,
        user_id: UUID,
        change: Callable[[list[TrailEntry]], tuple[list[TrailEntry], Result]],
    ) -> Result:
        """Atomically replace one student's entries with what `change` returns."""
        ...


class FileTrailStore:
    """One validated JSON file per student. The name derives only from the trusted user UUID."""

    def __init__(self, directory: Path) -> None:
        self._directory = directory
        self._write_lock = Lock()

    async def read(self, user_id: UUID) -> list[TrailEntry]:
        return await asyncio.to_thread(self._read, user_id)

    async def owners(self) -> list[UUID]:
        return await asyncio.to_thread(self._owners)

    async def update(
        self,
        user_id: UUID,
        change: Callable[[list[TrailEntry]], tuple[list[TrailEntry], Result]],
    ) -> Result:
        return await asyncio.to_thread(self._update, user_id, change)

    def _path(self, user_id: UUID) -> Path:
        return self._directory / f"{user_id}.json"

    def _owners(self) -> list[UUID]:
        if not self._directory.is_dir():
            return []
        owners: list[UUID] = []
        for path in self._directory.glob("*.json"):
            try:
                owners.append(UUID(path.stem))
            except ValueError:
                continue
        return owners

    def _update(
        self,
        user_id: UUID,
        change: Callable[[list[TrailEntry]], tuple[list[TrailEntry], Result]],
    ) -> Result:
        with self._write_lock:
            entries, result = change(self._read(user_id))
            self._write(user_id, entries)
            return result

    def _read(self, user_id: UUID) -> list[TrailEntry]:
        path = self._path(user_id)
        if path.is_symlink():
            raise TrailStoreError("stored learning trail path is invalid")
        if not path.exists():
            return []
        try:
            if path.stat().st_size > MAX_TRAIL_FILE_BYTES:
                raise TrailStoreError("stored learning trail exceeds its size limit")
            document = TrailDocument.model_validate(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValidationError) as error:
            raise TrailStoreError("stored learning trail is malformed or unavailable") from error
        if document.user_id != user_id:
            raise TrailStoreError("stored learning trail does not belong to this student")
        return document.entries

    def _write(self, user_id: UUID, entries: list[TrailEntry]) -> None:
        document = TrailDocument(user_id=user_id, entries=entries)
        temporary: str | None = None
        try:
            if self._directory.is_symlink():
                raise TrailStoreError("learning trail directory is invalid")
            self._directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            self._directory.chmod(0o700)
            descriptor, temporary = tempfile.mkstemp(dir=self._directory, suffix=".tmp")
            with os.fdopen(descriptor, "w", encoding="utf-8") as output:
                output.write(document.model_dump_json(indent=2))
                output.write("\n")
            os.replace(temporary, self._path(user_id))
            temporary = None
        except OSError as error:
            raise TrailStoreError("learning trail could not be saved") from error
        finally:
            if temporary is not None:
                Path(temporary).unlink(missing_ok=True)


class FileDraftStore:
    """At most one pending agent-drafted entry per student, in its own small file."""

    def __init__(self, directory: Path) -> None:
        self._directory = directory

    async def read(self, user_id: UUID) -> PendingDraft | None:
        return await asyncio.to_thread(self._read, user_id)

    async def write(self, user_id: UUID, draft: PendingDraft) -> None:
        await asyncio.to_thread(self._write, user_id, draft)

    async def clear(self, user_id: UUID) -> None:
        await asyncio.to_thread(self._clear, user_id)

    def _path(self, user_id: UUID) -> Path:
        return self._directory / f"{user_id}.draft.json"

    def _read(self, user_id: UUID) -> PendingDraft | None:
        path = self._path(user_id)
        if not path.is_file():
            return None
        try:
            return PendingDraft.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, ValidationError) as error:
            raise TrailStoreError("stored draft is malformed or unavailable") from error

    def _write(self, user_id: UUID, draft: PendingDraft) -> None:
        temporary: str | None = None
        try:
            if self._directory.is_symlink():
                raise TrailStoreError("learning trail directory is invalid")
            self._directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            descriptor, temporary = tempfile.mkstemp(dir=self._directory, suffix=".tmp")
            with os.fdopen(descriptor, "w", encoding="utf-8") as output:
                output.write(draft.model_dump_json(indent=2))
                output.write("\n")
            os.replace(temporary, self._path(user_id))
            temporary = None
        except OSError as error:
            raise TrailStoreError("draft could not be saved") from error
        finally:
            if temporary is not None:
                Path(temporary).unlink(missing_ok=True)

    def _clear(self, user_id: UUID) -> None:
        try:
            self._path(user_id).unlink(missing_ok=True)
        except OSError as error:
            raise TrailStoreError("draft could not be removed") from error
