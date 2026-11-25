"""Automatic owned-profile learning, complete retention, and context-only compaction."""

import asyncio
import json
from pathlib import Path

import pytest
from test_weekly_dreams import draft, prepare, setup_service, student

from agent_core import AgentInput, AgentResult, AgentRuntime, Event
from course_server.agent import CourseAgentService, InMemoryConversationStore
from course_server.dream_learning import (
    HistorySummary,
    Observation,
    ProfileChange,
    ProfileLearning,
    ProfileTracker,
)
from course_server.weekly_dreams import DreamFeedback, FileDreamStore, StudentFocus


class Intelligence:
    def __init__(self) -> None:
        self.seen: list[Observation] = []
        self.summarized: list[str] = []

    async def learn(self, principal, profile, observations):  # type: ignore[no-untyped-def]
        del principal, profile
        self.seen.extend(observations)
        observation = observations[-1]
        return ProfileLearning(
            changes=[
                ProfileChange(
                    field="engaged_questions",
                    value=observation.text,
                    observation_id=observation.id,
                    evidence_quote=observation.text,
                )
            ]
        )

    async def summarize(self, principal, entries):  # type: ignore[no-untyped-def]
        del principal
        self.summarized.extend(e["id"] for e in entries)
        return HistorySummary(
            text="Prior association suggestions were already explored; try a different angle.",
            covered_ids=[e["id"] for e in entries],
        )


class ReplyRuntime(AgentRuntime):
    async def run(self, *, context, input: AgentInput) -> AgentResult:  # type: ignore[no-untyped-def]
        del context
        return AgentResult(
            input_id=input.id, conversation_id=input.conversation_id, output_text="A course reply."
        )


def test_owned_chat_automatically_updates_profile_and_backfills_once(tmp_path: Path) -> None:
    async def scenario() -> None:
        service, context = setup_service(tmp_path)
        intelligence = Intelligence()
        tracker = ProfileTracker(service.store, intelligence)
        conversations = InMemoryConversationStore()
        agent = CourseAgentService(
            runtime=ReplyRuntime(), conversations=conversations, student_memory=tracker
        )
        own = context.principal
        old = await agent.create_conversation(own)
        past = Event(
            type="user.message",
            actor="user",
            conversation_id=old.id,
            principal_user_id=own.user_id,
            payload={"text": "How does memory routing work?"},
        )
        await conversations.append_events(old.id, [past])
        other = student("other")
        theirs = await agent.create_conversation(other)
        await conversations.append_events(
            theirs.id,
            [
                Event(
                    type="user.message",
                    actor="user",
                    conversation_id=theirs.id,
                    principal_user_id=other.user_id,
                    payload={"text": "PRIVATE OTHER STUDENT"},
                )
            ],
        )
        current = await agent.create_conversation(own)
        await agent.run(
            principal=own,
            conversation_id=current.id,
            text="Could compaction remove useful associations?",
        )
        memory = service.store.read(own)
        assert len(memory.observations) == 2
        assert len(memory.processed_observations) == 2
        assert memory.profile.engaged_questions
        assert all("PRIVATE OTHER" not in o.text for o in intelligence.seen)
        await tracker.backfill(own, conversations)
        assert len(service.store.read(own).observations) == 2

    asyncio.run(scenario())


def test_profile_changes_need_owned_observed_evidence_and_fresh_revision(tmp_path: Path) -> None:
    service, context = setup_service(tmp_path)
    tracker = ProfileTracker(service.store, None)
    own = context.principal
    observation = Observation(
        id="observed-1",
        kind="student_message",
        text="My current build is Weekly Dream.",
        source="conversation://own",
    )
    tracker.record(own, observation)
    revision = service.store.read(own).profile.revision
    learned = ProfileLearning(
        changes=[
            ProfileChange(
                field="current_weekly_build",
                operation="set",
                value="Weekly Dream",
                observation_id=observation.id,
                evidence_quote=observation.text,
            )
        ]
    )
    tracker.apply(own, revision, [observation], learned)
    assert service.store.read(own).profile.current_weekly_build == "Weekly Dream"
    with pytest.raises(ValueError, match="Profile changed"):
        tracker.apply(own, revision, [observation], learned)
    learned.changes[0].evidence_quote = "An invented quote"
    with pytest.raises(ValueError, match="exact quote"):
        tracker.apply(own, revision + 1, [observation], learned)
    forged = observation.model_copy(update={"id": "unrecorded"})
    learned.changes[0].observation_id = forged.id
    learned.changes[0].evidence_quote = forged.text
    with pytest.raises(ValueError, match="cleared"):
        tracker.apply(own, revision + 1, [forged], learned)


