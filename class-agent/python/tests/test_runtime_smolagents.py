from __future__ import annotations

import asyncio
from collections.abc import Iterator
from typing import Any
from uuid import uuid4

from smolagents import ChatMessage, ChatMessageStreamDelta, ChatMessageToolCall, Model
from smolagents.models import (
    ChatMessageToolCallFunction,
    ChatMessageToolCallStreamDelta,
    MessageRole,
)

from agent_core import AgentContext, AgentInput, AgentResult, Event, ModelProvider, PrincipalContext
from course_server.agent import (
    COURSE_APPLICATION_URI,
    COURSE_SYLLABUS_URI,
    GET_APPLICATION_TOOL_ID,
    READ_SYLLABUS_TOOL_ID,
    VISIT_WEBPAGE_TOOL_ID,
    WEB_IMAGE_SEARCH_TOOL_ID,
    WEB_SEARCH_TOOL_ID,
    CourseGetApplicationTool,
    CourseReadSyllabusTool,
    FileResourceProvider,
    PublicImageSearchTool,
    PublicVisitWebpageTool,
    ToolCatalog,
)
from course_server.workspace import load_component_registry
from course_server.workspace.constants import OPEN_COMPONENT_TOOL_ID
from course_server.workspace.tools import WorkspaceOpenComponentTool
from runtime_smolagents import SmolagentsRuntime


class HiddenCourseTool(CourseReadSyllabusTool):
    id = "ta.list_questions"


class ScriptedToolCallingModel(Model):  # type: ignore[misc]
    def __init__(self) -> None:
        super().__init__(model_id="scripted-model")
        self.calls = 0
        self.available_tool_names: list[str] = []
        self.message_text = ""
        self.message_snapshots: list[list[ChatMessage]] = []

    def generate(
        self,
        messages: list[ChatMessage],
        stop_sequences: list[str] | None = None,
        response_format: dict[str, str] | None = None,
        tools_to_call_from: list[Any] | None = None,
        **kwargs: Any,
    ) -> ChatMessage:
        self.message_text = "\n".join(str(message.content or "") for message in messages)
        self.message_snapshots.append(list(messages))
        del stop_sequences, response_format, kwargs
        self.available_tool_names = [tool.name for tool in tools_to_call_from or []]
        self.calls += 1
        if self.calls == 1:
            function = ChatMessageToolCallFunction(
                name="course_read_syllabus",
                arguments={},
            )
            call_id = "read-syllabus"
        else:
            function = ChatMessageToolCallFunction(
                name="final_answer",
                arguments={"answer": "The syllabus describes readings and student-built tools."},
            )
            call_id = "final-answer"
        return ChatMessage(
            role=MessageRole.ASSISTANT,
            content="",
            tool_calls=[ChatMessageToolCall(function=function, id=call_id, type="function")],
        )


class ScriptedProvider(ModelProvider[Model]):
    provider_id = "scripted"
    model_id = "scripted-model"

    def __init__(self, model: Model) -> None:
        self._model = model

    def create_model(self) -> Model:
        return self._model


class ScriptedStreamingToolCallingModel(ScriptedToolCallingModel):
    def generate_stream(
        self,
        messages: list[ChatMessage],
        stop_sequences: list[str] | None = None,
        response_format: dict[str, str] | None = None,
        tools_to_call_from: list[Any] | None = None,
        **kwargs: Any,
    ) -> Iterator[ChatMessageStreamDelta]:
        del messages, stop_sequences, response_format, kwargs
        self.available_tool_names = [tool.name for tool in tools_to_call_from or []]
        self.calls += 1
        if self.calls <= 2:
            progress_fragments = (
                ("I'll read ", "the syllabus before answering.")
                if self.calls == 1
                else ("I'll verify ", "one more detail.")
            )
            for fragment in progress_fragments:
                yield ChatMessageStreamDelta(content=fragment)
            yield ChatMessageStreamDelta(
                tool_calls=[
                    ChatMessageToolCallStreamDelta(
                        index=0,
                        id="read-syllabus",
                        type="function",
                        function=ChatMessageToolCallFunction(
                            name="course_read_syllabus",
                            arguments="{}",
                        ),
                    )
                ]
            )
            return
        fragments = [
            ("final-answer", "final_answer", '{"answer":"The syllabus says \\"'),
            (None, "", 'agents\\" are inspectable.\\n'),
            (None, "", 'Done."}'),
        ]
        for call_id, name, arguments in fragments:
            yield ChatMessageStreamDelta(
                tool_calls=[
                    ChatMessageToolCallStreamDelta(
                        index=0,
                        id=call_id,
                        type="function" if call_id else None,
                        function=ChatMessageToolCallFunction(
                            name=name,
                            arguments=arguments,
                        ),
                    )
                ]
            )


