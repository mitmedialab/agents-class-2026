from __future__ import annotations

import asyncio
import stat
from pathlib import Path
from uuid import uuid4

import pytest

from agent_core import PrincipalContext
from course_server.uploads import FileTemporaryUploadStore, UploadError


def public_principal() -> PrincipalContext:
    session_id = uuid4()
    return PrincipalContext(
        authenticated=False,
        anonymous_session_id=session_id,
        roles=["public"],
        session_id=session_id,
    )


def test_temporary_upload_is_private_and_principal_scoped(tmp_path: Path) -> None:
    async def scenario() -> None:
        store = FileTemporaryUploadStore(tmp_path / "uploads")
        owner = public_principal()
        receipt = await store.store(
            filename="../portrait.png",
            media_type="image/png; charset=binary",
            content=b"\x89PNG\r\n\x1a\nphoto-data",
            principal=owner,
        )

        assert receipt.filename == "portrait.png"
        assert receipt.media_type == "image/png"
        assert receipt.expires_at > receipt.created_at
        stored = await store.get_for_principal(receipt.id, owner)
        assert stored.path.read_bytes().endswith(b"photo-data")
        assert stat.S_IMODE(stored.path.stat().st_mode) == 0o600
        assert stat.S_IMODE(stored.path.parent.stat().st_mode) == 0o700

        with pytest.raises(UploadError, match="unavailable to this session"):
            await store.get_for_principal(receipt.id, public_principal())

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("filename", "media_type", "content", "message"),
    [
        ("empty.txt", "text/plain", b"", "empty"),
        ("script.js", "application/javascript", b"alert(1)", "unsupported"),
        ("", "text/plain", b"text", "filename"),
    ],
)
def test_temporary_upload_rejects_invalid_files(
    tmp_path: Path,
    filename: str,
    media_type: str,
    content: bytes,
    message: str,
) -> None:
    async def scenario() -> None:
        store = FileTemporaryUploadStore(tmp_path / "uploads")
        with pytest.raises(UploadError, match=message):
            await store.store(
                filename=filename,
                media_type=media_type,
                content=content,
                principal=public_principal(),
            )

    asyncio.run(scenario())