def test_no_retention_cutoff_and_compaction_preserves_canonical_records(tmp_path: Path) -> None:
    service, context = setup_service(tmp_path)
    for i in range(20):
        prepare(service, context)
        saved = service.save(context, draft(f"idea-{i}"))
        service.feedback(
            context.principal,
            DreamFeedback(
                dream_id=saved.id,
                item_key=f"idea-{i}",
                rating="already_explored",
                note="This is already familiar. " * 10,
            ),
        )
    before = service.store.read(context.principal)
    service.compaction_chars = 1800
    intelligence = Intelligence()
    service.tracker.intelligence = intelligence
    bundle = asyncio.run(service.prepare(context, 8, ["course://week/8"]))
    assert bundle.history_representation == "summarized"
    assert bundle.history_summary
    assert intelligence.summarized
    after = service.store.read(context.principal)
    assert len(after.dreams) == len(after.feedback) == 20
    assert after.dreams == before.dreams
    assert after.feedback == before.feedback
    # A small history is loaded in full without a summarizer call.
    service.compaction_chars = 100000
    full = asyncio.run(service.prepare(context, 8, ["course://week/8"]))
    assert len(full.previous_suggestions) == len(full.feedback) == 20
    assert full.history_representation == "full"


def test_bad_compaction_coverage_fails_without_discarding_history(tmp_path: Path) -> None:
    class MissingCoverage(Intelligence):
        async def summarize(self, principal, entries):  # type: ignore[no-untyped-def]
            return HistorySummary(text="Too vague.", covered_ids=[])

    service, context = setup_service(tmp_path)
    prepare(service, context)
    service.save(context, draft())
    service.compaction_chars = 20
    service.tracker.intelligence = MissingCoverage()
    with pytest.raises(ValueError, match="every supplied"):
        asyncio.run(service.prepare(context, 8, ["course://week/8"]))
    assert len(service.store.read(context.principal).dreams) == 1


def test_v1_data_is_upgraded_without_losing_content(tmp_path: Path) -> None:
    service, context = setup_service(tmp_path)
    prepare(service, context)
    saved = service.save(context, draft())
    path = service.store.root / f"{context.principal.user_id}.json"
    old = json.loads(path.read_text())
    old["schema_version"] = 1
    for field in (
        "observations",
        "processed_observations",
        "profile_updates",
        "conversation_backfilled",
    ):
        old.pop(field)
    path.write_text(json.dumps(old))
    restarted = FileDreamStore(service.store.root).read(context.principal)
    assert restarted.schema_version == 2
    assert restarted.dreams[0].id == saved.id
    assert restarted.profile.current_weekly_build == ""


def test_manual_edits_supersede_older_pending_observations(tmp_path: Path) -> None:
    service, context = setup_service(tmp_path)
    tracker = ProfileTracker(service.store, Intelligence())
    tracker.record(
        context.principal,
        Observation(
            id="old", kind="student_message", text="Old interest", source="conversation://old"
        ),
    )
    profile = service.store.read(context.principal).profile
    service.update_profile(
        context.principal,
        StudentFocus(
            interests=["New direction"],
            revision=profile.revision,
        ),
    )
    asyncio.run(tracker.refresh(context.principal))
    assert service.store.read(context.principal).profile.interests == ["New direction"]


