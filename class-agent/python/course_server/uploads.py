"""Principal-scoped temporary uploads for chat and application attachments."""

from __future__ import annotations

import asyncio
import os
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from agent_core import PrincipalContext

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
UPLOAD_TTL = timedelta(hours=24)
ALLOWED_UPLOAD_MEDIA_TYPES = frozenset(
    {
        "application/json",
        "application/pdf",
        "image/gif",
        "image/jpeg",
        "image/png",
        "image/webp",
        "text/csv",
        "text/markdown",
        "text/plain",
    }
)
APPLICATION_PHOTO_MEDIA_TYPES = frozenset({"image/jpeg", "image/png", "image/webp"})


class UploadError(RuntimeError):
    """A temporary upload was invalid, unavailable, expired, or foreign."""


class TemporaryUploadReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID
    filename: str
    media_type: str
    size_bytes: int = Field(ge=1, le=MAX_UPLOAD_BYTES)
    created_at: datetime
    expires_at: datetime


class _UploadMetadata(TemporaryUploadReceipt):
    principal_user_id: UUID | None = None
    anonymous_session_id: UUID | None = None


@dataclass(frozen=True)
class StoredTemporaryUpload:
    receipt: TemporaryUploadReceipt
    path: Path


class TemporaryUploadStore(Protocol):
    async def store(
        self,
        *,
        filename: str,
        media_type: str,
        content: bytes,
        principal: PrincipalContext,
    ) -> TemporaryUploadReceipt: ...

    async def get_for_principal(
        self,
        upload_id: UUID,
        principal: PrincipalContext,
    ) -> StoredTemporaryUpload: ...


class FileTemporaryUploadStore:
    """Private filesystem storage with generated paths and enforced expiry/ownership."""

    def __init__(self, directory: Path) -> None:
        self._directory = directory

    async def store(
        self,
        *,
        filename: str,
        media_type: str,
        content: bytes,
        principal: PrincipalContext,
    ) -> TemporaryUploadReceipt:
        safe_filename = _safe_filename(filename)
        normalized_media_type = media_type.partition(";")[0].strip().casefold()
        if normalized_media_type not in ALLOWED_UPLOAD_MEDIA_TYPES:
            raise UploadError("unsupported file type")
        if not content:
            raise UploadError("uploaded file is empty")
        if len(content) > MAX_UPLOAD_BYTES:
            raise UploadError("uploaded file exceeds the 10 MB limit")

        created_at = datetime.now(UTC)
        metadata = _UploadMetadata(
            id=uuid4(),
            filename=safe_filename,
            media_type=normalized_media_type,
            size_bytes=len(content),
            created_at=created_at,
            expires_at=created_at + UPLOAD_TTL,
            principal_user_id=principal.user_id,
            anonymous_session_id=principal.anonymous_session_id,
        )
        await asyncio.to_thread(self._write, metadata, content)
        return _receipt_from_metadata(metadata)

    async def get_for_principal(
        self,
        upload_id: UUID,
        principal: PrincipalContext,
    ) -> StoredTemporaryUpload:
        return await asyncio.to_thread(self._get, upload_id, principal)

    def _write(self, metadata: _UploadMetadata, content: bytes) -> None:
        self._directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._directory.chmod(0o700)
        self._remove_expired(datetime.now(UTC))
        upload_directory = self._directory / str(metadata.id)
        upload_directory.mkdir(mode=0o700)
        try:
            _write_private(upload_directory / "content.bin", content)
            _write_private(
                upload_directory / "metadata.json",
                (metadata.model_dump_json(indent=2) + "\n").encode(),
            )
        except Exception:
            shutil.rmtree(upload_directory, ignore_errors=True)
            raise

    def _get(
        self,
        upload_id: UUID,
        principal: PrincipalContext,
    ) -> StoredTemporaryUpload:
        upload_directory = self._directory / str(upload_id)
        try:
            metadata = _UploadMetadata.model_validate_json(
                (upload_directory / "metadata.json").read_text(encoding="utf-8")
            )
        except (OSError, ValueError) as error:
            raise UploadError("temporary upload was not found") from error
        if metadata.id != upload_id:
            raise UploadError("temporary upload metadata is invalid")
        if metadata.expires_at <= datetime.now(UTC):
            shutil.rmtree(upload_directory, ignore_errors=True)
            raise UploadError("temporary upload has expired")
        if (
            metadata.principal_user_id != principal.user_id
            or metadata.anonymous_session_id != principal.anonymous_session_id
        ):
            raise UploadError("temporary upload is unavailable to this session")
        content_path = upload_directory / "content.bin"
        if not content_path.is_file():
            raise UploadError("temporary upload content was not found")
        receipt = _receipt_from_metadata(metadata)
        return StoredTemporaryUpload(receipt=receipt, path=content_path)

    def _remove_expired(self, now: datetime) -> None:
        for candidate in self._directory.iterdir():
            if not candidate.is_dir() or candidate.is_symlink():
                continue
            try:
                UUID(candidate.name)
                metadata = _UploadMetadata.model_validate_json(
                    (candidate / "metadata.json").read_text(encoding="utf-8")
                )
            except (OSError, ValueError):
                continue
            if metadata.expires_at <= now:
                shutil.rmtree(candidate, ignore_errors=True)


def _safe_filename(filename: str) -> str:
    normalized = "".join(character for character in filename if character.isprintable()).strip()
    basename = Path(normalized).name
    if not basename:
        raise UploadError("filename is required")
    if len(basename) > 255:
        raise UploadError("filename is too long")
    return basename


def _write_private(path: Path, content: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as output:
        output.write(content)


def _receipt_from_metadata(metadata: _UploadMetadata) -> TemporaryUploadReceipt:
    return TemporaryUploadReceipt(
        id=metadata.id,
        filename=metadata.filename,
        media_type=metadata.media_type,
        size_bytes=metadata.size_bytes,
        created_at=metadata.created_at,
        expires_at=metadata.expires_at,
    )