class ScriptedWorkspaceModel(ScriptedToolCallingModel):
    def generate(
        self,
        messages: list[ChatMessage],
        stop_sequences: list[str] | None = None,
        response_format: dict[str, str] | None = None,
        tools_to_call_from: list[Any] | None = None,
        **kwargs: Any,
    ) -> ChatMessage:
        self.message_text = "\n".join(str(message.content or "") for message in messages)
        del stop_sequences, response_format, kwargs
        self.available_tool_names = [tool.name for tool in tools_to_call_from or []]
        self.calls += 1
        if self.calls == 1:
            function = ChatMessageToolCallFunction(
                name="workspace_open_component",
                arguments={
                    "component_id": "calendar",
                    "resource_uri": "course://schedule",
                    "title": "Course schedule",
                    "props": {"view": "agenda", "focus_date": "2026-09-20"},
                },
            )
            call_id = "open-calendar"
        else:
            function = ChatMessageToolCallFunction(
                name="final_answer",
                arguments={"answer": "I opened the schedule."},
            )
            call_id = "final-answer"
        return ChatMessage(
            role=MessageRole.ASSISTANT,
            content="",
            tool_calls=[ChatMessageToolCall(function=function, id=call_id, type="function")],
        )


class ScriptedApplicationStartModel(ScriptedToolCallingModel):
    def generate(
        self,
        messages: list[ChatMessage],
        stop_sequences: list[str] | None = None,
        response_format: dict[str, str] | None = None,
        tools_to_call_from: list[Any] | None = None,
        **kwargs: Any,
    ) -> ChatMessage:
        self.message_text = "\n".join(str(message.content or "") for message in messages)
        del stop_sequences, response_format, kwargs
        self.available_tool_names = [tool.name for tool in tools_to_call_from or []]
        self.calls += 1
        if self.calls == 1:
            function = ChatMessageToolCallFunction(
                name="course_get_application",
                arguments={},
            )
            call_id = "read-application"
        elif self.calls == 2:
            function = ChatMessageToolCallFunction(
                name="workspace_open_component",
                arguments={
                    "component_id": "draft-document",
                    "resource_uri": COURSE_APPLICATION_URI,
                },
            )
            call_id = "open-application"
        else:
            function = ChatMessageToolCallFunction(
                name="final_answer",
                arguments={"answer": "The application is open. What is your full name?"},
            )
            call_id = "final-answer"
        return ChatMessage(
            role=MessageRole.ASSISTANT,
            content="",
            tool_calls=[ChatMessageToolCall(function=function, id=call_id, type="function")],
        )


class ScriptedVisualWorkspaceModel(ScriptedToolCallingModel):
    def generate(
        self,
        messages: list[ChatMessage],
        stop_sequences: list[str] | None = None,
        response_format: dict[str, str] | None = None,
        tools_to_call_from: list[Any] | None = None,
        **kwargs: Any,
    ) -> ChatMessage:
        self.message_text = "\n".join(str(message.content or "") for message in messages)
        del stop_sequences, response_format, kwargs
        self.available_tool_names = [tool.name for tool in tools_to_call_from or []]
        self.calls += 1
        if self.calls == 1:
            function = ChatMessageToolCallFunction(
                name="workspace_open_component",
                arguments={
                    "component_id": "visual-composition",
                    "title": "Research overview",
                    "props": {
                        "root_id": "overview",
                        "elements": [
                            {
                                "id": "overview",
                                "type": "heading",
                                "text": "Research overview",
                            }
                        ],
                    },
                },
            )
            call_id = "open-visual"
        else:
            function = ChatMessageToolCallFunction(
                name="final_answer",
                arguments={
                    "answer": (
                        "The research overview covers wearable systems, memory tools, "
                        "software agents, and immersive interfaces in extensive detail."
                    )
                },
            )
            call_id = "final-answer"
        return ChatMessage(
            role=MessageRole.ASSISTANT,
            content="",
            tool_calls=[ChatMessageToolCall(function=function, id=call_id, type="function")],
        )


