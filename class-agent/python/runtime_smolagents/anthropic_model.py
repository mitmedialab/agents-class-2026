"""Claude model adapter used by the smolagents runtime."""

from __future__ import annotations

import json
from collections.abc import Generator
from dataclasses import dataclass
from typing import Any

from anthropic import Anthropic
from pydantic import SecretStr
from smolagents import ChatMessage, ChatMessageStreamDelta, Model
from smolagents.models import (
    ChatMessageToolCall,
    ChatMessageToolCallFunction,
    ChatMessageToolCallStreamDelta,
    MessageRole,
    get_clean_message_list,
    get_tool_json_schema,
    tool_role_conversions,
)
from smolagents.monitoring import TokenUsage

DEFAULT_ANTHROPIC_MODEL_ID = "claude-opus-5-5"
_MAX_TOKENS = 64_000
_EFFORT = "medium"
_FINAL_ANSWER_TOOL = "final_answer"
_REFUSAL_ANSWER = "I can't help with that request."
_FALLBACK_BETA = "server-side-fallback-2026-07-01"


def _claude_content(content: Any) -> Any:
    if not isinstance(content, list):
        return content
    blocks: list[dict[str, Any]] = []
    for block in content:
        if block["type"] == "image":
            blocks.append(
                {
                    "type": "image",
                    "source": {"type": "base64", "media_type": "image/png", "data": block["image"]},
                }
            )
        else:
            blocks.append({"type": "text", "text": block["text"]})
    return blocks


def _system_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    return "\n".join(block["text"] for block in content if block["type"] == "text")


def _claude_tool(tool: Any) -> dict[str, Any]:
    schema = get_tool_json_schema(tool)["function"]
    return {
        "name": schema["name"],
        "description": schema["description"],
        "input_schema": schema["parameters"],
    }


class AnthropicModel(Model):  # type: ignore[misc]
    """Calls Claude directly. Smolagents replays earlier tool calls as plain text."""

    def __init__(self, *, model_id: str, api_key: str, client: Any | None = None) -> None:
        super().__init__(model_id=model_id)
        self._client = client if client is not None else Anthropic(api_key=api_key)

    def _complete(
        self,
        messages: list[Any],
        stop_sequences: list[str] | None,
        tools_to_call_from: list[Any] | None,
    ) -> ChatMessage:
        conversation = get_clean_message_list(messages, role_conversions=tool_role_conversions)
        system = [m["content"] for m in conversation if m["role"] == MessageRole.SYSTEM]
        request: dict[str, Any] = {
            "model": self.model_id,
            "max_tokens": _MAX_TOKENS,
            "messages": [
                {"role": str(m["role"].value), "content": _claude_content(m["content"])}
                for m in conversation
                if m["role"] != MessageRole.SYSTEM
            ],
            "output_config": {"effort": _EFFORT},
            "betas": [_FALLBACK_BETA],
            "fallbacks": "default",
        }
        if system:
            request["system"] = "\n\n".join(_system_text(content) for content in system)
        if stop_sequences:
            request["stop_sequences"] = [item for item in stop_sequences if item.strip()]
        if tools_to_call_from:
            # Claude rejects a forced tool_choice, so a plain reply is handled in _to_chat_message.
            request["tools"] = [_claude_tool(tool) for tool in tools_to_call_from]

        with self._client.beta.messages.stream(**request) as stream:
            response = stream.get_final_message()
        return self._to_chat_message(response, tools_to_call_from)

    def _to_chat_message(self, response: Any, tools: list[Any] | None) -> ChatMessage:
        # A model that declined mid-turn leaves its blocks before the last fallback block.
        blocks = list(response.content)
        for position, block in enumerate(blocks):
            if block.type == "fallback":
                blocks = list(response.content)[position + 1 :]
        text = "".join(block.text for block in blocks if block.type == "text")
        calls = [
            ChatMessageToolCall(
                id=block.id,
                type="function",
                function=ChatMessageToolCallFunction(name=block.name, arguments=block.input),
            )
            for block in blocks
            if block.type == "tool_use"
        ]
        if response.stop_reason == "refusal" and not text:
            text = _REFUSAL_ANSWER
        can_finish = any(tool.name == _FINAL_ANSWER_TOOL for tool in tools or [])
        if not calls and text and can_finish:
            # The agent ends a run only through this tool, so a plain reply must become the call.
            calls = [
                ChatMessageToolCall(
                    id=f"{response.id}-final",
                    type="function",
                    function=ChatMessageToolCallFunction(
                        name=_FINAL_ANSWER_TOOL, arguments={"answer": text}
                    ),
                )
            ]
        return ChatMessage(
            role=MessageRole.ASSISTANT,
            content=text or None,
            tool_calls=calls or None,
            token_usage=TokenUsage(
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
            ),
        )

    def generate(
        self,
        messages: list[Any],
        stop_sequences: list[str] | None = None,
        response_format: dict[str, str] | None = None,
        tools_to_call_from: list[Any] | None = None,
        **kwargs: Any,
    ) -> ChatMessage:
        del response_format, kwargs
        return self._complete(messages, stop_sequences, tools_to_call_from)

    def generate_stream(
        self,
        messages: list[Any],
        stop_sequences: list[str] | None = None,
        response_format: dict[str, str] | None = None,
        tools_to_call_from: list[Any] | None = None,
        **kwargs: Any,
    ) -> Generator[ChatMessageStreamDelta]:
        """Yield the finished turn at once, because a fallback can replace partial tool input."""

        del response_format, kwargs
        message = self._complete(messages, stop_sequences, tools_to_call_from)
        yield ChatMessageStreamDelta(
            content=message.content if isinstance(message.content, str) else None,
            tool_calls=[
                ChatMessageToolCallStreamDelta(
                    index=index,
                    id=call.id,
                    type=call.type,
                    function=ChatMessageToolCallFunction(
                        name=call.function.name,
                        arguments=json.dumps(call.function.arguments),
                    ),
                )
                for index, call in enumerate(message.tool_calls or [])
            ],
            token_usage=message.token_usage,
        )


@dataclass(frozen=True)
class AnthropicModelProvider:
    """Creates transient Claude models from server-side secrets."""

    model_id: str
    api_key: SecretStr
    provider_id: str = "anthropic"

    def create_model(self) -> Model:
        return AnthropicModel(model_id=self.model_id, api_key=self.api_key.get_secret_value())
