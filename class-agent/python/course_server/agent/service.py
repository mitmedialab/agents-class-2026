"""Orchestration for the one logical Course Agent."""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol, cast
from uuid import UUID, uuid4

from agent_core import (
    AgentContext,
    AgentInput,
    AgentResult,
    AgentRuntime,
    Capability,
    Conversation,
    Event,
    PrincipalContext,
)
from course_server.uploads import TemporaryUploadStore, UploadError
from course_server.workspace import (
    ComponentRegistry,
    load_component_registry,
    project_workspace_events,
)

from .capabilities import ASK_TA_TOOL_ID, CourseCapabilityPolicy
from .skills import (
    READ_SKILL_REFERENCE_TOOL_ID,
    READ_SKILL_TOOL_ID,
    SkillCatalog,
)
from .store import ConversationAccessDenied, ConversationStore, principal_owns_conversation

RECENT_DIALOGUE_EVENT_LIMIT = 24
RECENT_SUPPORTING_EVENT_LIMIT = 16
_DIALOGUE_EVENT_TYPES = frozenset({"user.message", "agent.message"})
_SUPPORTING_EVENT_TYPES = frozenset(
    {
        "agent.tool.completed",
        "workspace.interaction",
        "email.ta_question.cancelled",
        "email.ta_question.confirmation_requested",
        "email.ta_question.queued",
        "email.ta_answer.received",
    }
)
_CONTINUATION_EVENT_TYPES = frozenset(
    {
        "email.ta_question.cancelled",
        "email.ta_question.queued",
    }
)
_CONTINUATION_EVENT_METADATA_KEY = "trigger_event_id"
_CONTINUATION_BLOCKED_TOOL_IDS = frozenset({ASK_TA_TOOL_ID})
EventObserver = Callable[[Event], None]
TextDeltaObserver = Callable[[str], None]
_UPLOAD_REFERENCE = re.compile(
    r"(?:upload_id:\s*|upload://)([0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-"
    r"[89ab][0-9a-f]{3}-[0-9a-f]{12})",
    re.IGNORECASE,
)


class ObservableAgentRuntime(Protocol):
    """Optional application adapter for live portable runtime events."""

    async def run_observed(
        self,
        *,
        context: AgentContext,
        input: AgentInput,
        event_observer: EventObserver,
        text_delta_observer: TextDeltaObserver | None = None,
    ) -> AgentResult: ...


def _principal_references(principal: PrincipalContext) -> dict[str, UUID | None]:
    return {
        "principal_user_id": principal.user_id,
        "anonymous_session_id": principal.anonymous_session_id,
    }


def _recent_context_events(events: list[Event]) -> list[Event]:
    """Keep dialogue and useful actions without spending context on run bookkeeping."""
    dialogue = [event for event in events if event.type in _DIALOGUE_EVENT_TYPES]
    supporting = [event for event in events if event.type in _SUPPORTING_EVENT_TYPES]
    retained_ids = {
        event.id
        for event in [
            *dialogue[-RECENT_DIALOGUE_EVENT_LIMIT:],
            *supporting[-RECENT_SUPPORTING_EVENT_LIMIT:],
        ]
    }
    return [event for event in events if event.id in retained_ids]


def _question_action_input(trigger: Event) -> str:
    """Describe a trusted action without prescribing or duplicating the agent's response."""

    if trigger.type == "email.ta_question.queued":
        return "The student approved sending the prepared question to course staff."
    return "The student cancelled the prepared course-staff question."


