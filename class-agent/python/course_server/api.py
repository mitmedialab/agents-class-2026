"""FastAPI transport for Phase 4 authentication and Course Agent routes."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID

from dotenv import load_dotenv
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.responses import StreamingResponse
from psycopg_pool import AsyncConnectionPool
from pydantic import BaseModel, ConfigDict, StringConstraints

from agent_core import AgentResult, Conversation, Event, PrincipalContext
from course_server.agent import (
    ConversationAccessDenied,
    ConversationStore,
    CourseAgentService,
    CourseResourceCatalog,
    FileResourceProvider,
    PublicCapabilityPolicy,
    ResourceSummary,
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

AUTH_COOKIE = "class_agent_auth"
ANON_COOKIE = "class_agent_anon"
API_PREFIX = "/api/v1"

NonEmptyText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


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


@dataclass
class AppRuntimeResources:
    """Resources owned by the production application lifespan."""

    pool: AsyncConnectionPool[Any] | None = None


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


async def _run_agent(
    *,
    state: AppState,
    principal: PrincipalContext,
    conversation_id: UUID,
    text: str,
    event_observer: Callable[[Event], None] | None = None,
    text_delta_observer: Callable[[str], None] | None = None,
    progress_delta_observer: Callable[[str], None] | None = None,
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

    def observe_progress_delta(progress_delta: str) -> None:
        with suppress(RuntimeError):
            loop.call_soon_threadsafe(
                event_queue.put_nowait,
                StreamProgressDelta(text=progress_delta),
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
                data={"type": "agent.progress.delta", "text": update.text},
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
        app.state.course_state.services = AppServices(
            authentication=AuthenticationService(auth_store),
            agent=CourseAgentService(
                runtime=build_runtime(
                    resolved_settings,
                    resources=course_resources,
                    uploads=upload_store,
                ),
                conversations=conversation_store,
                capability_policy=PublicCapabilityPolicy(
                    resource.uri for resource in course_resources.list_public()
                ),
            ),
            conversations=conversation_store,
            course_resources=course_resources,
            uploads=upload_store,
        )
        try:
            yield
        finally:
            app.state.course_state.services = None
            await pool.close()
            resources.pool = None

    app = FastAPI(
        title="Class Agent API",
        version="0.6.0",
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
