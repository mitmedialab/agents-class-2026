from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest

from course_server.notification_portraits import StudentNotificationPortraitRegistry


def test_portrait_registry_resolves_explicit_user_id(tmp_path: Path) -> None:
    user_id = uuid4()
    path = tmp_path / "student-notification-portraits.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "portraits": [
                    {
                        "user_id": str(user_id),
                        "asset_id": "valdemar_danry_portrait",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    registry = StudentNotificationPortraitRegistry.from_path(path)

    assert registry.asset_id_for(user_id) == "valdemar_danry_portrait"
    assert registry.asset_id_for(uuid4()) is None


def test_portrait_registry_rejects_duplicate_user_ids(tmp_path: Path) -> None:
    user_id = uuid4()
    path = tmp_path / "student-notification-portraits.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "portraits": [
                    {"user_id": str(user_id), "asset_id": "first_portrait"},
                    {"user_id": str(user_id), "asset_id": "second_portrait"},
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="duplicate user IDs"):
        StudentNotificationPortraitRegistry.from_path(path)


def test_missing_portrait_registry_is_empty(tmp_path: Path) -> None:
    registry = StudentNotificationPortraitRegistry.from_path(tmp_path / "missing.json")

    assert registry.asset_id_for(uuid4()) is None
