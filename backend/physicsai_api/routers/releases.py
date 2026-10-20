"""플랫폼 버전·버전 게시판 — 읽기 전용(GET만). 기록은 배포(RELEASES.md 갱신)로만 한다."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from .. import schemas as S
from ..auth import Principal
from ..deps import get_ctx, get_principal
from ..services import releases as svc

router = APIRouter(tags=["shell"])


@router.get("/version", response_model=S.VersionInfo)
def version(request: Request, _p: Principal = Depends(get_principal)) -> dict:
    return svc.version_info(get_ctx(request))


@router.get("/releases", response_model=S.ReleasesResponse)
def releases(request: Request, _p: Principal = Depends(get_principal)) -> dict:
    return svc.releases(get_ctx(request))
