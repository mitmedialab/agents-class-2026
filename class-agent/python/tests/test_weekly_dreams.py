"""Private memory, grounded citations, feedback continuity, and fail-closed tools."""

import asyncio
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from agent_core import PrincipalContext
from course_server.agent import (
    CourseCapabilityPolicy,
    FileResourceProvider,
    ResourceDefinition,
    ToolExecutionContext,
    ToolValidationError,
)
from course_server.weekly_dreams import (
    TOOL_IDS,
    DreamDraft,
    DreamFeedback,
    DreamItem,
    FileDreamStore,
    StudentFocus,
    WeeklyDreamService,
    WeeklyDreamTool,
)


def student(name: str = "brooke") -> PrincipalContext:
    return PrincipalContext(
        authenticated=True,
        user_id=uuid4(),
        username=name,
        display_name=name.title(),
        roles=["public", "student"],
        session_id=uuid4(),
    )


def setup_service(tmp_path: Path) -> tuple[WeeklyDreamService, ToolExecutionContext]:
    source = tmp_path / "lesson.md"
    source.write_text("# Memory\nSelective retrieval. Reading: https://arxiv.org/abs/2310.08560")
    resources = FileResourceProvider(
        [
            ResourceDefinition(
                uri="course://week/8", title="Memory", media_type="text/markdown", path=source
            )
        ]
    )
    service = WeeklyDreamService(FileDreamStore(tmp_path / "private"), resources)
    principal = student()
    service.update_profile(principal, StudentFocus(project="Associative idea networks"))
    return service, ToolExecutionContext(
        principal=principal,
        conversation_id=uuid4(),
        permitted_resource_uris=frozenset({"course://week/8"}),
    )


def draft(key: str = "retrieval-diversity") -> DreamDraft:
    return DreamDraft(
        week=8,
        headline="What should an idea network remember?",
        items=[
            DreamItem(
                kind="question",
                key=key,
                title="Memory and novelty",
                text="Could remembering previous associations narrow exploration?",
                source_ids=["course-1", "student-focus"],
            )
        ],
    )


def prepare(service: WeeklyDreamService, context: ToolExecutionContext) -> None:
    asyncio.run(service.prepare(context, 8, ["course://week/8"]))


def test_feedback_and_history_survive_new_conversation_and_process(tmp_path: Path) -> None:
    service, context = setup_service(tmp_path)
    prepare(service, context)
    saved = service.save(context, draft())
    service.feedback(
        context.principal,
        DreamFeedback(
            dream_id=saved.id,
            item_key="retrieval-diversity",
            rating="already_explored",
            note="Suggest something about communication constraints instead.",
        ),
    )
    restarted = WeeklyDreamService(FileDreamStore(tmp_path / "private"), service.resources)
    next_context = ToolExecutionContext(
        principal=context.principal,
        conversation_id=uuid4(),
        permitted_resource_uris=context.permitted_resource_uris,
    )
    bundle = asyncio.run(restarted.prepare(next_context, 8, ["course://week/8"]))
    assert bundle.feedback[0].rating == "already_explored"
    assert bundle.previous_suggestions[0].items[0].key == "retrieval-diversity"
    with pytest.raises(ToolValidationError, match="already made"):
        restarted.save(next_context, draft())
    new = restarted.save(next_context, draft("communication-constraints"))
    assert new.draft.items[0].key == "communication-constraints"
    assert service.store.read(student("someone-else")).dreams == []


@pytest.mark.parametrize("violation", ["missing", "link", "person", "no-personalization"])
def test_rejects_ungrounded_recommendations(tmp_path: Path, violation: str) -> None:
    service, context = setup_service(tmp_path)
    prepare(service, context)
    d = draft()
    if violation == "missing":
        d.items[0].source_ids = ["invented"]
    elif violation == "link":
        d.items[0].link = "https://invented.example/reading"
    elif violation == "person":
        d.items[0].kind = "person"
        d.items[0].person_name = "Invented classmate"
    else:
        d.items[0].source_ids = ["course-1"]
    with pytest.raises(ToolValidationError):
        service.save(context, d)


def test_profile_revision_and_clearing_invalidate_prepared_context(tmp_path: Path) -> None:
    service, context = setup_service(tmp_path)
    prepare(service, context)
    current = service.store.read(context.principal).profile
    service.update_profile(
        context.principal, StudentFocus(revision=current.revision, project="New direction")
    )
    with pytest.raises(ToolValidationError, match="focus changed"):
        service.save(context, draft())
    asyncio.run(WeeklyDreamTool(TOOL_IDS[5], service).execute({"confirm": True}, context))
    assert service.store.read(context.principal).profile.project == ""
    with pytest.raises(ToolValidationError, match="Prepare"):
        service.save(context, draft())


