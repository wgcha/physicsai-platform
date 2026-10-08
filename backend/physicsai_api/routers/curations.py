"""② 데이터 정리 API(phase2 §12.6)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request

from .. import schemas as S
from ..auth import Principal
from ..deps import get_ctx, get_principal
from ..services import curations as svc

router = APIRouter(tags=["curations"])
ERR = {404: {"model": S.ErrorResponse}, 422: {"model": S.ErrorResponse}}


@router.get("/studies/{study_id}/curation-sources", response_model=list[S.CurationSource], responses=ERR)
def sources(study_id: str, request: Request, _p: Principal = Depends(get_principal)) -> list:
    return svc.curation_sources(get_ctx(request), study_id)


@router.get("/studies/{study_id}/curations", response_model=list[S.Curation], responses=ERR)
def list_curations(study_id: str, request: Request, kind: str | None = Query(default=None, pattern="^(H3D|T01)$"),
                   _p: Principal = Depends(get_principal)) -> list:
    return svc.list_curations(get_ctx(request), study_id, kind)


@router.get("/curations/{curation_id}", response_model=S.Curation, responses=ERR)
def get_curation(curation_id: str, request: Request, _p: Principal = Depends(get_principal)) -> dict:
    return svc.get_curation(get_ctx(request), curation_id)


@router.get("/curations/{curation_id}/files", response_model=S.CurationFilesPage, responses=ERR)
def files(curation_id: str, request: Request, ok: bool | None = None, limit: int | None = Query(default=None, ge=1, le=200),
          cursor: str | None = None, _p: Principal = Depends(get_principal)) -> dict:
    return svc.curation_files(get_ctx(request), curation_id, ok, limit, cursor)