def public_principal() -> PrincipalContext:
    session_id = uuid4()
    return PrincipalContext(
        authenticated=False,
        anonymous_session_id=session_id,
        roles=["public"],
        session_id=session_id,
    )


def test_toolcalling_adapter_reads_authorized_resource_and_emits_portable_events() -> None:
    async def scenario() -> None:
        model = ScriptedToolCallingModel()
        resources = FileResourceProvider.with_sample_syllabus()
        runtime = SmolagentsRuntime(
            model_provider=ScriptedProvider(model),
            tools=ToolCatalog([CourseReadSyllabusTool(resources), HiddenCourseTool(resources)]),
            public_resource_index=(
                "Course Application Guide: capacity, deadlines, and required fields",
            ),
        )
        conversation_id = uuid4()
        context = AgentContext(
            principal=public_principal(),
            conversation_id=conversation_id,
            permitted_tool_ids=[READ_SYLLABUS_TOOL_ID],
            permitted_resource_uris=[COURSE_SYLLABUS_URI],
        )
        agent_input = AgentInput(
            conversation_id=conversation_id,
            text="What does the syllabus say?",
        )

        result = await runtime.run(context=context, input=agent_input)

        assert result.output_text == "The syllabus describes readings and student-built tools."
        assert "course_read_syllabus" in model.available_tool_names
        assert "ta_list_questions" not in model.available_tool_names
        assert "Official information available through tools" in model.message_text
        assert "Course Application Guide" in model.message_text
        assert "Application workflow:" not in model.message_text
        assert "exactly one missing field per message" not in model.message_text
        assert "resource identifiers" in model.message_text
        assert "Trusted platform metadata for follow-up workspace calls only" in (
            model.message_text
        )
        assert COURSE_SYLLABUS_URI in model.message_text
        assert "course://application" not in model.message_text
        assert [event.type for event in result.events] == [
            "agent.run.started",
            "agent.tool.requested",
            "resource.read",
            "agent.tool.completed",
            "agent.message",
            "agent.run.completed",
        ]
        assert result.events[2].payload == {"uri": COURSE_SYLLABUS_URI}
        assert AgentResult.model_validate_json(result.model_dump_json()) == result

    asyncio.run(scenario())


