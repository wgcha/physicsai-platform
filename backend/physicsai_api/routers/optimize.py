"""⑤ 최적화 API(phase2 §12.8)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from .. import schemas as S
from ..auth import Principal
from ..deps import get_ctx, get_principal
from ..services import optimize as svc

router = APIRouter(tags=["optimize"])
ERR = {404: {"model": S.ErrorResponse}}


@router.get("/studies/{study_id}/optimizations", response_model=list[S.Optimization], responses=ERR)
def list_opts(study_id: str, request: Request, _p: Principal = Depends(get_principal)) -> list:
    return svc.list_opts(get_ctx(request), study_id)


@router.get("/optimizations/{optimization_id}", response_model=S.Optimization, responses=ERR)
def get_opt(optimization_id: str, request: Request, _p: Principal = Depends(get_principal)) -> dict:
    return svc.get_opt(get_ctx(request), optimization_id)


@router.get("/studies/{study_id}/optimize/response-candidates", response_model=S.ResponseCandidates, responses=ERR)
def candidates(study_id: str, request: Request, model_id: str | None = None, _p: Principal = Depends(get_principal)) -> dict:
    return svc.response_candidates(get_ctx(request), study_id, model_id)
