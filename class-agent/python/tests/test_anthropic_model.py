from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any, ClassVar

from pydantic import SecretStr
from smolagents import ChatMessage, Tool
from smolagents.models import MessageRole, agglomerate_stream_deltas

from runtime_smolagents import AnthropicModelProvider
from runtime_smolagents.anthropic_model import AnthropicModel


class _Lookup(Tool):  # type: ignore[misc]
    name = "memory_get_mine"
    description = "Read."
    inputs: ClassVar[dict[str, Any]] = {"query": {"type": "string", "description": "Text."}}
    output_type = "string"

    def forward(self, query: str) -> str:
        return query


class _Final(Tool):  # type: ignore[misc]
    name = "final_answer"
    description = "Finish."
    inputs: ClassVar[dict[str, Any]] = {"answer": {"type": "string", "description": "Text."}}
    output_type = "string"

    def forward(self, answer: str) -> str:
        return answer


def _text(text: str) -> SimpleNamespace:
    return SimpleNamespace(type="text", text=text)


def _call(name: str, arguments: dict[str, Any]) -> SimpleNamespace:
    return SimpleNamespace(type="tool_use", id="call-1", name=name, input=arguments)


class _Client:
    def __init__(self, content: list[SimpleNamespace], stop_reason: str = "end_turn") -> None:
        self.requests: list[dict[str, Any]] = []
        self._response = SimpleNamespace(
            id="msg-1",
            content=content,
            stop_reason=stop_reason,
            usage=SimpleNamespace(input_tokens=3, output_tokens=4),
        )
        self.beta = SimpleNamespace(messages=SimpleNamespace(stream=self._stream))

    def _stream(self, **request: Any) -> _Client:
        self.requests.append(request)
        return self

    def __enter__(self) -> _Client:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def get_final_message(self) -> SimpleNamespace:
        return self._response


def _model(client: _Client) -> AnthropicModel:
    return AnthropicModel(model_id="claude-opus-5-5", api_key="unused", client=client)


def _messages() -> list[ChatMessage]:
    return [
        ChatMessage(role=MessageRole.SYSTEM, content=[{"type": "text", "text": "Rules."}]),
        ChatMessage(role=MessageRole.USER, content=[{"type": "text", "text": "Help."}]),
        ChatMessage(role=MessageRole.TOOL_CALL, content=[{"type": "text", "text": "Calling."}]),
        ChatMessage(role=MessageRole.TOOL_RESPONSE, content=[{"type": "text", "text": "Seen."}]),
    ]


def test_request_separates_system_text_and_never_forces_a_tool() -> None:
    client = _Client([_call("memory_get_mine", {"query": "week"})], stop_reason="tool_use")

    message = _model(client).generate(
        _messages(),
        stop_sequences=["Observation:", " "],
        tools_to_call_from=[_Lookup(), _Final()],
    )

    request = client.requests[0]
    assert request["system"] == "Rules."
    assert [item["role"] for item in request["messages"]] == ["user", "assistant", "user"]
    assert request["stop_sequences"] == ["Observation:"]
    assert request["tools"][0]["name"] == "memory_get_mine"
    assert request["tools"][0]["input_schema"]["required"] == ["query"]
    assert "tool_choice" not in request
    assert "thinking" not in request
    assert request["fallbacks"] == "default"
    assert message.tool_calls is not None
    assert message.tool_calls[0].function.arguments == {"query": "week"}
    assert message.token_usage is not None
    assert message.token_usage.output_tokens == 4


def test_a_plain_reply_finishes_the_run_through_final_answer() -> None:
    message = _model(_Client([_text("All done.")])).generate(
        _messages(), tools_to_call_from=[_Final()]
    )

    assert message.tool_calls is not None
    assert message.tool_calls[0].function.name == "final_answer"
    assert message.tool_calls[0].function.arguments == {"answer": "All done."}


def test_a_refusal_with_no_text_still_ends_the_run_with_an_answer() -> None:
    message = _model(_Client([], stop_reason="refusal")).generate(
        _messages(), tools_to_call_from=[_Final()]
    )

    assert message.tool_calls is not None
    assert message.tool_calls[0].function.arguments == {"answer": "I can't help with that request."}


def test_blocks_from_a_model_that_declined_are_dropped() -> None:
    client = _Client(
        [
            _call("memory_get_mine", {"query": "partial"}),
            SimpleNamespace(type="fallback"),
            _call("memory_get_mine", {"query": "kept"}),
        ]
    )

    message = _model(client).generate(_messages(), tools_to_call_from=[_Lookup()])

    assert message.tool_calls is not None
    assert [call.function.arguments for call in message.tool_calls] == [{"query": "kept"}]


def test_stream_yields_one_delta_the_agent_can_rebuild() -> None:
    client = _Client([_text("Checking."), _call("memory_get_mine", {"query": "week"})])

    deltas = list(_model(client).generate_stream(_messages(), tools_to_call_from=[_Lookup()]))

    rebuilt = agglomerate_stream_deltas(deltas)
    assert rebuilt.content == "Checking."
    assert rebuilt.tool_calls is not None
    assert json.loads(rebuilt.tool_calls[0].function.arguments) == {"query": "week"}


def test_provider_keeps_the_key_out_of_its_repr() -> None:
    provider = AnthropicModelProvider(
        model_id="claude-opus-5-5", api_key=SecretStr("test-secret-value")
    )

    assert provider.provider_id == "anthropic"
    assert "test-secret-value" not in repr(provider)
    assert isinstance(provider.create_model(), AnthropicModel)
