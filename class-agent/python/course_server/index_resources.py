"""Synchronize repository-owned public course resources into PostgreSQL search."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

import psycopg
from pydantic import BaseModel, ConfigDict

from course_server.agent import load_resource_definitions
from course_server.agent.capabilities import DEFAULT_RESOURCE_REGISTRY_PATH

DEFAULT_FAQ_PATH = DEFAULT_RESOURCE_REGISTRY_PATH.parent.parent / "course/faq/faq.json"


class FaqEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID
    question: str
    answer: str


class FaqDocument(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    entries: list[FaqEntry]


class ManifestResource(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    uri: str
    title: str
    description: str = ""
    media_type: str
    file: str
    visibility: Literal["public"] = "public"
    status: Literal["published", "provisional"] = "published"
    order: int = 1_000


class ResourceManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    resource: ManifestResource


def normalize_resource_text(text: str) -> str:
    """Produce deterministic text suitable for PostgreSQL full-text indexing."""

    return " ".join(text.split())


def load_faq_document(path: Path = DEFAULT_FAQ_PATH) -> FaqDocument:
    return FaqDocument.model_validate_json(path.read_text(encoding="utf-8"))


def refresh_resource_registry(
    registry_path: Path = DEFAULT_RESOURCE_REGISTRY_PATH,
) -> list[str]:
    """Regenerate resources.json from sidecar manifests under shared/course/."""

    shared_root = registry_path.parent.parent.resolve()
    course_root = shared_root / "course"
    ordered_entries: list[tuple[int, dict[str, str]]] = []
    seen_uris: set[str] = set()
    seen_paths: set[str] = set()
    for manifest_path in sorted(course_root.rglob("resource.json")):
        manifest = ResourceManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
        resource = manifest.resource
        if resource.uri in seen_uris:
            raise ValueError(f"duplicate resource URI in manifests: {resource.uri}")
        file_path = (manifest_path.parent / resource.file).resolve()
        if not file_path.is_relative_to(shared_root) or not file_path.is_file():
            raise ValueError(f"invalid resource file for {resource.uri}: {resource.file}")
        relative_path = file_path.relative_to(shared_root).as_posix()
        if relative_path in seen_paths:
            raise ValueError(f"duplicate resource file in manifests: {relative_path}")
        seen_uris.add(resource.uri)
        seen_paths.add(relative_path)
        ordered_entries.append(
            (
                resource.order,
                {
                    "uri": resource.uri,
                    "title": resource.title,
                    "description": resource.description,
                    "media_type": resource.media_type,
                    "path": relative_path,
                    "visibility": resource.visibility,
                    "status": resource.status,
                },
            )
        )
    ordered_entries.sort(key=lambda item: (item[0], item[1]["uri"]))
    entries = [entry for _, entry in ordered_entries]
    generated = (
        json.dumps(
            {"schema_version": 1, "resources": entries},
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )
    current = registry_path.read_text(encoding="utf-8") if registry_path.exists() else None
    if current != generated:
        registry_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = registry_path.with_name(f".{registry_path.name}.{uuid4().hex}.tmp")
        temporary_path.write_text(generated, encoding="utf-8")
        temporary_path.replace(registry_path)
    return [entry["uri"] for entry in entries]


def index_resources(
    database_url: str,
    *,
    registry_path: Path = DEFAULT_RESOURCE_REGISTRY_PATH,
    faq_path: Path = DEFAULT_FAQ_PATH,
) -> list[str]:
    """Upsert the public registry and FAQ, then remove stale indexed entries."""

    refresh_resource_registry(registry_path)
    definitions = load_resource_definitions(registry_path)
    faq = load_faq_document(faq_path)
    now = datetime.now(UTC)
    indexed_uris: list[str] = []

    with psycopg.connect(database_url) as connection, connection.transaction():
        for resource in definitions:
            text = resource.path.read_text(encoding="utf-8")
            normalized_text = normalize_resource_text(text)
            content_sha256 = hashlib.sha256(text.encode()).hexdigest()
            source_path = resource.path.relative_to(registry_path.parent.parent).as_posix()
            connection.execute(
                """
                INSERT INTO course_resources (
                    uri, title, description, media_type, visibility, status,
                    source_path, content_sha256, normalized_text, updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (uri) DO UPDATE SET
                    title = EXCLUDED.title,
                    description = EXCLUDED.description,
                    media_type = EXCLUDED.media_type,
                    visibility = EXCLUDED.visibility,
                    status = EXCLUDED.status,
                    source_path = EXCLUDED.source_path,
                    content_sha256 = EXCLUDED.content_sha256,
                    normalized_text = EXCLUDED.normalized_text,
                    updated_at = EXCLUDED.updated_at
                """,
                (
                    resource.uri,
                    resource.title,
                    resource.description,
                    resource.media_type,
                    resource.visibility,
                    resource.status,
                    source_path,
                    content_sha256,
                    normalized_text,
                    now,
                ),
            )
            indexed_uris.append(resource.uri)

        existing_resource_rows = connection.execute("SELECT uri FROM course_resources").fetchall()
        for (existing_uri,) in existing_resource_rows:
            if str(existing_uri) not in indexed_uris:
                connection.execute(
                    "DELETE FROM course_resources WHERE uri = %s",
                    (existing_uri,),
                )

        active_faq_ids = {entry.id for entry in faq.entries}
        for entry in faq.entries:
            connection.execute(
                """
                INSERT INTO faq_entries (
                    id, question, answer, source_question_id,
                    published_by_user_id, created_at, updated_at, active
                )
                VALUES (%s, %s, %s, NULL, NULL, %s, %s, true)
                ON CONFLICT (id) DO UPDATE SET
                    question = EXCLUDED.question,
                    answer = EXCLUDED.answer,
                    updated_at = EXCLUDED.updated_at,
                    active = true
                """,
                (entry.id, entry.question, entry.answer, now, now),
            )
        existing_faq_rows = connection.execute("SELECT id FROM faq_entries").fetchall()
        for (existing_id,) in existing_faq_rows:
            if existing_id not in active_faq_ids:
                connection.execute(
                    """
                    UPDATE faq_entries
                    SET active = false, updated_at = %s
                    WHERE id = %s
                    """,
                    (now, existing_id),
                )

    return indexed_uris


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Index public course resources in PostgreSQL")
    parser.add_argument(
        "--database-url",
        help="PostgreSQL URL; defaults to DATABASE_URL",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    database_url = arguments.database_url or os.environ.get("DATABASE_URL")
    if not database_url:
        raise SystemExit("DATABASE_URL or --database-url is required")
    indexed = index_resources(database_url)
    print(f"Indexed {len(indexed)} course resources:")
    for uri in indexed:
        print(f"- {uri}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
