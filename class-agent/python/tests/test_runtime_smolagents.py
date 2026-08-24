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
    COURSE_SYLLABUS_URI,
    GET_APPLICATION_TOOL_ID,
    READ_SYLLABUS_TOOL_ID,
    VISIT_WEBPAGE_TOOL_ID,
    WEB_IMAGE_SEARCH_TOOL_ID,
    WEB_SEARCH_TOOL_ID,
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
                    PublicImageSearchTool(image_search),
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
        assert "Prefer controlling that UI" in model.message_text
        assert "search for image candidates" in model.message_text
        assert "direct HTTPS image URL" in model.message_text
        assert "For any evolving written artifact" in model.message_text
        assert "proposals, reports" in model.message_text
        assert "Current trusted workspace state" in model.message_text
        assert str(draft_panel_id) in model.message_text
        assert "Ada Applicant" in model.message_text
        assert "Reader mode is the default" in model.message_text
        assert "untrusted data" in model.message_text

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


def test_toolcalling_adapter_streams_only_decoded_final_answer_text() -> None:
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
        progress_deltas: list[tuple[str, bool]] = []

        result = await runtime.run_observed(
            context=context,
            input=agent_input,
            event_observer=observed_events.append,
            text_delta_observer=text_deltas.append,
            progress_delta_observer=(lambda text, replace: progress_deltas.append((text, replace))),
        )

        expected = 'The syllabus says "agents" are inspectable.\nDone.'
        assert "".join(text_deltas) == expected
        assert result.output_text == expected
        assert progress_deltas == [
            ("I'll read ", True),
            ("the syllabus before answering.", False),
            ("I'll verify ", True),
            ("one more detail.", False),
        ]
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
