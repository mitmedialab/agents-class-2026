"""Owner-scoped HTTP routes for the People panel (memories and peer introductions)."""


from collections.abc import Awaitable, Callable
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from agent_core import PrincipalContext
from course_server.peer_memory import (
    MemoryUpdate,
    PeerMemoryAccessDenied,
    PeerMemoryConflict,
    PeerMemoryNotFound,
    PeerMemoryService,
    memory_view,
)

_PRIVATE_HEADERS = {"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"}


class IntroductionActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["send", "cancel", "accept", "decline"]


def create_peer_memory_router(
    *,
    require_principal: Callable[[Request], Awaitable[PrincipalContext]],
    service_for: Callable[[Request], PeerMemoryService | None],
) -> APIRouter:
    router = APIRouter()

    def _service(request: Request) -> PeerMemoryService:
        service = service_for(request)
        if service is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")
        return service

    def _not_found(error: Exception) -> HTTPException:
        # Absent, foreign and forbidden items share one response so nothing is disclosed.
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")

    @router.get("/people/mine", response_model=None)
    async def read_people(
        request: Request,
        principal: Annotated[PrincipalContext, Depends(require_principal)],
    ) -> Response:
        service = _service(request)
        try:
            memories = await service.list_mine(principal)
            introductions = await service.introductions_view(principal)
        except PeerMemoryAccessDenied as error:
            raise _not_found(error) from error
        return JSONResponse(
            content={
                "memories": [memory_view(memory) for memory in memories],
                "introductions": introductions,
            },
            headers=_PRIVATE_HEADERS,
        )

    @router.patch("/people/mine/memories/{memory_id}", response_model=None)
    async def update_memory(
        memory_id: UUID,
        payload: MemoryUpdate,
        request: Request,
        principal: Annotated[PrincipalContext, Depends(require_principal)],
    ) -> Response:
        service = _service(request)
        try:
            memory = await service.update_mine(principal, memory_id, payload)
        except (PeerMemoryAccessDenied, PeerMemoryNotFound) as error:
            raise _not_found(error) from error
        return JSONResponse(content={"memory": memory_view(memory)}, headers=_PRIVATE_HEADERS)

    @router.delete("/people/mine/memories/{memory_id}", response_model=None)
    async def delete_memory(
        memory_id: UUID,
        request: Request,
        principal: Annotated[PrincipalContext, Depends(require_principal)],
    ) -> Response:
        service = _service(request)
        try:
            await service.forget_mine(principal, memory_id)
        except (PeerMemoryAccessDenied, PeerMemoryNotFound) as error:
            raise _not_found(error) from error
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.post("/people/mine/introductions/{introduction_id}", response_model=None)
    async def act_on_introduction(
        introduction_id: UUID,
        payload: IntroductionActionRequest,
        request: Request,
        principal: Annotated[PrincipalContext, Depends(require_principal)],
    ) -> Response:
        service = _service(request)
        try:
            await service.transition(principal, introduction_id, payload.action)
            introductions = await service.introductions_view(principal)
        except (PeerMemoryAccessDenied, PeerMemoryNotFound) as error:
            raise _not_found(error) from error
        except PeerMemoryConflict as error:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
        return JSONResponse(content={"introductions": introductions}, headers=_PRIVATE_HEADERS)

    return router
