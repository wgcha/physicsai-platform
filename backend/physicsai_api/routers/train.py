"""① 학습데이터 API(phase2 §12.5)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request, Response

from .. import schemas as S
from ..auth import Principal
from ..deps import client_ip, get_ctx, get_principal, request_id
from ..services import train as svc

router = APIRouter(tags=["train"])
ERR = {403: {"model": S.ErrorResponse}, 404: {"model": S.ErrorResponse}, 409: {"model": S.ErrorResponse},
       422: {"model": S.ErrorResponse}, 503: {"model": S.ErrorResponse}}


@router.get("/studies/{study_id}/train", response_model=S.TrainSetup, responses=ERR)
def get_setup(study_id: str, request: Request, _p: Principal = Depends(get_principal)) -> dict:
    return svc.get_setup(get_ctx(request), study_id)


@router.put("/studies/{study_id}/train/params", response_model=S.TrainSetup, responses=ERR)
def put_params(study_id: str, body: S.TrainParamsPut, request: Request, principal: Principal = Depends(get_principal)) -> dict:
    return svc.put_params(get_ctx(request), principal, study_id, body, request_id(request), client_ip(request))


@router.post("/studies/{study_id}/train/tpl", response_model=S.TrainSetup, responses=ERR)
def generate_tpl(study_id: str, body: S.VersionBody, request: Request, principal: Principal = Depends(get_principal)) -> dict:
    return svc.generate_tpl(get_ctx(request), principal, study_id, body.version, request_id(request), client_ip(request))


@router.get("/train/doe-types", response_model=list[S.DoeType], responses=ERR)
def doe_types(request: Request, _p: Principal = Depends(get_principal)) -> list:
    return svc.doe_types(get_ctx(request))


@router.get("/studies/{study_id}/train/does", response_model=list[S.TrainDoe], responses=ERR)
def list_does(study_id: str, request: Request, _p: Principal = Depends(get_principal)) -> list:
    return svc.list_does(get_ctx(request), study_id)


@router.get("/train-does/{doe_id}", response_model=S.TrainDoe, responses=ERR)
def get_doe(doe_id: str, request: Request, _p: Principal = Depends(get_principal)) -> dict:
    return svc.get_doe(get_ctx(request), doe_id)


@router.get("/train-does/{doe_id}/runs", response_model=list[S.TrainRun], responses=ERR)
def list_runs(doe_id: str, request: Request, response: Response, state: str | None = None,
              limit: int | None = Query(default=None, ge=1, le=200), cursor: str | None = None,
              _p: Principal = Depends(get_principal)) -> list:
    items, nxt = svc.list_runs(get_ctx(request), doe_id, state, limit, cursor)
    if nxt:
        response.headers["X-Next-Cursor"] = nxt
    return items


@router.get("/train-does/{doe_id}/samples", response_model=S.SamplesPage, responses=ERR)
def samples(doe_id: str, request: Request, limit: int | None = Query(default=None, ge=1, le=200), cursor: str | None = None,
            _p: Principal = Depends(get_principal)) -> dict:
    return svc.doe_samples_page(get_ctx(request), doe_id, limit, cursor)
