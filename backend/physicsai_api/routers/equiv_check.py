"""⑤ 해석 등가성 판정(equiv-check.md §6): 레시피 CRUD·판정 미리보기/실행·이력·상세·곡선·표·메모."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request, Response

from .. import schemas as S
from ..auth import Principal
from ..deps import client_ip, get_ctx, get_principal, request_id
from ..schemas import equiv_check as EQ
from ..services import equiv_check as svc
from ..services import equiv_recipes as rec

router = APIRouter(tags=["equiv_check"])
ERR = {403: {"model": S.ErrorResponse}, 404: {"model": S.ErrorResponse}, 409: {"model": S.ErrorResponse}, 422: {"model": S.ErrorResponse}}
NO_STORE = {"Cache-Control": "no-store"}


# ---- 레시피 -------------------------------------------------------------------------------------------


@router.get("/equiv/recipes", response_model=list[EQ.EqRecipeListItem], responses=ERR)
def list_equiv_recipes(request: Request, study_id: str | None = Query(default=None, max_length=64),
                       principal: Principal = Depends(get_principal)) -> list:
    """시스템 기본(`sys:default`, 읽기 전용 제안값) + 전역 + 그 Study 레시피의 최신 활성 버전."""
    return rec.list_(get_ctx(request), principal, study_id)


@router.get("/equiv/recipes/{key}", response_model=EQ.EqRecipe, responses=ERR)
def get_equiv_recipe(key: str, request: Request, version: int | None = Query(default=None, ge=1),
                     principal: Principal = Depends(get_principal)) -> dict:
    """정의(삭제된 key도 이력용으로 조회 가능 — deleted: true)."""
    return rec.get(get_ctx(request), principal, key, version)


@router.get("/equiv/recipes/{key}/versions", response_model=EQ.EqRecipe, responses=ERR)
def equiv_recipe_versions(key: str, request: Request, principal: Principal = Depends(get_principal)) -> dict:
    return rec.get(get_ctx(request), principal, key, None, with_versions=True)


@router.post("/equiv/recipes", response_model=EQ.EqRecipe, status_code=201, responses=ERR)
def create_equiv_recipe(body: EQ.EqRecipeCreate, request: Request, principal: Principal = Depends(get_principal)) -> dict:
    """생성(power): definition | clone_from{key, version} | from_check(이력 스냅숏 복제) → version 1."""
    return rec.create(get_ctx(request), principal, body, request_id(request), client_ip(request))


@router.put("/equiv/recipes/{key}", response_model=EQ.EqRecipe, responses=ERR)
def update_equiv_recipe(key: str, body: EQ.EqRecipeUpdate, request: Request, principal: Principal = Depends(get_principal)) -> dict:
    """편집 = 새 버전(base_version이 최신과 다르면 409 EQ_RECIPE_VERSION_CONFLICT). 시스템 기본은 409 EQ_RECIPE_READONLY."""
    return rec.update(get_ctx(request), principal, key, body, request_id(request), client_ip(request))


@router.delete("/equiv/recipes/{key}", status_code=204, responses=ERR)
def delete_equiv_recipe(key: str, request: Request, principal: Principal = Depends(get_principal)) -> Response:
    """소프트 삭제(key 단위, 멱등). 이력 스냅숏·참조는 그대로."""
    rec.delete(get_ctx(request), principal, key, request_id(request), client_ip(request))
    return Response(status_code=204)


@router.post("/equiv/recipes/{key}/restore", response_model=EQ.EqRecipe, responses=ERR)
def restore_equiv_recipe(key: str, request: Request, principal: Principal = Depends(get_principal)) -> dict:
    """되살리기(관리자, 멱등)."""
    return rec.restore(get_ctx(request), principal, key, request_id(request), client_ip(request))


# ---- 판정 -------------------------------------------------------------------------------------------


@router.post("/studies/{study_id}/equiv-checks/preview", response_model=EQ.EqPreview, responses=ERR)
def preview_equiv_check(study_id: str, body: EQ.EqCheckCreate, request: Request, principal: Principal = Depends(get_principal)) -> dict:
    """미리보기(DB 쓰기 없음): 쌍 매칭·binding 해석·추출 필요 수·사본 예상 바이트·problems."""
    return svc.preview(get_ctx(request), principal, study_id, body)


@router.post("/studies/{study_id}/equiv-checks", response_model=EQ.EqCheckCreated, status_code=202, responses=ERR)
def create_equiv_check(study_id: str, body: EQ.EqCheckCreate, request: Request, principal: Principal = Depends(get_principal)) -> dict:
    """실행(power): 이력 행 + EQ_CHECK 작업. 필수 지표 미연결 422 METRIC_UNBOUND, 활성 상한 409 EQ_CHECK_LIMIT."""
    return svc.create(get_ctx(request), principal, study_id, body, request_id(request), client_ip(request))


@router.get("/studies/{study_id}/equiv-checks", response_model=list[EQ.EqCheckListItem], responses=ERR)
def list_equiv_checks(study_id: str, request: Request, response: Response, side_kind: str | None = Query(default=None, max_length=16),
                      side_ref: str | None = Query(default=None, max_length=64), verdict: str | None = Query(default=None, max_length=12),
                      recipe_key: str | None = Query(default=None, max_length=64), limit: int | None = Query(default=None, ge=1, le=200),
                      cursor: str | None = None, principal: Principal = Depends(get_principal)) -> list:
    """이력 목록(최신순). 다음 페이지가 있으면 헤더 X-Next-Cursor."""
    items, nxt = svc.list_(get_ctx(request), principal, study_id, side_kind=side_kind, side_ref=side_ref, verdict=verdict,
                           recipe_key=recipe_key, limit=limit, cursor=cursor)
    if nxt:
        response.headers["X-Next-Cursor"] = nxt
    return items


@router.get("/equiv-checks/{eq_id}", response_model=EQ.EqCheck, responses=ERR)
def get_equiv_check(eq_id: str, request: Request, response: Response, principal: Principal = Depends(get_principal)) -> dict:
    """행 + 스냅숏 + metrics.csv 요약 표(파일 읽기, no-store)."""
    response.headers.update(NO_STORE)
    return svc.detail(get_ctx(request), principal, eq_id)


@router.get("/equiv-checks/{eq_id}/curves", response_model=EQ.EqCurves, responses=ERR)
def equiv_check_curves(eq_id: str, request: Request, response: Response, pair: int = Query(ge=1), metric: str = Query(max_length=32),
                       max_points: int = Query(default=1000, ge=2, le=5000), principal: Principal = Depends(get_principal)) -> dict:
    response.headers.update(NO_STORE)
    return svc.curves(get_ctx(request), principal, eq_id, pair, metric, max_points)


@router.get("/equiv-checks/{eq_id}/table.csv", response_class=Response, responses={**ERR, 200: {"content": {"text/csv": {}}}})
def equiv_check_table_csv(eq_id: str, request: Request, principal: Principal = Depends(get_principal)) -> Response:
    """원표(UTF-8 BOM): pair_no,a_run,b_run,metric_id,a,b,diff,rel_pct,corr,status,reason."""
    body, name = svc.table_csv(get_ctx(request), principal, eq_id)
    return Response(body, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{name}"', "X-Content-Type-Options": "nosniff", **NO_STORE})


@router.patch("/equiv-checks/{eq_id}", response_model=EQ.EqCheckListItem, responses=ERR)
def patch_equiv_check(eq_id: str, body: EQ.EqNotePatch, request: Request, principal: Principal = Depends(get_principal)) -> dict:
    """메모(note)만 사후 수정 가능(작성자·관리자)."""
    return svc.patch_note(get_ctx(request), principal, eq_id, body, request_id(request), client_ip(request))
