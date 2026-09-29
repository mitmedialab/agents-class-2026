"""MCP-aligned agent tools for the isolated remote browser."""

from __future__ import annotations

from collections.abc import Mapping
from contextlib import suppress
from typing import ClassVar, cast
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from pydantic import JsonValue, ValidationError

from course_server.agent.capabilities import (
    ToolEmittedEvent,
    ToolExecutionContext,
    ToolExecutionResult,
    ToolValidationError,
    _https_result_url,
)
from course_server.workspace import (
    ComponentRegistry,
    OpenWorkspaceCommand,
    UpdateWorkspaceCommand,
    WorkspacePanel,
    WorkspaceState,
    WorkspaceValidationError,
)
from course_server.workspace.models import WorkspaceLayout

from .constants import (
    BROWSER_COMPARE_TOOL_ID,
    BROWSER_COMPONENT_ID,
    BROWSER_HIGHLIGHT_TEXT_TOOL_ID,
    BROWSER_NAVIGATE_TOOL_ID,
    BROWSER_OPEN_TOOL_ID,
    BROWSER_SCROLL_TOOL_ID,
    PAGE_CARDS_COMPONENT_ID,
)
from .models import (
    BrowserError,
    BrowserPage,
    BrowserSecurityError,
    BrowserSessionNotFound,
    BrowserSessionService,
)


def browser_page_props(page: BrowserPage) -> dict[str, JsonValue]:
    """Return only the validated state needed by the trusted browser renderer."""

    return {
        "session_id": str(page.session_id),
        "url": page.url,
        "title": page.title,
        "revision": page.revision,
        "viewport_width": page.viewport_width,
        "viewport_height": page.viewport_height,
        "scroll_y": page.scroll_y,
        "document_height": page.document_height,
    }


def browser_panel_update(
    state: WorkspaceState,
    *,
    session_id: UUID,
    page: BrowserPage,
) -> UpdateWorkspaceCommand:
    panel = next(
        (
            candidate
            for candidate in state.panels
            if candidate.component_id == BROWSER_COMPONENT_ID
            and candidate.props.get("session_id") == str(session_id)
        ),
        None,
    )
    if panel is None:
        raise ToolValidationError("The browser panel is no longer open.")
    return UpdateWorkspaceCommand(
        panel_id=panel.id,
        title=page.title,
        props=browser_page_props(page),
    )


def apply_browser_update(
    *,
    registry: ComponentRegistry,
    context: ToolExecutionContext,
    page: BrowserPage,
) -> UpdateWorkspaceCommand:
    try:
        current = WorkspaceState.model_validate(context.workspace_state)
        panel = _active_browser_panel(current)
        if panel is None:
            raise ToolValidationError("The browser panel is no longer open.")
        command = UpdateWorkspaceCommand(
            panel_id=panel.id,
            title=page.title,
            props=browser_page_props(page),
        )
        updated = registry.apply(current, command)
    except (ValidationError, WorkspaceValidationError) as error:
        raise ToolValidationError("The browser workspace state is invalid.") from error
    context.workspace_state.clear()
    context.workspace_state.update(updated.model_dump(mode="json", exclude_none=True))
    return command


def _required_string(arguments: Mapping[str, JsonValue], name: str, maximum: int) -> str:
    value = arguments.get(name)
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ToolValidationError(f"{name} must contain 1 to {maximum} characters")
    return value.strip()


def _active_browser_panel(state: WorkspaceState) -> WorkspacePanel | None:
    focused = next(
        (panel for panel in state.panels if panel.id == state.focused_panel_id),
        None,
    )
    if focused is not None and focused.component_id == BROWSER_COMPONENT_ID:
        return focused
    return next(
        (panel for panel in reversed(state.panels) if panel.component_id == BROWSER_COMPONENT_ID),
        None,
    )


def _active_page_cards_panel(state: WorkspaceState) -> WorkspacePanel | None:
    focused = next(
        (panel for panel in state.panels if panel.id == state.focused_panel_id),
        None,
    )
    if focused is not None and focused.component_id == PAGE_CARDS_COMPONENT_ID:
        return focused
    return next(
        (
            panel
            for panel in reversed(state.panels)
            if panel.component_id == PAGE_CARDS_COMPONENT_ID
        ),
        None,
    )


