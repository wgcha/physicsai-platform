"""⑤ 플랫폼 내장 최적화 API(phase3 §18.6 S13). 반복 작업 SURROGATE_OPT는 POST /jobs로 만들 수 없다."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response

from .. import schemas as S
from ..auth import Principal
from ..deps import client_ip, get_ctx, get_principal, request_id
from ..services import surrogate_opts as svc

router = APIRouter(tags=["surrogate-opts"])
ERR = {403: {"model": S.ErrorResponse}, 404: {"model": S.ErrorResponse}, 409: {"model": S.ErrorResponse},
       422: {"model": S.ErrorResponse}}


@router.post("/studies/{study_id}/surrogate-opts/preview", response_model=S.SurrogateOptPreview, responses=ERR)
def preview_surrogate_opt(study_id: str, body: S.SurrogateOptCreate, request: Request,
                          _p: Principal = Depends(get_principal)) -> dict:
    """미리보기(동기, 저장 없음): 자유·정수·고정 변수, 탐색 수, 예측 최대 run·예상 분, problems(생성 때는 422)."""
    return svc.preview(get_ctx(request), study_id, body)


@router.post("/studies/{study_id}/surrogate-opts", response_model=S.SurrogateOpt, status_code=201, responses=ERR)
def create_surrogate_opt(study_id: str, body: S.SurrogateOptCreate, request: Request,
                         principal: Principal = Depends(get_principal)) -> dict:
    """생성(power): 탐색 PREDICT_BATCH(새 DOE) 또는 반복 작업 1(완료 배치 재사용)을 한 트랜잭션에서."""
    return svc.create(get_ctx(request), principal, study_id, body, request_id(request), client_ip(request))


@router.get("/studies/{study_id}/surrogate-opts", response_model=list[S.SurrogateOptSummary], responses=ERR)
def list_surrogate_opts(study_id: str, request: Request, _p: Principal = Depends(get_principal)) -> list:
    return svc.list_opts(get_ctx(request), study_id)


@router.get("/surrogate-opts/{opt_id}", response_model=S.SurrogateOpt, responses=ERR)
def get_surrogate_opt(opt_id: str, request: Request, principal: Principal = Depends(get_principal)) -> dict:
    """상세: 반복별 배치·적합 품질·후보, 검증 run, 최적 설계, 진행 문구."""
    return svc.get_opt(get_ctx(request), principal, opt_id)


@router.get("/surrogate-opts/{opt_id}/runs.csv", response_class=Response,
            responses={**ERR, 200: {"content": {"text/csv": {}}}})
def surrogate_opt_runs_csv(opt_id: str, request: Request, principal: Principal = Depends(get_principal)) -> Response:
    """검증 run CSV(UTF-8 BOM·CRLF): iter,batch,doe_no,run_key,<변수>,objective,<제약>,predicted,feasible,state."""
    body, name = svc.runs_csv(get_ctx(request), principal, opt_id)
    return Response(body, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{name}"', "X-Content-Type-Options": "nosniff"})


@router.post("/surrogate-opts/{opt_id}/cancel", response_model=S.SurrogateOpt, status_code=202, responses=ERR)
def cancel_surrogate_opt(opt_id: str, request: Request, principal: Principal = Depends(get_principal)) -> dict:
    """일괄 취소(power, 등록자 또는 관리자): 반복 작업·배치 부모·비종료 하위 전부, 멱등."""
    return svc.cancel(get_ctx(request), principal, opt_id, request_id(request), client_ip(request))


@router.post("/surrogate-opts/{opt_id}/resume", response_model=S.SurrogateOptResume, status_code=201, responses=ERR)
def resume_surrogate_opt(opt_id: str, request: Request, principal: Principal = Depends(get_principal)) -> dict:
    """이어서 실행(power, FAILED만): 반복 작업 재시도 또는 배치 실패만 다시."""
    return svc.resume(get_ctx(request), principal, opt_id, request_id(request), client_ip(request))
