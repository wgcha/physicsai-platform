"""DOE 표본 형상 그리드 미리보기 API(doe-preview.md §6.6): 생성·조회·취소. 셀 PNG·GLB·manifest는 `/artifacts/{id}/media`·`/content`.
화면 전용이라 세 operation 모두 `x-mcp.exclude`(사유 "화면 전용 형상 그림 생성")."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from .. import schemas as S
from ..auth import Principal
from ..deps import client_ip, get_ctx, get_principal, request_id
from ..schemas import mcp as M
from ..services import doe_preview_api as svc

router = APIRouter(tags=["doe-preview"])
ERR = {403: {"model": S.ErrorResponse}, 404: {"model": S.ErrorResponse}, 409: {"model": S.ErrorResponse},
       422: {"model": S.ErrorResponse}, 429: {"model": S.ErrorResponse}}
XMCP = M.xmcp_exclude("화면 전용 형상 그림 생성")


@router.post("/studies/{study_id}/doe-previews", response_model=S.DoePreview, openapi_extra=XMCP,
             responses={**ERR, 202: {"model": S.DoePreview, "description": "QUEUED·RUNNING — GET /doe-previews/{id}로 1초 간격 폴링"}})
def create_doe_preview(study_id: str, body: S.DoePreviewReq, request: Request, principal: Principal = Depends(get_principal)) -> dict:
    """DOE 표본 형상 그리드 미리보기(power): 셀이 전부 캐시에 있으면 200(cache_hit, 작업 없음) | 202 DOE_PREVIEW(CPU 대기열).
    409 DOE_PREVIEW_UNSUPPORTED·GEOM_PREP_STALE·DOE_PREVIEW_UNAVAILABLE·STUDY_CLEANUP_RUNNING, 422 DOE_SAMPLING_INVALID, 429 PREVIEW_BUSY."""
    out, status = svc.create(get_ctx(request), principal, study_id, body, request_id(request), client_ip(request))
    if status == 202:
        return JSONResponse(S.DoePreview.model_validate(out).model_dump(mode="json"), status_code=202)  # type: ignore[return-value]
    return out


@router.get("/doe-previews/{preview_id}", response_model=S.DoePreview, responses=ERR, openapi_extra=XMCP)
def get_doe_preview(preview_id: str, request: Request, _p: Principal = Depends(get_principal)) -> dict:
    """미리보기 상태·셀(렌더가 끝난 만큼 채워짐, 화면은 실행 중 1초 간격 폴링·종료 시 멈춤). train_doe는 셀마다 생성 결과(gen)."""
    return svc.get(get_ctx(request), preview_id)


@router.post("/doe-previews/{preview_id}/cancel", response_model=S.DoePreview, status_code=202, responses=ERR, openapi_extra=XMCP)
def cancel_doe_preview(preview_id: str, request: Request, principal: Principal = Depends(get_principal)) -> dict:
    """[취소](요청자·관리자): 작업 취소 플래그 — 완료 청크 셀은 캐시에 남는다. 끝난 미리보기는 409 JOB_TERMINAL."""
    return svc.cancel(get_ctx(request), principal, preview_id, request_id(request), client_ip(request))
