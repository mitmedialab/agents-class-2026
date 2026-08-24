"""ToolCallingAgent adapter that emits only portable platform results."""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Callable, Iterable, Mapping
from threading import Lock
from typing import Any, cast

from pydantic import JsonValue, TypeAdapter
from smolagents import ChatMessageStreamDelta, FinalAnswerStep, Model, Tool, ToolCallingAgent
from smolagents.monitoring import LogLevel

from agent_core import AgentContext, AgentInput, AgentResult, Event, ModelProvider
from course_server.agent.capabilities import (
    ExecutableTool,
    ResourceNotFound,
    ToolCatalog,
    ToolExecutionContext,
    ToolExecutionResult,
)

_JSON_OBJECT = TypeAdapter(dict[str, JsonValue])
_TOOL_NAME_CHARACTER = re.compile(r"[^A-Za-z0-9_]")
_FINAL_ANSWER_START = re.compile(r'"answer"\s*:\s*"')


def _event_principal_fields(context: AgentContext) -> dict[str, Any]:
    return {
        "principal_user_id": context.principal.user_id,
        "anonymous_session_id": context.principal.anonymous_session_id,
    }


def _runtime_tool_name(tool_id: str) -> str:
    name = _TOOL_NAME_CHARACTER.sub("_", tool_id)
    if not name or name[0].isdigit():
        name = f"tool_{name}"
    return name


def _smolagents_inputs(schema: Mapping[str, JsonValue]) -> dict[str, dict[str, Any]]:
    properties = schema.get("properties", {})
    required_value = schema.get("required", [])
    if not isinstance(properties, dict) or not isinstance(required_value, list):
        raise ValueError("tool input_schema must be an object JSON Schema")
    required = {value for value in required_value if isinstance(value, str)}
    inputs: dict[str, dict[str, Any]] = {}
    for name, raw_property in properties.items():
        if not isinstance(raw_property, dict):
            raise ValueError(f"tool input property {name} must be an object")
        raw_type = raw_property.get("type", "any")
        input_type = raw_type if isinstance(raw_type, str) else "any"
        description = raw_property.get("description", name)
        inputs[name] = {
            "type": input_type,
            "description": description if isinstance(description, str) else name,
        }
        if name not in required:
            inputs[name]["nullable"] = True
    return inputs


def _tool_error_category(error: Exception) -> str:
    if isinstance(error, PermissionError):
        return "permission_denied"
    if isinstance(error, ResourceNotFound):
        return "resource_not_found"
    if isinstance(error, (TypeError, ValueError)):
        return "invalid_request"
    return "temporary_failure"


def _render_tool_result(result: ToolExecutionResult) -> str:
    if isinstance(result.content, str):
        return result.content
    return json.dumps(result.content, ensure_ascii=False, sort_keys=True)


def _partial_json_answer(arguments: str) -> str | None:
    """Decode the complete prefix of a possibly incomplete JSON answer string."""

    match = _FINAL_ANSWER_START.search(arguments)
    if match is None:
        return None
    output: list[str] = []
    cursor = match.end()
    escapes = {
        '"': '"',
        "\\": "\\",
        "/": "/",
        "b": "\b",
        "f": "\f",
        "n": "\n",
        "r": "\r",
        "t": "\t",
    }
    while cursor < len(arguments):
        character = arguments[cursor]
        if character == '"':
            break
        if character != "\\":
            output.append(character)
            cursor += 1
            continue
        if cursor + 1 >= len(arguments):
            break
        escape = arguments[cursor + 1]
        if escape in escapes:
            output.append(escapes[escape])
            cursor += 2
            continue
        if escape != "u" or cursor + 6 > len(arguments):
            break
        try:
            codepoint = int(arguments[cursor + 2 : cursor + 6], 16)
        except ValueError:
            break
        cursor += 6
        if 0xD800 <= codepoint <= 0xDBFF:
            if cursor + 6 > len(arguments) or arguments[cursor : cursor + 2] != "\\u":
                break
            try:
                low_surrogate = int(arguments[cursor + 2 : cursor + 6], 16)
            except ValueError:
                break
            if not 0xDC00 <= low_surrogate <= 0xDFFF:
                break
            codepoint = 0x10000 + ((codepoint - 0xD800) << 10) + (low_surrogate - 0xDC00)
            cursor += 6
        output.append(chr(codepoint))
    return "".join(output)


