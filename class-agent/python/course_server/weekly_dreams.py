"""Private weekly lookaheads: application-owned memory and Course Agent tools.

The existing Course Agent generates the content. This module enforces identity,
bounded evidence, persistence, and explicit feedback; it does not infer preferences.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import tempfile
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, ClassVar, Literal, cast
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, JsonValue, StringConstraints

from agent_core import PrincipalContext
from course_server.agent.capabilities import (
    CourseResourceCatalog,
    ExecutableTool,
    ToolExecutionContext,
    ToolExecutionResult,
    ToolValidationError,
)
from course_server.course_roster import CourseRoster
from course_server.weekly_dream_ids import WEEKLY_DREAM_TOOL_IDS

# Intentional context/storage bounds for a small class, not deployment defaults.
HISTORY_LIMIT = 8
SOURCE_LIMIT = 6
SOURCE_TEXT_LIMIT = 16000
MAX_DREAM_WORDS = 110
TOOL_IDS = WEEKLY_DREAM_TOOL_IDS
_BUNDLE_KEY = "weekly_dream_bundle"
_TEXT_URL = re.compile(r"https?://[^\s<>\[\]()]+")
Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1600)]
ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=160)]


class DreamModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class StudentFocus(DreamModel):
    """Student-confirmed additions; roster remains a separate source of truth."""

    interests: list[ShortText] = Field(default_factory=list, max_length=12)
    project: str = Field(default="", max_length=3000)
    open_questions: list[Text] = Field(default_factory=list, max_length=6)
    revision: int = Field(default=0, ge=0)


class DreamSource(DreamModel):
    id: ShortText
    title: ShortText
    uri: str = Field(min_length=1, max_length=500)
    text: str = Field(max_length=SOURCE_TEXT_LIMIT)
    links: list[str] = Field(default_factory=list, max_length=40)
    digest: str


class DreamItem(DreamModel):
    kind: Literal["connection", "reading", "person", "question"]
    key: Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9-]{2,79}$")]
    title: ShortText
    text: Text
    source_ids: list[ShortText] = Field(min_length=1, max_length=4)
    link: str | None = Field(default=None, max_length=2048)
    person_name: ShortText | None = None


class DreamDraft(DreamModel):
    week: int = Field(ge=1, le=52)
    headline: ShortText
    items: list[DreamItem] = Field(min_length=1, max_length=4)


class DreamFeedback(DreamModel):
    dream_id: UUID
    item_key: ShortText
    rating: Literal["useful", "already_explored", "not_relevant"]
    note: str = Field(default="", max_length=800)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class SavedDream(DreamModel):
    id: UUID = Field(default_factory=uuid4)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    profile_revision: int
    draft: DreamDraft
    sources: list[DreamSource]
    mode: Literal["course_agent", "reviewed_example"] = "course_agent"


class DreamMemory(DreamModel):
    schema_version: Literal[1] = 1
    profile: StudentFocus = Field(default_factory=StudentFocus)
    dreams: list[SavedDream] = Field(default_factory=list, max_length=HISTORY_LIMIT)
    feedback: list[DreamFeedback] = Field(default_factory=list, max_length=HISTORY_LIMIT * 4)


def student_owner(principal: PrincipalContext) -> UUID:
    if not principal.authenticated or "student" not in principal.roles or principal.user_id is None:
        raise PermissionError("Student login required for private weekly dreams.")
    return principal.user_id


class FileDreamStore:
    """One bounded private JSON record per trusted user UUID, with atomic locked updates.

    Matches the application's existing local-file storage pattern. No user-selectable
    filenames, roster copies, raw chat logs, or framework memory are persisted here.
    """

    def __init__(self, root: Path) -> None:
        self.root = root

    @contextmanager
    def transaction(self, principal: PrincipalContext) -> Iterator[DreamMemory]:
        owner = student_owner(principal)
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        path = self.root / f"{owner}.json"
        lock_path = self.root / f"{owner}.lock"
        if path.is_symlink() or lock_path.is_symlink() or self.root.is_symlink():
            raise ValueError("Dream storage cannot use symbolic links.")
        descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, "a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            memory = (
                DreamMemory.model_validate_json(path.read_text(encoding="utf-8"))
                if path.exists()
                else DreamMemory()
            )
            yield memory
            with tempfile.NamedTemporaryFile(mode="w", dir=self.root, delete=False) as output:
                temporary = Path(output.name)
                try:
                    os.chmod(temporary, 0o600)
                    output.write(memory.model_dump_json(indent=2))
                    output.flush()
                    os.fsync(output.fileno())
                    os.replace(temporary, path)
                finally:
                    temporary.unlink(missing_ok=True)

    def read(self, principal: PrincipalContext) -> DreamMemory:
        with self.transaction(principal) as memory:
            return memory.model_copy(deep=True)


class DreamBundle(DreamModel):
    week: int
    student_name: str
    profile: StudentFocus
    roster_context: str
    sources: list[DreamSource]
    peer_names: list[str]
    previous_suggestions: list[DreamDraft]
    feedback: list[DreamFeedback]


def make_source(source_id: str, title: str, uri: str, text: str) -> DreamSource:
    bounded = text[:SOURCE_TEXT_LIMIT]
    # A model may select a link observed in supplied evidence, never invent a target.
    links = list(
        dict.fromkeys(
            match.rstrip(".,;:!?")
            for match in _TEXT_URL.findall(bounded)
            if match.startswith("https://")
        )
    )[:40]
    return DreamSource(
        id=source_id,
        title=title[:160],
        uri=uri,
        text=bounded,
        links=links,
        digest=hashlib.sha256(bounded.encode()).hexdigest(),
    )


class WeeklyDreamService:
    def __init__(
        self,
        store: FileDreamStore,
        resources: CourseResourceCatalog,
        roster: CourseRoster | None = None,
        own_project_reader: ExecutableTool | None = None,
    ) -> None:
        self.store = store
        self.resources = resources
        self.roster = roster
        self.own_project_reader = own_project_reader

    async def prepare(
        self,
        context: ToolExecutionContext,
        week: int,
        resource_uris: list[str],
        project_paths: list[str] | None = None,
    ) -> DreamBundle:
        student_owner(context.principal)
        if not 1 <= week <= 52 or not 1 <= len(resource_uris) <= SOURCE_LIMIT:
            raise ToolValidationError("Choose a week and one to six course resources.")
        if len(set(resource_uris)) != len(resource_uris):
            raise ToolValidationError("Do not repeat course resources.")
        memory = self.store.read(context.principal)
        sources: list[DreamSource] = []
        for index, uri in enumerate(resource_uris):
            if uri not in context.permitted_resource_uris or not self.resources.is_public(uri):
                raise PermissionError("Dream evidence must be authorized public course material.")
            resource = await self.resources.read(uri)
            sources.append(make_source(f"course-{index + 1}", resource.title, uri, resource.text))
        if project_paths:
            if self.own_project_reader is None or len(project_paths) > 4:
                raise ToolValidationError(
                    "Own-project access is unavailable or too many paths requested."
                )
            for index, path in enumerate(project_paths):
                result = await self.own_project_reader.execute(
                    {"view": "file", "path": path}, context
                )
                sources.append(
                    make_source(
                        f"project-{index + 1}",
                        "Your project: " + path,
                        "student://own-project",
                        json.dumps(result.content),
                    )
                )
        roster_context = "No course roster available; use only the student's confirmed focus."
        peer_names: list[str] = []
        if self.roster is not None:
            own = next(
                (m for m in self.roster.active_members if m.username == context.principal.username),
                None,
            )
            if own is None:
                raise PermissionError("Active student roster entry required.")
            roster_context = "\n".join([own.name, *own.keywords, *own.project_ideas])
            sources.append(
                make_source(
                    "student-roster",
                    "Your course project interests",
                    "student://roster",
                    roster_context,
                )
            )
            if "course://students/roster" in context.permitted_resource_uris:
                for index, member in enumerate(self.roster.active_members):
                    if member.username == own.username:
                        continue
                    text = "\n".join([member.name, *member.keywords, *member.project_ideas])
                    if member.website:
                        text += "\n" + str(member.website)
                    sources.append(
                        make_source(f"peer-{index}", member.name, "course://students/roster", text)
                    )
                    peer_names.append(member.name)
        if memory.profile.project or memory.profile.interests or memory.profile.open_questions:
            sources.append(
                make_source(
                    "student-focus",
                    "Your confirmed focus",
                    "student://focus",
                    memory.profile.model_dump_json(),
                )
            )
        bundle = DreamBundle(
            week=week,
            student_name=context.principal.display_name or context.principal.username or "Student",
            profile=memory.profile,
            roster_context=roster_context,
            sources=sources,
            peer_names=peer_names,
            previous_suggestions=[dream.draft for dream in memory.dreams],
            feedback=memory.feedback,
        )
        context.transient_state[_BUNDLE_KEY] = bundle.model_dump(mode="json")
        return bundle

    def save(
        self,
        context: ToolExecutionContext,
        draft: DreamDraft,
        *,
        mode: Literal["course_agent", "reviewed_example"] = "course_agent",
    ) -> SavedDream:
        student_owner(context.principal)
        raw = context.transient_state.get(_BUNDLE_KEY)
        if not isinstance(raw, dict):
            raise ToolValidationError("Prepare fresh source context before saving a dream.")
        bundle = DreamBundle.model_validate(raw)
        if draft.week != bundle.week:
            raise ToolValidationError("Dream week must match the prepared sources.")
        words = " ".join([draft.headline, *(i.title + " " + i.text for i in draft.items)])
        if len(words.split()) > MAX_DREAM_WORDS:
            raise ToolValidationError("Keep the entire weekly dream to 110 words or fewer.")
        kinds = [item.kind for item in draft.items]
        keys = [item.key for item in draft.items]
        if len(set(kinds)) != len(kinds) or len(set(keys)) != len(keys):
            raise ToolValidationError("Use at most one suggestion of each kind and unique keys.")
        sources = {source.id: source for source in bundle.sources}
        for item in draft.items:
            if any(source_id not in sources for source_id in item.source_ids):
                raise ToolValidationError("Every suggestion needs supplied source evidence.")
            if not any(source_id.startswith("course-") for source_id in item.source_ids):
                raise ToolValidationError("Every suggestion must connect to course material.")
            if not any(
                source_id in {"student-focus", "student-roster"} or source_id.startswith("project-")
                for source_id in item.source_ids
            ):
                raise ToolValidationError("Every suggestion must connect to the student's work.")
            if item.link and not any(item.link in sources[s].links for s in item.source_ids):
                raise ToolValidationError("Recommended links must occur in cited source text.")
            # Email and chat render the prose too. Checking only item.link would let
            # a model bypass grounding by placing an invented URL in its title/text.
            cited_links = {link for s in item.source_ids for link in sources[s].links}
            prose_links = {
                link.rstrip(".,;:!?") for link in _TEXT_URL.findall(item.title + " " + item.text)
            }
            if not prose_links.issubset(cited_links):
                raise ToolValidationError("Links in suggestion text must occur in cited sources.")
            if item.kind == "reading" and item.link is None:
                raise ToolValidationError("A reading recommendation needs an evidenced HTTPS link.")
            if item.kind == "person":
                if item.person_name not in bundle.peer_names or not any(
                    sources[s].title == item.person_name and s.startswith("peer-")
                    for s in item.source_ids
                ):
                    raise ToolValidationError(
                        "Recommend only a peer evidenced in the active roster."
                    )
            elif item.person_name is not None:
                raise ToolValidationError("Only person suggestions may name a recommended peer.")
        used_ids = {s for item in draft.items for s in item.source_ids}
        headline_links = {link.rstrip(".,;:!?") for link in _TEXT_URL.findall(draft.headline)}
        if not headline_links.issubset({link for s in used_ids for link in sources[s].links}):
            raise ToolValidationError("Links in the headline must occur in cited sources.")
        with self.store.transaction(context.principal) as memory:
            if memory.profile.revision != bundle.profile.revision:
                raise ToolValidationError("Your focus changed; prepare fresh context first.")
            previous_keys = {i.key for d in memory.dreams for i in d.draft.items}
            if previous_keys.intersection(keys):
                raise ToolValidationError("This suggestion was already made; choose a new angle.")
            used = {s for i in draft.items for s in i.source_ids}
            dream = SavedDream(
                profile_revision=memory.profile.revision,
                draft=draft,
                sources=[s for s in bundle.sources if s.id in used],
                mode=mode,
            )
            memory.dreams = [dream, *memory.dreams][:HISTORY_LIMIT]
            retained = {d.id for d in memory.dreams}
            memory.feedback = [f for f in memory.feedback if f.dream_id in retained]
        context.transient_state.pop(_BUNDLE_KEY, None)
        return dream

    def feedback(self, principal: PrincipalContext, feedback: DreamFeedback) -> None:
        with self.store.transaction(principal) as memory:
            dream = next((d for d in memory.dreams if d.id == feedback.dream_id), None)
            if dream is None or feedback.item_key not in {i.key for i in dream.draft.items}:
                raise ToolValidationError("Suggestion not found in your private dream history.")
            memory.feedback = [
                f
                for f in memory.feedback
                if (f.dream_id, f.item_key) != (feedback.dream_id, feedback.item_key)
            ] + [feedback]

    def update_profile(self, principal: PrincipalContext, profile: StudentFocus) -> StudentFocus:
        with self.store.transaction(principal) as memory:
            if memory.profile.revision != profile.revision:
                raise ToolValidationError("Focus changed; read your current memory before editing.")
            memory.profile = profile.model_copy(update={"revision": profile.revision + 1})
            return memory.profile


class PrepareInput(DreamModel):
    week: int = Field(ge=1, le=52)
    resource_uris: list[str] = Field(min_length=1, max_length=SOURCE_LIMIT)
    project_paths: list[str] = Field(default_factory=list, max_length=4)


class FeedbackInput(DreamModel):
    dream_id: UUID
    item_key: ShortText
    rating: Literal["useful", "already_explored", "not_relevant"]
    note: str = Field(default="", max_length=800)


class EmptyInput(DreamModel):
    pass


class ClearInput(DreamModel):
    confirm: Literal[True]


def inline_tool_schema(schema: dict[str, JsonValue]) -> dict[str, JsonValue]:
    """Inline local definitions: the runtime adapter forwards properties, not $defs."""
    definitions = schema.get("$defs", {})

    def expand(value: JsonValue) -> JsonValue:
        if isinstance(value, list):
            return [expand(item) for item in value]
        if isinstance(value, dict):
            reference = value.get("$ref")
            if isinstance(reference, str):
                if not reference.startswith("#/$defs/") or not isinstance(definitions, dict):
                    raise ValueError("Only local tool schema references are supported.")
                return expand(definitions[reference.removeprefix("#/$defs/")])
            return {key: expand(item) for key, item in value.items() if key != "$defs"}
        return value

    return cast(dict[str, JsonValue], expand(schema))


class WeeklyDreamTool:
    """Six narrow tools; no tool argument can select a student or storage path."""

    redact_arguments_in_events = True
    _INPUTS: ClassVar[dict[str, type[BaseModel]]] = {
        TOOL_IDS[0]: PrepareInput,
        TOOL_IDS[1]: DreamDraft,
        TOOL_IDS[2]: EmptyInput,
        TOOL_IDS[3]: FeedbackInput,
        TOOL_IDS[4]: StudentFocus,
        TOOL_IDS[5]: ClearInput,
    }
    _DESCRIPTIONS: ClassVar[dict[str, str]] = {
        TOOL_IDS[0]: (
            "Prepare a private weekly dream from authorized course resources, "
            "your interests, focus, previous dreams and feedback. Read the weekly-dream skill."
        ),
        TOOL_IDS[1]: (
            "Save an evidence-backed dream after dream.prepare_mine in this run. "
            "Source IDs and links must come from that bundle. Return the saved content."
        ),
        TOOL_IDS[2]: ("Read your own dream history, explicit feedback and editable project focus."),
        TOOL_IDS[3]: (
            "Record explicit student feedback on their own suggestions. "
            "Do not infer a rating or feedback from silence."
        ),
        TOOL_IDS[4]: (
            "Replace your confirmed focus only on your explicit request. "
            "Use the revision from dream.history_mine. Empty fields clear information."
        ),
        TOOL_IDS[5]: (
            "Clear your dreams, feedback and focus only after your explicit request. "
            "Does not change course records, backups, or existing chat history."
        ),
    }

    def __init__(self, tool_id: str, service: WeeklyDreamService) -> None:
        self.id = tool_id
        self.description = self._DESCRIPTIONS[tool_id]
        self.input_schema = inline_tool_schema(self._INPUTS[tool_id].model_json_schema())
        self.service = service

    async def execute(
        self, arguments: Mapping[str, JsonValue], context: ToolExecutionContext
    ) -> ToolExecutionResult:
        student_owner(context.principal)
        value = self._INPUTS[self.id].model_validate(dict(arguments))
        if isinstance(value, PrepareInput):
            result: BaseModel = await self.service.prepare(
                context, value.week, value.resource_uris, value.project_paths
            )
        elif isinstance(value, DreamDraft):
            result = self.service.save(context, value)
        elif isinstance(value, FeedbackInput):
            self.service.feedback(context.principal, DreamFeedback(**value.model_dump()))
            return ToolExecutionResult(
                content="Your feedback is saved.",
                summary="Updated private dream feedback.",
                storage_policy="server_summary",
            )
        elif isinstance(value, StudentFocus):
            result = self.service.update_profile(context.principal, value)
        elif isinstance(value, ClearInput):
            with self.service.store.transaction(context.principal) as memory:
                memory.dreams = []
                memory.feedback = []
                memory.profile = StudentFocus(revision=memory.profile.revision + 1)
            context.transient_state.pop(_BUNDLE_KEY, None)
            return ToolExecutionResult(
                content=(
                    "Your weekly dream memory is cleared. "
                    "Course records and chat history are unchanged."
                ),
                summary="Cleared private weekly dream memory.",
                storage_policy="server_summary",
            )
        else:
            result = self.service.store.read(context.principal)
        return ToolExecutionResult(
            content=result.model_dump(mode="json"),
            summary="Read or updated the current student's private weekly dream state.",
            storage_policy="server_summary",
        )