def _active_session_id(context: ToolExecutionContext) -> UUID:
    try:
        state = WorkspaceState.model_validate(context.workspace_state)
        panel = _active_browser_panel(state)
        value = panel.props.get("session_id") if panel is not None else None
        if not isinstance(value, str):
            raise ValueError
        return UUID(value)
    except (ValidationError, ValueError) as error:
        raise ToolValidationError(
            "No active remote browser is open. Open a page before controlling it."
        ) from error


def _active_browser_url(context: ToolExecutionContext) -> str:
    try:
        state = WorkspaceState.model_validate(context.workspace_state)
        panel = _active_browser_panel(state)
        value = panel.props.get("url") if panel is not None else None
        if not isinstance(value, str) or not value:
            raise ValueError
        return value
    except (ValidationError, ValueError) as error:
        raise ToolValidationError(
            "No active remote browser is open. Open a page before controlling it."
        ) from error


def _reject_unknown(arguments: Mapping[str, JsonValue], allowed: frozenset[str]) -> None:
    unknown = set(arguments) - allowed
    if unknown:
        raise ToolValidationError(f"unexpected arguments: {', '.join(sorted(unknown))}")


class _BrowserToolError(ToolValidationError):
    def __init__(self, error: BrowserError) -> None:
        super().__init__(str(error))
        self.reason_code = "browser_" + type(error).__name__.removeprefix("Browser").lower()


def _browser_error(error: BrowserError) -> _BrowserToolError:
    return _BrowserToolError(error)


def _updated_result(
    *,
    command: UpdateWorkspaceCommand,
    page: BrowserPage,
    summary: str,
    extra: dict[str, JsonValue] | None = None,
) -> ToolExecutionResult:
    content: dict[str, JsonValue] = {
        "session_id": str(page.session_id),
        "url": page.url,
        "title": page.title,
        "revision": page.revision,
        "text_excerpt": page.text_excerpt,
    }
    if extra:
        content.update(extra)
    return ToolExecutionResult(
        content=content,
        summary=summary,
        storage_policy="server_summary",
        emitted_events=[
            ToolEmittedEvent(
                type="workspace.panel.updated",
                payload={"command": command.model_dump(mode="json", exclude_none=True)},
            )
        ],
    )


