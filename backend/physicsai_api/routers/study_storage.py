"""Study 용량·정리 보고서(phase3 §5.6). 계산·정리 실행은 POST /studies/{id}/jobs(STUDY_STORAGE_SCAN·STUDY_CLEANUP)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from .. import schemas as S
from ..auth import Principal
from ..deps import get_ctx, get_principal
from ..services import study_storage as svc

router = APIRouter(tags=["studies"])
ERR = {404: {"model": S.ErrorResponse}}


@router.get("/studies/{study_id}/storage", response_model=S.StorageReport, responses=ERR)
def get_study_storage(study_id: str, request: Request, principal: Principal = Depends(get_principal)) -> dict:
    return svc.get_report(get_ctx(request), principal, study_id)