def test_application_guide_and_web_action_are_retained_as_natural_history() -> None:
    async def scenario() -> None:
        model = ScriptedToolCallingModel()
        resources = FileResourceProvider.with_sample_syllabus()
        runtime = SmolagentsRuntime(
            model_provider=ScriptedProvider(model),
            tools=ToolCatalog([CourseReadSyllabusTool(resources)]),
        )
        conversation_id = uuid4()
        principal = public_principal()
        context = AgentContext(
            principal=principal,
            conversation_id=conversation_id,
            recent_events=[
                Event(
                    type="agent.tool.completed",
                    actor="course-agent",
                    anonymous_session_id=principal.anonymous_session_id,
                    conversation_id=conversation_id,
                    payload={
                        "tool_id": GET_APPLICATION_TOOL_ID,
                        "storage_policy": "server_full",
                        "result": "Ask for one field at a time and search after the full name.",
                    },
                ),
                Event(
                    type="agent.tool.completed",
                    actor="course-agent",
                    anonymous_session_id=principal.anonymous_session_id,
                    conversation_id=conversation_id,
                    payload={
                        "tool_id": WEB_SEARCH_TOOL_ID,
                        "storage_policy": "server_summary",
                        "summary": "Searched the public web.",
                    },
                ),
                Event(
                    type="workspace.interaction",
                    actor="user",
                    anonymous_session_id=principal.anonymous_session_id,
                    conversation_id=conversation_id,
                    payload={
                        "panel_id": str(uuid4()),
                        "component_id": "calendar",
                        "action": "calendar.select_event",
                        "value": "week-3",
                    },
                ),
            ],
            permitted_tool_ids=[READ_SYLLABUS_TOOL_ID],
            permitted_resource_uris=[COURSE_SYLLABUS_URI],
        )

        await runtime.run(
            context=context,
            input=AgentInput(conversation_id=conversation_id, text="Continue."),
        )

        assert "Official application guide:" in model.message_text
        assert "search after the full name" in model.message_text
        assert "Public web search completed" in model.message_text
        assert "calendar.select_event" in model.message_text
        assert "week-3" in model.message_text
        assert GET_APPLICATION_TOOL_ID not in model.message_text
        assert WEB_SEARCH_TOOL_ID not in model.message_text

    asyncio.run(scenario())


def test_dialogue_history_is_replayed_with_roles_and_continuity_guidance() -> None:
    async def scenario() -> None:
        model = ScriptedToolCallingModel()
        resources = FileResourceProvider.with_sample_syllabus()
        runtime = SmolagentsRuntime(
            model_provider=ScriptedProvider(model),
            tools=ToolCatalog([CourseReadSyllabusTool(resources)]),
        )
        conversation_id = uuid4()
        principal = public_principal()
        context = AgentContext(
            principal=principal,
            conversation_id=conversation_id,
            recent_events=[
                Event(
                    type="user.message",
                    actor="user",
                    anonymous_session_id=principal.anonymous_session_id,
                    conversation_id=conversation_id,
                    payload={"text": "I am applying to the course."},
                ),
                Event(
                    type="agent.message",
                    actor="course-agent",
                    anonymous_session_id=principal.anonymous_session_id,
                    conversation_id=conversation_id,
                    payload={"text": "Please upload a class-only representative picture."},
                ),
            ],
            permitted_tool_ids=[READ_SYLLABUS_TOOL_ID],
            permitted_resource_uris=[COURSE_SYLLABUS_URI],
        )

        await runtime.run(
            context=context,
            input=AgentInput(
                conversation_id=conversation_id,
                text="[Temporary upload: face.png]",
            ),
        )

        first_messages = model.message_snapshots[0]
        assert [message.role for message in first_messages] == [
            MessageRole.SYSTEM,
            MessageRole.USER,
            MessageRole.ASSISTANT,
            MessageRole.USER,
        ]
        system_text = str(first_messages[0].content)
        assert "Continue the conversation coherently" in system_text
        assert "I am applying to the course." not in system_text
        assert "Please upload a class-only representative picture." not in system_text
        assert "I am applying to the course." in str(first_messages[1].content)
        assert "Please upload a class-only representative picture." in str(
            first_messages[2].content
        )
        assert "[Temporary upload: face.png]" in str(first_messages[3].content)

    asyncio.run(scenario())


