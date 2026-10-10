from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request, Response

from .. import schemas as S
from ..auth import Principal
from ..deps import client_ip, get_ctx, get_principal, request_id
from ..services import stage4_predict as svc

router = APIRouter(tags=["param-sets"])
ERR = {404: {"model": S.ErrorResponse}, 409: {"model": S.ErrorResponse}, 422: {"model": S.ErrorResponse}}


@router.post("/studies/{study_id}/param-sets", response_model=S.ParamSet, status_code=201, responses=ERR)
def register(study_id: str, body: S.ParamSetCreate, request: Request, principal: Principal = Depends(get_principal)) -> dict:
    return svc.register_param_set(get_ctx(request), principal, study_id, body.path, request_id(request), client_ip(request))


@router.post("/studies/{study_id}/param-sets/from-train", response_model=S.ParamSet, status_code=201, responses=ERR)
def from_train(study_id: str, body: S.ParamSetFromTrain, request: Request, principal: Principal = Depends(get_principal)) -> dict:
    """F(phase2 §6.13): ① DOE 결과로 파라미터 세트 만들기."""
    return svc.register_param_set_from_train(get_ctx(request), principal, study_id, body, request_id(request), client_ip(request))


@router.get("/studies/{study_id}/param-sets", response_model=list[S.ParamSet], responses=ERR)
def list_sets(study_id: str, request: Request, response: Response, limit: int | None = Query(default=None, ge=1, le=200),
              cursor: str | None = None, _p: Principal = Depends(get_principal)) -> list:
    items, nxt = svc.list_param_sets(get_ctx(request), study_id, limit, cursor)
    if nxt:
        response.headers["X-Next-Cursor"] = nxt
    return items


@router.get("/param-sets/{ps_id}", response_model=S.ParamSet, responses=ERR)
def get_set(ps_id: str, request: Request, _p: Principal = Depends(get_principal)) -> dict:
    return svc.get_param_set(get_ctx(request), ps_id)


@router.get("/param-sets/{ps_id}/samples", response_model=S.SamplesPage, responses=ERR)
def samples(ps_id: str, request: Request, limit: int | None = Query(default=None, ge=1, le=200), cursor: str | None = None,
            _p: Principal = Depends(get_principal)) -> dict:
    return svc.get_samples(get_ctx(request), ps_id, limit, cursor)


@router.post("/studies/{study_id}/predict/check", response_model=S.PredictCheckResponse, responses=ERR)
def predict_check(study_id: str, body: S.PredictCheckRequest, request: Request, _p: Principal = Depends(get_principal)) -> dict:
    return svc.predict_check(get_ctx(request), study_id, body.param_set_id, body.values)
