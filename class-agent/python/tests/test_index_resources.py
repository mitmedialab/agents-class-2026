import json
from pathlib import Path

from course_server.index_resources import (
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


def test_resource_registry_is_generated_from_sidecar_manifests(tmp_path: Path) -> None:
    resource_directory = tmp_path / "shared/course/guide"
    resource_directory.mkdir(parents=True)
    (resource_directory / "guide.md").write_text("# Guide\n", encoding="utf-8")
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
                    "visibility": "public",
                    "status": "published",
                },
            }
        ),
        encoding="utf-8",
    )
    registry_path = tmp_path / "shared/registry/resources.json"

    assert refresh_resource_registry(registry_path) == ["course://guide"]
    generated = json.loads(registry_path.read_text(encoding="utf-8"))
    assert generated["resources"][0]["path"] == "course/guide/guide.md"
