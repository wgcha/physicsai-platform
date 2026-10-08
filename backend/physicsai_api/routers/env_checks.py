"""환경 점검 API(phase2 §12.2, 전역 관리자)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request, Response

from .. import schemas as S
from ..auth import Principal
from ..deps import client_ip, get_ctx, get_principal, get_token, request_id
from ..services import env_checks as svc

router = APIRouter(tags=["admin"])
ERR = {403: {"model": S.ErrorResponse}, 404: {"model": S.ErrorResponse}, 409: {"model": S.ErrorResponse}}


@router.post("/admin/env-checks", response_model=S.EnvCheck, status_code=202, responses=ERR)
def create(request: Request, principal: Principal = Depends(get_principal)) -> dict:
    return svc.create(get_ctx(request), principal, get_token(request), request_id(request), client_ip(request))


@router.get("/admin/env-checks", response_model=list[S.EnvCheckSummary], responses=ERR)
def list_checks(request: Request, response: Response, limit: int | None = Query(default=None, ge=1, le=200),
                cursor: str | None = None, principal: Principal = Depends(get_principal)) -> list:
    items, nxt = svc.list_(get_ctx(request), principal, limit, cursor)
    if nxt:
        response.headers["X-Next-Cursor"] = nxt
    return items


@router.get("/admin/env-checks/latest", response_model=S.EnvCheck, responses=ERR)
def latest(request: Request, principal: Principal = Depends(get_principal)) -> dict:
    return svc.latest(get_ctx(request), principal)


@router.get("/admin/env-checks/{check_id}", response_model=S.EnvCheck, responses=ERR)
def get_check(check_id: str, request: Request, principal: Principal = Depends(get_principal)) -> dict:
    return svc.get(get_ctx(request), principal, check_id)
