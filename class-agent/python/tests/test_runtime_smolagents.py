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
    WEB_SEARCH_TOOL_ID,
    CourseReadSyllabusTool,
    FileResourceProvider,
    ToolCatalog,
)
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
        if self.calls == 1:
            yield ChatMessageStreamDelta(content="I'll read the syllabus before answering.")
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
        assert GET_APPLICATION_TOOL_ID not in model.message_text
        assert WEB_SEARCH_TOOL_ID not in model.message_text

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
        progress_deltas: list[str] = []

        result = await runtime.run_observed(
            context=context,
            input=agent_input,
            event_observer=observed_events.append,
            text_delta_observer=text_deltas.append,
            progress_delta_observer=progress_deltas.append,
        )

        expected = 'The syllabus says "agents" are inspectable.\nDone.'
        assert "".join(text_deltas) == expected
        assert result.output_text == expected
        assert "".join(progress_deltas) == "I'll read the syllabus before answering."
        assert all("course_read_syllabus" not in delta for delta in text_deltas)
        assert [event.type for event in observed_events] == [
            "agent.run.started",
            "agent.tool.requested",
            "resource.read",
            "agent.tool.completed",
            "agent.message",
            "agent.run.completed",
        ]

    asyncio.run(scenario())
