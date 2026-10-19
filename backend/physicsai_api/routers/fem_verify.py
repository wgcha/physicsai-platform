"""④ 조립 FEM 검증(phase3 §21.3.8 S16): 미리보기·생성·목록·상세·컨투어·커브·표·취소·다시 실행."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request, Response

from .. import schemas as S
from ..auth import Principal
from ..deps import client_ip, get_ctx, get_principal, request_id
from ..schemas import fem_verify as FV
from ..services import fem_verify as svc

router = APIRouter(tags=["fem_verify"])
ERR = {403: {"model": S.ErrorResponse}, 404: {"model": S.ErrorResponse}, 409: {"model": S.ErrorResponse},
       422: {"model": S.ErrorResponse}}


@router.post("/studies/{study_id}/fem-verifications/preview", response_model=FV.FvPreview, responses=ERR)
def preview_fem_verification(study_id: str, body: FV.FemVerifyCreate, request: Request,
                             principal: Principal = Depends(get_principal)) -> dict:
    """미리보기(저장 없음, power): 출처 해석·조립 원본 검사·FEM 필드·문제/경고. 409 HPC_NOT_CONFIGURED·TEMPLATE_NOT_CONFIGURED 등."""
    return svc.preview(get_ctx(request), principal, study_id, body)


@router.post("/studies/{study_id}/fem-verifications", response_model=FV.FemVerification, status_code=201, responses=ERR)
def create_fem_verification(study_id: str, body: FV.FemVerifyCreate, request: Request,
                            principal: Principal = Depends(get_principal)) -> dict:
    """생성(power): 같은 설계점의 성공한 예측이 없으면 동반 예측(WAITING_PREDICT), 있으면 FEM_VERIFY(RUNNING)."""
    return svc.create(get_ctx(request), principal, study_id, body, request_id(request), client_ip(request))


@router.get("/studies/{study_id}/fem-verifications", response_model=list[FV.FemVerifyListItem], responses=ERR)
def list_fem_verifications(study_id: str, request: Request, response: Response, predict_job_id: str | None = None,
                           batch_id: str | None = None, opt_id: str | None = None, status: str | None = None,
                           limit: int | None = Query(default=None, ge=1, le=200), cursor: str | None = None,
                           principal: Principal = Depends(get_principal)) -> list:
    """목록(최신순). 다음 페이지가 있으면 헤더 X-Next-Cursor."""
    items, nxt = svc.list_(get_ctx(request), principal, study_id, predict_job_id=predict_job_id, batch_id=batch_id,
                           opt_id=opt_id, status=status, limit=limit, cursor=cursor)
    if nxt:
        response.headers["X-Next-Cursor"] = nxt
    return items


@router.get("/fem-verifications/{fid}", response_model=FV.FemVerification, responses=ERR)
def get_fem_verification(fid: str, request: Request, principal: Principal = Depends(get_principal)) -> dict:
    return svc.detail(get_ctx(request), principal, fid)


@router.get("/fem-verifications/{fid}/media", response_model=FV.FvMedia, responses=ERR)
def fem_verification_media(fid: str, request: Request, principal: Principal = Depends(get_principal)) -> dict:
    """컨투어 두 쪽(예측·FEM, 같은 범례). MediaFile = §15.4 + S16 playable·codec·transcoded."""
    return svc.media(get_ctx(request), principal, fid)


@router.get("/fem-verifications/{fid}/curves", response_model=FV.FvCurves, responses=ERR)
def fem_verification_curves(fid: str, request: Request, name: str | None = Query(default=None, max_length=400),
                            max_points: int = Query(default=500, ge=2, le=5000),
                            principal: Principal = Depends(get_principal)) -> dict:
    return svc.curves(get_ctx(request), principal, fid, name, max_points)


@router.get("/fem-verifications/{fid}/table.csv", response_class=Response,
            responses={**ERR, 200: {"content": {"text/csv": {}}}})
def fem_verification_table_csv(fid: str, request: Request, principal: Principal = Depends(get_principal)) -> Response:
    """응답 비교 표 CSV(UTF-8 BOM): name,unit,stat,pred_min,pred_max,fem_min,fem_max,pred_value,fem_value,diff,diff_pct."""
    body, name = svc.table_csv(get_ctx(request), principal, fid)
    return Response(body, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{name}"', "X-Content-Type-Options": "nosniff"})


@router.post("/fem-verifications/{fid}/cancel", response_model=FV.FemVerification, status_code=202, responses=ERR)
def cancel_fem_verification(fid: str, request: Request, principal: Principal = Depends(get_principal)) -> dict:
    """취소(power, 등록자·관리자, 멱등): 예측 대기 중이면 동반 예측, 해석 중이면 FEM_VERIFY를 취소한다."""
    return svc.cancel(get_ctx(request), principal, fid, request_id(request), client_ip(request))


@router.post("/fem-verifications/{fid}/rerun", response_model=FV.FemVerification, status_code=201, responses=ERR)
def rerun_fem_verification(fid: str, request: Request, principal: Principal = Depends(get_principal)) -> dict:
    """다시 실행(FAILED·CANCELED만, 아니면 409 FEM_VERIFY_NOT_RERUNNABLE)."""
    return svc.rerun(get_ctx(request), principal, fid, request_id(request), client_ip(request))
