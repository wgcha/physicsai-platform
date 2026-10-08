from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from physicsai_core import __version__

from .. import schemas as S
from ..auth import Principal
from ..deps import get_ctx, get_principal, get_token, request_id
from ..services import system

router = APIRouter(tags=["shell"])


@router.get("/health", response_model=S.Health)
def health() -> dict:
    return {"status": "ok", "version": __version__}


@router.get("/me", response_model=S.Me)
def me(principal: Principal = Depends(get_principal)) -> dict:
    return {"user_id": principal.user_id, "username": principal.username, "display_name": principal.display_name,
            "is_global_admin": principal.is_global_admin, "roles": dict(principal.roles)}


@router.get("/projects", response_model=list[S.Project])
def projects(request: Request, principal: Principal = Depends(get_principal)) -> list:
    return get_ctx(request).auth.projects(principal, get_token(request), request_id(request))


@router.get("/status", response_model=S.StatusResponse)
def status(request: Request, principal: Principal = Depends(get_principal)) -> dict:
    return system.status(get_ctx(request), principal)


@router.get("/resources", response_model=S.ResourcesResponse, responses={404: {"model": S.ErrorResponse}})
def resources(request: Request, _p: Principal = Depends(get_principal)) -> dict:
    return system.resources(get_ctx(request))