class BrowserOpenTool:
    id = BROWSER_OPEN_TOOL_ID
    description = (
        "Open or inspect a public HTTPS page in an isolated server-side browser and display its "
        "live screenshot in the trusted workspace. Calling this with the active panel's current "
        "URL snapshots that existing session, including any page the user reached by clicking, "
        "and returns readable page text without opening a duplicate panel. Use this instead of "
        "webpage-viewer live mode when the site blocks iframe embedding."
    )
    input_schema: ClassVar[dict[str, JsonValue]] = {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "format": "uri",
                "pattern": "^https://[^\\s]+$",
                "maxLength": 2_048,
            }
        },
        "required": ["url"],
        "additionalProperties": False,
    }

    def __init__(self, service: BrowserSessionService, registry: ComponentRegistry) -> None:
        self._service = service
        self._registry = registry

    async def execute(
        self,
        arguments: Mapping[str, JsonValue],
        context: ToolExecutionContext,
    ) -> ToolExecutionResult:
        _reject_unknown(arguments, frozenset({"url"}))
        try:
            current = WorkspaceState.model_validate(context.workspace_state)
        except ValidationError as error:
            raise ToolValidationError("The browser workspace state is invalid.") from error
        existing_panel = _active_browser_panel(current)
        url = _required_string(arguments, "url", 2_048)
        replaced_stale_session = False
        try:
            prior_session_value = (
                existing_panel.props.get("session_id") if existing_panel is not None else None
            )
            if isinstance(prior_session_value, str):
                prior_session_id = UUID(prior_session_value)
                try:
                    if existing_panel is not None and existing_panel.props.get("url") == url:
                        page = (
                            await self._service.snapshot(
                                principal=context.principal,
                                conversation_id=context.conversation_id,
                                session_id=prior_session_id,
                            )
                        ).page
                    else:
                        page = await self._service.navigate(
                            principal=context.principal,
                            conversation_id=context.conversation_id,
                            session_id=prior_session_id,
                            url=url,
                        )
                except BrowserSessionNotFound:
                    page = await self._service.open(
                        principal=context.principal,
                        conversation_id=context.conversation_id,
                        url=url,
                    )
                    replaced_stale_session = True
            else:
                page = await self._service.open(
                    principal=context.principal,
                    conversation_id=context.conversation_id,
                    url=url,
                )
        except BrowserError as error:
            raise _browser_error(error) from error
        manifest = self._registry.get(BROWSER_COMPONENT_ID)
        if manifest is None:
            raise ToolValidationError("The trusted browser viewer is unavailable.")
        layout = (
            WorkspaceLayout(
                width=manifest.default_size.width,
                height=manifest.default_size.height,
            )
            if manifest.default_size is not None
            else None
        )
        command: OpenWorkspaceCommand | UpdateWorkspaceCommand
        event_type: str
        if existing_panel is not None:
            command = UpdateWorkspaceCommand(
                panel_id=existing_panel.id,
                title=page.title,
                props=browser_page_props(page),
            )
            event_type = "workspace.panel.updated"
        else:
            command = OpenWorkspaceCommand(
                panel=WorkspacePanel(
                    id=uuid4(),
                    component_id=BROWSER_COMPONENT_ID,
                    title=page.title,
                    props=browser_page_props(page),
                    state={},
                    layout=layout,
                )
            )
            event_type = "workspace.panel.opened"
        try:
            updated = self._registry.apply(current, command)
        except (ValidationError, WorkspaceValidationError) as error:
            await self._service.close_session(
                principal=context.principal,
                conversation_id=context.conversation_id,
                session_id=page.session_id,
            )
            raise ToolValidationError("The browser panel could not be opened.") from error
        if existing_panel is not None and replaced_stale_session:
            raw_prior_session_id = existing_panel.props.get("session_id")
            if isinstance(raw_prior_session_id, str) and raw_prior_session_id != str(
                page.session_id
            ):
                with suppress(ValueError, BrowserError):
                    await self._service.close_session(
                        principal=context.principal,
                        conversation_id=context.conversation_id,
                        session_id=UUID(raw_prior_session_id),
                    )
        context.workspace_state.clear()
        context.workspace_state.update(updated.model_dump(mode="json", exclude_none=True))
        return ToolExecutionResult(
            content={
                "session_id": str(page.session_id),
                "url": page.url,
                "title": page.title,
                "revision": page.revision,
                "text_excerpt": page.text_excerpt,
            },
            summary=f"Opened {page.title} in the remote browser.",
            storage_policy="server_summary",
            emitted_events=[
                ToolEmittedEvent(
                    type=event_type,
                    payload={"command": command.model_dump(mode="json", exclude_none=True)},
                )
            ],
        )


