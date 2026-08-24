"""Framework-independent domain contracts for the Class Agent platform."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal, Self, TypeVar
from uuid import UUID, uuid4

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    StringConstraints,
    model_validator,
)

SCHEMA_VERSION: Literal[1] = 1

Role = Literal["public", "student", "ta", "instructor", "admin"]
MemoryPrivacy = Literal["personal", "course_private"]
CapabilityStatus = Literal["available", "obtainable", "unavailable"]
PermissionStatus = Literal["requested", "granted", "denied", "revoked"]
NodeType = Literal[
    "web",
    "browser_extension",
    "local_bridge",
    "raspberry_pi",
    "device",
]

NonEmptyString = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1),
]
JsonObject = dict[str, JsonValue]


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _require_timezone(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must include a timezone")
    return value


AwareDatetime = Annotated[datetime, AfterValidator(_require_timezone)]

Item = TypeVar("Item")


def _require_unique(values: list[Item], field_name: str) -> None:
    if len(values) != len(set(values)):
        raise ValueError(f"{field_name} must not contain duplicates")


class ContractModel(BaseModel):
    """Base behavior shared by canonical wire contracts."""

    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
        allow_inf_nan=False,
    )


class PrincipalContext(ContractModel):
    """Trusted identity and role information resolved before an agent run."""

    authenticated: bool
    user_id: UUID | None = None
    anonymous_session_id: UUID | None = None
    username: NonEmptyString | None = None
    display_name: NonEmptyString | None = None
    roles: list[Role]
    session_id: UUID

    @model_validator(mode="after")
    def validate_identity(self) -> Self:
        _require_unique(self.roles, "roles")

        if self.authenticated:
            if self.user_id is None or self.username is None:
                raise ValueError("authenticated principals require user_id and username")
            if self.anonymous_session_id is not None:
                raise ValueError("authenticated principals cannot have an anonymous_session_id")
            if "public" not in self.roles or not any(role != "public" for role in self.roles):
                raise ValueError(
                    "authenticated principals require public and at least one authenticated role"
                )
            return self

        if self.user_id is not None or self.username is not None or self.display_name is not None:
            raise ValueError("anonymous principals cannot have user profile fields")
        if self.anonymous_session_id is None:
            raise ValueError("anonymous principals require anonymous_session_id")
        if self.roles != ["public"]:
            raise ValueError("anonymous principals must have exactly the public role")
        return self


class Event(ContractModel):
    """Portable durable-history envelope."""

    id: UUID = Field(default_factory=uuid4)
    schema_version: Literal[1] = SCHEMA_VERSION
    timestamp: AwareDatetime = Field(default_factory=_utc_now)
    type: NonEmptyString
    actor: NonEmptyString
    principal_user_id: UUID | None = None
    anonymous_session_id: UUID | None = None
    conversation_id: UUID | None = None
    node_id: UUID | None = None
    payload: JsonObject = Field(default_factory=dict)
    metadata: JsonObject = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_principal_reference(self) -> Self:
        if self.principal_user_id is not None and self.anonymous_session_id is not None:
            raise ValueError("an event cannot reference both a user and an anonymous session")
        return self


class Conversation(ContractModel):
    """A durable conversation owned by one authenticated or anonymous principal."""

    id: UUID = Field(default_factory=uuid4)
    user_id: UUID | None = None
    anonymous_session_id: UUID | None = None
    created_at: AwareDatetime = Field(default_factory=_utc_now)
    updated_at: AwareDatetime = Field(default_factory=_utc_now)
    title: NonEmptyString | None = None
    archived_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def validate_conversation(self) -> Self:
        if sum((self.user_id is not None, self.anonymous_session_id is not None)) != 1:
            raise ValueError("a conversation must have exactly one principal owner")
        if self.updated_at < self.created_at:
            raise ValueError("updated_at cannot be earlier than created_at")
        if self.archived_at is not None and self.archived_at < self.created_at:
            raise ValueError("archived_at cannot be earlier than created_at")
        return self


class Memory(ContractModel):
    """A selected, user-owned memory distinct from event history."""

    id: UUID = Field(default_factory=uuid4)
    user_id: UUID
    created_at: AwareDatetime = Field(default_factory=_utc_now)
    updated_at: AwareDatetime = Field(default_factory=_utc_now)
    kind: NonEmptyString
    content: NonEmptyString
    source_event_ids: list[UUID] = Field(default_factory=list)
    privacy: MemoryPrivacy
    metadata: JsonObject = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_memory(self) -> Self:
        _require_unique(self.source_event_ids, "source_event_ids")
        if self.updated_at < self.created_at:
            raise ValueError("updated_at cannot be earlier than created_at")
        return self


class CapabilityAcquisition(ContractModel):
    """Trusted platform instruction for obtaining a capability."""

    type: NonEmptyString
    metadata: JsonObject = Field(default_factory=dict)


class Capability(ContractModel):
    """A capability and its availability for the current principal."""

    id: NonEmptyString
    status: CapabilityStatus
    acquisition: CapabilityAcquisition | None = None
    node_id: UUID | None = None
    metadata: JsonObject = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_acquisition(self) -> Self:
        if self.status == "obtainable" and self.acquisition is None:
            raise ValueError("obtainable capabilities require acquisition instructions")
        return self


class Permission(ContractModel):
    """A principal-owned permission for a scoped capability."""

    id: UUID = Field(default_factory=uuid4)
    capability: NonEmptyString
    scope: JsonObject
    status: PermissionStatus
    principal_user_id: UUID | None = None
    anonymous_session_id: UUID | None = None
    node_id: UUID | None = None
    created_at: AwareDatetime = Field(default_factory=_utc_now)
    updated_at: AwareDatetime = Field(default_factory=_utc_now)
    metadata: JsonObject = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_permission(self) -> Self:
        owners = (self.principal_user_id is not None, self.anonymous_session_id is not None)
        if sum(owners) != 1:
            raise ValueError("a permission must have exactly one principal owner")
        if self.updated_at < self.created_at:
            raise ValueError("updated_at cannot be earlier than created_at")
        return self


class Node(ContractModel):
    """A runtime endpoint that can provide capabilities."""

    id: UUID = Field(default_factory=uuid4)
    user_id: UUID | None = None
    type: NodeType
    name: NonEmptyString
    capabilities: list[NonEmptyString] = Field(default_factory=list)
    online: bool
    last_seen_at: AwareDatetime

    @model_validator(mode="after")
    def validate_capabilities(self) -> Self:
        _require_unique(self.capabilities, "capabilities")
        return self


class AgentContext(ContractModel):
    """Inspectable, already-authorized context supplied to an agent runtime."""

    principal: PrincipalContext
    conversation_id: UUID
    recent_events: list[Event] = Field(default_factory=list)
    selected_memories: list[Memory] = Field(default_factory=list)
    capabilities: list[Capability] = Field(default_factory=list)
    permissions: list[Permission] = Field(default_factory=list)
    permitted_tool_ids: list[NonEmptyString] = Field(default_factory=list)
    permitted_resource_uris: list[NonEmptyString] = Field(default_factory=list)
    active_skill_ids: list[NonEmptyString] = Field(default_factory=list)
    metadata: JsonObject = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_collections(self) -> Self:
        _require_unique([event.id for event in self.recent_events], "recent event IDs")
        _require_unique([memory.id for memory in self.selected_memories], "memory IDs")
        _require_unique([capability.id for capability in self.capabilities], "capability IDs")
        _require_unique([permission.id for permission in self.permissions], "permission IDs")
        _require_unique(self.permitted_tool_ids, "permitted_tool_ids")
        _require_unique(self.permitted_resource_uris, "permitted_resource_uris")
        _require_unique(self.active_skill_ids, "active_skill_ids")
        return self


class AgentInput(ContractModel):
    """A user input for one agent-runtime invocation."""

    id: UUID = Field(default_factory=uuid4)
    conversation_id: UUID
    text: NonEmptyString
    metadata: JsonObject = Field(default_factory=dict)


class AgentResult(ContractModel):
    """Portable output from one agent-runtime invocation."""

    id: UUID = Field(default_factory=uuid4)
    input_id: UUID
    conversation_id: UUID
    output_text: str
    events: list[Event] = Field(default_factory=list)
    metadata: JsonObject = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_events(self) -> Self:
        _require_unique([event.id for event in self.events], "event IDs")
        return self
