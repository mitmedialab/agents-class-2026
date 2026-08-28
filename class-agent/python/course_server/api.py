"""FastAPI transport for Phase 4 authentication and Course Agent routes."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated, Any, Literal, cast
from uuid import UUID, uuid4

from dotenv import load_dotenv
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.responses import StreamingResponse
from psycopg_pool import AsyncConnectionPool
from pydantic import BaseModel, ConfigDict, Field, JsonValue, StringConstraints

from agent_core import AgentResult, Conversation, Event, PrincipalContext
from course_server.agent import (
    ConversationAccessDenied,
    ConversationStore,
    CourseAgentService,
    CourseResourceCatalog,
    FileResourceProvider,
    PublicCapabilityPolicy,
    ResourceNotFound,
    ResourceSummary,
    ToolValidationError,
)
from course_server.agent.store import principal_owns_conversation
from course_server.agent_cli import build_runtime
from course_server.auth import (
    AuthenticationService,
    InvalidCredentials,
    InvalidSession,
    LoginRateLimited,
)
from course_server.auth.models import SessionCredential
from course_server.browser import (
    BROWSER_COMPONENT_ID,
    BrowserCapacityReached,
    BrowserError,
    BrowserNavigationError,
    BrowserSecurityError,
    BrowserSessionNotFound,
    BrowserSessionService,
    BrowserUnavailable,
    ThreadedPlaywrightBrowserSessionService,
)
from course_server.browser.tools import browser_page_props
from course_server.config import AgentSettings
from course_server.index_resources import index_resources
from course_server.migrations import apply_migrations
from course_server.postgres.auth_store import PostgresAuthStore, create_auth_pool
from course_server.postgres.conversation_store import PostgresConversationStore
from course_server.uploads import (
    MAX_UPLOAD_BYTES,
    FileTemporaryUploadStore,
    TemporaryUploadReceipt,
    TemporaryUploadStore,
    UploadError,
)
from course_server.workspace import (
    CloseWorkspaceCommand,
    ComponentRegistry,
    FocusWorkspaceCommand,
    OpenWorkspaceCommand,
    UpdateWorkspaceCommand,
    WorkspacePanel,
    WorkspaceValidationError,
    load_component_registry,
    project_workspace_events,
)

logger = logging.getLogger(__name__)

AUTH_COOKIE = "class_agent_auth"
ANON_COOKIE = "class_agent_anon"
API_PREFIX = "/api/v1"

NonEmptyText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
CourseAssetId = Annotated[
    str,
    StringConstraints(strip_whitespace=True, pattern=r"^[a-z][a-z0-9_]*$", max_length=100),
]


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LoginRequest(ApiModel):
    username: str
    access_code: str


class CreateConversationRequest(ApiModel):
    title: NonEmptyText | None = None


class RunRequest(ApiModel):
    text: NonEmptyText


class AgentRunRequest(RunRequest):
    conversation_id: UUID


class WorkspacePanelActionRequest(ApiModel):
    action: Literal["focus", "close"]
    panel_id: UUID


class WorkspaceInteractionRequest(ApiModel):
    panel_id: UUID
    action: Literal[
        "calendar.select_event",
        "calendar.change_view",
        "document.change_page",
        "document.find_text",
        "page_cards.select",
        "visual.change",
        "draft.change",
    ]
    value: JsonValue


class BrowserScrollRequest(ApiModel):
    panel_id: UUID
    delta_y: int = Field(ge=-1_600, le=1_600)


class BrowserClickRequest(ApiModel):
    panel_id: UUID
    x: int = Field(ge=0, le=4_095)
    y: int = Field(ge=0, le=15_999)


class BrowserResizeRequest(ApiModel):
    panel_id: UUID
    width: int = Field(ge=320, le=4_096)
    height: int = Field(ge=240, le=4_096)


class PrincipalResponse(ApiModel):
    authenticated: bool
    user_id: UUID | None = None
    anonymous_session_id: UUID | None = None
    username: str | None = None
    display_name: str | None = None
    roles: list[str]
    session_id: UUID

    @classmethod
    def from_principal(cls, principal: PrincipalContext) -> PrincipalResponse:
        return cls.model_validate(principal.model_dump())


class RunResponse(ApiModel):
    output_text: str
    event_ids: list[UUID]

    @classmethod
    def from_result(cls, result: AgentResult) -> RunResponse:
        return cls(
            output_text=result.output_text,
            event_ids=[event.id for event in result.events],
        )


class ConversationDetailResponse(ApiModel):
    conversation: Conversation
    events: list[Event]


@dataclass(frozen=True)
class AppServices:
    """Injectable application services used by the HTTP adapter."""

    authentication: AuthenticationService
    agent: CourseAgentService
    conversations: ConversationStore
    course_resources: CourseResourceCatalog | None = None
    uploads: TemporaryUploadStore | None = None
    workspace_registry: ComponentRegistry | None = None
    browser: BrowserSessionService | None = None


@dataclass
class AppRuntimeResources:
    """Resources owned by the production application lifespan."""

    pool: AsyncConnectionPool[Any] | None = None
    browser: BrowserSessionService | None = None


@dataclass
class AppState:
    services: AppServices | None
    resources: AppRuntimeResources


@dataclass(frozen=True)
class StreamTextDelta:
    text: str


@dataclass(frozen=True)
class StreamProgressDelta:
    text: str
    replace: bool


CookieAction = Callable[[Response], None]


def _get_app_state(request: Request) -> AppState:
    state = getattr(request.app.state, "course_state", None)
    if not isinstance(state, AppState) or state.services is None:
        raise RuntimeError("application state is not configured")
    return state


def _delete_cookie(response: Response, name: str) -> None:
    response.delete_cookie(
        name,
        path="/",
        httponly=True,
        secure=True,
        samesite="lax",
    )


def _set_session_cookie(
    response: Response,
    name: str,
    credential: SessionCredential,
) -> None:
    max_age = max(0, int((credential.expires_at - datetime.now(UTC)).total_seconds()))
    response.set_cookie(
        name,
        credential.token,
        path="/",
        expires=credential.expires_at,
        max_age=max_age,
        httponly=True,
        secure=True,
        samesite="lax",
    )


def _queue_cookie_action(request: Request, action: CookieAction) -> None:
    actions = getattr(request.state, "session_cookie_actions", None)
    if not isinstance(actions, list):
        actions = []
        request.state.session_cookie_actions = actions
    actions.append(action)


async def _resolve_or_create_principal(
    request: Request,
    app_state: AppState,
) -> PrincipalContext:
    assert app_state.services is not None
    authentication = app_state.services.authentication
    auth_token = request.cookies.get(AUTH_COOKIE)
    if auth_token:
        try:
            return await authentication.resolve_authenticated(auth_token)
        except InvalidSession:
            _queue_cookie_action(
                request,
                lambda response: _delete_cookie(response, AUTH_COOKIE),
            )

    anonymous_token = request.cookies.get(ANON_COOKIE)
    if anonymous_token:
        try:
            return await authentication.resolve_anonymous(anonymous_token)
        except InvalidSession:
            pass

    credential = await authentication.create_anonymous()
    principal = await authentication.resolve_anonymous(credential.token)
    _queue_cookie_action(
        request,
        lambda response: _set_session_cookie(response, ANON_COOKIE, credential),
    )
    return principal


async def _require_principal(request: Request) -> PrincipalContext:
    return await _resolve_or_create_principal(request, _get_app_state(request))


async def _require_owned_conversation(
    *,
    state: AppState,
    principal: PrincipalContext,
    conversation_id: UUID,
) -> Conversation:
    assert state.services is not None
    conversation = await state.services.conversations.get_conversation(conversation_id)
    if conversation is None or not principal_owns_conversation(principal, conversation):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")
    return conversation


def _browser_http_error(error: BrowserError) -> HTTPException:
    if isinstance(error, BrowserSessionNotFound):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")
    if isinstance(error, BrowserCapacityReached):
        return HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="remote browser capacity reached",
            headers={"Retry-After": "30"},
        )
    if isinstance(error, (BrowserSecurityError, BrowserNavigationError)):
        return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error))
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="remote browser unavailable",
    )


def _valid_page_card_selection(
    props: dict[str, JsonValue],
    value: JsonValue,
) -> bool:
    items = props.get("items")
    return (
        isinstance(value, str)
        and isinstance(items, list)
        and any(isinstance(item, dict) and item.get("id") == value for item in items)
    )


def _valid_visual_change(
    props: dict[str, JsonValue],
    value: JsonValue,
) -> bool:
    if not isinstance(value, dict):
        return False
    element_id = value.get("element_id")
    changed_value = value.get("value")
    elements = props.get("elements")
    if (
        not isinstance(element_id, str)
        or not isinstance(changed_value, str)
        or not isinstance(elements, list)
    ):
        return False
    return any(
        isinstance(element, dict)
        and element.get("id") == element_id
        and (
            (element.get("type") == "input" and len(changed_value) <= 2_000)
            or (element.get("type") == "textarea" and len(changed_value) <= 8_000)
        )
        for element in elements
    )


def _draft_fields(props: dict[str, JsonValue]) -> list[dict[str, JsonValue]] | None:
    fields = props.get("fields")
    if not isinstance(fields, list) or not all(isinstance(field, dict) for field in fields):
        return None
    return cast(list[dict[str, JsonValue]], fields)


def _valid_draft_change(props: dict[str, JsonValue], value: JsonValue) -> bool:
    if not isinstance(value, dict):
        return False
    field_id = value.get("field_id")
    changed_value = value.get("value")
    fields = _draft_fields(props)
    return (
        isinstance(field_id, str)
        and isinstance(changed_value, str)
        and len(changed_value) <= 4_000
        and fields is not None
        and any(field.get("id") == field_id for field in fields)
    )


APPLICATION_DRAFT_FIELDS: tuple[tuple[str, str], ...] = (
    ("name", "Name"),
    ("email", "Email"),
    (
        "department_research_group_year_of_study_mit",
        "Department / Research Group / Year of Study MIT",
    ),
    ("personal_webpage", "Personal Webpage"),
    ("interests", "Interests"),
    ("why_take_this_class", "Why do you want to take this class?"),
    ("knowledgeable_about", "Knowledgeable about"),
    ("skill_set", "Skill-set (practical knowledge and builder experience)"),
    ("registration_status", "Registration Status"),
    ("listener_willing_to_do_weekly_builds", "For listeners: willing to do weekly builds"),
    ("questions_or_comments_for_instructors", "Questions or comments for instructors"),
    ("photo_upload_id", "Recent profile photo"),
)

LEGACY_APPLICATION_FIELD_IDS: dict[str, str] = {
    "department_research_group_year_of_study_mit": "background",
    "personal_webpage": "webpage",
    "why_take_this_class": "why",
    "skill_set": "skills",
    "registration_status": "registration",
    "photo_upload_id": "photo",
}


def _empty_application_draft_props() -> dict[str, JsonValue]:
    return {
        "title": "Course Application Draft",
        "description": "Complete every field below. Your changes are saved when you leave a field.",
        "status": "draft",
        "fields": [
            {"id": field_id, "label": label, "value": "", "status": "missing"}
            for field_id, label in APPLICATION_DRAFT_FIELDS
        ],
    }


def _normalized_application_draft_props(
    existing_props: dict[str, JsonValue],
) -> dict[str, JsonValue]:
    normalized = _empty_application_draft_props()
    existing_fields = _draft_fields(existing_props) or []
    fields_by_id = {
        field_id: field
        for field in existing_fields
        if isinstance((field_id := field.get("id")), str)
    }
    normalized_fields = cast(list[dict[str, JsonValue]], normalized["fields"])
    for field in normalized_fields:
        field_id = cast(str, field["id"])
        prior = fields_by_id.get(field_id) or fields_by_id.get(
            LEGACY_APPLICATION_FIELD_IDS.get(field_id, "")
        )
        if prior is None:
            continue
        value = prior.get("value")
        field["value"] = value if isinstance(value, str) else ""
        status_value = prior.get("status")
        field["status"] = (
            status_value
            if status_value in {"missing", "candidate", "inferred", "confirmed"}
            else ("candidate" if field["value"] else "missing")
        )
        source = prior.get("source")
        if isinstance(source, str) and source:
            field["source"] = source
    return normalized


async def _run_agent(
    *,
    state: AppState,
    principal: PrincipalContext,
    conversation_id: UUID,
    text: str,
    event_observer: Callable[[Event], None] | None = None,
    text_delta_observer: Callable[[str], None] | None = None,
    progress_delta_observer: Callable[[str, bool], None] | None = None,
) -> AgentResult:
    assert state.services is not None
    try:
        return await state.services.agent.run(
            principal=principal,
            conversation_id=conversation_id,
            text=text,
            event_observer=event_observer,
            text_delta_observer=text_delta_observer,
            progress_delta_observer=progress_delta_observer,
        )
    except ConversationAccessDenied as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found") from error
    except Exception as error:
        logger.exception("agent run failed")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="agent temporarily unavailable",
        ) from error


def _sse(*, event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, separators=(',', ':'))}\n\n"


async def _stream_agent_run(
    *,
    state: AppState,
    principal: PrincipalContext,
    conversation_id: UUID,
    text: str,
) -> AsyncIterator[str]:
    yield _sse(
        event="status",
        data={
            "type": "agent.status",
            "stage": "preparing_context",
            "label": "Preparing conversation context",
        },
    )
    event_queue: asyncio.Queue[Event | StreamTextDelta | StreamProgressDelta | None] = (
        asyncio.Queue()
    )
    loop = asyncio.get_running_loop()

    def observe_event(event: Event) -> None:
        with suppress(RuntimeError):
            loop.call_soon_threadsafe(event_queue.put_nowait, event)

    def observe_text_delta(text_delta: str) -> None:
        with suppress(RuntimeError):
            loop.call_soon_threadsafe(
                event_queue.put_nowait,
                StreamTextDelta(text=text_delta),
            )

    def observe_progress_delta(progress_delta: str, replace: bool) -> None:
        with suppress(RuntimeError):
            loop.call_soon_threadsafe(
                event_queue.put_nowait,
                StreamProgressDelta(text=progress_delta, replace=replace),
            )

    run_task = asyncio.create_task(
        _run_agent(
            state=state,
            principal=principal,
            conversation_id=conversation_id,
            text=text,
            event_observer=observe_event,
            text_delta_observer=observe_text_delta,
            progress_delta_observer=observe_progress_delta,
        )
    )
    run_task.add_done_callback(lambda _task: event_queue.put_nowait(None))

    streamed_text = False
    while True:
        update = await event_queue.get()
        if update is None:
            break
        if isinstance(update, StreamTextDelta):
            streamed_text = True
            yield _sse(
                event="message",
                data={"type": "agent.text.delta", "text": update.text},
            )
            continue
        if isinstance(update, StreamProgressDelta):
            yield _sse(
                event="progress",
                data={
                    "type": "agent.progress.delta",
                    "text": update.text,
                    "replace": update.replace,
                },
            )
            continue
        event = update
        if event.type == "agent.message":
            text_value = event.payload.get("text")
            if isinstance(text_value, str):
                yield _sse(
                    event="message",
                    data={
                        "type": "agent.text.done" if streamed_text else "agent.text.delta",
                        "text": text_value,
                    },
                )
        elif event.type in {
            "agent.run.started",
            "agent.tool.requested",
            "agent.tool.completed",
            "agent.tool.failed",
            "resource.read",
            "workspace.panel.opened",
            "workspace.panel.updated",
            "workspace.panel.closed",
        }:
            yield _sse(
                event="platform",
                data={"type": event.type, "event": event.model_dump(mode="json")},
            )

    try:
        await run_task
    except HTTPException:
        yield _sse(
            event="error",
            data={"type": "system.error", "category": "temporary_failure"},
        )
        return
    yield _sse(event="done", data={"type": "agent.run.completed"})


def _streaming_response(stream: AsyncIterator[str]) -> StreamingResponse:
    return StreamingResponse(
        stream,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


def create_app(
    *,
    settings: AgentSettings | None = None,
    services: AppServices | None = None,
) -> FastAPI:
    """Create an injectable test app or a PostgreSQL-backed production app."""

    if settings is not None and services is not None:
        raise ValueError("settings and services are mutually exclusive")

    resources = AppRuntimeResources()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if services is not None:
            yield
            return

        if settings is None:
            load_dotenv(override=False)
        resolved_settings = settings or AgentSettings.from_environment()
        apply_migrations(resolved_settings.database_url)
        index_resources(resolved_settings.database_url)
        pool = create_auth_pool(resolved_settings.database_url)
        await pool.open()
        await pool.wait()
        resources.pool = pool
        auth_store = PostgresAuthStore(pool)
        conversation_store = PostgresConversationStore(pool)
        course_resources = FileResourceProvider.from_registry()
        upload_store = FileTemporaryUploadStore(resolved_settings.upload_data_path)
        component_registry = load_component_registry()
        browser_service: BrowserSessionService | None = None
        if resolved_settings.browser_enabled:
            playwright_browser = ThreadedPlaywrightBrowserSessionService(
                max_sessions=resolved_settings.browser_max_sessions,
                max_sessions_per_principal=(resolved_settings.browser_max_sessions_per_principal),
                session_ttl_seconds=resolved_settings.browser_session_ttl_seconds,
                executable_path=resolved_settings.browser_executable_path,
            )
            try:
                await playwright_browser.start()
            except BrowserUnavailable:
                logger.warning("Remote browser unavailable; browser tools are disabled")
            else:
                browser_service = playwright_browser
                resources.browser = browser_service
        app.state.course_state.services = AppServices(
            authentication=AuthenticationService(auth_store),
            agent=CourseAgentService(
                runtime=build_runtime(
                    resolved_settings,
                    resources=course_resources,
                    uploads=upload_store,
                    components=component_registry,
                    browser=browser_service,
                ),
                conversations=conversation_store,
                capability_policy=PublicCapabilityPolicy(
                    (resource.uri for resource in course_resources.list_public()),
                    browser_enabled=browser_service is not None,
                ),
                workspace_registry=component_registry,
                uploads=upload_store,
            ),
            conversations=conversation_store,
            course_resources=course_resources,
            uploads=upload_store,
            workspace_registry=component_registry,
            browser=browser_service,
        )
        try:
            yield
        finally:
            app.state.course_state.services = None
            if browser_service is not None:
                await browser_service.close()
                resources.browser = None
            await pool.close()
            resources.pool = None

    app = FastAPI(
        title="Class Agent API",
        version="0.7.1",
        lifespan=lifespan,
    )
    app.state.course_state = AppState(services=services, resources=resources)

    @app.middleware("http")
    async def apply_session_cookies(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request.state.session_cookie_actions = []
        response = await call_next(request)
        for action in request.state.session_cookie_actions:
            action(response)
        return response

    router = APIRouter()

    @router.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @router.post("/auth/login", response_model=PrincipalResponse)
    async def login(
        payload: LoginRequest,
        response: Response,
        request: Request,
    ) -> PrincipalResponse:
        state = _get_app_state(request)
        assert state.services is not None
        try:
            credential = await state.services.authentication.login(
                username=payload.username,
                access_code=payload.access_code,
            )
        except InvalidCredentials as error:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="invalid username or access code",
            ) from error
        except LoginRateLimited as error:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="too many failed login attempts",
                headers={"Retry-After": "900"},
            ) from error
        principal = await state.services.authentication.resolve_authenticated(credential.token)
        _set_session_cookie(response, AUTH_COOKIE, credential)
        return PrincipalResponse.from_principal(principal)

    @router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
    async def logout(request: Request, response: Response) -> None:
        state = _get_app_state(request)
        assert state.services is not None
        token = request.cookies.get(AUTH_COOKIE)
        if token:
            await state.services.authentication.logout(token)
        _delete_cookie(response, AUTH_COOKIE)

    @router.get("/auth/me", response_model=PrincipalResponse)
    async def me(
        principal: Annotated[PrincipalContext, Depends(_require_principal)],
    ) -> PrincipalResponse:
        return PrincipalResponse.from_principal(principal)

    @router.get("/course/resources", response_model=list[ResourceSummary])
    async def list_course_resources(
        request: Request,
        principal: Annotated[PrincipalContext, Depends(_require_principal)],
    ) -> list[ResourceSummary]:
        state = _get_app_state(request)
        assert state.services is not None
        catalog = state.services.course_resources
        if catalog is None:
            catalog = FileResourceProvider.from_registry()
        permitted = frozenset(
            PublicCapabilityPolicy(resource.uri for resource in catalog.list_public())
            .authorize(principal)
            .resource_uris
        )
        return [resource for resource in catalog.list_public() if resource.uri in permitted]

    @router.get("/course/resources/content", response_model=None)
    async def read_course_resource_content(
        uri: NonEmptyText,
        request: Request,
        principal: Annotated[PrincipalContext, Depends(_require_principal)],
    ) -> Response:
        state = _get_app_state(request)
        assert state.services is not None
        catalog = state.services.course_resources
        if catalog is None:
            catalog = FileResourceProvider.from_registry()
        permitted = frozenset(
            PublicCapabilityPolicy(resource.uri for resource in catalog.list_public())
            .authorize(principal)
            .resource_uris
        )
        if uri not in permitted:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")
        try:
            resource = await catalog.read_file(uri)
        except ResourceNotFound as error:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="not found",
            ) from error
        return Response(
            content=resource.data,
            media_type=resource.media_type,
            headers={
                "Cache-Control": "private, max-age=60",
                "X-Class-Agent-Resource-Uri": resource.uri,
                "X-Content-Type-Options": "nosniff",
            },
        )

    @router.get("/course/resources/asset", response_model=None)
    async def read_course_resource_asset(
        uri: NonEmptyText,
        asset_id: CourseAssetId,
        request: Request,
        principal: Annotated[PrincipalContext, Depends(_require_principal)],
    ) -> Response:
        state = _get_app_state(request)
        assert state.services is not None
        catalog = state.services.course_resources
        if catalog is None:
            catalog = FileResourceProvider.from_registry()
        permitted = frozenset(
            PublicCapabilityPolicy(resource.uri for resource in catalog.list_public())
            .authorize(principal)
            .resource_uris
        )
        if uri not in permitted:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")
        try:
            asset = await catalog.read_asset(uri, asset_id)
        except ResourceNotFound as error:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="not found",
            ) from error
        return Response(
            content=asset.data,
            media_type=asset.media_type,
            headers={
                "Cache-Control": "private, max-age=3600",
                "X-Class-Agent-Resource-Uri": asset.uri,
                "X-Class-Agent-Asset-Id": asset_id,
                "X-Content-Type-Options": "nosniff",
            },
        )

    @router.post(
        "/uploads",
        response_model=TemporaryUploadReceipt,
        status_code=status.HTTP_201_CREATED,
    )
    async def upload_file(
        filename: str,
        request: Request,
        principal: Annotated[PrincipalContext, Depends(_require_principal)],
    ) -> TemporaryUploadReceipt:
        state = _get_app_state(request)
        assert state.services is not None
        upload_store = state.services.uploads
        if upload_store is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="temporary uploads are unavailable",
            )
        content_length = request.headers.get("content-length")
        if content_length is not None:
            try:
                declared_length = int(content_length)
            except ValueError as error:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="invalid content length",
                ) from error
            if declared_length > MAX_UPLOAD_BYTES:
                raise HTTPException(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail="uploaded file exceeds the 10 MB limit",
                )

        chunks: list[bytes] = []
        size = 0
        async for chunk in request.stream():
            size += len(chunk)
            if size > MAX_UPLOAD_BYTES:
                raise HTTPException(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail="uploaded file exceeds the 10 MB limit",
                )
            chunks.append(chunk)
        try:
            return await upload_store.store(
                filename=filename,
                media_type=request.headers.get("content-type", ""),
                content=b"".join(chunks),
                principal=principal,
            )
        except UploadError as error:
            response_status = (
                status.HTTP_415_UNSUPPORTED_MEDIA_TYPE
                if "unsupported file type" in str(error)
                else status.HTTP_400_BAD_REQUEST
            )
            raise HTTPException(status_code=response_status, detail=str(error)) from error

    @router.get("/uploads/{upload_id}/content", response_model=None)
    async def read_upload_content(
        upload_id: UUID,
        request: Request,
        principal: Annotated[PrincipalContext, Depends(_require_principal)],
    ) -> Response:
        state = _get_app_state(request)
        assert state.services is not None
        upload_store = state.services.uploads
        if upload_store is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="temporary uploads are unavailable",
            )
        try:
            upload = await upload_store.get_for_principal(upload_id, principal)
            content = await asyncio.to_thread(upload.path.read_bytes)
        except (UploadError, OSError) as error:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="not found",
            ) from error
        return Response(
            content=content,
            media_type=upload.receipt.media_type,
            headers={
                "Cache-Control": "private, no-store",
                "Content-Disposition": f'inline; filename="{upload.receipt.filename}"',
                "X-Content-Type-Options": "nosniff",
            },
        )

    @router.get("/conversations", response_model=list[Conversation])
    async def list_conversations(
        request: Request,
        principal: Annotated[PrincipalContext, Depends(_require_principal)],
    ) -> list[Conversation]:
        state = _get_app_state(request)
        assert state.services is not None
        return await state.services.conversations.list_conversations(principal)

    @router.post(
        "/conversations",
        response_model=Conversation,
    )
    async def create_conversation(
        payload: CreateConversationRequest,
        request: Request,
        principal: Annotated[PrincipalContext, Depends(_require_principal)],
    ) -> Conversation:
        state = _get_app_state(request)
        assert state.services is not None
        return await state.services.agent.create_conversation(principal, title=payload.title)

    @router.get(
        "/conversations/{conversation_id}",
        response_model=ConversationDetailResponse,
    )
    async def get_conversation(
        conversation_id: UUID,
        request: Request,
        principal: Annotated[PrincipalContext, Depends(_require_principal)],
    ) -> ConversationDetailResponse:
        state = _get_app_state(request)
        conversation = await _require_owned_conversation(
            state=state,
            principal=principal,
            conversation_id=conversation_id,
        )
        assert state.services is not None
        events = await state.services.conversations.list_events(conversation_id)
        return ConversationDetailResponse(conversation=conversation, events=events)

    @router.post(
        "/conversations/{conversation_id}/application-draft",
        response_model=Event,
    )
    async def ensure_application_draft(
        conversation_id: UUID,
        request: Request,
        principal: Annotated[PrincipalContext, Depends(_require_principal)],
    ) -> Event:
        state = _get_app_state(request)
        await _require_owned_conversation(
            state=state,
            principal=principal,
            conversation_id=conversation_id,
        )
        assert state.services is not None
        events = await state.services.conversations.list_events(conversation_id)
        registry = state.services.workspace_registry or load_component_registry()
        workspace = project_workspace_events(events, registry)
        existing = next(
            (
                panel
                for panel in workspace.panels
                if panel.component_id == "draft-document"
                and (
                    panel.state.get("document_kind") == "course-application"
                    or panel.resource_uri == "course://application"
                )
            ),
            None,
        )
        if existing is None:
            command: OpenWorkspaceCommand | FocusWorkspaceCommand | UpdateWorkspaceCommand = (
                OpenWorkspaceCommand(
                    panel=WorkspacePanel(
                        id=uuid4(),
                        component_id="draft-document",
                        title="Course Application Draft",
                        resource_uri="course://application",
                        props=_empty_application_draft_props(),
                        state={"document_kind": "course-application"},
                    )
                )
            )
            event_type = "workspace.panel.opened"
        elif (
            existing.resource_uri != "course://application"
            or existing.state.get("document_kind") != "course-application"
            or [field.get("id") for field in (_draft_fields(existing.props) or [])]
            != [field_id for field_id, _ in APPLICATION_DRAFT_FIELDS]
        ):
            command = UpdateWorkspaceCommand(
                panel_id=existing.id,
                props=_normalized_application_draft_props(existing.props),
                resource_uri="course://application",
                state={"document_kind": "course-application"},
            )
            event_type = "workspace.panel.updated"
        else:
            command = FocusWorkspaceCommand(panel_id=existing.id)
            event_type = "workspace.panel.updated"
        registry.apply(workspace, command)
        event = Event(
            type=event_type,
            actor="course-agent",
            principal_user_id=principal.user_id,
            anonymous_session_id=principal.anonymous_session_id,
            conversation_id=conversation_id,
            payload={"command": command.model_dump(mode="json", exclude_none=True)},
        )
        await state.services.conversations.append_events(conversation_id, [event])
        return event

    @router.post(
        "/conversations/{conversation_id}/workspace/actions",
        response_model=Event,
    )
    async def apply_workspace_panel_action(
        conversation_id: UUID,
        payload: WorkspacePanelActionRequest,
        request: Request,
        principal: Annotated[PrincipalContext, Depends(_require_principal)],
    ) -> Event:
        state = _get_app_state(request)
        await _require_owned_conversation(
            state=state,
            principal=principal,
            conversation_id=conversation_id,
        )
        assert state.services is not None
        events = await state.services.conversations.list_events(conversation_id)
        registry = state.services.workspace_registry or load_component_registry()
        workspace = project_workspace_events(events, registry)
        panel = next(
            (candidate for candidate in workspace.panels if candidate.id == payload.panel_id),
            None,
        )
        command = (
            FocusWorkspaceCommand(panel_id=payload.panel_id)
            if payload.action == "focus"
            else CloseWorkspaceCommand(panel_id=payload.panel_id)
        )
        try:
            registry.apply(workspace, command)
        except WorkspaceValidationError as error:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(error),
            ) from error
        event = Event(
            type=(
                "workspace.panel.updated" if payload.action == "focus" else "workspace.panel.closed"
            ),
            actor="user",
            principal_user_id=principal.user_id,
            anonymous_session_id=principal.anonymous_session_id,
            conversation_id=conversation_id,
            payload={"command": command.model_dump(mode="json", exclude_none=True)},
        )
        await state.services.conversations.append_events(conversation_id, [event])
        if (
            payload.action == "close"
            and panel is not None
            and panel.component_id == BROWSER_COMPONENT_ID
            and state.services.browser is not None
        ):
            raw_session_id = panel.props.get("session_id")
            if isinstance(raw_session_id, str):
                with suppress(ValueError, BrowserError):
                    await state.services.browser.close_session(
                        principal=principal,
                        conversation_id=conversation_id,
                        session_id=UUID(raw_session_id),
                    )
        return event

    @router.post(
        "/conversations/{conversation_id}/workspace/interactions",
        response_model=Event,
    )
    async def record_workspace_interaction(
        conversation_id: UUID,
        payload: WorkspaceInteractionRequest,
        request: Request,
        principal: Annotated[PrincipalContext, Depends(_require_principal)],
    ) -> Event:
        state = _get_app_state(request)
        await _require_owned_conversation(
            state=state,
            principal=principal,
            conversation_id=conversation_id,
        )
        assert state.services is not None
        events = await state.services.conversations.list_events(conversation_id)
        registry = state.services.workspace_registry or load_component_registry()
        workspace = project_workspace_events(events, registry)
        panel = next(
            (candidate for candidate in workspace.panels if candidate.id == payload.panel_id),
            None,
        )
        if panel is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="unknown panel",
            )
        valid = (
            (
                payload.action == "calendar.select_event"
                and panel.component_id == "calendar"
                and isinstance(payload.value, str)
                and 0 < len(payload.value) <= 200
            )
            or (
                payload.action == "calendar.change_view"
                and panel.component_id == "calendar"
                and isinstance(payload.value, str)
                and payload.value in {"month", "agenda"}
            )
            or (
                payload.action == "document.change_page"
                and panel.component_id == "document-viewer"
                and isinstance(payload.value, int)
                and not isinstance(payload.value, bool)
                and payload.value >= 1
            )
            or (
                payload.action == "document.find_text"
                and panel.component_id == "document-viewer"
                and isinstance(payload.value, str)
                and len(payload.value) <= 500
            )
            or (
                payload.action == "page_cards.select"
                and panel.component_id == "page-cards"
                and _valid_page_card_selection(panel.props, payload.value)
            )
            or (
                payload.action == "visual.change"
                and panel.component_id == "visual-composition"
                and _valid_visual_change(panel.props, payload.value)
            )
            or (
                payload.action == "draft.change"
                and panel.component_id == "draft-document"
                and _valid_draft_change(panel.props, payload.value)
            )
        )
        if not valid:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="invalid workspace interaction",
            )
        event = Event(
            type="workspace.interaction",
            actor="user",
            principal_user_id=principal.user_id,
            anonymous_session_id=principal.anonymous_session_id,
            conversation_id=conversation_id,
            payload={
                "panel_id": str(panel.id),
                "component_id": panel.component_id,
                "action": payload.action,
                "value": payload.value,
            },
        )
        persisted_events = [event]
        if payload.action == "draft.change":
            assert isinstance(payload.value, dict)
            field_id = cast(str, payload.value["field_id"])
            changed_value = cast(str, payload.value["value"])
            fields = _draft_fields(panel.props)
            assert fields is not None
            updated_fields: list[dict[str, JsonValue]] = []
            for field in fields:
                updated = dict(field)
                if updated.get("id") == field_id:
                    updated["value"] = changed_value
                    updated["status"] = "confirmed" if changed_value.strip() else "missing"
                    updated["source"] = "Confirmed by applicant" if changed_value.strip() else ""
                updated_fields.append(updated)
            command = UpdateWorkspaceCommand(
                panel_id=panel.id,
                props={"fields": updated_fields},
            )
            persisted_events.append(
                Event(
                    type="workspace.panel.updated",
                    actor="user",
                    principal_user_id=principal.user_id,
                    anonymous_session_id=principal.anonymous_session_id,
                    conversation_id=conversation_id,
                    payload={"command": command.model_dump(mode="json", exclude_none=True)},
                )
            )
        await state.services.conversations.append_events(conversation_id, persisted_events)
        return persisted_events[-1]

    @router.get(
        "/conversations/{conversation_id}/browser/{session_id}/snapshot",
        response_model=None,
    )
    async def browser_snapshot(
        conversation_id: UUID,
        session_id: UUID,
        request: Request,
        principal: Annotated[PrincipalContext, Depends(_require_principal)],
    ) -> Response:
        state = _get_app_state(request)
        await _require_owned_conversation(
            state=state,
            principal=principal,
            conversation_id=conversation_id,
        )
        assert state.services is not None
        browser = state.services.browser
        if browser is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="remote browser unavailable",
            )
        try:
            snapshot = await browser.snapshot(
                principal=principal,
                conversation_id=conversation_id,
                session_id=session_id,
            )
        except BrowserError as error:
            raise _browser_http_error(error) from error
        return Response(
            content=snapshot.png,
            media_type="image/png",
            headers={
                "Cache-Control": "private, no-store",
                "X-Content-Type-Options": "nosniff",
                "X-Class-Agent-Browser-Revision": str(snapshot.page.revision),
            },
        )

    @router.get(
        "/conversations/{conversation_id}/browser/previews/{preview_id}/snapshot",
        response_model=None,
    )
    async def browser_preview_snapshot(
        conversation_id: UUID,
        preview_id: UUID,
        request: Request,
        principal: Annotated[PrincipalContext, Depends(_require_principal)],
    ) -> Response:
        state = _get_app_state(request)
        await _require_owned_conversation(
            state=state,
            principal=principal,
            conversation_id=conversation_id,
        )
        assert state.services is not None
        browser = state.services.browser
        if browser is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="remote browser unavailable",
            )
        try:
            snapshot = await browser.preview_snapshot(
                principal=principal,
                conversation_id=conversation_id,
                preview_id=preview_id,
            )
        except BrowserError as error:
            raise _browser_http_error(error) from error
        return Response(
            content=snapshot.png,
            media_type="image/png",
            headers={
                "Cache-Control": "private, no-store",
                "X-Content-Type-Options": "nosniff",
                "X-Class-Agent-Browser-Revision": str(snapshot.preview.revision),
            },
        )

    @router.post(
        "/conversations/{conversation_id}/browser/{session_id}/scroll",
        response_model=Event,
    )
    async def scroll_browser_session(
        conversation_id: UUID,
        session_id: UUID,
        payload: BrowserScrollRequest,
        request: Request,
        principal: Annotated[PrincipalContext, Depends(_require_principal)],
    ) -> Event:
        state = _get_app_state(request)
        await _require_owned_conversation(
            state=state,
            principal=principal,
            conversation_id=conversation_id,
        )
        if payload.delta_y == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="scroll distance must not be zero",
            )
        assert state.services is not None
        browser = state.services.browser
        if browser is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="remote browser unavailable",
            )
        events = await state.services.conversations.list_events(conversation_id)
        registry = state.services.workspace_registry or load_component_registry()
        workspace = project_workspace_events(events, registry)
        panel = next(
            (
                candidate
                for candidate in workspace.panels
                if candidate.id == payload.panel_id
                and candidate.component_id == BROWSER_COMPONENT_ID
                and candidate.props.get("session_id") == str(session_id)
            ),
            None,
        )
        if panel is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="browser panel not found",
            )
        try:
            try:
                page = await browser.scroll(
                    principal=principal,
                    conversation_id=conversation_id,
                    session_id=session_id,
                    delta_y=payload.delta_y,
                )
            except BrowserSessionNotFound:
                raw_url = panel.props.get("url")
                if not isinstance(raw_url, str):
                    raise
                recovered = await browser.open(
                    principal=principal,
                    conversation_id=conversation_id,
                    url=raw_url,
                )
                page = await browser.scroll(
                    principal=principal,
                    conversation_id=conversation_id,
                    session_id=recovered.session_id,
                    delta_y=payload.delta_y,
                )
            command = UpdateWorkspaceCommand(
                panel_id=panel.id,
                title=page.title,
                props=browser_page_props(page),
            )
            registry.apply(workspace, command)
        except BrowserError as error:
            raise _browser_http_error(error) from error
        except (ToolValidationError, WorkspaceValidationError) as error:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(error),
            ) from error
        event = Event(
            type="workspace.panel.updated",
            actor="user",
            principal_user_id=principal.user_id,
            anonymous_session_id=principal.anonymous_session_id,
            conversation_id=conversation_id,
            payload={"command": command.model_dump(mode="json", exclude_none=True)},
            metadata={"interaction": "browser.scroll"},
        )
        await state.services.conversations.append_events(conversation_id, [event])
        return event

    @router.post(
        "/conversations/{conversation_id}/browser/{session_id}/resize",
        response_model=Event,
    )
    async def resize_browser_session(
        conversation_id: UUID,
        session_id: UUID,
        payload: BrowserResizeRequest,
        request: Request,
        principal: Annotated[PrincipalContext, Depends(_require_principal)],
    ) -> Event:
        state = _get_app_state(request)
        await _require_owned_conversation(
            state=state,
            principal=principal,
            conversation_id=conversation_id,
        )
        assert state.services is not None
        browser = state.services.browser
        if browser is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="remote browser unavailable",
            )
        events = await state.services.conversations.list_events(conversation_id)
        registry = state.services.workspace_registry or load_component_registry()
        workspace = project_workspace_events(events, registry)
        panel = next(
            (
                candidate
                for candidate in workspace.panels
                if candidate.id == payload.panel_id
                and candidate.component_id == BROWSER_COMPONENT_ID
                and candidate.props.get("session_id") == str(session_id)
            ),
            None,
        )
        if panel is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="browser panel not found",
            )
        try:
            try:
                page = await browser.resize(
                    principal=principal,
                    conversation_id=conversation_id,
                    session_id=session_id,
                    width=payload.width,
                    height=payload.height,
                )
            except BrowserSessionNotFound:
                raw_url = panel.props.get("url")
                if not isinstance(raw_url, str):
                    raise
                recovered = await browser.open(
                    principal=principal,
                    conversation_id=conversation_id,
                    url=raw_url,
                )
                page = await browser.resize(
                    principal=principal,
                    conversation_id=conversation_id,
                    session_id=recovered.session_id,
                    width=payload.width,
                    height=payload.height,
                )
            command = UpdateWorkspaceCommand(
                panel_id=panel.id,
                title=page.title,
                props=browser_page_props(page),
            )
            registry.apply(workspace, command)
        except BrowserError as error:
            raise _browser_http_error(error) from error
        except WorkspaceValidationError as error:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(error),
            ) from error
        event = Event(
            type="workspace.panel.updated",
            actor="system",
            principal_user_id=principal.user_id,
            anonymous_session_id=principal.anonymous_session_id,
            conversation_id=conversation_id,
            payload={"command": command.model_dump(mode="json", exclude_none=True)},
            metadata={"interaction": "browser.resize"},
        )
        await state.services.conversations.append_events(conversation_id, [event])
        return event

    @router.post(
        "/conversations/{conversation_id}/browser/{session_id}/click",
        response_model=Event,
    )
    async def click_browser_session(
        conversation_id: UUID,
        session_id: UUID,
        payload: BrowserClickRequest,
        request: Request,
        principal: Annotated[PrincipalContext, Depends(_require_principal)],
    ) -> Event:
        state = _get_app_state(request)
        await _require_owned_conversation(
            state=state,
            principal=principal,
            conversation_id=conversation_id,
        )
        assert state.services is not None
        browser = state.services.browser
        if browser is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="remote browser unavailable",
            )
        events = await state.services.conversations.list_events(conversation_id)
        registry = state.services.workspace_registry or load_component_registry()
        workspace = project_workspace_events(events, registry)
        panel = next(
            (
                candidate
                for candidate in workspace.panels
                if candidate.id == payload.panel_id
                and candidate.component_id == BROWSER_COMPONENT_ID
                and candidate.props.get("session_id") == str(session_id)
            ),
            None,
        )
        if panel is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="browser panel not found",
            )
        try:
            try:
                page = await browser.click(
                    principal=principal,
                    conversation_id=conversation_id,
                    session_id=session_id,
                    x=payload.x,
                    y=payload.y,
                )
            except BrowserSessionNotFound:
                raw_url = panel.props.get("url")
                if not isinstance(raw_url, str):
                    raise
                recovered = await browser.open(
                    principal=principal,
                    conversation_id=conversation_id,
                    url=raw_url,
                )
                page = await browser.click(
                    principal=principal,
                    conversation_id=conversation_id,
                    session_id=recovered.session_id,
                    x=payload.x,
                    y=payload.y,
                )
            command = UpdateWorkspaceCommand(
                panel_id=panel.id,
                title=page.title,
                props=browser_page_props(page),
            )
            registry.apply(workspace, command)
        except BrowserError as error:
            raise _browser_http_error(error) from error
        except WorkspaceValidationError as error:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(error),
            ) from error
        event = Event(
            type="workspace.panel.updated",
            actor="user",
            principal_user_id=principal.user_id,
            anonymous_session_id=principal.anonymous_session_id,
            conversation_id=conversation_id,
            payload={"command": command.model_dump(mode="json", exclude_none=True)},
            metadata={
                "interaction": "browser.click",
                "url": page.url,
                "title": page.title,
            },
        )
        await state.services.conversations.append_events(conversation_id, [event])
        return event

    @router.post(
        "/conversations/{conversation_id}/run",
        response_model=RunResponse,
    )
    async def run_conversation(
        conversation_id: UUID,
        payload: RunRequest,
        request: Request,
        principal: Annotated[PrincipalContext, Depends(_require_principal)],
    ) -> RunResponse:
        state = _get_app_state(request)
        await _require_owned_conversation(
            state=state,
            principal=principal,
            conversation_id=conversation_id,
        )
        result = await _run_agent(
            state=state,
            principal=principal,
            conversation_id=conversation_id,
            text=payload.text,
        )
        return RunResponse.from_result(result)

    @router.post("/conversations/{conversation_id}/run/stream")
    async def stream_conversation_run(
        conversation_id: UUID,
        payload: RunRequest,
        request: Request,
        principal: Annotated[PrincipalContext, Depends(_require_principal)],
    ) -> StreamingResponse:
        state = _get_app_state(request)
        await _require_owned_conversation(
            state=state,
            principal=principal,
            conversation_id=conversation_id,
        )
        return _streaming_response(
            _stream_agent_run(
                state=state,
                principal=principal,
                conversation_id=conversation_id,
                text=payload.text,
            )
        )

    @router.post("/agent/run", response_model=None)
    async def run_agent(
        payload: AgentRunRequest,
        request: Request,
        principal: Annotated[PrincipalContext, Depends(_require_principal)],
    ) -> RunResponse | StreamingResponse:
        state = _get_app_state(request)
        await _require_owned_conversation(
            state=state,
            principal=principal,
            conversation_id=payload.conversation_id,
        )
        if "text/event-stream" in request.headers.get("accept", ""):
            return _streaming_response(
                _stream_agent_run(
                    state=state,
                    principal=principal,
                    conversation_id=payload.conversation_id,
                    text=payload.text,
                )
            )
        result = await _run_agent(
            state=state,
            principal=principal,
            conversation_id=payload.conversation_id,
            text=payload.text,
        )
        return RunResponse.from_result(result)

    app.include_router(router, prefix=API_PREFIX)
    app.include_router(router, include_in_schema=False)
    return app


def main() -> None:
    """Run the development API server through Uvicorn's application factory."""

    import uvicorn

    uvicorn.run(
        "course_server.api:create_app",
        factory=True,
        host="127.0.0.1",
        port=8000,
    )


if __name__ == "__main__":
    main()
