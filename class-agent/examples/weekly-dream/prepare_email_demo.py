"""Prepare two Codex-authored examples through the real validator; never sends mail."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from uuid import uuid4

from agent_core import PrincipalContext
from course_server.agent import FileResourceProvider, ResourceDefinition, ToolExecutionContext
from course_server.dream_email import email_body, email_html
from course_server.dream_preview import PREVIEW_USER_ID
from course_server.weekly_dreams import DreamDraft, FileDreamStore, StudentFocus, WeeklyDreamService

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "var/dream-email-demo"


async def main() -> None:
    if OUT.exists():
        raise ValueError(
            "Email demo already prepared; preserve it instead of overwriting or resending."
        )
    fixture = json.loads((ROOT / "examples/weekly-dream/brooke.json").read_text())
    principal = PrincipalContext(
        authenticated=True,
        user_id=PREVIEW_USER_ID,
        username="test-brooke-dream",
        display_name="Brooke Smilen",
        roles=["public", "student"],
        session_id=uuid4(),
    )
    resources = FileResourceProvider(
        [
            ResourceDefinition(
                uri="course://slides/week-07",
                title="Memory & Personalization",
                media_type="text/plain",
                path=ROOT / "shared/course/slides/week-07/accessibility.txt",
            ),
            ResourceDefinition(
                uri="course://schedule",
                title="Course schedule and readings",
                media_type="text/markdown",
                path=ROOT / "shared/course/schedule/schedule.md",
            ),
        ]
    )
    store = FileDreamStore(OUT / "memory")
    service = WeeklyDreamService(store, resources)
    source_profile = FileDreamStore(ROOT / "var/dream-preview").read(principal).profile
    if not (source_profile.project or source_profile.interests):
        source_profile = StudentFocus.model_validate(fixture["profile"])
    service.update_profile(principal, source_profile.model_copy(update={"revision": 0}))
    contexts = [
        (
            8,
            fixture["resource_uris"],
            DreamDraft.model_validate(fixture["editions"][0]),
            "Weekly Dream demo — Memory & personalization",
        ),
        (
            9,
            ["course://schedule"],
            DreamDraft.model_validate(
                {
                    "week": 9,
                    "headline": "Let your agents perceive different things",
                    "items": [
                        {
                            "kind": "connection",
                            "key": "multimodal-diverse-perception",
                            "title": "A connection",
                            "text": "Moving from what your agents remember to what they perceive: tomorrow’s multimodal topic suggests giving agents an image, an audio clip, or a written description of the same scene. How do their ideas compare with a text-only associative network?",
                            "source_ids": ["course-1", "student-focus"],
                        },
                        {
                            "kind": "reading",
                            "key": "imagebind-shared-embedding",
                            "title": "Read ImageBind",
                            "text": "ImageBind’s shared embedding space offers one way to connect these inputs without converting everything into prose.",
                            "link": "https://openaccess.thecvf.com/content/CVPR2023/html/Girdhar_ImageBind_One_Embedding_Space_To_Bind_Them_All_CVPR_2023_paper.html",
                            "source_ids": ["course-1", "student-focus"],
                        },
                        {
                            "kind": "question",
                            "key": "alignment-versus-associative-diversity",
                            "title": "A question",
                            "text": "Does aligning different inputs help agents discover associations, or remove the differences that make their ideas novel?",
                            "source_ids": ["course-1", "student-focus"],
                        },
                    ],
                }
            ),
            "Weekly Dream demo — Multimodal agents · November 10",
        ),
    ]
    output = []
    for week, uris, draft, subject in contexts:
        context = ToolExecutionContext(
            principal=principal, conversation_id=uuid4(), permitted_resource_uris=frozenset(uris)
        )
        bundle = await service.prepare(context, week, uris)
        saved = service.save(context, draft, mode="reviewed_example")
        label = "memory" if week == 8 else "multimodal"
        words = len(
            (" ".join([draft.headline, *[i.title + " " + i.text for i in draft.items]])).split()
        )
        record = {
            "label": label,
            "subject": subject,
            "html": email_html(saved, demo=True),
            "plain_text": email_body(saved),
            "words": words,
            "authorship": "Codex-authored demonstration, not autonomous runtime output",
            "previous_dreams_in_context": len(bundle.previous_suggestions),
            "saved_dream": saved.model_dump(mode="json"),
        }
        output.append(record)
        (OUT / f"{label}.html").write_text(record["html"])
    (OUT / "messages.json").write_text(json.dumps(output, indent=2) + "\n")
    print(
        json.dumps(
            [
                {
                    "label": r["label"],
                    "words": r["words"],
                    "previous_dreams": r["previous_dreams_in_context"],
                }
                for r in output
            ]
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
