"""브라우저 분할 업로드(upload-report.md §4) — 허용된 유일한 업로드 경로. 청크 PUT octet-stream(폼·파일 파트 없음).

전부 `x-mcp.exclude`(LLM 클라이언트는 파일을 올리지 않음 — API 토큰 요청은 403), 인증은 대시보드 쿠키 + CSRF 헤더.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Header, Query, Request
from starlette.concurrency import run_in_threadpool

from physicsai_core.errors import DomainError

from .. import schemas as S
from ..auth import Principal
from ..deps import client_ip, get_ctx, get_principal, request_id
from ..schemas import mcp as M
from ..services import upload_chunks, upload_complete
from ..services import uploads as svc

router = APIRouter(tags=["uploads"])
ERR = {403: {"model": S.ErrorResponse}, 404: {"model": S.ErrorResponse}, 409: {"model": S.ErrorResponse},
       413: {"model": S.ErrorResponse}, 422: {"model": S.ErrorResponse}, 429: {"model": S.ErrorResponse},
       503: {"model": S.ErrorResponse}, 507: {"model": S.ErrorResponse}}
XMCP = M.xmcp_exclude("웹 파일 업로드")
OCTET = "application/octet-stream"
CHUNK_BODY = {"requestBody": {"required": True, "content": {OCTET: {"schema": {"type": "string", "format": "binary"}}}}}
CHUNK_XMCP = {**CHUNK_BODY, **XMCP}


@router.get("/uploads/config", response_model=S.UploadConfig, responses=ERR, openapi_extra=XMCP)
def upload_config(request: Request, _p: Principal = Depends(get_principal)) -> dict:
    """업로드 설정: 청크 크기·상한·purpose별 허용 패턴·항상 거부 목록·여유 공간. 프런트가 미리 검사에 쓴다."""
    return svc.config_out(get_ctx(request))


@router.post("/studies/{study_id}/uploads", response_model=S.UploadOut, status_code=201, responses=ERR, openapi_extra=XMCP)
def create_upload(study_id: str, body: S.UploadCreate, request: Request, principal: Principal = Depends(get_principal)) -> dict:
    """업로드 세션 생성(이름·패턴·크기·디스크 사전 검사, 폴더 <upload_root>/<사용자>/<UTC>_<이름>/ 생성). 해당 Study 프로젝트 power 이상."""
    return svc.create_upload(get_ctx(request), principal, study_id, body, request_id(request), client_ip(request))


@router.get("/studies/{study_id}/uploads", response_model=list[S.UploadOut], responses=ERR, openapi_extra=XMCP)
def list_uploads(study_id: str, request: Request, state: Literal["OPEN", "COMPLETED", "CANCELED", "STALE"] | None = None,
                 mine: bool = True, principal: Principal = Depends(get_principal)) -> list:
    """Study의 업로드 최근 50개(이어 올리기·출처 보기). mine=false(남의 세션 포함)는 전역 관리자만."""
    return svc.list_uploads(get_ctx(request), principal, study_id, state, mine)


@router.get("/uploads/{upload_id}", response_model=S.UploadOut, responses=ERR, openapi_extra=XMCP)
def get_upload(upload_id: str, request: Request, principal: Principal = Depends(get_principal)) -> dict:
    """파일별 received(서버가 받은 크기 — 이어 올리기 offset)·done·sha256. 본인 또는 전역 관리자."""
    return svc.get_upload(get_ctx(request), principal, upload_id)


@router.post("/uploads/{upload_id}/files", response_model=S.UploadOut, responses=ERR, openapi_extra=XMCP)
def add_files(upload_id: str, body: S.UploadAddFiles, request: Request, principal: Principal = Depends(get_principal)) -> dict:
    """OPEN 세션에 파일 추가(complete가 알려 준 누락분). 새 파일 index는 기존 뒤에 붙는다. 같은 검사."""
    return svc.add_files(get_ctx(request), principal, upload_id, body)


@router.put("/uploads/{upload_id}/files/{index}", response_model=S.UploadChunkOut, responses=ERR, openapi_extra=CHUNK_XMCP)
async def put_chunk(upload_id: str, index: int, request: Request, offset: int = Query(ge=0),
                    x_chunk_sha256: str | None = Header(default=None, pattern=r"^[0-9a-fA-F]{64}$"),
                    principal: Principal = Depends(get_principal)) -> dict:
    """청크(application/octet-stream, ≤ chunk_size). offset은 서버가 받은 크기와 같아야 한다(409 + received).
    헤더 X-Chunk-Sha256(청크 sha256)이 있으면 검증(다르면 422, 쓰지 않음). 파일 전체 sha256은 서버가 받으며 계산해 기록."""
    ctx = get_ctx(request)
    ctype = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if ctype != OCTET:
        raise DomainError("UNSUPPORTED_MEDIA_TYPE", f"Content-Type은 {OCTET} 이어야 합니다", status=415)
    limit = ctx.settings.upload.chunk_bytes
    try:
        declared = int(request.headers.get("content-length", "-1"))
    except ValueError:
        declared = -1
    if declared > limit:
        raise DomainError("CHUNK_TOO_LARGE", f"청크가 chunk_size({limit} B)보다 큽니다", status=413, limit=limit)
    buf = bytearray()
    async for part in request.stream():
        buf += part
        if len(buf) > limit:
            raise DomainError("CHUNK_TOO_LARGE", f"청크가 chunk_size({limit} B)보다 큽니다", status=413, limit=limit)
    return await run_in_threadpool(upload_chunks.put_chunk, ctx, principal, upload_id, index, offset, bytes(buf), x_chunk_sha256)


@router.post("/uploads/{upload_id}/complete", response_model=S.UploadCompleteOut, responses=ERR, openapi_extra=XMCP)
def complete_upload(upload_id: str, request: Request, principal: Principal = Depends(get_principal)) -> dict:
    """모든 파일이 done이면 해당 purpose의 기존 paths/inspect를 서버가 호출. ok=true면 COMPLETED, ok=false면 OPEN 유지."""
    return upload_complete.complete(get_ctx(request), principal, upload_id, request_id(request), client_ip(request))


@router.delete("/uploads/{upload_id}", response_model=S.UploadOut, responses=ERR, openapi_extra=XMCP)
def cancel_upload(upload_id: str, request: Request, principal: Principal = Depends(get_principal)) -> dict:
    """OPEN 세션 취소 — 폴더를 <upload_root>/_backup/<사용자>/<폴더명>으로 이동(삭제 없음). COMPLETED는 409 UPLOAD_CLOSED."""
    return svc.cancel(get_ctx(request), principal, upload_id, request_id(request), client_ip(request))


@router.post("/admin/uploads/cleanup-stale", response_model=S.UploadCleanupOut, responses=ERR, openapi_extra=XMCP)
def cleanup_stale_uploads(request: Request, principal: Principal = Depends(get_principal)) -> dict:
    """전역 관리자: 낡은 OPEN 세션(upload.stale_hours 초과)을 _backup으로 옮기고 STALE로 — 즉시 실행."""
    return svc.cleanup_stale(get_ctx(request), principal)
