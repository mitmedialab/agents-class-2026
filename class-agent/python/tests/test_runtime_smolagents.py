from __future__ import annotations

import asyncio
from collections.abc import Iterator
from pathlib import Path
from typing import Any, ClassVar
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
    READ_SKILL_TOOL_ID,
    READ_SYLLABUS_TOOL_ID,
    VISIT_WEBPAGE_TOOL_ID,
    WEB_IMAGE_SEARCH_TOOL_ID,
    WEB_SEARCH_TOOL_ID,
    CourseGetApplicationTool,
    CourseReadSyllabusTool,
    CourseSubmitApplicationTool,
    FileResourceProvider,
    PublicImageSearchTool,
    PublicVisitWebpageTool,
    ReadSkillTool,
    SkillCatalog,
    ToolCatalog,
    ToolExecutionResult,
)
from course_server.agent.capabilities import ToolEmittedEvent
from course_server.workspace import load_component_registry
from course_server.workspace.constants import OPEN_COMPONENT_TOOL_ID
from course_server.workspace.tools import WorkspaceOpenComponentTool
from runtime_smolagents import SmolagentsRuntime
from runtime_smolagents.runtime import (
    _conversation_history,
    _render_tool_result,
    _smolagents_inputs,
)


class HiddenCourseTool(CourseReadSyllabusTool):
    id = "ta.list_questions"


class ConfirmationTool:
    id = "course.ask_ta"
    description = "Prepare a question for course staff."
    input_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    }

    async def execute(self, arguments: Any, context: Any) -> ToolExecutionResult:
        del arguments, context
        return ToolExecutionResult(
            content={"confirmation_required": True},
            summary="Prepared a staff question awaiting student confirmation.",
            storage_policy="server_summary",
            emitted_events=[
                ToolEmittedEvent(
                    type="email.ta_question.confirmation_requested",
                    payload={
                        "question_id": str(uuid4()),
                        "question": (
                            "Are students permitted to use fog machines as part of weekly builds? "
                            "If so, are there any course-specific safety requirements or approvals "
                            "required?"
                        ),
                    },
                )
            ],
        )


def test_runtime_presents_the_exact_confirmed_question_as_trusted_context() -> None:
    principal = PrincipalContext(
        authenticated=True,
        user_id=uuid4(),
        username="student",
        roles=["public", "student"],
        session_id=uuid4(),
    )
    context = AgentContext(
        principal=principal,
        conversation_id=uuid4(),
        recent_events=[
            Event(
                type="email.ta_question.queued",
                actor="user",
                principal_user_id=principal.user_id,
                payload={
                    "question": "Which assignments are group work?",
                    "status": "queued",
                },
            )
        ],
    )

    history = _conversation_history(context)

    assert "submitted to course staff" in history
    assert "Which assignments are group work?" in history


def test_runtime_preserves_application_tool_constraints() -> None:
    inputs = _smolagents_inputs(CourseSubmitApplicationTool.input_schema)

    assert inputs["school"]["enum"] == [
        "MIT Media Lab",
        "MIT",
        "Harvard",
        "Wellesley",
        "Other",
    ]
    assert inputs["registration_status"]["enum"] == ["for credit", "listener"]
    assert inputs["listener_willing_to_do_weekly_builds"]["enum"] == [
        "yes",
        "no",
        "not applicable",
    ]
    assert inputs["github_id"]["pattern"].startswith("^[A-Za-z0-9]")
    assert inputs["degree_start_year"]["pattern"] == "^\\d{4}$"
    assert inputs["email"]["format"] == "email"


def test_runtime_marks_every_presented_tool_result_as_primary_ui_content() -> None:
    for event_type in (
        "email.ta_question.confirmation_requested",
        "workspace.panel.opened",
        "workspace.panel.updated",
    ):
        rendered = _render_tool_result(
            ToolExecutionResult(
                content={"status": "displayed"},
                emitted_events=[ToolEmittedEvent(type=event_type)],
            )
        )

        assert "platform UI now presents" in rendered
        assert "do not repeat or quote information that UI already shows" in rendered

    ordinary_result = _render_tool_result(ToolExecutionResult(content={"status": "complete"}))
    assert "platform UI now presents" not in ordinary_result


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