def test_unauthorized_inputs_and_other_students_feedback_are_rejected(tmp_path: Path) -> None:
    service, context = setup_service(tmp_path)
    with pytest.raises(PermissionError):
        asyncio.run(service.prepare(context, 8, ["course://private/grades"]))
    with pytest.raises(ValidationError):
        asyncio.run(
            WeeklyDreamTool(TOOL_IDS[2], service).execute({"user_id": str(uuid4())}, context)
        )
    prepare(service, context)
    saved = service.save(context, draft())
    with pytest.raises(ToolValidationError):
        service.feedback(
            student("other"),
            DreamFeedback(dream_id=saved.id, item_key="retrieval-diversity", rating="useful"),
        )
    assert (
        tmp_path / "private" / f"{context.principal.user_id}.json"
    ).stat().st_mode & 0o777 == 0o600


def test_policy_filters_before_model_and_tools_check_again(tmp_path: Path) -> None:
    service, context = setup_service(tmp_path)
    assert set(TOOL_IDS) <= set(
        CourseCapabilityPolicy(weekly_dream_enabled=True).authorize(context.principal).tool_ids
    )
    assert not set(TOOL_IDS).intersection(
        CourseCapabilityPolicy().authorize(context.principal).tool_ids
    )
    anonymous = PrincipalContext(
        authenticated=False, anonymous_session_id=uuid4(), roles=["public"], session_id=uuid4()
    )
    assert not set(TOOL_IDS).intersection(
        CourseCapabilityPolicy(weekly_dream_enabled=True).authorize(anonymous).tool_ids
    )
    with pytest.raises(PermissionError):
        asyncio.run(
            WeeklyDreamTool(TOOL_IDS[2], service).execute(
                {},
                ToolExecutionContext(
                    principal=anonymous,
                    conversation_id=uuid4(),
                    permitted_resource_uris=frozenset(),
                ),
            )
        )


def test_requires_prepare_and_matching_week(tmp_path: Path) -> None:
    service, context = setup_service(tmp_path)
    with pytest.raises(ToolValidationError):
        service.save(context, draft())
    prepare(service, context)
    d = draft()
    d.week = 9
    with pytest.raises(ToolValidationError):
        service.save(context, d)


def test_email_length_is_enforced_before_storage(tmp_path: Path) -> None:
    from course_server.dream_email import email_body, email_subject

    service, context = setup_service(tmp_path)
    prepare(service, context)
    too_long = draft()
    too_long.items[0].text = "word " * 111
    with pytest.raises(ToolValidationError, match="110 words"):
        service.save(context, too_long)
    assert not service.store.read(context.principal).dreams
    saved = service.save(context, draft())
    assert email_subject(saved) == "Your weekly dream · Week 8"
    assert saved.draft.items[0].text in email_body(saved)


