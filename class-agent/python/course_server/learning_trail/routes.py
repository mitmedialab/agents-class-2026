"""HTTP routes for the student-facing trail panel. Behavior lives in `LearningTrailService`."""

from collections.abc import Awaitable, Callable
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel

from agent_core import PrincipalContext

from .models import (
    PendingDraft,
    SharedTrailSummary,
    StaffFeedbackDraft,
    TopicCoverage,
    TrailConnection,
    TrailEntry,
    TrailEntryDraft,
    TrailEntryPatch,
    TrailFeedbackDraft,
    TrailTopic,
)
from .service import (
    LearningTrailService,
    TrailAccessDenied,
    TrailEntryNotFound,
    TrailLimitExceeded,
)
from .store import TrailStoreError


class TrailResponse(BaseModel):
    entries: list[TrailEntry]


class TrailConnectionsResponse(BaseModel):
    connections: dict[UUID, list[TrailConnection]]


class TrailTopicsResponse(BaseModel):
    topics: list[TrailTopic]
    coverage: TopicCoverage


class SharedStudentsResponse(BaseModel):
    students: list[SharedTrailSummary]


def _http_error(error: Exception) -> HTTPException:
    if isinstance(error, TrailAccessDenied):
        return HTTPException(status.HTTP_403_FORBIDDEN, str(error))
    if isinstance(error, TrailEntryNotFound):
        return HTTPException(status.HTTP_404_NOT_FOUND, "not found")
    if isinstance(error, TrailLimitExceeded):
        return HTTPException(status.HTTP_409_CONFLICT, str(error))
    return HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "learning trail unavailable")


_HANDLED = (TrailAccessDenied, TrailEntryNotFound, TrailLimitExceeded, TrailStoreError)