class CourseAgentService:
    """Persists portable history around a replaceable AgentRuntime."""

    def __init__(
        self,
        *,
        runtime: AgentRuntime,
        conversations: ConversationStore,
        capability_policy: CourseCapabilityPolicy | None = None,
        skills: SkillCatalog | None = None,
        workspace_registry: ComponentRegistry | None = None,
        uploads: TemporaryUploadStore | None = None,
    ) -> None:
        self._runtime = runtime
        self._conversations = conversations
        self._capability_policy = capability_policy or CourseCapabilityPolicy()
        self._skills = skills
        self._workspace_registry = workspace_registry or load_component_registry()
        self._uploads = uploads

    async def _authorized_upload_uris(
        self,
        *,
        principal: PrincipalContext,
        current_text: str,
        previous_events: list[Event],
    ) -> list[str]:
        if self._uploads is None:
            return []
        texts = [current_text]
        texts.extend(
            text
            for event in previous_events
            if event.type == "user.message"
            and event.actor == "user"
            and isinstance((text := event.payload.get("text")), str)
        )
        upload_ids = dict.fromkeys(
            UUID(match.group(1)) for text in texts for match in _UPLOAD_REFERENCE.finditer(text)
        )
        authorized: list[str] = []
        for upload_id in upload_ids:
            try:
                await self._uploads.get_for_principal(upload_id, principal)
            except UploadError:
                continue
            authorized.append(f"upload://{upload_id}")
        return authorized

    async def create_conversation(
        self,
        principal: PrincipalContext,
        *,
        title: str | None = None,
    ) -> Conversation:
        now = datetime.now(UTC)
        conversation = Conversation(
            user_id=principal.user_id,
            anonymous_session_id=principal.anonymous_session_id,
            created_at=now,
            updated_at=now,
            title=title,
        )
        await self._conversations.create_conversation(conversation)
        return conversation

    async def run(
        self,
        *,
        principal: PrincipalContext,
        conversation_id: UUID,
        text: str,
        event_observer: EventObserver | None = None,
        text_delta_observer: TextDeltaObserver | None = None,
    ) -> AgentResult:
        previous_events = await self._owned_conversation_events(principal, conversation_id)
        agent_input = AgentInput(conversation_id=conversation_id, text=text)
        user_event = Event(
            type="user.message",
            actor="user",
            conversation_id=conversation_id,
            payload={"text": agent_input.text, "input_id": str(agent_input.id)},
            **_principal_references(principal),
        )
        await self._conversations.append_events(conversation_id, [user_event])

        return await self._execute(
            principal=principal,
            conversation_id=conversation_id,
            agent_input=agent_input,
            previous_events=previous_events,
            event_observer=event_observer,
            text_delta_observer=text_delta_observer,
        )

    async def continue_after_event(
        self,
        *,
        principal: PrincipalContext,
        conversation_id: UUID,
        trigger_event_id: UUID,
        event_observer: EventObserver | None = None,
        text_delta_observer: TextDeltaObserver | None = None,
    ) -> AgentResult:
        """Let the agent react to one trusted action without inventing a user message."""

        previous_events = await self._owned_conversation_events(principal, conversation_id)
        trigger = next(
            (event for event in previous_events if event.id == trigger_event_id),
            None,
        )
        if trigger is None or trigger.type not in _CONTINUATION_EVENT_TYPES:
            raise ConversationAccessDenied("continuation event not found")

        trigger_key = str(trigger_event_id)
        for event in reversed(previous_events):
            if (
                event.type == "agent.message"
                and event.metadata.get(_CONTINUATION_EVENT_METADATA_KEY) == trigger_key
                and isinstance((output_text := event.payload.get("text")), str)
            ):
                raw_input_id = event.payload.get("input_id")
                input_id = UUID(raw_input_id) if isinstance(raw_input_id, str) else uuid4()
                return AgentResult(
                    input_id=input_id,
                    conversation_id=conversation_id,
                    output_text=output_text,
                )

        agent_input = AgentInput(
            conversation_id=conversation_id,
            text=_question_action_input(trigger),
            metadata={_CONTINUATION_EVENT_METADATA_KEY: trigger_key},
        )
        return await self._execute(
            principal=principal,
            conversation_id=conversation_id,
            agent_input=agent_input,
            previous_events=previous_events,
            trigger_event_id=trigger_event_id,
            blocked_tool_ids=_CONTINUATION_BLOCKED_TOOL_IDS,
            event_observer=event_observer,
            text_delta_observer=text_delta_observer,
        )

    async def _owned_conversation_events(
        self,
        principal: PrincipalContext,
        conversation_id: UUID,
    ) -> list[Event]:
        conversation = await self._conversations.get_conversation(conversation_id)
        if conversation is None or not principal_owns_conversation(principal, conversation):
            raise ConversationAccessDenied("conversation not found")
        if conversation.archived_at is not None:
            raise ConversationAccessDenied("conversation is archived")
        return await self._conversations.list_events(conversation_id)

    async def _execute(
        self,
        *,
        principal: PrincipalContext,
        conversation_id: UUID,
        agent_input: AgentInput,
        previous_events: list[Event],
        trigger_event_id: UUID | None = None,
        blocked_tool_ids: frozenset[str] = frozenset(),
        event_observer: EventObserver | None = None,
        text_delta_observer: TextDeltaObserver | None = None,
    ) -> AgentResult:

        authorized = self._capability_policy.authorize(principal)
        authorized_skills = self._skills.authorized_metadata(principal) if self._skills else ()
        skill_tool_ids = (
            (READ_SKILL_TOOL_ID, READ_SKILL_REFERENCE_TOOL_ID) if authorized_skills else ()
        )
        permitted_tool_ids = tuple(
            tool_id
            for tool_id in (*authorized.tool_ids, *skill_tool_ids)
            if tool_id not in blocked_tool_ids
        )
        authorized_uploads = await self._authorized_upload_uris(
            principal=principal,
            current_text=agent_input.text,
            previous_events=previous_events,
        )
        workspace_state = project_workspace_events(
            previous_events,
            self._workspace_registry,
        )
        context = AgentContext(
            principal=principal,
            conversation_id=conversation_id,
            recent_events=_recent_context_events(previous_events),
            capabilities=[
                Capability(id=tool_id, status="available") for tool_id in permitted_tool_ids
            ],
            permitted_tool_ids=list(permitted_tool_ids),
            permitted_resource_uris=[*authorized.resource_uris, *authorized_uploads],
            metadata={
                "workspace_state": workspace_state.model_dump(mode="json", exclude_none=True),
                "authorized_resource_index": list(authorized.resource_index),
                "authorized_skill_index": [
                    {
                        "id": skill.id,
                        "name": skill.name,
                        "description": skill.description,
                    }
                    for skill in authorized_skills
                ],
            },
        )
        observed_method = getattr(self._runtime, "run_observed", None)
        observers_requested = event_observer is not None or text_delta_observer is not None
        if observers_requested and observed_method is not None:
            observed_runtime = cast(ObservableAgentRuntime, self._runtime)
            result = await observed_runtime.run_observed(
                context=context,
                input=agent_input,
                event_observer=event_observer or (lambda _event: None),
                text_delta_observer=text_delta_observer,
            )
        else:
            result = await self._runtime.run(context=context, input=agent_input)
            if event_observer is not None:
                for event in result.events:
                    event_observer(event)
        if result.input_id != agent_input.id or result.conversation_id != conversation_id:
            raise ValueError("runtime returned a result for a different input or conversation")
        if trigger_event_id is not None:
            trigger_key = str(trigger_event_id)
            tagged_events = [
                event.model_copy(
                    update={
                        "metadata": {
                            **event.metadata,
                            _CONTINUATION_EVENT_METADATA_KEY: trigger_key,
                        }
                    }
                )
                if event.type in {"agent.run.started", "agent.message", "agent.run.completed"}
                else event
                for event in result.events
            ]
            result = result.model_copy(update={"events": tagged_events})
        await self._conversations.append_events(conversation_id, result.events)
        return result
