"""Bounded execution and safe diagnostics at the smolagents adapter boundary."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from typing import Any, Literal

from smolagents import ToolCallingAgent
from smolagents.memory import ActionStep, TaskStep

StopReason = Literal["repeated_tool_calls", "step_limit", "presentation_review_missing"]
# Three consecutive batches with identical inputs and observations indicate a stall.
_REPEAT_LIMIT = 3
# Reserve time to checkpoint a workspace, review presentation, and answer.
_FINISHING_STEPS = 3


class RunStopped(RuntimeError):
    def __init__(self, reason: StopReason) -> None:
        super().__init__(reason)
        self.reason = reason


class BoundedToolCallingAgent(ToolCallingAgent):  # type: ignore[misc]
    """Keep framework fallbacks from masquerading as successfully completed agent work."""

    def __init__(self, *, diagnostic: Callable[[dict[str, Any]], None], **kwargs: Any) -> None:
        self._diagnostic = diagnostic
        self._previous_call_batch: str | None = None
        self._repeats = 0
        self._budget_warning_sent = False
        super().__init__(**kwargs)

    def _handle_max_steps_reached(self, task: str) -> object:
        # The framework otherwise makes an extra unreviewed model call here.
        raise RunStopped("step_limit")

    def _finalize_step(self, step: object) -> None:
        super()._finalize_step(step)
        if not isinstance(step, ActionStep):
            return
        message = step.model_output_message
        calls = message.tool_calls if message is not None else None
        names = [
            call.function.name if call.function.name in self.tools else "unregistered_tool"
            for call in calls or []
        ]
        self._diagnostic(
            {
                "step": step.step_number,
                "tool_names": names,
                "error_type": type(step.error).__name__ if step.error is not None else None,
            }
        )
        if step.is_final_answer:
            return
        if calls:
            # Arguments are used only for an ephemeral fingerprint, never diagnostics.
            batch = json.dumps(
                {
                    "calls": [(call.function.name, call.function.arguments) for call in calls],
                    "observation": step.observations,
                    "error_type": type(step.error).__name__ if step.error else None,
                },
                sort_keys=True,
                default=str,
            )
            fingerprint = hashlib.sha256(batch.encode()).hexdigest()
            self._repeats = self._repeats + 1 if fingerprint == self._previous_call_batch else 1
            self._previous_call_batch = fingerprint
            if self._repeats >= _REPEAT_LIMIT:
                raise RunStopped("repeated_tool_calls")
            if self._repeats == _REPEAT_LIMIT - 1:
                self.memory.steps.append(
                    TaskStep(
                        task=(
                            "Runtime notice: the same calls repeated. Use the existing "
                            "results; do not repeat the batch. If blocked, explain the limitation. "
                            "If a presentation review succeeded, call final_answer now."
                        )
                    )
                )
        else:
            self._previous_call_batch = None
            self._repeats = 0
        if not self._budget_warning_sent and self.max_steps - step.step_number <= _FINISHING_STEPS:
            self._budget_warning_sent = True
            self.memory.steps.append(
                TaskStep(
                    task=(
                        "Runtime notice: this run has at most three steps left. Finish now or save "
                        "a progress checkpoint in the workspace, including evidence "
                        "and remaining work. Perform the required presentation review, then call "
                        "final_answer. State incomplete coverage honestly; do not invent a result."
                    )
                )
            )
