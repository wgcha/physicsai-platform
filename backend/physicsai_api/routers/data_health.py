"""③-1 데이터 점검 결과 API(data-health.md §8). 작업 생성은 기존 `POST /studies/{id}/jobs`(job_type=DATA_HEALTH).
사람 판단 단계라 `x-mcp.exclude`(사유는 DATASET_CREATE와 같음, DH-13)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from .. import schemas as S
from ..auth import Principal
from ..deps import get_ctx, get_principal
from ..schemas import mcp as M
from ..services import data_health_api as svc

router = APIRouter(tags=["data-health"])
ERR = {404: {"model": S.ErrorResponse}, 409: {"model": S.ErrorResponse}}
XMCP = M.xmcp_exclude("③ 데이터셋 사람 판단 단계 — DATASET_CREATE와 같음")


@router.get("/jobs/{job_id}/data-health", response_model=S.DataHealthReport, responses=ERR, openapi_extra=XMCP)
def get_data_health(job_id: str, request: Request, _p: Principal = Depends(get_principal)) -> dict:
    """데이터 점검 결과(`report.json`): 요약·지표별 분포·run별 판정(제외 필수·추천·사유). 작업이 DATA_HEALTH가 아니면 404,
    미완료 409 REPORT_NOT_READY, 파일 없음 404 REPORT_MISSING. 크기가 상한을 넘으면 `truncated=true`(score 상위만)."""
    return svc.get_report(get_ctx(request), job_id)