class _FinalAnswerDeltaExtractor:
    """Extract text only after the model selects the final-answer tool."""

    def __init__(self, observer: Callable[[str], None]) -> None:
        self._observer = observer
        self._tool_names: dict[int, str] = {}
        self._arguments: dict[int, str] = {}
        self._emitted: dict[int, str] = {}

    def add(self, delta: ChatMessageStreamDelta) -> None:
        for tool_call in delta.tool_calls or []:
            if tool_call.index is None or tool_call.function is None:
                continue
            index = tool_call.index
            function = tool_call.function
            if function.name:
                self._tool_names[index] = function.name
            if isinstance(function.arguments, str) and function.arguments:
                self._arguments[index] = self._arguments.get(index, "") + function.arguments
            elif isinstance(function.arguments, dict):
                answer = function.arguments.get("answer")
                if self._tool_names.get(index) == "final_answer" and isinstance(answer, str):
                    self._emit_new(index, answer)
                    continue
            if self._tool_names.get(index) != "final_answer":
                continue
            answer_prefix = _partial_json_answer(self._arguments.get(index, ""))
            if answer_prefix is not None:
                self._emit_new(index, answer_prefix)

    def _emit_new(self, index: int, answer_prefix: str) -> None:
        emitted = self._emitted.get(index, "")
        if not answer_prefix.startswith(emitted):
            return
        new_text = answer_prefix[len(emitted) :]
        if new_text:
            self._observer(new_text)
            self._emitted[index] = answer_prefix


def _run_streaming_agent(
    agent: ToolCallingAgent,
    text: str,
    text_delta_observer: Callable[[str], None],
    progress_delta_observer: Callable[[str], None] | None = None,
) -> object:
    extractor = _FinalAnswerDeltaExtractor(text_delta_observer)
    output: object | None = None
    stream = cast(Iterable[object], agent.run(text, stream=True, reset=True))
    for item in stream:
        if isinstance(item, ChatMessageStreamDelta):
            if item.content and progress_delta_observer is not None:
                progress_delta_observer(item.content)
            extractor.add(item)
        elif isinstance(item, FinalAnswerStep):
            output = item.output
    if output is None:
        raise RuntimeError("agent stream completed without a final answer")
    return output


class _EventCollector:
    def __init__(self, event_observer: Callable[[Event], None] | None = None) -> None:
        self._events: list[Event] = []
        self._event_observer = event_observer
        self._lock = Lock()

    def add(self, event: Event) -> None:
        with self._lock:
            self._events.append(event)
        if self._event_observer is not None:
            self._event_observer(event)

    def snapshot(self) -> list[Event]:
        with self._lock:
            return list(self._events)


class _SmolagentsToolAdapter(Tool):  # type: ignore[misc]
    skip_forward_signature_validation = True

    def __init__(
        self,
        *,
        platform_tool: ExecutableTool,
        execution_context: ToolExecutionContext,
        agent_context: AgentContext,
        collector: _EventCollector,
    ) -> None:
        self._platform_tool = platform_tool
        self._execution_context = execution_context
        self._agent_context = agent_context
        self._collector = collector
        self.name = _runtime_tool_name(platform_tool.id)
        self.description = platform_tool.description
        self.inputs = _smolagents_inputs(platform_tool.input_schema)
        self.output_type = "string"
        super().__init__()

    def forward(self, **arguments: Any) -> str:
        portable_arguments = _JSON_OBJECT.validate_python(arguments)
        common = {
            "actor": "course-agent",
            "conversation_id": self._agent_context.conversation_id,
            **_event_principal_fields(self._agent_context),
        }
        self._collector.add(
            Event(
                type="agent.tool.requested",
                payload={
                    "tool_id": self._platform_tool.id,
                    "arguments": portable_arguments,
                },
                **common,
            )
        )
        try:
            result = asyncio.run(
                self._platform_tool.execute(portable_arguments, self._execution_context)
            )
        except Exception as error:
            category = _tool_error_category(error)
            self._collector.add(
                Event(
                    type="agent.tool.failed",
                    payload={"tool_id": self._platform_tool.id, "category": category},
                    **common,
                )
            )
            raise RuntimeError(f"{category}: tool execution failed") from error

        for resource_uri in result.resource_uris:
            self._collector.add(
                Event(
                    type="resource.read",
                    payload={"uri": resource_uri},
                    **common,
                )
            )
        completed_payload = _JSON_OBJECT.validate_python(
            {
                "tool_id": self._platform_tool.id,
                "storage_policy": result.storage_policy,
                "resource_uris": result.resource_uris,
            }
        )
        if result.storage_policy == "server_full":
            completed_payload["result"] = result.content
        elif result.storage_policy == "server_summary" and result.summary is not None:
            completed_payload["summary"] = result.summary
        self._collector.add(Event(type="agent.tool.completed", payload=completed_payload, **common))
        return _render_tool_result(result)


def _conversation_history(context: AgentContext) -> str:
    lines: list[str] = []
    for event in context.recent_events:
        if event.type not in {"user.message", "agent.message"}:
            continue
        text = event.payload.get("text")
        if isinstance(text, str):
            speaker = "User" if event.type == "user.message" else "Class Agent"
            lines.append(f"{speaker}: {text}")
    return "\n".join(lines)