class BrowserCompareTool:
    id = BROWSER_COMPARE_TOOL_ID
    description = (
        "Capture and display two to four public HTTPS pages as adjacent website cards. "
        "Use this whenever several websites, projects, sources, or options are being "
        "presented as candidates so the user can compare them visually. Each column scrolls "
        "independently. Set presentation=thumbnails for a 2x2 gallery: supply a verified "
        "image_url from staff.discover_showcase_images when available; otherwise the tool "
        "captures the supplied weekly-page URL as a screenshot automatically. Use the actual "
        "weekly build URL discovered from website navigation or repository documentation. "
        "Use browser.open instead when showing only one page."
    )
    input_schema: ClassVar[dict[str, JsonValue]] = {
        "type": "object",
        "properties": {
            "presentation": {"type": "string", "enum": ["previews", "thumbnails"]},
            "heading": {"type": "string", "minLength": 1, "maxLength": 200},
            "description": {"type": "string", "maxLength": 2_000},
            "candidates": {
                "type": "array",
                "minItems": 2,
                "maxItems": 4,
                "items": {
                    "type": "object",
                    "properties": {
                        "url": {
                            "type": "string",
                            "format": "uri",
                            "pattern": "^https://[^\\s]+$",
                            "maxLength": 2_048,
                        },
                        "image_url": {"type": "string", "maxLength": 2048},
                        "title": {"type": "string", "minLength": 1, "maxLength": 500},
                        "description": {"type": "string", "maxLength": 2_000},
                    },
                    "required": ["url"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["candidates"],
        "additionalProperties": False,
    }

    def __init__(self, service: BrowserSessionService, registry: ComponentRegistry) -> None:
        self._service = service
        self._registry = registry

    async def execute(
        self,
        arguments: Mapping[str, JsonValue],
        context: ToolExecutionContext,
    ) -> ToolExecutionResult:
        _reject_unknown(
            arguments, frozenset({"heading", "description", "candidates", "presentation"})
        )
        raw_candidates = arguments.get("candidates")
        if not isinstance(raw_candidates, list) or not 2 <= len(raw_candidates) <= 4:
            raise ToolValidationError("candidates must contain two to four pages")
        heading_value = arguments.get("heading", "Website candidates")
        description_value = arguments.get("description")
        if not isinstance(heading_value, str) or not heading_value.strip():
            raise ToolValidationError("heading must be non-blank text")
        if description_value is not None and not isinstance(description_value, str):
            raise ToolValidationError("description must be text")

        presentation = arguments.get("presentation", "previews")
        if not isinstance(presentation, str) or presentation not in {"previews", "thumbnails"}:
            raise ToolValidationError("presentation must be previews or thumbnails")
        selected_sites = context.transient_state.get("showcase_selection_sites")
        if isinstance(selected_sites, list):
            # Each selected site must appear exactly once; path boundaries distinguish
            # student repositories hosted under the same GitHub Pages origin.
            remaining = list(selected_sites)
            for candidate in raw_candidates:
                if not isinstance(candidate, dict) or not isinstance(candidate.get("url"), str):
                    raise ToolValidationError("Showcase candidates require website URLs.")
                parsed = urlsplit(str(candidate["url"]))
                matches = [
                    site
                    for site in remaining
                    if isinstance(site, str)
                    and urlsplit(site).netloc == parsed.netloc
                    and (
                        parsed.path.rstrip("/") == urlsplit(site).path.rstrip("/")
                        or parsed.path.startswith(urlsplit(site).path.rstrip("/") + "/")
                    )
                ]
                if len(matches) != 1:
                    raise ToolValidationError(
                        "Display each selected student's registered site exactly once."
                    )
                remaining.remove(matches[0])
            if remaining or presentation != "thumbnails":
                raise ToolValidationError(
                    "Showcase requires all four selected students in a thumbnail gallery."
                )
        items: list[dict[str, JsonValue]] = []
        capture_failures: list[JsonValue] = []
        captured_pages: list[JsonValue] = []
        try:
            for index, raw_candidate in enumerate(raw_candidates, start=1):
                if not isinstance(raw_candidate, dict):
                    raise ToolValidationError("each candidate must be an object")
                unknown = set(raw_candidate) - {"url", "title", "description", "image_url"}
                if unknown:
                    raise ToolValidationError(
                        f"unexpected candidate arguments: {', '.join(sorted(unknown))}"
                    )
                url = _required_string(raw_candidate, "url", 2_048)
                title = raw_candidate.get("title")
                description = raw_candidate.get("description")
                if title is not None and (
                    not isinstance(title, str) or not title.strip() or len(title) > 500
                ):
                    raise ToolValidationError("candidate title is invalid")
                if description is not None and (
                    not isinstance(description, str) or len(description) > 2_000
                ):
                    raise ToolValidationError("candidate description is invalid")
                if _https_result_url(url) is None:
                    raise ToolValidationError("Candidate URL must be credential-free public HTTPS.")
                image_url = raw_candidate.get("image_url")
                if image_url is not None:
                    known = context.transient_state.get("page_image_candidates", [])
                    if (
                        presentation != "thumbnails"
                        or not isinstance(image_url, str)
                        or _https_result_url(image_url) is None
                        or not isinstance(known, list)
                        or image_url not in known
                    ):
                        raise ToolValidationError(
                            "Thumbnail images must come from image discovery in this run."
                        )
                    item: dict[str, JsonValue] = {
                        "id": f"candidate-{index}",
                        "url": url,
                        "title": title.strip() if isinstance(title, str) else url,
                        "image_url": image_url,
                    }
                else:
                    try:
                        preview = await self._service.create_preview(
                            principal=context.principal,
                            conversation_id=context.conversation_id,
                            url=url,
                        )
                    except BrowserSecurityError:
                        raise
                    except BrowserError as error:
                        if presentation != "thumbnails":
                            raise
                        # Preserve other students when one public page cannot be captured.
                        items.append(
                            {
                                "id": f"candidate-{index}",
                                "url": url,
                                "title": title.strip() if isinstance(title, str) else url,
                                "preview_unavailable": True,
                                "description": (
                                    ((description + " · ") if description else "")
                                    + "Screenshot unavailable; use the website link."
                                )[:2000],
                            }
                        )
                        capture_failures.append(
                            {"url": url, "reason_code": _browser_error(error).reason_code}
                        )
                        continue
                    captured_pages.append(
                        {
                            "url": preview.url,
                            "title": preview.title,
                            "text_excerpt": preview.text_excerpt,
                        }
                    )
                    item = {
                        "id": f"candidate-{index}",
                        "url": preview.url,
                        "title": title.strip() if isinstance(title, str) else preview.title,
                        "preview_id": str(preview.preview_id),
                        "revision": preview.revision,
                    }
                    if presentation == "thumbnails":
                        description = (
                            (description + " · ") if description else ""
                        ) + "Build-page screenshot"
                if isinstance(description, str) and description.strip():
                    item["description"] = description.strip()[:2000]
                items.append(item)
        except BrowserError as error:
            raise _browser_error(error) from error

        try:
            current = WorkspaceState.model_validate(context.workspace_state)
        except ValidationError as error:
            raise ToolValidationError("The browser workspace state is invalid.") from error
        existing_panel = _active_page_cards_panel(current)
        props: dict[str, JsonValue] = {
            "presentation": presentation,
            "heading": heading_value.strip()[:200],
            "items": cast(JsonValue, items),
        }
        if isinstance(description_value, str) and description_value.strip():
            props["description"] = description_value.strip()[:2_000]
        manifest = self._registry.get(PAGE_CARDS_COMPONENT_ID)
        if manifest is None:
            raise ToolValidationError("The trusted page-card viewer is unavailable.")
        command: OpenWorkspaceCommand | UpdateWorkspaceCommand
        event_type: str
        if existing_panel is not None:
            command = UpdateWorkspaceCommand(
                panel_id=existing_panel.id,
                title=heading_value.strip()[:200],
                props=props,
            )
            event_type = "workspace.panel.updated"
        else:
            layout = (
                WorkspaceLayout(
                    width=manifest.default_size.width,
                    height=manifest.default_size.height,
                )
                if manifest.default_size is not None
                else None
            )
            command = OpenWorkspaceCommand(
                panel=WorkspacePanel(
                    id=uuid4(),
                    component_id=PAGE_CARDS_COMPONENT_ID,
                    title=heading_value.strip()[:200],
                    props=props,
                    state={},
                    layout=layout,
                )
            )
            event_type = "workspace.panel.opened"
        try:
            updated = self._registry.apply(current, command)
        except (ValidationError, WorkspaceValidationError) as error:
            raise ToolValidationError("The page cards could not be opened.") from error
        context.workspace_state.clear()
        context.workspace_state.update(updated.model_dump(mode="json", exclude_none=True))
        if isinstance(selected_sites, list):
            context.transient_state["showcase_gallery_props"] = props
        return ToolExecutionResult(
            content={
                "capture_failures": capture_failures,
                "status": "partial_images" if capture_failures else "ready",
                "heading": heading_value.strip()[:200],
                "candidate_count": len(items),
                "captured_pages": captured_pages,
                "review_instruction": "Check captured page evidence for the intended weekly build. "
                "If it shows an error or the wrong page, resolve the exact URL from sources and "
                "repair the gallery before reporting completion.",
                "candidates": [
                    {"id": item["id"], "url": item["url"], "title": item["title"]} for item in items
                ],
            },
            summary=f"Displayed {len(items)} website candidates for comparison."
            + (
                " Unavailable previews: "
                + ", ".join(
                    str(failure["reason_code"])
                    for failure in capture_failures
                    if isinstance(failure, dict)
                )
                if capture_failures
                else ""
            ),
            storage_policy="server_summary",
            emitted_events=[
                ToolEmittedEvent(
                    type=event_type,
                    payload={"command": command.model_dump(mode="json", exclude_none=True)},
                )
            ],
        )


class BrowserNavigateTool:
    id = BROWSER_NAVIGATE_TOOL_ID
    description = "Navigate the active remote-browser panel to another public HTTPS URL."
    input_schema: ClassVar[dict[str, JsonValue]] = {
        "type": "object",
        "properties": {
            "url": {"type": "string", "format": "uri", "maxLength": 2_048},
        },
        "required": ["url"],
        "additionalProperties": False,
    }

    def __init__(self, service: BrowserSessionService, registry: ComponentRegistry) -> None:
        self._service = service
        self._registry = registry

    async def execute(
        self,
        arguments: Mapping[str, JsonValue],
        context: ToolExecutionContext,
    ) -> ToolExecutionResult:
        _reject_unknown(arguments, frozenset({"url"}))
        url = _required_string(arguments, "url", 2_048)
        try:
            try:
                page = await self._service.navigate(
                    principal=context.principal,
                    conversation_id=context.conversation_id,
                    session_id=_active_session_id(context),
                    url=url,
                )
            except BrowserSessionNotFound:
                page = await self._service.open(
                    principal=context.principal,
                    conversation_id=context.conversation_id,
                    url=url,
                )
        except BrowserError as error:
            raise _browser_error(error) from error
        command = apply_browser_update(registry=self._registry, context=context, page=page)
        return _updated_result(
            command=command,
            page=page,
            summary=f"Navigated the remote browser to {page.title}.",
        )


class BrowserScrollTool:
    id = BROWSER_SCROLL_TOOL_ID
    description = "Scroll the active remote-browser page and refresh its workspace view."
    input_schema: ClassVar[dict[str, JsonValue]] = {
        "type": "object",
        "properties": {
            "delta_y": {"type": "integer", "minimum": -1_600, "maximum": 1_600},
        },
        "required": ["delta_y"],
        "additionalProperties": False,
    }

    def __init__(self, service: BrowserSessionService, registry: ComponentRegistry) -> None:
        self._service = service
        self._registry = registry

    async def execute(
        self,
        arguments: Mapping[str, JsonValue],
        context: ToolExecutionContext,
    ) -> ToolExecutionResult:
        _reject_unknown(arguments, frozenset({"delta_y"}))
        delta_y = arguments.get("delta_y")
        if not isinstance(delta_y, int) or isinstance(delta_y, bool):
            raise ToolValidationError("delta_y must be an integer")
        try:
            try:
                page = await self._service.scroll(
                    principal=context.principal,
                    conversation_id=context.conversation_id,
                    session_id=_active_session_id(context),
                    delta_y=delta_y,
                )
            except BrowserSessionNotFound:
                recovered = await self._service.open(
                    principal=context.principal,
                    conversation_id=context.conversation_id,
                    url=_active_browser_url(context),
                )
                page = await self._service.scroll(
                    principal=context.principal,
                    conversation_id=context.conversation_id,
                    session_id=recovered.session_id,
                    delta_y=delta_y,
                )
        except BrowserError as error:
            raise _browser_error(error) from error
        command = apply_browser_update(registry=self._registry, context=context, page=page)
        return _updated_result(
            command=command,
            page=page,
            summary="Scrolled the remote browser page.",
        )


class BrowserHighlightTextTool:
    id = BROWSER_HIGHLIGHT_TEXT_TOOL_ID
    description = (
        "Find visible text in an open remote-browser page, scroll it into view, and mark the "
        "first matching element in the workspace screenshot."
    )
    input_schema: ClassVar[dict[str, JsonValue]] = {
        "type": "object",
        "properties": {
            "text": {"type": "string", "minLength": 1, "maxLength": 500},
        },
        "required": ["text"],
        "additionalProperties": False,
    }

    def __init__(self, service: BrowserSessionService, registry: ComponentRegistry) -> None:
        self._service = service
        self._registry = registry

    async def execute(
        self,
        arguments: Mapping[str, JsonValue],
        context: ToolExecutionContext,
    ) -> ToolExecutionResult:
        _reject_unknown(arguments, frozenset({"text"}))
        query = _required_string(arguments, "text", 500)
        try:
            try:
                page, matches = await self._service.highlight_text(
                    principal=context.principal,
                    conversation_id=context.conversation_id,
                    session_id=_active_session_id(context),
                    text=query,
                )
            except BrowserSessionNotFound:
                recovered = await self._service.open(
                    principal=context.principal,
                    conversation_id=context.conversation_id,
                    url=_active_browser_url(context),
                )
                page, matches = await self._service.highlight_text(
                    principal=context.principal,
                    conversation_id=context.conversation_id,
                    session_id=recovered.session_id,
                    text=query,
                )
        except BrowserError as error:
            raise _browser_error(error) from error
        command = apply_browser_update(registry=self._registry, context=context, page=page)
        return _updated_result(
            command=command,
            page=page,
            summary=(
                f"Highlighted text matching {query!r}."
                if matches
                else f"No visible text matched {query!r}."
            ),
            extra={"matches": matches},
        )