def test_short_email_preview_and_feedback_continuity(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    from course_server.dream_preview import create_preview_app

    with TestClient(create_preview_app(state_path=tmp_path)) as client:
        first = client.post("/action", json={"action": "example"})
        assert first.status_code == 200
        saved = first.json()["memory"]["dreams"][0]
        words = saved["draft"]["headline"] + " ".join(
            i["title"] + " " + i["text"] for i in saved["draft"]["items"]
        )
        assert len(words.split()) <= 100
        assert client.post("/action", json={"action": "example"}).status_code == 400
        assert (
            client.post(
                "/action",
                json={
                    "action": "feedback",
                    "payload": {
                        "dream_id": saved["id"],
                        "item_key": "memory-association-coverage",
                        "rating": "already_explored",
                    },
                },
            ).status_code
            == 200
        )
        follow_up = client.post("/action", json={"action": "example"})
        assert follow_up.status_code == 200
        assert "compaction" in follow_up.json()["memory"]["dreams"][0]["draft"]["headline"]
        assert (
            client.post(
                "/action",
                json={"action": "clear"},
                headers={
                    "Origin": "https://untrusted.example",
                },
            ).status_code
            == 403
        )


def test_tool_schemas_survive_runtime_property_projection(tmp_path: Path) -> None:
    import json

    service, _ = setup_service(tmp_path)
    for tool_id in TOOL_IDS:
        schema = WeeklyDreamTool(tool_id, service).input_schema
        assert "$ref" not in json.dumps(schema)
        assert "$defs" not in schema
    save_schema = WeeklyDreamTool(TOOL_IDS[1], service).input_schema
    assert "source_ids" in json.dumps(save_schema["properties"])


def test_full_history_is_retained_after_many_weeks(tmp_path: Path) -> None:
    service, context = setup_service(tmp_path)
    for i in range(10):
        prepare(service, context)
        saved = service.save(context, draft(f"connection-{i}"))
        service.feedback(
            context.principal,
            DreamFeedback(
                dream_id=saved.id,
                item_key=f"connection-{i}",
                rating="useful",
            ),
        )
    memory = service.store.read(context.principal)
    assert len(memory.dreams) == 10
    assert len(memory.feedback) == 10
    retained = {d.id for d in memory.dreams}
    assert all(f.dream_id in retained for f in memory.feedback)


def test_reviewed_sample_reset_is_explicit_and_replayable(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    from course_server.dream_preview import create_preview_app

    with TestClient(create_preview_app(state_path=tmp_path)) as client:
        assert client.post("/action", json={"action": "example"}).status_code == 200
        assert (
            client.post(
                "/action",
                json={
                    "action": "clear",
                    "payload": {"confirm": True},
                },
            ).status_code
            == 200
        )
        assert client.get("/state").json()["memory"]["profile"]["project"] == ""
        assert client.post("/action", json={"action": "reset_example"}).status_code == 400
        # Restarting does not silently restore an intentionally cleared profile.
    with TestClient(create_preview_app(state_path=tmp_path)) as client:
        assert client.get("/state").json()["memory"]["profile"]["project"] == ""
        reset = client.post(
            "/action",
            json={
                "action": "reset_example",
                "payload": {"confirm": True},
            },
        )
        assert reset.status_code == 200
        assert reset.json()["memory"]["profile"]["project"]
        assert reset.json()["memory"]["dreams"] == []
        assert client.post("/action", json={"action": "example"}).status_code == 200


@pytest.mark.parametrize("field", ["headline", "title", "text"])
def test_rejects_invented_links_in_email_prose(tmp_path: Path, field: str) -> None:
    service, context = setup_service(tmp_path)
    prepare(service, context)
    d = draft()
    if field == "headline":
        d.headline = "See https://invented.example/paper"
    else:
        setattr(d.items[0], field, "See https://invented.example/paper")
    with pytest.raises(ToolValidationError, match="Links"):
        service.save(context, d)
    assert service.store.read(context.principal).dreams == []


def test_accepts_evidenced_links_followed_by_sentence_punctuation(tmp_path: Path) -> None:
    from course_server.weekly_dreams import make_source

    source = make_source(
        "course-1", "Reading", "course://reading", "Read https://arxiv.org/abs/2310.08560."
    )
    assert source.links == ["https://arxiv.org/abs/2310.08560"]
    service, context = setup_service(tmp_path)
    prepare(service, context)
    d = draft()
    d.items[0].text = "Read https://arxiv.org/abs/2310.08560."
    assert service.save(context, d).draft.items[0].text.endswith(".")


def test_real_runtime_prepares_and_saves_without_private_event_payloads(tmp_path: Path) -> None:
    import json
    from typing import Any

    from smolagents import ChatMessage, ChatMessageToolCall, Model
    from smolagents.models import ChatMessageToolCallFunction, MessageRole

    from agent_core import AgentContext, AgentInput, ModelProvider
    from course_server.agent import ToolCatalog
    from runtime_smolagents import SmolagentsRuntime

    service, context = setup_service(tmp_path)
    suggestion = draft()

    class DreamModel(Model):  # type: ignore[misc]
        def __init__(self) -> None:
            super().__init__(model_id="scripted-dream-model")
            self.calls = 0
            self.tool_names: list[str] = []

        def generate(
            self,
            messages: list[ChatMessage],
            stop_sequences: list[str] | None = None,
            response_format: dict[str, str] | None = None,
            tools_to_call_from: list[Any] | None = None,
            **kwargs: Any,
        ) -> ChatMessage:
            del messages, stop_sequences, response_format, kwargs
            self.tool_names = [t.name for t in tools_to_call_from or []]
            script = [
                ("dream_prepare_mine", {"week": 8, "resource_uris": ["course://week/8"]}),
                ("dream_save_mine", suggestion.model_dump(mode="json")),
                ("final_answer", {"answer": "Saved your weekly dream."}),
            ]
            name, arguments = script[self.calls]
            self.calls += 1
            return ChatMessage(
                role=MessageRole.ASSISTANT,
                content="",
                tool_calls=[
                    ChatMessageToolCall(
                        id=f"call-{self.calls}",
                        type="function",
                        function=ChatMessageToolCallFunction(name=name, arguments=arguments),
                    ),
                ],
            )

    class Provider(ModelProvider[Model]):
        provider_id = "scripted"
        model_id = "scripted-dream-model"

        def create_model(self) -> Model:
            return model

    model = DreamModel()
    runtime = SmolagentsRuntime(
        model_provider=Provider(),
        tools=ToolCatalog([WeeklyDreamTool(t, service) for t in TOOL_IDS]),
    )
    result = asyncio.run(
        runtime.run(
            context=AgentContext(
                principal=context.principal,
                conversation_id=context.conversation_id,
                permitted_tool_ids=list(TOOL_IDS[:3]),
                permitted_resource_uris=list(context.permitted_resource_uris),
            ),
            input=AgentInput(conversation_id=context.conversation_id, text="Make my weekly dream."),
        )
    )
    assert result.output_text == "Saved your weekly dream."
    assert service.store.read(context.principal).dreams[0].draft == suggestion
    assert "dream_update_profile_mine" not in model.tool_names
    events = json.dumps([e.model_dump(mode="json") for e in result.events])
    assert suggestion.items[0].text not in events
    assert "Associative idea networks" not in events
    requests = [e for e in result.events if e.type == "agent.tool.requested"]
    assert len(requests) == 2
    assert all(e.payload["arguments_redacted"] is True for e in requests)
