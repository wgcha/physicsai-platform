"""형상 3D 보기·미리보기·결과 3D 컨투어 API(geometry-view.md §6.5·§13.5). GLB·manifest는 `/artifacts/{id}/media`·`/content`."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from .. import schemas as S
from ..auth import Principal
from ..deps import client_ip, get_ctx, get_principal, request_id
from ..services import contour3d_api as c3_svc
from ..services import geom_view_api as svc

router = APIRouter(tags=["geom-view"])
ERR = {403: {"model": S.ErrorResponse}, 404: {"model": S.ErrorResponse}, 409: {"model": S.ErrorResponse},
       422: {"model": S.ErrorResponse}, 429: {"model": S.ErrorResponse}}


@router.get("/param-sets/{ps_id}/view", response_model=S.GeomView, responses=ERR)
def param_set_view(ps_id: str, request: Request, _p: Principal = Depends(get_principal)) -> dict:
    """공칭 3D 뷰(NP_VIEW 결과): status READY면 GLB(`/artifacts/{glb_artifact_id}/media`)·manifest(`/content`). altair 세트 409 VIEW_NATIVE_ONLY."""
    return svc.get_view(get_ctx(request), ps_id)


@router.post("/param-sets/{ps_id}/previews", response_model=S.GeomPreview,
             responses={**ERR, 202: {"model": S.GeomPreview, "description": "QUEUED·RUNNING — GET /previews/{id}로 폴링"}})
def create_preview(ps_id: str, body: S.GeomPreviewCreate, request: Request, principal: Principal = Depends(get_principal)) -> dict:
    """형상 미리보기(power): 캐시 적중 200(cache_hit) | 202 GEOM_PREVIEW(레인 PREVIEW, DOE 중에도 실행). 429 PREVIEW_BUSY."""
    out, status = svc.create_preview(get_ctx(request), principal, ps_id, body, request_id(request), client_ip(request))
    if status == 202:
        return JSONResponse(S.GeomPreview.model_validate(out).model_dump(mode="json"), status_code=202)  # type: ignore[return-value]
    return out


@router.get("/previews/{preview_id}", response_model=S.GeomPreview, responses=ERR)
def get_preview(preview_id: str, request: Request, _p: Principal = Depends(get_principal)) -> dict:
    """미리보기 상태·결과(화면은 실행 중 0.5초 간격 폴링, 종료 상태에서 멈춤)."""
    return svc.get_preview(get_ctx(request), preview_id)


@router.get("/studies/{study_id}/train/view", response_model=S.GeomView, responses=ERR)
def train_view(study_id: str, request: Request, _p: Principal = Depends(get_principal)) -> dict:
    """①-1·①-2 공칭 3D 뷰(TX_VIEW 결과, 미리보기 없음 — preview_available=false). 학습 설정 없음 404."""
    return svc.train_view(get_ctx(request), study_id)


@router.post("/contour3d", response_model=S.Contour3d,
             responses={**ERR, 202: {"model": S.Contour3d, "description": "생성 중 — progress(대기 안내)·GET /contour3d/{id} 폴링"}})
def create_contour3d(body: S.Contour3dCreate, request: Request, principal: Principal = Depends(get_principal)) -> dict:
    """결과 3D 컨투어(열 때 생성): 캐시 적중 200·진행 중 202는 로그인 사용자(member), 새 생성(202 CONTOUR_3D)은 power(403). 409 CONTOUR3D_NOT_CONFIGURED·PREREQUISITE_MISSING."""
    out, status = c3_svc.create(get_ctx(request), principal, body, request_id(request), client_ip(request))
    if status == 202:
        return JSONResponse(S.Contour3d.model_validate(out).model_dump(mode="json"), status_code=202)  # type: ignore[return-value]
    return out


@router.get("/contour3d/{contour_id}", response_model=S.Contour3d, responses=ERR)
def get_contour3d(contour_id: str, request: Request, _p: Principal = Depends(get_principal)) -> dict:
    """3D 컨투어 상태·진행 단계(대기·H3D 읽기·형상·프레임 변환·완료·실패)·예상 시간·결과 산출물 id."""
    return c3_svc.get(get_ctx(request), contour_id)


@router.post("/contour3d/{contour_id}/cancel", response_model=S.Contour3d, responses=ERR)
def cancel_contour3d(contour_id: str, request: Request, principal: Principal = Depends(get_principal)) -> dict:
    """대기 안내 화면 [취소](power): 작업 취소 → CANCELED(캐시 안 함). 끝난 생성은 409 JOB_TERMINAL."""
    return c3_svc.cancel(get_ctx(request), principal, contour_id, request_id(request), client_ip(request))
