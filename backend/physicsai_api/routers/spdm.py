"""② SPDM 가져오기 목록(phase2 §12.6). 가져오기 자체는 작업(SPDM_IMPORT) — 업로드 엔드포인트 없음."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from .. import schemas as S
from ..auth import Principal
from ..deps import get_ctx, get_principal
from ..services import curations as svc

router = APIRouter(tags=["spdm"])


@router.get("/studies/{study_id}/spdm-imports", response_model=list[S.SpdmImport], responses={404: {"model": S.ErrorResponse}})
def list_imports(study_id: str, request: Request, _p: Principal = Depends(get_principal)) -> list:
    return svc.list_imports(get_ctx(request), study_id)