class ScriptedStreamingTAConfirmationModel(ScriptedToolCallingModel):
    def generate_stream(
        self,
        messages: list[ChatMessage],
        stop_sequences: list[str] | None = None,
        response_format: dict[str, str] | None = None,
        tools_to_call_from: list[Any] | None = None,
        **kwargs: Any,
    ) -> Iterator[ChatMessageStreamDelta]:
        self.message_text = "\n".join(str(message.content or "") for message in messages)
        del stop_sequences, response_format, kwargs
        self.available_tool_names = [tool.name for tool in tools_to_call_from or []]
        self.calls += 1
        if self.calls == 1:
            yield ChatMessageStreamDelta(content="I'll prepare the staff question now.")
            yield ChatMessageStreamDelta(
                tool_calls=[
                    ChatMessageToolCallStreamDelta(
                        index=0,
                        id="ask-course-staff",
                        type="function",
                        function=ChatMessageToolCallFunction(
                            name="course_ask_ta",
                            arguments="{}",
                        ),
                    )
                ]
            )
            return
        yield ChatMessageStreamDelta(
            tool_calls=[
                ChatMessageToolCallStreamDelta(
                    index=0,
                    id="final-answer",
                    type="function",
                    function=ChatMessageToolCallFunction(
                        name="final_answer",
                        arguments=(
                            '{"answer":"I could not find a documented answer. Please use Send if '
                            'you want the prepared question delivered."}'
                        ),
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


class ScriptedSkillModel(ScriptedToolCallingModel):
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
                name="skills_read",
                arguments={"skill_id": "course-help"},
            )
            call_id = "read-skill"
        else:
            function = ChatMessageToolCallFunction(
                name="final_answer",
                arguments={"answer": "I used the relevant course guidance."},
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
                        "root_id": "root",
                        "elements": [
                            {
                                "id": "root",
                                "type": "group",
                                "children": ["overview", "detail"],
                            },
                            {
                                "id": "overview",
                                "type": "heading",
                                "text": "Research overview",
                            },
                            {
                                "id": "detail",
                                "type": "text",
                                "text": (
                                    "Wearable systems, memory tools, software agents, and "
                                    "immersive interfaces are the four main research areas."
                                ),
                            },
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
                        "I've organized the findings in the workspace. Wearable systems, memory "
                        "tools, software agents, and immersive interfaces are the four main "
                        "research areas."
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
            metadata={
                "authorized_skill_index": [
                    {
                        "id": "course-help",
                        "name": "course-help",
                        "description": "Answer official course questions.",
                    }
                ]
            },
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
        assert "course-help: Answer official course questions." in model.message_text
        assert "call skills.read before applying it" in model.message_text
        assert "Use official course resources as the source of truth" not in model.message_text
        assert "Read the official course syllabus resource" not in model.message_text
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


def test_runtime_loads_authorized_skill_body_only_after_explicit_tool_call() -> None:
    async def scenario() -> None:
        model = ScriptedSkillModel()
        skills = SkillCatalog.from_registry(Path(__file__).resolve().parents[2] / "skills")
        runtime = SmolagentsRuntime(
            model_provider=ScriptedProvider(model),
            tools=ToolCatalog([ReadSkillTool(skills)]),
        )
        conversation_id = uuid4()
        context = AgentContext(
            principal=public_principal(),
            conversation_id=conversation_id,
            permitted_tool_ids=[READ_SKILL_TOOL_ID],
            metadata={
                "authorized_skill_index": [
                    {
                        "id": "course-help",
                        "name": "course-help",
                        "description": "Answer official course questions.",
                    }
                ]
            },
        )

        result = await runtime.run(
            context=context,
            input=AgentInput(conversation_id=conversation_id, text="What are the course policies?"),
        )

        first_prompt = "\n".join(
            str(message.content or "") for message in model.message_snapshots[0]
        )
        second_prompt = "\n".join(
            str(message.content or "") for message in model.message_snapshots[1]
        )
        assert "course-help: Answer official course questions." in first_prompt
        assert "Use official course resources as the source of truth" not in first_prompt
        assert "Use official course resources as the source of truth" in second_prompt
        assert [
            event.payload["tool_id"]
            for event in result.events
            if event.type == "agent.tool.requested"
        ] == [READ_SKILL_TOOL_ID]
        completed = next(event for event in result.events if event.type == "agent.tool.completed")
        assert completed.payload["storage_policy"] == "server_summary"
        assert "instructions" not in completed.payload

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
        assert "Current trusted workspace state" in model.message_text
        assert str(draft_panel_id) in model.message_text
        assert "Ada Applicant" in model.message_text
        assert "preferred presentation surface" not in model.message_text
        assert "Search public images through a DuckDuckGo-first provider" not in model.message_text

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
        assert len(fields) == 17
        assert result.output_text == "The application is open. What is your full name?"
        assert "Recognize course-application intent semantically" not in model.message_text
        assert "Use the API-provided structured tools" in model.message_text

    asyncio.run(scenario())


def test_visual_workspace_preserves_model_authored_response_without_rewriting() -> None:
    async def scenario() -> None:
        model = ScriptedVisualWorkspaceModel()
        registry = load_component_registry()
        runtime = SmolagentsRuntime(
            model_provider=ScriptedProvider(model),
            tools=ToolCatalog([WorkspaceOpenComponentTool(registry, strict_visual_policy=False)]),
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

        expected = (
            "I've organized the findings in the workspace. Wearable systems, memory tools, "
            "software agents, and immersive interfaces are the four main research areas."
        )
        assert result.output_text == expected
        assert result.events[-2].payload["text"] == result.output_text
        assert "do not repeat or quote information that UI already shows" in model.message_text

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


def test_staff_confirmation_preserves_the_model_authored_final_response() -> None:
    async def scenario() -> None:
        model = ScriptedStreamingTAConfirmationModel()
        runtime = SmolagentsRuntime(
            model_provider=ScriptedProvider(model),
            tools=ToolCatalog([ConfirmationTool()]),
        )
        conversation_id = uuid4()
        observed_events: list[Event] = []
        text_deltas: list[str] = []

        result = await runtime.run_observed(
            context=AgentContext(
                principal=public_principal(),
                conversation_id=conversation_id,
                permitted_tool_ids=[ConfirmationTool.id],
            ),
            input=AgentInput(
                conversation_id=conversation_id,
                text="Can I use a local model?",
            ),
            event_observer=observed_events.append,
            text_delta_observer=text_deltas.append,
        )

        expected = (
            "I could not find a documented answer. Please use Send if you want the prepared "
            "question delivered."
        )
        assert any(
            event.type == "email.ta_question.confirmation_requested" for event in observed_events
        )
        assert "".join(text_deltas) == expected
        assert result.output_text == expected
        assert result.events[-2].payload["text"] == expected
        assert "I can ask course staff about this." not in result.output_text
        assert "do not repeat or quote information that UI already shows" in model.message_text
        assert "Put each piece of substantive information in either the UI or chat" in (
            model.message_text
        )

    asyncio.run(scenario())
