from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request, Response

from .. import schemas as S
from ..auth import Principal
from ..deps import client_ip, get_ctx, get_principal, request_id
from ..services import studies as svc

router = APIRouter(tags=["models"])
ERR = {404: {"model": S.ErrorResponse}, 409: {"model": S.ErrorResponse}}


@router.get("/studies/{study_id}/models", response_model=list[S.Model], responses=ERR)
def list_models(study_id: str, request: Request, response: Response, status: str | None = None,
                limit: int | None = Query(default=None, ge=1, le=200), cursor: str | None = None,
                _p: Principal = Depends(get_principal)) -> list:
    items, nxt = svc.list_models(get_ctx(request), study_id, status, limit, cursor)
    if nxt:
        response.headers["X-Next-Cursor"] = nxt
    return items


@router.get("/models/{model_id}", response_model=S.Model, responses=ERR)
def get_model(model_id: str, request: Request, _p: Principal = Depends(get_principal)) -> dict:
    return svc.get_model(get_ctx(request), model_id)


@router.patch("/models/{model_id}", response_model=S.Model, responses=ERR)
def patch_model(model_id: str, body: S.ModelPatch, request: Request, principal: Principal = Depends(get_principal)) -> dict:
    return svc.patch_model(get_ctx(request), principal, model_id, body, request_id(request), client_ip(request))


@router.put("/studies/{study_id}/final-model", response_model=S.Study, responses=ERR)
def put_final(study_id: str, body: S.FinalModelRequest, request: Request, principal: Principal = Depends(get_principal)) -> dict:
    return svc.set_final(get_ctx(request), principal, study_id, body.model_id, request_id(request), client_ip(request))
