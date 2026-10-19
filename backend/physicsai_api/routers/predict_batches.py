"""④ 일괄 예측(DOE) API(phase3 §14.7 S9). 생성은 POST /studies/{id}/jobs(job_type PREDICT_BATCH)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response

from .. import schemas as S
from ..auth import Principal
from ..deps import client_ip, get_ctx, get_principal, request_id
from ..services import design_map as dm_svc
from ..services import predict_batches as svc

router = APIRouter(tags=["predict-batches"])
ERR = {403: {"model": S.ErrorResponse}, 404: {"model": S.ErrorResponse}, 409: {"model": S.ErrorResponse},
       422: {"model": S.ErrorResponse}}


@router.post("/studies/{study_id}/predict-batches/preview", response_model=S.PredictBatchPreview, responses=ERR)
def preview_batch(study_id: str, body: S.PredictBatchPreviewRequest, request: Request,
                  _p: Principal = Depends(get_principal)) -> dict:
    """조합 미리보기(동기, 워커 없음). 조합 문제는 200 `problems`(작업 생성 때는 422 BATCH_SOURCE_INVALID)."""
    return svc.preview(get_ctx(request), study_id, body)


@router.get("/studies/{study_id}/predict-batches", response_model=list[S.PredictBatchSummary], responses=ERR)
def list_batches(study_id: str, request: Request, _p: Principal = Depends(get_principal)) -> list:
    return svc.list_batches(get_ctx(request), study_id)


@router.get("/predict-batches/{batch_id}", response_model=S.PredictBatch, responses=ERR)
def get_batch(batch_id: str, request: Request, principal: Principal = Depends(get_principal)) -> dict:
    """배치 상세: 행마다 DOE #·run_key·폴더·값·응답·상태·하위 작업 id."""
    return svc.get_batch(get_ctx(request), principal, batch_id)


@router.get("/predict-batches/{batch_id}/table.csv", response_class=Response,
            responses={**ERR, 200: {"content": {"text/csv": {}}}})
def batch_table_csv(batch_id: str, request: Request, principal: Principal = Depends(get_principal)) -> Response:
    """결과 표 CSV(UTF-8 BOM): doe_no,run_key,folder,<파라미터>,<응답>,state."""
    body, name = svc.table_csv(get_ctx(request), principal, batch_id)
    return Response(body, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{name}"', "X-Content-Type-Options": "nosniff"})


@router.get("/predict-batches/{batch_id}/curves", response_model=S.BatchCurves, responses=ERR)
def batch_curves(batch_id: str, request: Request, name: str | None = Query(default=None, max_length=400),
                 max_points: int = Query(default=500, ge=2, le=2000), _p: Principal = Depends(get_principal)) -> dict:
    """커브 겹쳐보기: 완료 run의 같은 이름 계열(run ≤ predict_batch.curve_max_runs, 점 ≤ max_points, 최소·최대 보존)."""
    return svc.curves(get_ctx(request), batch_id, name, max_points)


@router.get("/predict-batches/{batch_id}/design-map", response_model=S.DesignMap, responses=ERR)
def batch_design_map(batch_id: str, request: Request, response: Response, _p: Principal = Depends(get_principal)) -> dict:
    """설계공간 지도(§17.4 S12): run별 반영값 + 대표값(커브 계열별 max·min·|max|, RESP, 결과 표). 파일별 캐시."""
    response.headers["Cache-Control"] = "no-store"
    return dm_svc.design_map(get_ctx(request), batch_id)


@router.post("/predict-batches/{batch_id}/cancel", response_model=S.PredictBatch, status_code=202, responses=ERR)
def cancel_batch(batch_id: str, request: Request, principal: Principal = Depends(get_principal)) -> dict:
    """일괄 취소(power, 등록자 또는 관리자): 부모·비종료 하위 전부, 멱등."""
    return svc.cancel_batch(get_ctx(request), principal, batch_id, request_id(request), client_ip(request))


@router.post("/predict-batches/{batch_id}/retry-failed", response_model=S.BatchRetryFailed, status_code=201,
             responses=ERR)
def retry_failed_batch(batch_id: str, request: Request, principal: Principal = Depends(get_principal)) -> dict:
    """실패만 다시(power): 생성 실패 run → 부모 새 작업, 실패·취소·중단 하위 → 기존 재시도."""
    return svc.retry_failed(get_ctx(request), principal, batch_id, request_id(request), client_ip(request))


@router.post("/predict-batches/{batch_id}/extract-responses", response_model=S.Job, status_code=201, responses=ERR)
def extract_batch_responses(batch_id: str, request: Request, principal: Principal = Depends(get_principal)) -> dict:
    """성능 다시 추출(power, phase3 §22.3.5): 끝난 배치의 H3D 성능을 현재 템플릿 정의로 다시 추출하는 PB_RESP_EXTRACT 작업."""
    return svc.extract_responses(get_ctx(request), principal, batch_id, request_id(request), client_ip(request))
