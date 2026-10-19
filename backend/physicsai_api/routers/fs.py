"""서버 경로 탐색(phase3 §12 S7, D3-46). 읽기 전용 — 이름·크기·mtime만, 업로드·쓰기 없음."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request

from .. import schemas as S
from ..auth import Principal
from ..deps import get_ctx, get_principal
from ..services import fs_browse as svc

router = APIRouter(tags=["fs"])
ERR = {403: {"model": S.ErrorResponse}, 422: {"model": S.ErrorResponse}}


@router.get("/fs/roots", response_model=S.FsRoots, responses=ERR)
def fs_roots(request: Request, include_spdm: bool = False, principal: Principal = Depends(get_principal)) -> dict:
    """include_spdm=true(phase3 §21.3.8 S16): SPDM 루트(설정)를 `SPDM <i>(읽기 전용)` 루트로 덧붙인다."""
    return svc.roots(get_ctx(request), principal, include_spdm)


@router.get("/fs/list", response_model=S.FsList, responses=ERR)
def fs_list(request: Request, path: str = Query(max_length=400), exts: str | None = Query(default=None, max_length=200),
            principal: Principal = Depends(get_principal)) -> dict:
    return svc.list_dir(get_ctx(request), principal, path, exts)