class SmolagentsRuntime:
    """Default runtime adapter; smolagents objects never cross this boundary."""

    def __init__(
        self,
        *,
        model_provider: ModelProvider[Model],
        tools: ToolCatalog,
        max_steps: int = 10,
        agent_id: str = "course-agent",
    ) -> None:
        self._model_provider = model_provider
        self._tools = tools
        self._max_steps = max_steps
        self._agent_id = agent_id

    async def run(
        self,
        *,
        context: AgentContext,
        input: AgentInput,
    ) -> AgentResult:
        return await self._run(context=context, input=input, event_observer=None)

    async def run_observed(
        self,
        *,
        context: AgentContext,
        input: AgentInput,
        event_observer: Callable[[Event], None],
        text_delta_observer: Callable[[str], None] | None = None,
        progress_delta_observer: Callable[[str], None] | None = None,
    ) -> AgentResult:
        """Run while reporting the same portable events included in the result."""

        return await self._run(
            context=context,
            input=input,
            event_observer=event_observer,
            text_delta_observer=text_delta_observer,
            progress_delta_observer=progress_delta_observer,
        )

    async def _run(
        self,
        *,
        context: AgentContext,
        input: AgentInput,
        event_observer: Callable[[Event], None] | None,
        text_delta_observer: Callable[[str], None] | None = None,
        progress_delta_observer: Callable[[str], None] | None = None,
    ) -> AgentResult:
        if input.conversation_id != context.conversation_id:
            raise ValueError("agent input and context must reference the same conversation")

        authorized_tools = self._tools.authorized(context.permitted_tool_ids)
        runtime_names = [_runtime_tool_name(tool.id) for tool in authorized_tools]
        if len(runtime_names) != len(set(runtime_names)):
            raise ValueError("authorized tool IDs collide after runtime name conversion")

        collector = _EventCollector(event_observer)
        execution_context = ToolExecutionContext(
            principal=context.principal,
            conversation_id=context.conversation_id,
            permitted_resource_uris=frozenset(context.permitted_resource_uris),
        )
        runtime_tools = [
            _SmolagentsToolAdapter(
                platform_tool=tool,
                execution_context=execution_context,
                agent_context=context,
                collector=collector,
            )
            for tool in authorized_tools
        ]
        history = _conversation_history(context)
        instructions = (
            "You are the single logical Class Agent. Use only the tools provided for this "
            "run. Never claim to have read a resource unless a provided tool returned it. "
            "If official course information is absent, say it is not documented. Before "
            "using a non-final tool, briefly state what you are about to do as ordinary "
            "user-facing content. Do not reveal private reasoning, and do not include a "
            "progress message alongside the final_answer tool.\n"
            f"Trusted principal roles: {', '.join(context.principal.roles)}."
        )
        if history:
            instructions = f"{instructions}\nPrior conversation:\n{history}"

        model = self._model_provider.create_model()
        agent = ToolCallingAgent(
            tools=runtime_tools,
            model=model,
            instructions=instructions,
            max_steps=self._max_steps,
            add_base_tools=False,
            max_tool_threads=1,
            stream_outputs=(text_delta_observer is not None or progress_delta_observer is not None),
            verbosity_level=LogLevel.OFF,
        )
        event_fields = {
            "actor": self._agent_id,
            "conversation_id": context.conversation_id,
            **_event_principal_fields(context),
        }
        started = Event(
            type="agent.run.started",
            payload={"input_id": str(input.id)},
            metadata={
                "runtime": "smolagents-toolcalling",
                "provider": self._model_provider.provider_id,
                "model": self._model_provider.model_id,
            },
            **event_fields,
        )
        if event_observer is not None:
            event_observer(started)

        if text_delta_observer is None and progress_delta_observer is None:
            output = await asyncio.to_thread(agent.run, input.text, reset=True)
        else:
            output = await asyncio.to_thread(
                _run_streaming_agent,
                agent,
                input.text,
                text_delta_observer or (lambda _delta: None),
                progress_delta_observer,
            )
        output_text = str(output)
        agent_message = Event(
            type="agent.message",
            payload={"text": output_text, "input_id": str(input.id)},
            **event_fields,
        )
        completed = Event(
            type="agent.run.completed",
            payload={"input_id": str(input.id)},
            metadata={"runtime": "smolagents-toolcalling"},
            **event_fields,
        )
        if event_observer is not None:
            event_observer(agent_message)
            event_observer(completed)
        return AgentResult(
            input_id=input.id,
            conversation_id=context.conversation_id,
            output_text=output_text,
            events=[started, *collector.snapshot(), agent_message, completed],
            metadata={
                "runtime": "smolagents-toolcalling",
                "provider": self._model_provider.provider_id,
                "model": self._model_provider.model_id,
            },
        )
