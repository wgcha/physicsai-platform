"""API 토큰 관리(mcp.md §4.4) — 세션 전용(토큰 요청 403 SESSION_REQUIRED). mcp.enabled=false면 404 MCP_DISABLED."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request, Response

from .. import schemas as S
from ..auth import Principal
from ..deps import client_ip, get_ctx, get_principal, request_id
from ..schemas import mcp as M
from ..services import api_tokens as svc

router = APIRouter(tags=["api-tokens"])
ERR = {403: {"model": S.ErrorResponse}, 404: {"model": S.ErrorResponse}, 409: {"model": S.ErrorResponse},
       422: {"model": S.ErrorResponse}}
SESSION_ONLY = M.xmcp_exclude("토큰 관리(세션 전용)", session_only=True)


@router.get("/me/api-tokens", response_model=list[M.ApiToken], responses=ERR, openapi_extra=SESSION_ONLY)
def list_my_api_tokens(request: Request, principal: Principal = Depends(get_principal)) -> list:
    """내 API 토큰(최신순, 폐기 포함 최근 90일). 평문·해시는 돌려주지 않는다."""
    return svc.list_mine(get_ctx(request), principal)


@router.post("/me/api-tokens", response_model=M.ApiTokenCreated, status_code=201, responses=ERR, openapi_extra=SESSION_ONLY)
def create_my_api_token(body: M.ApiTokenCreate, request: Request, principal: Principal = Depends(get_principal)) -> dict:
    """API 토큰 발급. 평문 `token`은 이 응답에서 한 번만 — 다시 볼 수 없다. 403 API_TOKEN_SCOPE, 409 API_TOKEN_LIMIT·API_TOKEN_NAME_EXISTS,
    422 API_TOKEN_EXPIRY_TOO_LONG."""
    return svc.create(get_ctx(request), principal, body, request_id(request), client_ip(request))


@router.delete("/me/api-tokens/{token_id}", status_code=204, responses=ERR, openapi_extra=SESSION_ONLY)
def revoke_my_api_token(token_id: str, request: Request, principal: Principal = Depends(get_principal)) -> Response:
    """내 토큰 폐기(멱등, 행은 남기고 revoked_at 기록)."""
    svc.revoke_mine(get_ctx(request), principal, token_id, request_id(request), client_ip(request))
    return Response(status_code=204)


@router.get("/admin/api-tokens", response_model=list[M.ApiTokenAdmin], responses=ERR, openapi_extra=SESSION_ONLY)
def admin_list_api_tokens(request: Request, user_id: str | None = Query(default=None, max_length=200),
                          active: bool | None = None, principal: Principal = Depends(get_principal)) -> list:
    """전역 관리자: 전체 API 토큰 목록(사용자·유효 여부 거르기)."""
    return svc.admin_list(get_ctx(request), principal, user_id, active)


@router.post("/admin/api-tokens/{token_id}/revoke", response_model=M.ApiTokenAdmin, responses=ERR, openapi_extra=SESSION_ONLY)
def admin_revoke_api_token(token_id: str, request: Request, principal: Principal = Depends(get_principal)) -> dict:
    """전역 관리자: 토큰 즉시 폐기(계정 정지 등)."""
    return svc.admin_revoke(get_ctx(request), principal, token_id, request_id(request), client_ip(request))
