"""Inspectable behavior observations and evidence-backed student-profile updates."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from agent_core import Event, PrincipalContext

if TYPE_CHECKING:
    from course_server.agent.store import ConversationStore
    from course_server.weekly_dreams import FileDreamStore, StudentFocus

logger = logging.getLogger(__name__)


class Observation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    kind: Literal["student_message", "own_build", "own_roster"]
    text: str
    source: str
    week: int | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ProfileChange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    field: Literal["interests", "current_weekly_build", "prior_builds", "engaged_questions"]
    operation: Literal["add", "remove", "set"] = "add"
    value: str = Field(min_length=1, max_length=3000)
    observation_id: str
    evidence_quote: str = Field(min_length=1, max_length=3000)


class ProfileLearning(BaseModel):
    model_config = ConfigDict(extra="forbid")
    changes: list[ProfileChange] = Field(default_factory=list, max_length=30)


class HistorySummary(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=12000)
    covered_ids: list[str]


class DreamIntelligence(Protocol):
    async def learn(
        self, principal: PrincipalContext, profile: StudentFocus, observations: list[Observation]
    ) -> ProfileLearning: ...

    async def summarize(
        self, principal: PrincipalContext, entries: list[dict[str, str]]
    ) -> HistorySummary: ...


class ProfileTracker:
    def __init__(self, store: FileDreamStore, intelligence: DreamIntelligence | None) -> None:
        self.store = store
        self.intelligence = intelligence

    async def backfill(self, principal: PrincipalContext, conversations: ConversationStore) -> None:
        if not principal.authenticated or "student" not in principal.roles:
            return
        if self.store.read(principal).conversation_backfilled:
            return
        for conversation in await conversations.list_conversations(principal):
            if conversation.user_id != principal.user_id or conversation.archived_at is not None:
                continue
            for event in await conversations.list_events(conversation.id):
                if (
                    event.type == "user.message"
                    and event.actor == "user"
                    and event.principal_user_id == principal.user_id
                ):
                    text = event.payload.get("text")
                    if isinstance(text, str) and text.strip():
                        self.record(
                            principal,
                            Observation(
                                id=str(event.id),
                                kind="student_message",
                                text=text,
                                source=f"conversation://{conversation.id}/events/{event.id}",
                                created_at=event.timestamp,
                            ),
                        )
        with self.store.transaction(principal) as memory:
            memory.conversation_backfilled = True

    async def observe(self, principal: PrincipalContext, event: Event) -> None:
        # Called only after the conversation service establishes ownership and saves input.
        if not principal.authenticated or "student" not in principal.roles:
            return
        if event.type != "user.message" or event.actor != "user":
            return
        if event.principal_user_id != principal.user_id:
            raise PermissionError("Observation must belong to the authenticated student.")
        text = event.payload.get("text")
        if not isinstance(text, str) or not text.strip():
            return
        self.record(
            principal,
            Observation(
                id=str(event.id),
                kind="student_message",
                text=text,
                source=f"conversation://{event.conversation_id}/events/{event.id}",
            ),
        )
        try:
            await self.refresh(principal)
        except Exception as error:
            # The original event and pending observation survive; a learning failure must
            # not turn a successful course chat into an HTTP error or a false success.
            logger.warning("Dream profile learning pending (%s)", type(error).__name__)

    def record(self, principal: PrincipalContext, observation: Observation) -> None:
        with self.store.transaction(principal) as memory:
            if not any(o.id == observation.id for o in memory.observations):
                memory.observations.append(observation)

    async def refresh(self, principal: PrincipalContext) -> None:
        if self.intelligence is None:
            return
        memory = self.store.read(principal)
        pending = sorted(
            [o for o in memory.observations if o.id not in memory.processed_observations],
            key=lambda o: (o.created_at, o.id),
        )
        # Small extraction batches, with no age/count deletion from durable history.
        for start in range(0, len(pending), 4):
            batch = pending[start : start + 4]
            current = self.store.read(principal).profile
            learned = await self.intelligence.learn(principal, current, batch)
            self.apply(principal, current.revision, batch, learned)

    def apply(
        self,
        principal: PrincipalContext,
        revision: int,
        observations: list[Observation],
        learning: ProfileLearning,
    ) -> None:
        sources = {o.id: o for o in observations}
        for change in learning.changes:
            source = sources.get(change.observation_id)
            if source is None or change.evidence_quote not in source.text:
                raise ValueError("Profile changes require an exact quote from observed behavior.")
            if source.kind == "own_roster" and change.field != "interests":
                raise ValueError(
                    "Roster metadata supports interests, not inferred build/question history."
                )
            if change.field == "current_weekly_build" and change.operation != "set":
                raise ValueError("Current weekly build uses set.")
            if change.field != "current_weekly_build" and change.operation == "set":
                raise ValueError("List fields use add/remove.")
        with self.store.transaction(principal) as memory:
            if memory.profile.revision != revision:
                raise ValueError("Profile changed while learning; retry from fresh context.")
            if not set(sources).issubset({o.id for o in memory.observations}):
                raise ValueError("Observations were cleared while learning.")
            for change in learning.changes:
                if change.field == "current_weekly_build":
                    old = memory.profile.current_weekly_build
                    if old and old != change.value and old not in memory.profile.prior_builds:
                        memory.profile.prior_builds.append(old)
                    memory.profile.current_weekly_build = change.value
                    if change.value in memory.profile.prior_builds:
                        memory.profile.prior_builds.remove(change.value)
                else:
                    values = getattr(memory.profile, change.field)
                    if change.operation == "add" and change.value not in values:
                        values.append(change.value)
                    elif change.operation == "remove" and change.value in values:
                        values.remove(change.value)
            # Revalidate aggregate fields before committing an inferred update.
            memory.profile = type(memory.profile).model_validate(memory.profile.model_dump())
            if learning.changes:
                memory.profile.revision += 1
            memory.profile_updates.extend(learning.changes)
            memory.processed_observations.extend(sources)
