"""Orchestration for the one logical Course Agent."""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol, cast
from uuid import UUID

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

from .capabilities import PublicCapabilityPolicy
from .store import ConversationAccessDenied, ConversationStore, principal_owns_conversation

RECENT_EVENT_LIMIT = 50
EventObserver = Callable[[Event], None]
TextDeltaObserver = Callable[[str], None]
ProgressDeltaObserver = Callable[[str, bool], None]
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
        progress_delta_observer: ProgressDeltaObserver | None = None,
    ) -> AgentResult: ...


def _principal_references(principal: PrincipalContext) -> dict[str, UUID | None]:
    return {
        "principal_user_id": principal.user_id,
        "anonymous_session_id": principal.anonymous_session_id,
    }


class CourseAgentService:
    """Persists portable history around a replaceable AgentRuntime."""

    def __init__(
        self,
        *,
        runtime: AgentRuntime,
        conversations: ConversationStore,
        capability_policy: PublicCapabilityPolicy | None = None,
        workspace_registry: ComponentRegistry | None = None,
        uploads: TemporaryUploadStore | None = None,
    ) -> None:
        self._runtime = runtime
        self._conversations = conversations
        self._capability_policy = capability_policy or PublicCapabilityPolicy()
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
        progress_delta_observer: ProgressDeltaObserver | None = None,
    ) -> AgentResult:
        conversation = await self._conversations.get_conversation(conversation_id)
        if conversation is None or not principal_owns_conversation(principal, conversation):
            raise ConversationAccessDenied("conversation not found")
        if conversation.archived_at is not None:
            raise ConversationAccessDenied("conversation is archived")

        previous_events = await self._conversations.list_events(conversation_id)
        agent_input = AgentInput(conversation_id=conversation_id, text=text)
        user_event = Event(
            type="user.message",
            actor="user",
            conversation_id=conversation_id,
            payload={"text": agent_input.text, "input_id": str(agent_input.id)},
            **_principal_references(principal),
        )
        await self._conversations.append_events(conversation_id, [user_event])

        authorized = self._capability_policy.authorize(principal)
        authorized_uploads = await self._authorized_upload_uris(
            principal=principal,
            current_text=text,
            previous_events=previous_events,
        )
        workspace_state = project_workspace_events(
            previous_events,
            self._workspace_registry,
        )
        context = AgentContext(
            principal=principal,
            conversation_id=conversation_id,
            recent_events=previous_events[-RECENT_EVENT_LIMIT:],
            capabilities=[
                Capability(id=tool_id, status="available") for tool_id in authorized.tool_ids
            ],
            permitted_tool_ids=list(authorized.tool_ids),
            permitted_resource_uris=[*authorized.resource_uris, *authorized_uploads],
            metadata={
                "workspace_state": workspace_state.model_dump(mode="json", exclude_none=True)
            },
        )
        observed_method = getattr(self._runtime, "run_observed", None)
        observers_requested = (
            event_observer is not None
            or text_delta_observer is not None
            or progress_delta_observer is not None
        )
        if observers_requested and observed_method is not None:
            observed_runtime = cast(ObservableAgentRuntime, self._runtime)
            result = await observed_runtime.run_observed(
                context=context,
                input=agent_input,
                event_observer=event_observer or (lambda _event: None),
                text_delta_observer=text_delta_observer,
                progress_delta_observer=progress_delta_observer,
            )
        else:
            result = await self._runtime.run(context=context, input=agent_input)
            if event_observer is not None:
                for event in result.events:
                    event_observer(event)
        if result.input_id != agent_input.id or result.conversation_id != conversation_id:
            raise ValueError("runtime returned a result for a different input or conversation")
        await self._conversations.append_events(conversation_id, result.events)
        return result
