from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import StreamingResponse

from .. import schemas as S
from ..schemas import predict_runs as PR
from ..auth import Principal
from ..deps import client_ip, get_ctx, get_principal, request_id
from ..services import error_bundle as eb_svc
from ..services import hpc_resolve as resolve_svc
from ..services import job_files as files_svc
from ..services import jobs as svc
from ..services import predict_runs as runs_svc

router = APIRouter(tags=["jobs"])
ERR = {404: {"model": S.ErrorResponse}, 409: {"model": S.ErrorResponse}, 422: {"model": S.ErrorResponse},
       503: {"model": S.ErrorResponse}}


@router.post("/studies/{study_id}/jobs", response_model=S.Job, status_code=201, responses=ERR)
def create_job(study_id: str, body: S.JobCreate, request: Request, principal: Principal = Depends(get_principal)) -> dict:
    return svc.create_job(get_ctx(request), principal, study_id, body.job_type, body.params, request_id(request),
                          client_ip(request))


@router.get("/jobs", response_model=list[S.JobSummary])
def list_jobs(request: Request, response: Response, study_id: str | None = None, state: str | None = None,
              mine: bool = False, job_type: str | None = None, limit: int | None = Query(default=None, ge=1, le=200),
              cursor: str | None = None, principal: Principal = Depends(get_principal)) -> list:
    items, nxt = svc.list_jobs(get_ctx(request), principal, study_id=study_id, state=state, mine=mine,
                               job_type=job_type, limit=limit, cursor=cursor)
    if nxt:
        response.headers["X-Next-Cursor"] = nxt
    return items


@router.get("/jobs/{job_id}", response_model=S.Job, responses={**ERR, 304: {"description": "변경 없음"}})
def get_job(job_id: str, request: Request, response: Response, include: str | None = None,
            principal: Principal = Depends(get_principal)):
    ctx = get_ctx(request)
    include_commands = include == "commands"
    if not include_commands:
        etag = svc.job_etag(ctx, job_id)
        if etag and request.headers.get("if-none-match") == etag:
            return Response(status_code=304, headers={"ETag": etag})
    detail, etag = svc.get_job(ctx, principal, job_id, include_commands)
    response.headers["ETag"] = etag
    return detail


@router.get("/jobs/{job_id}/log", response_model=S.LogChunk, responses=ERR)
def job_log(job_id: str, request: Request, cursor: int = Query(default=0, ge=0),
            limit: int = Query(default=65536, ge=1, le=262144), _p: Principal = Depends(get_principal)) -> dict:
    return svc.read_log(get_ctx(request), job_id, None, cursor, limit)


@router.get("/jobs/{job_id}/steps/{step_no}/log", response_model=S.LogChunk, responses=ERR)
def step_log(job_id: str, step_no: int, request: Request, cursor: int = Query(default=0, ge=0),
             limit: int = Query(default=65536, ge=1, le=262144), _p: Principal = Depends(get_principal)) -> dict:
    return svc.read_log(get_ctx(request), job_id, step_no, cursor, limit)


@router.post("/jobs/{job_id}/cancel", response_model=S.Job, status_code=202, responses=ERR)
def cancel(job_id: str, request: Request, principal: Principal = Depends(get_principal)) -> dict:
    return svc.cancel_job(get_ctx(request), principal, job_id, request_id(request), client_ip(request))


@router.post("/jobs/{job_id}/retry", response_model=S.Job, status_code=201, responses=ERR)
def retry(job_id: str, request: Request, body: S.RetryRequest | None = None, principal: Principal = Depends(get_principal)) -> dict:
    return svc.retry_job(get_ctx(request), principal, job_id, body.from_step if body else None, request_id(request),
                         client_ip(request))


@router.get("/jobs/{job_id}/hpc-jobs", response_model=list[S.HpcJob], responses=ERR)
def hpc_jobs(job_id: str, request: Request, _p: Principal = Depends(get_principal)) -> list:
    return files_svc.list_hpc_jobs(get_ctx(request), job_id)


@router.post("/jobs/{job_id}/hpc-jobs/{hpc_job_id}/resolve", response_model=S.HpcJob, status_code=202,
             responses={**ERR, 403: {"model": S.ErrorResponse}})
def resolve_hpc_job(job_id: str, hpc_job_id: str, body: S.HpcResolveRequest, request: Request,
                    principal: Principal = Depends(get_principal)) -> dict:
    """SCX 제출 결과 모름 조치(phase3 §16.5) — recheck(같은 request_id로 다시 확인)·attach(SCX에서 찾은 잡 ID 연결)·
    mark_not_submitted(제출 안 됨 확인 → 행 실패). 요청만 기록하고 워커가 다음 폴링에서 처리한다(202, resolve_pending=true).
    주의: SCX에 잡이 실제로 있는데 '제출 안 됨'으로 표시하면 같은 해석이 두 번 돌 수 있습니다(폴더는 따로)."""
    return resolve_svc.request_resolve(get_ctx(request), principal, job_id, hpc_job_id, body.action, body.external_job_id,
                                       body.version, request_id(request), client_ip(request))


@router.get(
    "/jobs/{job_id}/error-bundle.zip",
    response_class=StreamingResponse,
    responses={403: {"model": S.ErrorResponse}, 404: {"model": S.ErrorResponse}, 409: {"model": S.ErrorResponse},
               200: {"content": {"application/zip": {}}}},
)
def error_bundle(job_id: str, request: Request, principal: Principal = Depends(get_principal)) -> StreamingResponse:
    """오류 묶음(phase2 §10): 작업 등록자 본인 또는 전역 관리자. 실패·취소·중단 또는 주의 코드가 있는 비종료 작업."""
    body, name = eb_svc.build(get_ctx(request), principal, job_id, request_id(request), client_ip(request))
    return StreamingResponse(body, media_type="application/zip",
                             headers={"Content-Disposition": f'attachment; filename="{name}"', "X-Content-Type-Options": "nosniff"})


# ---- ④ 단일 예측 실행 목록(phase3 §21.2 S16 V1) ----------------------------------------------------


@router.get("/studies/{study_id}/predict-runs", response_model=list[PR.PredictRunSummary], responses=ERR)
def list_predict_runs(study_id: str, request: Request, response: Response, mode: str | None = None,
                      state: str | None = None, limit: int | None = Query(default=None, ge=1, le=200),
                      cursor: str | None = None, principal: Principal = Depends(get_principal)) -> list:
    """그 Study의 단일 예측(일괄 하위 제외, 재시도 묶음은 최신 1행). mode = all | template | prepared,
    state = 쉼표 구분 작업 상태. 다음 페이지가 있으면 헤더 X-Next-Cursor."""
    items, nxt = runs_svc.list_runs(get_ctx(request), principal, study_id, mode=mode, state=state, limit=limit, cursor=cursor)
    if nxt:
        response.headers["X-Next-Cursor"] = nxt
    return items


@router.get("/predict-runs/{job_id}", response_model=PR.PredictRunDetail, responses=ERR)
def get_predict_run(job_id: str, request: Request, principal: Principal = Depends(get_principal)) -> dict:
    """단일 예측 상세: 목록 행 + 최근접·응답 표·경로(없으면 null)·표시 설정. 일괄 하위·다른 유형은 404 NOT_PREDICT_RUN."""
    return runs_svc.get_run(get_ctx(request), principal, job_id)
