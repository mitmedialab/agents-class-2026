"""Opt-in local recording factory. Public source data and real tools, scripted model.

Run only in an isolated local test deployment:
PYTHONPATH=python:examples uv run uvicorn peer_recording:create_recording_app --factory
For local course-inbox QA, set MCP_MESSAGING_ENABLED=true and MAIL_ENABLED=true
with the isolated QA roster and database. Inbox delivery runs in the API process.
External email delivery is performed separately by the mail worker.
Use the ordinary Course Agent factory for model-backed operation.
"""

import json

from smolagents.models import (
    ChatMessage,
    ChatMessageStreamDelta,
    ChatMessageToolCall,
    ChatMessageToolCallFunction,
    ChatMessageToolCallStreamDelta,
    MessageRole,
    Model,
)

PROMPT = (
    "I'm struggling with sensor input and feedback design for my hardware prototype. "
    "Can you find classmates' projects I could learn from and show them in the workspace?"
)


class RecordingModel(Model):
    def __init__(self, builds):
        super().__init__(model_id="peer-recording-script")
        self.step = 0
        self.example = None
        self.builds = builds

    def next_call(self, messages):
        if self.example is None:
            last_user = next((m for m in reversed(messages) if m.role == MessageRole.USER), None)
            text = str(last_user.content if last_user else "").replace("\u2019", "'")
            self.example = PROMPT in text
        if not self.example:
            if self.step == 0:
                self.step += 1
                return "workspace_review_presentation", {"decision": "no_visual"}
            return "final_answer", {
                "answer": (
                    "Local scripted demo. Open Peer learning in the top menu for your weekly pairs, "
                    "or ask the hardware prototype example question to see peer builds in "
                    "the workspace."
                )
            }
        plan = [
            ("peer_get_context", {}),
            ("peer_query_builds", {"query": "hardware sensor", "week": 6}),
            *[("peer_read_build", {"build_id": b["id"]}) for b in self.builds],
            (
                "workspace_open_component",
                {
                    "component_id": "peer-discovery",
                    "title": "Peer learning",
                    "props": {
                        "view": "recommendations",
                        "build_ids": [b["id"] for b in self.builds],
                    },
                },
            ),
            ("workspace_review_presentation", {"decision": "workspace_ready"}),
            (
                "final_answer",
                {
                    "answer": (
                        "**Scripted demo · real student projects.**\n\n"
                        "I opened three hardware builds in the workspace. Compare Sol lamba's "
                        "data-to-light feedback, the listening robot's sound-driven behavior, "
                        "and the smart-lighting build's controls. Open each build to inspect "
                        "the original implementation."
                    )
                },
            ),
        ]
        result = plan[min(self.step, len(plan) - 1)]
        self.step += 1
        return result

    def generate(self, messages, **kwargs):
        name, arguments = self.next_call(messages)
        return ChatMessage(
            role=MessageRole.ASSISTANT,
            content="",
            tool_calls=[
                ChatMessageToolCall(
                    id=f"recording-{self.step}",
                    type="function",
                    function=ChatMessageToolCallFunction(name=name, arguments=arguments),
                )
            ],
        )

    def generate_stream(self, messages, **kwargs):
        name, arguments = self.next_call(messages)
        yield ChatMessageStreamDelta(
            tool_calls=[
                ChatMessageToolCallStreamDelta(
                    index=0,
                    id=f"recording-{self.step}",
                    type="function",
                    function=ChatMessageToolCallFunction(
                        name=name, arguments=json.dumps(arguments)
                    ),
                )
            ]
        )


class RecordingProvider:
    provider_id = "local-scripted-recording"
    model_id = "peer-recording-script"

    def __init__(self, builds):
        self.builds = builds

    def create_model(self):
        return RecordingModel(self.builds)


def create_recording_app():
    # This opt-in factory retains the actual auth, tool catalog, execution checks,
    # source reads, events and workspace reducer. Only model decisions are scripted.
    import course_server.api as api

    original = api.build_runtime

    def recording_runtime(*args, **kwargs):
        runtime = original(*args, **kwargs)
        peer = kwargs.get("peer_discovery")
        if peer is None:
            raise RuntimeError("Recording requires the configured public peer catalog.")
        selected = [
            b.model_dump()
            for b in peer.store.catalog().builds
            if b.week == 6
            and b.project_id in {"agents2026-juan-ruben", "agents2026-sean", "agents2026-david"}
        ]
        if len(selected) != 3:
            raise RuntimeError("Recording requires the three public hardware example sources.")
        runtime._model_provider = RecordingProvider(selected)
        return runtime

    api.build_runtime = recording_runtime
    return api.create_app()