def test_workspace_tool_emits_validated_portable_panel_event() -> None:
    async def scenario() -> None:
        def image_search(_query: str, _limit: int) -> list[dict[str, object]]:
            return []

        model = ScriptedWorkspaceModel()
        registry = load_component_registry()
        runtime = SmolagentsRuntime(
            model_provider=ScriptedProvider(model),
            tools=ToolCatalog(
                [
                    WorkspaceOpenComponentTool(registry),
                    PublicImageSearchTool(image_search, lambda url: url),
                    PublicVisitWebpageTool(lambda _url: "# Readable page"),
                ]
            ),
        )
        conversation_id = uuid4()
        draft_panel_id = uuid4()
        context = AgentContext(
            principal=public_principal(),
            conversation_id=conversation_id,
            permitted_tool_ids=[
                OPEN_COMPONENT_TOOL_ID,
                WEB_IMAGE_SEARCH_TOOL_ID,
                VISIT_WEBPAGE_TOOL_ID,
            ],
            permitted_resource_uris=["course://schedule"],
            metadata={
                "workspace_state": {
                    "panels": [
                        {
                            "id": str(draft_panel_id),
                            "component_id": "draft-document",
                            "title": "Course application",
                            "resource_uri": "course://application",
                            "props": {
                                "title": "Course application",
                                "fields": [
                                    {
                                        "id": "name",
                                        "label": "Name",
                                        "value": "Ada Applicant",
                                        "status": "confirmed",
                                    }
                                ],
                            },
                            "state": {},
                        }
                    ],
                    "focused_panel_id": str(draft_panel_id),
                }
            },
        )

        result = await runtime.run(
            context=context,
            input=AgentInput(conversation_id=conversation_id, text="Show the schedule."),
        )

        assert [event.type for event in result.events] == [
            "agent.run.started",
            "agent.tool.requested",
            "agent.tool.completed",
            "workspace.panel.opened",
            "agent.message",
            "agent.run.completed",
        ]
        command = result.events[3].payload["command"]
        assert isinstance(command, dict)
        panel = command["panel"]
        assert isinstance(panel, dict)
        assert panel["component_id"] == "calendar"
        assert "workspace_open_component" in model.available_tool_names
        assert "preferred presentation surface" in model.message_text
        assert "show schedules in the calendar" in model.message_text
        assert "specific paper, PDF, text file" in model.message_text
        assert "specific website in webpage-viewer" in model.message_text
        assert "For knowledge questions" in model.message_text
        assert "Never use document-viewer merely because the source" in model.message_text
        assert "course overviews" in model.message_text
        assert "Prefer controlling the best-fit UI" in model.message_text
        assert "make the best available workspace UI part of the first answer" in model.message_text
        assert "presentation pass before the first open" in model.message_text
        assert "instead of repeating one hero-and-card template" in model.message_text
        assert "stack, row, and grid as equal layout options" in model.message_text
        assert (
            "Use side-by-side columns only when items are genuinely parallel" in model.message_text
        )
        assert "Do not repeat multiple two-column sections" in model.message_text
        assert "must not be a stack of long paragraphs" in model.message_text
        assert "numbered surfaced stages for methods" in model.message_text
        assert "optional side-by-side treatment" in model.message_text
        assert "diagrammatic group or meaningful image" in model.message_text
        assert "banner for one strong panoramic" in model.message_text
        assert "feature for a large image beside concise copy" in model.message_text
        assert "card for repeated project" in model.message_text
        assert "avatar for a compact person profile" in model.message_text
        assert "These are options, not a checklist" in model.message_text
        assert "Do not default every answer" in model.message_text
        assert "roughly one-third to one-half" in model.message_text
        assert "Never place a tiny thumbnail" in model.message_text
        assert "bar for categorical comparisons" in model.message_text
        assert "line for change across an ordered sequence" in model.message_text
        assert "Never invent, estimate, or visually imply numeric data" in model.message_text
        assert (
            "must declare data_kind, data_source, comparison_basis, and unit" in model.message_text
        )
        assert "rejects qualitative 3-2-1 ranks" in model.message_text
        assert "primary editorial section" in model.message_text
        assert "do not wrap it in another raised or accent card" in model.message_text
        assert "coral, secondary (sky), success (mint)" in model.message_text
        assert "per-value tones" in model.message_text
        assert "avoid arbitrary rainbow coloring" in model.message_text
        assert "Every series object uses label and values—never name" in model.message_text
        assert '"tones":["secondary","coral"]' in model.message_text
        assert "Never put tones or value_tones on the chart element itself" in model.message_text
        assert "the workspace is the answer" in model.message_text
        assert "must not list, summarize, or restate facts" in model.message_text
        assert "one current surface" in model.message_text
        assert "let it replace the old one" in model.message_text
        assert "explicitly assess whether the subject has meaningful visual" in model.message_text
        assert "named people, physical projects" in model.message_text
        assert "figures, diagrams, screenshots" in model.message_text
        assert "paper title or project name plus figure" in model.message_text
        assert "short natural-language query without site: filters" in model.message_text
        assert "complete the search before the first workspace open call" in model.message_text
        assert "Inspect dimensions_known, width, height" in model.message_text
        assert "split_layout_safe, recommended_width" in model.message_text
        assert "source_width and source_height" in model.message_text
        assert "unknown-dimension or small result as a banner" in model.message_text
        assert "aspect ratio of 2:1 or wider is shallow" in model.message_text
        assert "Never put that shallow image in a row" in model.message_text
        assert "administrative answers" in model.message_text
        assert "workspace platform enforces this" in model.message_text
        assert "composition that skipped image search" in model.message_text
        assert "direct HTTPS image URL" in model.message_text
        assert "For any evolving written artifact" in model.message_text
        assert "proposals, reports" in model.message_text
        assert "Workspace focus is silent UI housekeeping" in model.message_text
        assert "Do not call workspace.focus_component when" in model.message_text
        assert "call it directly" in model.message_text
        assert "Use non-final tools directly" in model.message_text
        assert "make one bounded public-web research pass" in model.message_text
        assert "preserve every clearly supported result" in model.message_text
        assert "Do not leave supported later fields empty" in model.message_text
        assert "too shallow" in model.message_text
        assert "strict turn-by-turn interview" in model.message_text
        assert "contain exactly one focused request or question" in model.message_text
        assert "Never list, preview, or ask about later missing fields" in model.message_text
        assert "one atomic draft update" in model.message_text
        assert "immediately use final_answer and wait for the user" in model.message_text
        assert "confirmation requests belong only in final_answer" in model.message_text
        assert "never ask an open-ended question for a value already present" in model.message_text
        assert "for class use only" in model.message_text
        assert "need not be a formal headshot" in model.message_text
        assert "every canonical field is confirmed" in model.message_text
        assert "Current trusted workspace state" in model.message_text
        assert str(draft_panel_id) in model.message_text
        assert "Ada Applicant" in model.message_text
        assert "Reader mode is the default" in model.message_text
        assert "untrusted data" in model.message_text

    asyncio.run(scenario())


