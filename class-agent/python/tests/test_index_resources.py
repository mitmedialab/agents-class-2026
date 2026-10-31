import json
from pathlib import Path

import pytest
from pypdf import PdfWriter

from course_server.index_resources import (
    DEFAULT_FAQ_PATH,
    load_faq_document,
    normalize_resource_text,
    refresh_resource_registry,
)


def test_resource_normalization_is_deterministic() -> None:
    assert normalize_resource_text("One\n\n  two\tthree") == "One two three"


def test_seed_faq_has_stable_unique_entries() -> None:
    faq = load_faq_document()

    assert len(faq.entries) >= 4
    assert len({entry.id for entry in faq.entries}) == len(faq.entries)


def test_seed_faq_documents_weekly_assignment_extension_policy() -> None:
    faq = load_faq_document()

    policy = next(
        entry
        for entry in faq.entries
        if entry.question == "What is the late policy for weekly assignments?"
    )
    assert "two extensions during the semester" in policy.answer
    assert "each for up to three days" in policy.answer
    assert "do not need to provide a reason" in policy.answer
    assert "before the deadline" in policy.answer
    assert "handled individually" in policy.answer

    faq_markdown = DEFAULT_FAQ_PATH.with_suffix(".md").read_text(encoding="utf-8")
    assert f"### {policy.question}" in faq_markdown
    assert policy.answer in faq_markdown


def test_resource_registry_is_generated_from_sidecar_manifests(tmp_path: Path) -> None:
    resource_directory = tmp_path / "shared/course/guide"
    resource_directory.mkdir(parents=True)
    (resource_directory / "guide.md").write_text("# Guide\n", encoding="utf-8")
    (resource_directory / "portrait.jpg").write_bytes(b"jpeg fixture")
    (resource_directory / "resource.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "resource": {
                    "uri": "course://guide",
                    "title": "Guide",
                    "description": "A generated registry entry.",
                    "media_type": "text/markdown",
                    "file": "guide.md",
                    "assets": {"guide_portrait": "portrait.jpg"},
                    "visibility": "public",
                    "status": "published",
                    "announcement": {
                        "revision": "fall-2026-v1",
                        "published_at": "2026-09-05T12:00:00Z",
                        "summary": "The guide is now available.",
                    },
                    "deadline": {
                        "kind": "assignment",
                        "due_at": "2026-09-17T23:59:00-04:00",
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    registry_path = tmp_path / "shared/registry/resources.json"

    assert refresh_resource_registry(registry_path) == ["course://guide"]
    generated = json.loads(registry_path.read_text(encoding="utf-8"))
    assert generated["resources"][0]["path"] == "course/guide/guide.md"
    assert generated["resources"][0]["assets"] == {"guide_portrait": "course/guide/portrait.jpg"}
    assert generated["resources"][0]["announcement"]["revision"] == "fall-2026-v1"
    assert generated["resources"][0]["deadline"]["kind"] == "assignment"


def test_slide_thumbnail_is_generated_and_refreshed_with_deck_bytes(tmp_path: Path) -> None:
    from PIL import Image
    from pypdf import PdfWriter

    directory = tmp_path / "shared/course/slides/week-01"
    directory.mkdir(parents=True)
    pdf_path = directory / "slides.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=1600, height=900)
    writer.write(pdf_path)
    (directory / "resource.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "resource": {
                    "uri": "course://slides/week-01",
                    "title": "Lecture",
                    "media_type": "application/pdf",
                    "file": "slides.pdf",
                },
            }
        )
    )
    registry_path = tmp_path / "shared/registry/resources.json"
    refresh_resource_registry(registry_path)
    asset = json.loads(registry_path.read_text())["resources"][0]["assets"]["first_slide"]
    with Image.open(tmp_path / "shared" / asset) as image:
        assert image.size == (320, 180)
    refresh_resource_registry(registry_path)
    assert json.loads(registry_path.read_text())["resources"][0]["assets"]["first_slide"] == asset
    writer.add_blank_page(width=1600, height=900)
    writer.write(pdf_path)
    refresh_resource_registry(registry_path)
    assert json.loads(registry_path.read_text())["resources"][0]["assets"]["first_slide"] != asset


def test_slide_accessibility_sidecar_is_registered_inside_its_deck_directory(
    tmp_path: Path,
) -> None:
    directory = tmp_path / "shared/course/slides/week-01"
    directory.mkdir(parents=True)
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=345)
    writer.write(directory / "slides.pdf")
    (directory / "accessibility.txt").write_text("1 | A visible diagram.\n", encoding="utf-8")
    manifest_path = directory / "resource.json"
    resource_manifest = {
        "uri": "course://slides/week-01",
        "title": "Lecture",
        "media_type": "application/pdf",
        "file": "slides.pdf",
        "accessibility_file": "accessibility.txt",
    }
    manifest = {"schema_version": 1, "resource": resource_manifest}
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    registry_path = tmp_path / "shared/registry/resources.json"

    refresh_resource_registry(registry_path)
    entry = json.loads(registry_path.read_text())["resources"][0]
    assert entry["accessibility_path"] == "course/slides/week-01/accessibility.txt"

    resource_manifest["accessibility_file"] = "../outside.txt"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    (directory.parent / "outside.txt").write_text("1 | Outside.\n", encoding="utf-8")
    with pytest.raises(ValueError, match="invalid accessibility file"):
        refresh_resource_registry(registry_path)