def test_changed_feedback_is_retained_as_history(tmp_path: Path) -> None:
    service, context = setup_service(tmp_path)
    prepare(service, context)
    saved = service.save(context, draft())
    for rating in ("useful", "already_explored"):
        service.feedback(
            context.principal,
            DreamFeedback(
                dream_id=saved.id,
                item_key="retrieval-diversity",
                rating=rating,
            ),
        )
    assert [f.rating for f in service.store.read(context.principal).feedback] == [
        "useful",
        "already_explored",
    ]


def test_large_profile_is_compacted_without_changing_stored_context(tmp_path: Path) -> None:
    service, context = setup_service(tmp_path)
    focus = service.store.read(context.principal).profile
    service.update_profile(
        context.principal,
        StudentFocus(
            revision=focus.revision,
            project="Associative networks",
            engaged_questions=["A question about memory " * 20 for _ in range(20)],
        ),
    )
    service.compaction_chars = 1800
    service.tracker.intelligence = Intelligence()
    bundle = asyncio.run(service.prepare(context, 8, ["course://week/8"]))
    assert bundle.profile is None
    assert bundle.history_summary
    assert len(service.store.read(context.principal).profile.engaged_questions) == 20


def test_learning_failure_keeps_observation_pending_and_preserves_reply(tmp_path: Path) -> None:
    class Unavailable(Intelligence):
        async def learn(self, principal, profile, observations):  # type: ignore[no-untyped-def]
            raise RuntimeError("simulated provider failure")

    async def scenario() -> None:
        service, context = setup_service(tmp_path)
        tracker = ProfileTracker(service.store, Unavailable())
        agent = CourseAgentService(
            runtime=ReplyRuntime(),
            conversations=InMemoryConversationStore(),
            student_memory=tracker,
        )
        conversation = await agent.create_conversation(context.principal)
        result = await agent.run(
            principal=context.principal,
            conversation_id=conversation.id,
            text="How does compaction work?",
        )
        assert result.output_text == "A course reply."
        memory = service.store.read(context.principal)
        assert len(memory.observations) == 1
        assert not memory.processed_observations

    asyncio.run(scenario())


def test_clear_prevents_old_chat_backfill_from_repopulating_memory(tmp_path: Path) -> None:
    from course_server.weekly_dreams import TOOL_IDS, WeeklyDreamTool

    async def scenario() -> None:
        service, context = setup_service(tmp_path)
        tracker = ProfileTracker(service.store, None)
        conversations = InMemoryConversationStore()
        agent = CourseAgentService(
            runtime=ReplyRuntime(), conversations=conversations, student_memory=tracker
        )
        conversation = await agent.create_conversation(context.principal)
        await agent.run(
            principal=context.principal,
            conversation_id=conversation.id,
            text="A question about agent memory",
        )
        assert service.store.read(context.principal).observations
        await WeeklyDreamTool(TOOL_IDS[5], service).execute({"confirm": True}, context)
        await tracker.backfill(context.principal, conversations)
        assert not service.store.read(context.principal).observations

    asyncio.run(scenario())


def test_roster_does_not_establish_question_or_completed_build_history(tmp_path: Path) -> None:
    service, context = setup_service(tmp_path)
    tracker = ProfileTracker(service.store, None)
    source = Observation(
        id="roster-1", kind="own_roster", text="Interested in language", source="student://roster"
    )
    tracker.record(context.principal, source)
    revision = service.store.read(context.principal).profile.revision
    changes = ProfileLearning(
        changes=[
            ProfileChange(
                field="engaged_questions",
                value="A question never asked",
                observation_id=source.id,
                evidence_quote="language",
            )
        ]
    )
    with pytest.raises(ValueError, match="Roster metadata"):
        tracker.apply(context.principal, revision, [source], changes)
    changes.changes[0].field = "interests"
    changes.changes[0].value = "language"
    tracker.apply(context.principal, revision, [source], changes)
    assert service.store.read(context.principal).profile.interests == ["language"]