def test_agent_owned_application_start_opens_canonical_draft_once() -> None:
    async def scenario() -> None:
        model = ScriptedApplicationStartModel()
        resources = FileResourceProvider.from_registry()
        registry = load_component_registry()
        runtime = SmolagentsRuntime(
            model_provider=ScriptedProvider(model),
            tools=ToolCatalog(
                [
                    CourseGetApplicationTool(resources),
                    WorkspaceOpenComponentTool(registry),
                ]
            ),
        )
        conversation_id = uuid4()

        result = await runtime.run(
            context=AgentContext(
                principal=public_principal(),
                conversation_id=conversation_id,
                permitted_tool_ids=[GET_APPLICATION_TOOL_ID, OPEN_COMPONENT_TOOL_ID],
                permitted_resource_uris=[COURSE_APPLICATION_URI],
                metadata={"workspace_state": {"panels": []}},
            ),
            input=AgentInput(
                conversation_id=conversation_id,
                text="Can you help me put my name in for the class?",
            ),
        )

        requested_tools = [
            event.payload["tool_id"]
            for event in result.events
            if event.type == "agent.tool.requested"
        ]
        assert requested_tools == [GET_APPLICATION_TOOL_ID, OPEN_COMPONENT_TOOL_ID]
        opened_event = next(
            event for event in result.events if event.type == "workspace.panel.opened"
        )
        command = opened_event.payload["command"]
        assert isinstance(command, dict)
        panel = command["panel"]
        assert isinstance(panel, dict)
        assert panel["resource_uri"] == COURSE_APPLICATION_URI
        assert panel["state"] == {"document_kind": "course-application"}
        props = panel["props"]
        assert isinstance(props, dict)
        fields = props["fields"]
        assert isinstance(fields, list)
        assert len(fields) == 13
        assert result.output_text == "The application is open. What is your full name?"
        assert "Recognize course-application intent semantically" in model.message_text
        assert "call course.get_application exactly once" in model.message_text
        assert "Open the form during that first turn" in model.message_text

    asyncio.run(scenario())


