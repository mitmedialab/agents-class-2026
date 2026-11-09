"""Thin authenticated HTTP endpoints for the native peer workspace."""

from collections.abc import Awaitable, Callable

from fastapi import APIRouter, HTTPException, Request

from agent_core import PrincipalContext
from course_server.agent.capabilities import ToolValidationError

from .models import Feedback, ProfileUpdate
from .service import PeerDiscovery, student_id
from .tools import Refresh


def peer_router(
    resolve: Callable[[Request], Awaitable[PrincipalContext]],
    get_service: Callable[[Request], PeerDiscovery | None],
) -> APIRouter:
    router = APIRouter(prefix="/peer-discovery", tags=["Peer discovery"])

    async def authorized(request: Request) -> tuple[PrincipalContext, PeerDiscovery]:
        principal = await resolve(request)
        try:
            student_id(principal)
        except ToolValidationError as error:
            raise HTTPException(403, str(error)) from error
        service = get_service(request)
        if service is None:
            raise HTTPException(503, "Peer discovery is not enabled on this deployment.")
        return principal, service

    @router.get("")
    async def read(request: Request) -> dict[str, object]:
        principal, service = await authorized(request)
        return service.context(principal)

    @router.post("/weekly")
    async def weekly(request: Request) -> dict[str, object]:
        principal, service = await authorized(request)
        try:
            return await service.prepare_weekly(principal)
        except ToolValidationError as error:
            raise HTTPException(503, str(error)) from error

    @router.put("/profile")
    async def profile(request: Request, update: ProfileUpdate) -> dict[str, object]:
        principal, service = await authorized(request)
        try:
            service.update_profile(principal, update, "Student saved the memory form")
        except ToolValidationError as error:
            raise HTTPException(400, str(error)) from error
        return service.context(principal)

    @router.delete("/memory")
    async def forget(request: Request) -> dict[str, object]:
        principal, service = await authorized(request)
        service.store.forget(student_id(principal))
        return service.context(principal)

    @router.post("/feedback")
    async def feedback(request: Request, value: Feedback) -> dict[str, object]:
        principal, service = await authorized(request)
        try:
            service.feedback(principal, value)
        except ToolValidationError as error:
            raise HTTPException(400, str(error)) from error
        return service.context(principal)

    @router.post("/refresh")
    async def refresh(request: Request, value: Refresh) -> dict[str, object]:
        principal, service = await authorized(request)
        try:
            return await service.refresh(principal, value.project_ids, value.weeks)
        except ToolValidationError as error:
            raise HTTPException(400, str(error)) from error

    return router
