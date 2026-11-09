"""Loopback-only review harness; never mounted in the production Course Agent API.

Reviewed examples exercise the real private store and validation. Optional live mode
uses the existing CourseAgentService + SmolagentsRuntime; no second agent definition.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field, JsonValue, SecretStr

from agent_core import PrincipalContext
from course_server.agent import (
    CourseAgentService,
    CourseCapabilityPolicy,
    CourseReadPublicFileTool,
    CourseShowPublicFilesTool,
    FileResourceProvider,
    InMemoryConversationStore,
    ReadSkillReferenceTool,
    ReadSkillTool,
    ResourceDefinition,
    SkillCatalog,
    ToolCatalog,
    ToolExecutionContext,
    ToolValidationError,
)
from course_server.agent.capabilities import AuthorizedCapabilities
from course_server.config import AgentSettings
from course_server.weekly_dreams import (
    TOOL_IDS,
    DreamDraft,
    DreamFeedback,
    FileDreamStore,
    StudentFocus,
    WeeklyDreamService,
    WeeklyDreamTool,
)
from runtime_smolagents import OpenAIModelProvider, SmolagentsRuntime

ROOT = Path(__file__).resolve().parents[2]
PREVIEW_PORT = 8767
PREVIEW_USER_ID = UUID("b65f4cba-2058-4ebc-8b8a-858e2f27f559")


class PreviewAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["example", "reset_example", "live", "profile", "feedback", "clear"]
    payload: dict[str, JsonValue] = Field(default_factory=dict)


class PreviewPolicy(CourseCapabilityPolicy):
    """The harness intentionally grants only dream, source-read, and Skill tools."""

    def authorize(self, principal: PrincipalContext) -> AuthorizedCapabilities:
        allowed = super().authorize(principal)
        return AuthorizedCapabilities(
            tool_ids=(*TOOL_IDS[:3], "course.read_public_file", "course.show_public_files"),
            resource_uris=allowed.resource_uris,
            resource_index=allowed.resource_index,
        )


def create_preview_app(
    *, state_path: Path | None = None, fixture_path: Path | None = None
) -> FastAPI:
    fixture = json.loads((fixture_path or ROOT / "examples/weekly-dream/brooke.json").read_text())
    principal = PrincipalContext(
        authenticated=True,
        user_id=PREVIEW_USER_ID,
        username="test-brooke-dream",
        display_name=fixture["name"],
        roles=["public", "student"],
        session_id=uuid4(),
    )
    resources = FileResourceProvider(
        [
            ResourceDefinition(
                uri="course://slides/week-07",
                title="Memory & Personalization — lecture text",
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
    store = FileDreamStore(state_path or ROOT / "var/dream-preview")
    service = WeeklyDreamService(store, resources)
    # Only a missing record is seeded; clearing memory remains cleared across restarts.
    if not (store.root / f"{principal.user_id}.json").exists():
        service.update_profile(principal, StudentFocus.model_validate(fixture["profile"]))
    app = FastAPI(title="Weekly dream — local review")
    generation_lock = asyncio.Lock()

    def context() -> ToolExecutionContext:
        return ToolExecutionContext(
            principal=principal,
            conversation_id=uuid4(),
            permitted_resource_uris=frozenset(fixture["resource_uris"]),
        )

    @app.middleware("http")
    async def local_only(request: Request, call_next):  # type: ignore[no-untyped-def]
        if request.url.hostname not in {"127.0.0.1", "localhost", "testserver"}:
            return JSONResponse({"detail": "Local review only"}, status_code=403)
        origin = request.headers.get("origin")
        if (
            request.method == "POST"
            and origin
            and origin
            not in {
                f"http://127.0.0.1:{PREVIEW_PORT}",
                f"http://localhost:{PREVIEW_PORT}",
                "http://testserver",
            }
        ):
            return JSONResponse({"detail": "Cross-origin request denied"}, status_code=403)
        if request.method == "POST" and not request.headers.get("content-type", "").startswith(
            "application/json"
        ):
            return JSONResponse({"detail": "JSON required"}, status_code=415)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(ROOT / "examples/weekly-dream/preview.html")

    @app.get("/tokens.css")
    def tokens() -> FileResponse:
        return FileResponse(ROOT / "packages/ui/src/styles.css")

    @app.get("/state")
    def state() -> dict[str, object]:
        return {
            "name": fixture["name"],
            "week": fixture["week"],
            "memory": store.read(principal).model_dump(mode="json"),
            "live_available": bool(os.environ.get("OPENAI_API_KEY")),
            "notice": fixture["notice"],
        }

    @app.post("/action")
    async def action(value: PreviewAction) -> dict[str, object]:
        try:
            if value.action == "profile":
                service.update_profile(principal, StudentFocus.model_validate(value.payload))
            elif value.action == "feedback":
                service.feedback(principal, DreamFeedback.model_validate(value.payload))
            elif value.action in {"clear", "reset_example"}:
                if value.payload != {"confirm": True}:
                    raise ToolValidationError("Explicit confirmation required.")
                async with generation_lock:
                    await WeeklyDreamTool(TOOL_IDS[5], service).execute(
                        {"confirm": True}, context()
                    )
                    if value.action == "reset_example":
                        revision = store.read(principal).profile.revision
                        profile = StudentFocus.model_validate(fixture["profile"])
                        service.update_profile(
                            principal, profile.model_copy(update={"revision": revision})
                        )
            elif value.action == "example":
                async with generation_lock:
                    ctx = context()
                    await service.prepare(ctx, fixture["week"], fixture["resource_uris"])
                    existing = {
                        item.key for d in store.read(principal).dreams for item in d.draft.items
                    }
                    edition = next(
                        (
                            d
                            for d in fixture["editions"]
                            if not existing.intersection(i["key"] for i in d["items"])
                        ),
                        None,
                    )
                    if edition is None:
                        raise ToolValidationError(
                            "Both reviewed examples are saved. Reset the Brooke sample to replay."
                        )
                    if existing and not any(
                        f.item_key == "memory-association-coverage"
                        and f.rating == "already_explored"
                        for f in store.read(principal).feedback
                    ):
                        raise ToolValidationError(
                            "For this scripted follow-up, mark the first connection "
                            "Already explored."
                        )
                    service.save(ctx, DreamDraft.model_validate(edition), mode="reviewed_example")
            else:
                async with generation_lock:
                    key = os.environ.get("OPENAI_API_KEY")
                    if not key:
                        raise ToolValidationError(
                            "Set OPENAI_API_KEY in your uncommitted .env to run live generation."
                        )
                    from course_server.dream_intelligence import RuntimeDreamIntelligence

                    provider = OpenAIModelProvider(
                        model_id=os.environ.get("MODEL_ID")
                        or str(AgentSettings.model_fields["model_id"].default),
                        api_key=SecretStr(key),
                    )
                    service.tracker.intelligence = RuntimeDreamIntelligence(provider)
                    skills = SkillCatalog.from_registry(ROOT / "skills")
                    tools = ToolCatalog(
                        [
                            *(WeeklyDreamTool(tool_id, service) for tool_id in TOOL_IDS),
                            CourseReadPublicFileTool(resources),
                            CourseShowPublicFilesTool(resources),
                            ReadSkillTool(skills),
                            ReadSkillReferenceTool(skills),
                        ]
                    )
                    runtime = SmolagentsRuntime(
                        model_provider=provider,
                        tools=tools,
                        public_resource_index=(r.title for r in resources.list_public()),
                        max_steps=12,
                    )
                    agent = CourseAgentService(
                        runtime=runtime,
                        conversations=InMemoryConversationStore(),
                        capability_policy=PreviewPolicy(resources),
                        skills=skills,
                    )
                    conversation = await agent.create_conversation(principal)
                    previous_ids = {d.id for d in store.read(principal).dreams}
                    await agent.run(
                        principal=principal,
                        conversation_id=conversation.id,
                        text=(
                            f"Create and save my weekly dream for build week {fixture['week']}. "
                            "Read the weekly-dream skill. Use the available memory lecture and "
                            "course schedule. Read my saved focus and feedback. Do not edit my "
                            "profile or clear memory. Omit a person without verified peer evidence."
                        ),
                    )
                    if not any(d.id not in previous_ids for d in store.read(principal).dreams):
                        raise ToolValidationError(
                            "The model did not save a validated dream; no success is being claimed."
                        )
            return state()
        except (ValueError, PermissionError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from None
        except Exception:
            raise HTTPException(
                status_code=502,
                detail="Generation failed; no verified success. Check local server configuration.",
            ) from None

    return app


def main() -> None:
    import uvicorn

    load_dotenv(ROOT / ".env", override=False)
    uvicorn.run(create_preview_app(), host="127.0.0.1", port=PREVIEW_PORT)


if __name__ == "__main__":
    main()