def test_visual_workspace_carries_the_detail_without_a_duplicate_chat_answer() -> None:
    async def scenario() -> None:
        model = ScriptedVisualWorkspaceModel()
        registry = load_component_registry()
        runtime = SmolagentsRuntime(
            model_provider=ScriptedProvider(model),
            tools=ToolCatalog([WorkspaceOpenComponentTool(registry)]),
        )
        conversation_id = uuid4()
        result = await runtime.run(
            context=AgentContext(
                principal=public_principal(),
                conversation_id=conversation_id,
                permitted_tool_ids=[OPEN_COMPONENT_TOOL_ID],
            ),
            input=AgentInput(conversation_id=conversation_id, text="Show the research."),
        )

        assert result.output_text == "I've organized the answer into a visual workspace."
        assert result.events[-2].payload["text"] == result.output_text
        assert "wearable systems" not in result.output_text

    asyncio.run(scenario())


def test_toolcalling_adapter_observes_portable_events_during_the_run() -> None:
    async def scenario() -> None:
        model = ScriptedToolCallingModel()
        resources = FileResourceProvider.with_sample_syllabus()
        runtime = SmolagentsRuntime(
            model_provider=ScriptedProvider(model),
            tools=ToolCatalog([CourseReadSyllabusTool(resources)]),
        )
        conversation_id = uuid4()
        context = AgentContext(
            principal=public_principal(),
            conversation_id=conversation_id,
            permitted_tool_ids=[READ_SYLLABUS_TOOL_ID],
            permitted_resource_uris=[COURSE_SYLLABUS_URI],
        )
        agent_input = AgentInput(
            conversation_id=conversation_id,
            text="What does the syllabus say?",
        )
        observed: list[Event] = []

        result = await runtime.run_observed(
            context=context,
            input=agent_input,
            event_observer=observed.append,
        )

        assert [event.id for event in observed] == [event.id for event in result.events]
        assert [event.type for event in observed] == [
            "agent.run.started",
            "agent.tool.requested",
            "resource.read",
            "agent.tool.completed",
            "agent.message",
            "agent.run.completed",
        ]

    asyncio.run(scenario())


def test_toolcalling_adapter_discards_nonfinal_text_and_streams_final_answer() -> None:
    async def scenario() -> None:
        model = ScriptedStreamingToolCallingModel()
        resources = FileResourceProvider.with_sample_syllabus()
        runtime = SmolagentsRuntime(
            model_provider=ScriptedProvider(model),
            tools=ToolCatalog([CourseReadSyllabusTool(resources)]),
        )
        conversation_id = uuid4()
        context = AgentContext(
            principal=public_principal(),
            conversation_id=conversation_id,
            permitted_tool_ids=[READ_SYLLABUS_TOOL_ID],
            permitted_resource_uris=[COURSE_SYLLABUS_URI],
        )
        agent_input = AgentInput(
            conversation_id=conversation_id,
            text="What does the syllabus say?",
        )
        observed_events: list[Event] = []
        text_deltas: list[str] = []

        result = await runtime.run_observed(
            context=context,
            input=agent_input,
            event_observer=observed_events.append,
            text_delta_observer=text_deltas.append,
        )

        expected = 'The syllabus says "agents" are inspectable.\nDone.'
        assert "".join(text_deltas) == expected
        assert result.output_text == expected
        assert "syllabus before answering" not in "".join(text_deltas)
        assert "one more detail" not in "".join(text_deltas)
        assert all("course_read_syllabus" not in delta for delta in text_deltas)
        assert [event.type for event in observed_events] == [
            "agent.run.started",
            "agent.tool.requested",
            "resource.read",
            "agent.tool.completed",
            "agent.tool.requested",
            "resource.read",
            "agent.tool.completed",
            "agent.message",
            "agent.run.completed",
        ]

    asyncio.run(scenario())
