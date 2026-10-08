from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse, StreamingResponse

from .. import schemas as S
from ..auth import Principal
from ..deps import get_ctx, get_principal
from ..services import jobs as svc

router = APIRouter(tags=["artifacts"])


@router.get("/jobs/{job_id}/artifacts", response_model=list[S.Artifact], responses={404: {"model": S.ErrorResponse}})
def list_artifacts(job_id: str, request: Request, _p: Principal = Depends(get_principal)) -> list:
    return svc.list_artifacts(get_ctx(request), job_id)


@router.get(
    "/jobs/{job_id}/artifacts/input.zip",
    response_class=StreamingResponse,
    responses={404: {"model": S.ErrorResponse}, 409: {"model": S.ErrorResponse}, 200: {"content": {"application/zip": {}}}},
)
def input_zip(job_id: str, request: Request, _p: Principal = Depends(get_principal)) -> StreamingResponse:
    """④ 예측 입력 파일(INPUT/*.rad·*.inc) zip 스트리밍. RAD_ASSEMBLE 완료 전·PREDICT 외 작업은 409 INPUT_NOT_READY."""
    body, name = svc.input_zip(get_ctx(request), job_id)
    return StreamingResponse(body, media_type="application/zip",
                             headers={"Content-Disposition": f'attachment; filename="{name}"', "X-Content-Type-Options": "nosniff"})


@router.get(
    "/artifacts/{artifact_id}/content",
    response_class=FileResponse,
    responses={404: {"model": S.ErrorResponse}, 200: {"content": {"application/octet-stream": {}}}},
)
def content(artifact_id: str, request: Request, _p: Principal = Depends(get_principal)) -> FileResponse:
    path, ctype, name = svc.artifact_file(get_ctx(request), artifact_id)
    return FileResponse(path, media_type=ctype, filename=name, headers={"X-Content-Type-Options": "nosniff"})
