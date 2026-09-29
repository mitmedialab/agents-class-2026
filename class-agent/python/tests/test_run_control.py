from __future__ import annotations

import asyncio
import json
from typing import Any
from uuid import uuid4

import pytest
from smolagents import ChatMessage, ChatMessageStreamDelta, ChatMessageToolCall, Model
from smolagents.models import ChatMessageToolCallFunction, ChatMessageToolCallStreamDelta
from test_runtime_smolagents import ScriptedProvider, public_principal

from agent_core import AgentContext, AgentInput
from course_server.agent import ToolCatalog
from course_server.workspace.tools import WorkspaceReviewPresentationTool
from runtime_smolagents import SmolagentsRuntime


class RepeatingModel(Model):  # type: ignore[misc]
    def __init__(self, mode: str) -> None:
        super().__init__()
        self.mode = mode
        self.calls = 0
        self.seen: list[str] = []

    def generate(self, messages: list[ChatMessage], **kwargs: Any) -> ChatMessage:
        self.calls += 1
        self.seen.append(str(messages))
        # Alternating invalid arguments reach the budget; repeated valid calls hit the stall guard.
        decision = "no_visual" if self.mode != "budget" else f"invalid-{self.calls}"
        name = "workspace_review_presentation"
        args = {"decision": decision}
        if self.mode == "recover" and self.calls == 3:
            name, args = "final_answer", {"answer": "Review complete."}
        return ChatMessage(
            role="assistant",
            tool_calls=[
                ChatMessageToolCall(
                    id=f"call-{self.calls}",
                    type="function",
                    function=ChatMessageToolCallFunction(name=name, arguments=args),
                )
            ],
        )

    def generate_stream(self, messages: list[ChatMessage], **kwargs: Any) -> Any:
        message = self.generate(messages, **kwargs)
        for call in message.tool_calls or []:
            yield ChatMessageStreamDelta(
                tool_calls=[
                    ChatMessageToolCallStreamDelta(
                        index=0,
                        id=call.id,
                        type="function",
                        function=ChatMessageToolCallFunction(
                            name=call.function.name,
                            arguments=json.dumps(call.function.arguments),
                        ),
                    )
                ]
            )


@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize(
    "mode,reason", [("repeat", "repeated_tool_calls"), ("budget", "step_limit")]
)
def test_interrupted_runs_preserve_events_and_never_generate_unreviewed_fallback(
    streaming: bool,
    mode: str,
    reason: str,
) -> None:
    async def scenario() -> None:
        model = RepeatingModel(mode)
        runtime = SmolagentsRuntime(
            model_provider=ScriptedProvider(model),
            tools=ToolCatalog([WorkspaceReviewPresentationTool()]),
            max_steps=3,
        )
        c = uuid4()
        context = AgentContext(
            principal=public_principal(),
            conversation_id=c,
            permitted_tool_ids=["workspace.review_presentation"],
            metadata={"workspace_state": {"panels": []}},
        )
        input = AgentInput(conversation_id=c, text="Test interrupted run")
        if streaming:
            result = await runtime.run_observed(
                context=context,
                input=input,
                event_observer=lambda _: None,
                text_delta_observer=lambda _: None,
            )
        else:
            result = await runtime.run(context=context, input=input)
        assert result.metadata["termination_reason"] == reason
        assert "task is incomplete" in result.output_text
        assert model.calls == (3 if mode == "repeat" else 4)
        assert result.events[-1].payload["outcome"] == "incomplete"
        assert any(e.type == "agent.run.interrupted" for e in result.events)
        assert any(e.type == "agent.tool.requested" for e in result.events)
        diagnostics = [e.payload for e in result.events if e.type == "agent.step.completed"]
        assert len(diagnostics) == model.calls
        assert all(set(d) == {"step", "tool_names", "error_type"} for d in diagnostics)
        assert "Runtime notice" in model.seen[-1]
        if mode == "budget":
            assert diagnostics[-1]["error_type"] == "AgentToolExecutionError"

    asyncio.run(scenario())


def test_repeat_warning_allows_model_to_finish_normally() -> None:
    async def scenario() -> None:
        model = RepeatingModel("recover")
        runtime = SmolagentsRuntime(
            model_provider=ScriptedProvider(model),
            tools=ToolCatalog([WorkspaceReviewPresentationTool()]),
            max_steps=5,
        )
        c = uuid4()
        result = await runtime.run(
            context=AgentContext(
                principal=public_principal(),
                conversation_id=c,
                permitted_tool_ids=["workspace.review_presentation"],
                metadata={"workspace_state": {"panels": []}},
            ),
            input=AgentInput(conversation_id=c, text="Finish the review"),
        )
        assert result.output_text == "Review complete."
        assert result.events[-1].payload["outcome"] == "complete"
        assert result.metadata["termination_reason"] is None
        assert "same calls repeated" in model.seen[-1]

    asyncio.run(scenario())


