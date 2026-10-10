from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request, Response

from .. import schemas as S
from ..auth import Principal
from ..deps import get_ctx, get_principal
from ..services import stage3_model as svc

router = APIRouter(tags=["datasets"])
ERR = {404: {"model": S.ErrorResponse}}


@router.get("/studies/{study_id}/datasets", response_model=list[S.Dataset], responses=ERR)
def list_datasets(study_id: str, request: Request, response: Response, limit: int | None = Query(default=None, ge=1, le=200),
                  cursor: str | None = None, _p: Principal = Depends(get_principal)) -> list:
    items, nxt = svc.list_datasets(get_ctx(request), study_id, limit, cursor)
    if nxt:
        response.headers["X-Next-Cursor"] = nxt
    return items


@router.get("/datasets/{dataset_id}", response_model=S.Dataset, responses=ERR)
def get_dataset(dataset_id: str, request: Request, _p: Principal = Depends(get_principal)) -> dict:
    return svc.get_dataset(get_ctx(request), dataset_id)