def build_learning_trail_router(
    *,
    require_principal: Callable[[Request], Awaitable[PrincipalContext]],
    get_service: Callable[[Request], LearningTrailService | None],
) -> APIRouter:
    router = APIRouter(prefix="/learning-trail")

    def service_for(request: Request) -> LearningTrailService:
        service = get_service(request)
        if service is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "not found")
        return service

    @router.get("", response_model=TrailResponse)
    async def list_entries(
        request: Request,
        principal: Annotated[PrincipalContext, Depends(require_principal)],
    ) -> TrailResponse:
        try:
            return TrailResponse(entries=await service_for(request).list_mine(principal))
        except _HANDLED as error:
            raise _http_error(error) from error

    @router.get("/connections", response_model=TrailConnectionsResponse)
    async def list_connections(
        request: Request,
        principal: Annotated[PrincipalContext, Depends(require_principal)],
    ) -> TrailConnectionsResponse:
        try:
            return TrailConnectionsResponse(
                connections=await service_for(request).connections(principal)
            )
        except _HANDLED as error:
            raise _http_error(error) from error

    @router.get("/topics", response_model=TrailTopicsResponse)
    async def list_topics(
        request: Request,
        principal: Annotated[PrincipalContext, Depends(require_principal)],
    ) -> TrailTopicsResponse:
        service = service_for(request)
        try:
            return TrailTopicsResponse(
                topics=await service.topics(), coverage=await service.coverage(principal)
            )
        except _HANDLED as error:
            raise _http_error(error) from error

    @router.get("/draft", response_model=PendingDraft)
    async def read_draft(
        request: Request,
        principal: Annotated[PrincipalContext, Depends(require_principal)],
    ) -> PendingDraft:
        try:
            pending = await service_for(request).pending_draft(principal)
        except _HANDLED as error:
            raise _http_error(error) from error
        if pending is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "no pending draft")
        return pending

    @router.post("/draft/accept", response_model=TrailEntry, status_code=status.HTTP_201_CREATED)
    async def accept_draft(
        draft: TrailEntryDraft,
        request: Request,
        principal: Annotated[PrincipalContext, Depends(require_principal)],
    ) -> TrailEntry:
        try:
            return await service_for(request).accept_draft(principal, draft)
        except _HANDLED as error:
            raise _http_error(error) from error

    @router.delete("/draft", status_code=status.HTTP_204_NO_CONTENT)
    async def discard_draft(
        request: Request,
        principal: Annotated[PrincipalContext, Depends(require_principal)],
    ) -> Response:
        try:
            await service_for(request).discard_draft(principal)
        except _HANDLED as error:
            raise _http_error(error) from error
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.post("/entries", response_model=TrailEntry, status_code=status.HTTP_201_CREATED)
    async def create_entry(
        draft: TrailEntryDraft,
        request: Request,
        principal: Annotated[PrincipalContext, Depends(require_principal)],
    ) -> TrailEntry:
        try:
            return await service_for(request).create(principal, draft)
        except _HANDLED as error:
            raise _http_error(error) from error

    @router.patch("/entries/{entry_id}", response_model=TrailEntry)
    async def update_entry(
        entry_id: UUID,
        patch: TrailEntryPatch,
        request: Request,
        principal: Annotated[PrincipalContext, Depends(require_principal)],
    ) -> TrailEntry:
        try:
            return await service_for(request).update(principal, entry_id, patch)
        except _HANDLED as error:
            raise _http_error(error) from error

    @router.delete("/entries/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
    async def delete_entry(
        entry_id: UUID,
        request: Request,
        principal: Annotated[PrincipalContext, Depends(require_principal)],
    ) -> Response:
        try:
            await service_for(request).delete(principal, entry_id)
        except _HANDLED as error:
            raise _http_error(error) from error
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.post(
        "/entries/{entry_id}/feedback",
        response_model=TrailEntry,
        status_code=status.HTTP_201_CREATED,
    )
    async def add_feedback(
        entry_id: UUID,
        draft: TrailFeedbackDraft,
        request: Request,
        principal: Annotated[PrincipalContext, Depends(require_principal)],
    ) -> TrailEntry:
        try:
            return await service_for(request).add_feedback(principal, entry_id, draft)
        except _HANDLED as error:
            raise _http_error(error) from error

    @router.delete("/entries/{entry_id}/feedback/{feedback_id}", response_model=TrailEntry)
    async def delete_feedback(
        entry_id: UUID,
        feedback_id: UUID,
        request: Request,
        principal: Annotated[PrincipalContext, Depends(require_principal)],
    ) -> TrailEntry:
        try:
            return await service_for(request).delete_feedback(principal, entry_id, feedback_id)
        except _HANDLED as error:
            raise _http_error(error) from error

    @router.get("/students", response_model=SharedStudentsResponse)
    async def list_shared_students(
        request: Request,
        principal: Annotated[PrincipalContext, Depends(require_principal)],
    ) -> SharedStudentsResponse:
        try:
            students = await service_for(request).list_shared_students(principal)
        except _HANDLED as error:
            raise _http_error(error) from error
        return SharedStudentsResponse(students=students)

    @router.get("/students/{student_id}/entries", response_model=TrailResponse)
    async def list_shared_entries(
        student_id: UUID,
        request: Request,
        principal: Annotated[PrincipalContext, Depends(require_principal)],
    ) -> TrailResponse:
        try:
            entries = await service_for(request).list_shared_entries(principal, student_id)
        except _HANDLED as error:
            raise _http_error(error) from error
        return TrailResponse(entries=entries)

    @router.post(
        "/students/{student_id}/entries/{entry_id}/feedback",
        response_model=TrailEntry,
        status_code=status.HTTP_201_CREATED,
    )
    async def add_staff_feedback(
        student_id: UUID,
        entry_id: UUID,
        draft: StaffFeedbackDraft,
        request: Request,
        principal: Annotated[PrincipalContext, Depends(require_principal)],
    ) -> TrailEntry:
        try:
            return await service_for(request).add_staff_feedback(
                principal, student_id, entry_id, draft
            )
        except _HANDLED as error:
            raise _http_error(error) from error

    @router.delete(
        "/students/{student_id}/entries/{entry_id}/feedback/{feedback_id}",
        response_model=TrailEntry,
    )
    async def delete_staff_feedback(
        student_id: UUID,
        entry_id: UUID,
        feedback_id: UUID,
        request: Request,
        principal: Annotated[PrincipalContext, Depends(require_principal)],
    ) -> TrailEntry:
        try:
            return await service_for(request).delete_staff_feedback(
                principal, student_id, entry_id, feedback_id
            )
        except _HANDLED as error:
            raise _http_error(error) from error

    return router
