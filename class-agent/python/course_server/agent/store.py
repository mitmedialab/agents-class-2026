"""Application-owned persistence boundary for conversations and canonical events."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from agent_core import Conversation, Event, PrincipalContext


class ConversationAccessDenied(RuntimeError):
    """A conversation does not exist for the current principal."""


class EventAlreadyExists(ValueError):
    """A canonical event with this stable ID was already persisted."""


def principal_owns_conversation(
    principal: PrincipalContext,
    conversation: Conversation,
) -> bool:
    if principal.authenticated:
        return conversation.user_id == principal.user_id
    return conversation.anonymous_session_id == principal.anonymous_session_id


class ConversationStore(Protocol):
    async def create_conversation(self, conversation: Conversation) -> None: ...

    async def get_conversation(self, conversation_id: UUID) -> Conversation | None: ...

    async def list_conversations(self, principal: PrincipalContext) -> list[Conversation]: ...

    async def append_events(self, conversation_id: UUID, events: list[Event]) -> None: ...

    async def list_events(self, conversation_id: UUID) -> list[Event]: ...


class InMemoryConversationStore:
    """Deterministic conversation adapter for unit and CLI orchestration tests."""

    def __init__(self) -> None:
        self.conversations: dict[UUID, Conversation] = {}
        self.events: dict[UUID, list[Event]] = {}

    async def create_conversation(self, conversation: Conversation) -> None:
        if conversation.id in self.conversations:
            raise ValueError("conversation already exists")
        self.conversations[conversation.id] = conversation
        self.events[conversation.id] = []

    async def get_conversation(self, conversation_id: UUID) -> Conversation | None:
        return self.conversations.get(conversation_id)

    async def list_conversations(self, principal: PrincipalContext) -> list[Conversation]:
        return sorted(
            (
                conversation
                for conversation in self.conversations.values()
                if principal_owns_conversation(principal, conversation)
            ),
            key=lambda conversation: conversation.updated_at,
            reverse=True,
        )

    async def append_events(self, conversation_id: UUID, events: list[Event]) -> None:
        conversation = self.conversations.get(conversation_id)
        if conversation is None:
            raise ConversationAccessDenied("conversation not found")
        if any(event.conversation_id != conversation_id for event in events):
            raise ValueError("every persisted event must reference its conversation")
        existing_ids = {event.id for event in self.events[conversation_id]}
        if any(event.id in existing_ids for event in events):
            raise EventAlreadyExists("event already exists")
        self.events[conversation_id].extend(events)
        if events:
            latest_timestamp = max(event.timestamp for event in events)
            if latest_timestamp > conversation.updated_at:
                self.conversations[conversation_id] = conversation.model_copy(
                    update={"updated_at": latest_timestamp}
                )

    async def list_events(self, conversation_id: UUID) -> list[Event]:
        if conversation_id not in self.conversations:
            raise ConversationAccessDenied("conversation not found")
        return sorted(
            self.events[conversation_id],
            key=lambda event: (event.timestamp, str(event.id)),
        )