def test_interruption_persists_workspace_and_next_turn_resumes_from_it() -> None:
    from agent_core import PrincipalContext
    from course_server.agent import CourseAgentService, InMemoryConversationStore
    from course_server.agent.capabilities import AuthorizedCapabilities, CourseCapabilityPolicy
    from course_server.workspace import load_component_registry, project_workspace_events
    from course_server.workspace.tools import WorkspaceOpenComponentTool

    class WorkspacePolicy(CourseCapabilityPolicy):
        def authorize(self, principal: PrincipalContext) -> AuthorizedCapabilities:
            return AuthorizedCapabilities(
                tool_ids=("workspace.open_component", "workspace.review_presentation"),
                resource_uris=(),
            )

    class CheckpointModel(RepeatingModel):
        def generate(self, messages: list[ChatMessage], **kwargs: Any) -> ChatMessage:
            message = super().generate(messages, **kwargs)
            assert message.tool_calls
            call = message.tool_calls[0].function
            if self.calls == 1:
                call.name = "workspace_open_component"
                call.arguments = {
                    "component_id": "draft-document",
                    "title": "Review progress",
                    "props": {
                        "title": "Review progress",
                        "content": "Reviewed A with source references. Remaining: B, C, D.",
                    },
                }
            elif self.calls == 5:
                call.arguments = {"decision": "keep_current"}
            elif self.calls == 6:
                call.name = "final_answer"
                call.arguments = {"answer": "Resumed from the saved checkpoint."}
            return message

    async def scenario() -> None:
        model = CheckpointModel("repeat")
        registry = load_component_registry()
        runtime = SmolagentsRuntime(
            model_provider=ScriptedProvider(model),
            tools=ToolCatalog(
                [
                    WorkspaceOpenComponentTool(registry),
                    WorkspaceReviewPresentationTool(),
                ]
            ),
            max_steps=8,
        )
        store = InMemoryConversationStore()
        service = CourseAgentService(
            runtime=runtime, conversations=store, capability_policy=WorkspacePolicy()
        )
        principal = public_principal()
        conversation = await service.create_conversation(principal)
        first = await service.run(
            principal=principal, conversation_id=conversation.id, text="Start review"
        )
        assert first.metadata["termination_reason"] == "repeated_tool_calls"
        events = await store.list_events(conversation.id)
        state = project_workspace_events(events, registry)
        assert len(state.panels) == 1
        assert "Remaining: B, C, D" in str(state.panels[0].props)
        assert any(e.type == "agent.step.completed" for e in events)
        second = await service.run(
            principal=principal, conversation_id=conversation.id, text="Continue"
        )
        assert second.output_text == "Resumed from the saved checkpoint."
        assert "Remaining: B, C, D" in model.seen[-1]

    asyncio.run(scenario())


def test_repeated_calls_with_changing_results_are_not_a_stall() -> None:
    from collections.abc import Mapping
    from typing import ClassVar

    from pydantic import JsonValue

    from course_server.agent import ToolExecutionContext, ToolExecutionResult

    class ChangingRead:
        id = "test.read"
        description = "Read changing test state."
        input_schema: ClassVar[dict[str, JsonValue]] = {"type": "object", "properties": {}}
        revision = 0

        async def execute(
            self, arguments: Mapping[str, JsonValue], context: ToolExecutionContext
        ) -> ToolExecutionResult:
            self.revision += 1
            return ToolExecutionResult(content={"revision": self.revision})

    class PollingModel(RepeatingModel):
        def generate(self, messages: list[ChatMessage], **kwargs: Any) -> ChatMessage:
            message = super().generate(messages, **kwargs)
            assert message.tool_calls
            call = message.tool_calls[0].function
            call.name = "test_read" if self.calls < 4 else "final_answer"
            call.arguments = {} if self.calls < 4 else {"answer": "Finished."}
            return message

    async def scenario() -> None:
        model = PollingModel("repeat")
        runtime = SmolagentsRuntime(
            model_provider=ScriptedProvider(model), tools=ToolCatalog([ChangingRead()]), max_steps=5
        )
        c = uuid4()
        result = await runtime.run(
            context=AgentContext(
                principal=public_principal(), conversation_id=c, permitted_tool_ids=["test.read"]
            ),
            input=AgentInput(conversation_id=c, text="Read until updated."),
        )
        assert result.output_text == "Finished."
        assert result.metadata["termination_reason"] is None

    asyncio.run(scenario())
