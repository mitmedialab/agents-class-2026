"""Exercise the real selection and comparison tools through the model/runtime boundary."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from uuid import uuid4

from smolagents import ChatMessage, ChatMessageToolCall, Model
from smolagents.models import ChatMessageToolCallFunction
from test_browser import FakeBrowserSessionService
from test_runtime_smolagents import ScriptedProvider
from test_showcase import candidate, request
from test_student_projects import FakeStudentProjects, principal

from agent_core import AgentContext, AgentInput
from course_server.agent import ReadSkillTool, SkillCatalog, ToolCatalog
from course_server.agent.capabilities import ExecutableTool
from course_server.browser.tools import BrowserCompareTool
from course_server.student_projects import (
    InspectStudentRepositoryTool,
    InspectStudentSiteTool,
    ListStudentProjectsTool,
    StudentProject,
)
from course_server.student_projects.images import DiscoverShowcaseImagesTool
from course_server.student_projects.screening import ScreenShowcaseTool
from course_server.student_projects.showcase import (
    Eligibility,
    ReadShowcaseHistoryTool,
    SelectShowcaseTool,
)
from course_server.workspace import load_component_registry, project_workspace_events
from course_server.workspace.tools import (
    WorkspaceReviewPresentationTool,
)
from runtime_smolagents import SmolagentsRuntime


class ShowcaseCatalog(FakeStudentProjects):
    def list_projects(self) -> list[StudentProject]:
        return [
            StudentProject(f"agents2026-{name}", f"https://{name}.example.edu") for name in "abcd"
        ]


class ShowcaseModel(Model):  # type: ignore[misc]
    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    def generate(self, messages: list[ChatMessage], **kwargs: Any) -> ChatMessage:
        self.calls += 1
        actions: list[tuple[str, dict[str, Any]]]
        if self.calls == 1:
            actions = [("skills_read", {"skill_id": "weekly-build-showcase"})]
        elif self.calls == 2:
            actions = [
                ("staff_read_showcase_history", {}),
                ("staff_screen_weekly_showcase", {"week": 4}),
            ]
        elif self.calls == 3:
            actions = []
            for name in "ab":
                project = f"agents2026-{name}"
                actions.append(("course_inspect_student_site", {"project_id": project}))
                for view in ("tree", "commits", "file"):
                    arguments = {"project_id": project, "view": view}
                    if view == "file":
                        arguments["path"] = "week4/README.md"
                    actions.append(("staff_inspect_student_repository", arguments))
        elif self.calls == 4:
            actions = [
                (
                    "staff_select_weekly_showcase",
                    {
                        **request(*(candidate(n) for n in "ab")).model_dump(mode="json"),
                        "eligible_projects": [
                            Eligibility(
                                project_id=f"agents2026-{n}",
                                student_name=n,
                                post_evidence="Week 4 post",
                            ).model_dump(mode="json")
                            for n in "abcd"
                        ],
                    },
                )
            ]
        elif self.calls == 5:
            actions = [
                (
                    "staff_discover_showcase_images",
                    {
                        "project_id": f"agents2026-{n}",
                        "page_urls": [f"https://{n}.example.edu/week4"],
                    },
                )
                for n in "abcd"
            ]
            actions.append(
                (
                    "browser_compare",
                    {
                        "presentation": "thumbnails",
                        "heading": "Week 4 showcase",
                        "candidates": [
                            {
                                "url": f"https://{n}.example.edu/week4",
                                "title": n,
                                **(
                                    {"image_url": f"https://{n}.example.edu/week4/build.png"}
                                    if n in "ab"
                                    else {}
                                ),
                            }
                            for n in "abcd"
                        ],
                    },
                )
            )
        elif self.calls == 6:
            actions = [("workspace_review_presentation", {"decision": "workspace_ready"})]
        else:
            actions = [("final_answer", {"answer": "The four selected sites are displayed."})]
        return ChatMessage(
            role="assistant",
            tool_calls=[
                ChatMessageToolCall(
                    id=f"call-{self.calls}-{i}",
                    type="function",
                    function=ChatMessageToolCallFunction(name=name, arguments=args),
                )
                for i, (name, args) in enumerate(actions)
            ],
        )


def test_showcase_selection_reaches_validated_four_image_workspace(tmp_path: Path) -> None:
    async def scenario() -> None:
        path = tmp_path / "history.json"
        path.write_text('{"schema_version":1,"issues":[]}')
        skills = SkillCatalog.from_registry(Path(__file__).resolve().parents[2] / "skills")
        projects = ShowcaseCatalog()
        browser = FakeBrowserSessionService()
        registry = load_component_registry()
        tools: list[ExecutableTool] = [
            ReadSkillTool(skills),
            ReadShowcaseHistoryTool(path),
            ListStudentProjectsTool(projects),
            InspectStudentSiteTool(
                projects, lambda url: {"url": url, "text": "Week 4 build and demo"}
            ),
            InspectStudentRepositoryTool(projects),
            SelectShowcaseTool(projects, path),
            ScreenShowcaseTool(projects, lambda url: "Week 4 build and demo", path),
            DiscoverShowcaseImagesTool(
                projects,
                lambda url: {
                    "images": [{"image_url": url.rsplit("/week4", 1)[0] + "/week4/build.png"}]
                },
                lambda url: url,
            ),
            BrowserCompareTool(browser, registry),
            WorkspaceReviewPresentationTool(),
        ]
        model = ShowcaseModel()
        runtime = SmolagentsRuntime(
            model_provider=ScriptedProvider(model), tools=ToolCatalog(tools), max_steps=10
        )
        c = uuid4()
        result = await runtime.run(
            context=AgentContext(
                principal=principal("instructor"),
                conversation_id=c,
                permitted_tool_ids=[t.id for t in tools],
                metadata={"workspace_state": {"panels": []}},
            ),
            input=AgentInput(
                conversation_id=c,
                text="Review Week 4 using the supplied assignment and select four sites.",
            ),
        )
        assert result.metadata["termination_reason"] is None
        assert model.calls == 7
        assert (
            sum(
                e.type == "agent.tool.completed"
                and e.payload.get("tool_id") == "staff.discover_showcase_images"
                for e in result.events
            )
            == 4
        )
        state = project_workspace_events(result.events, registry)
        assert len(state.panels) == 1
        assert state.panels[0].component_id == "page-cards"
        assert state.panels[0].props["presentation"] == "thumbnails"
        items = state.panels[0].props["items"]
        assert isinstance(items, list) and len(items) == 4
        for n, item in zip("abcd", items, strict=True):
            assert isinstance(item, dict)
            assert item["url"] == f"https://{n}.example.edu/week4"
            if n in "ab":
                assert item["image_url"] == f"https://{n}.example.edu/week4/build.png"
            else:
                assert "preview_id" in item
                assert "screenshot" in str(item["description"])
        assert len(browser.previews) == 2
        assert any(
            e.type == "agent.tool.completed"
            and e.payload["tool_id"] == "staff.select_weekly_showcase"
            for e in result.events
        )
        assert path.read_text() == '{"schema_version":1,"issues":[]}'

    asyncio.run(scenario())
