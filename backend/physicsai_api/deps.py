"""FastAPI 의존성: 인증(§5.2)·CSRF 헤더(§5.4)·문맥."""

from __future__ import annotations

import uuid

from fastapi import Request

from physicsai_core.errors import DomainError

from .auth import Principal
from .context import AppContext

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def get_ctx(request: Request) -> AppContext:
    return request.app.state.ctx


def request_id(request: Request) -> str:
    rid = getattr(request.state, "request_id", None)
    if not rid:
        rid = request.headers.get("x-request-id") or str(uuid.uuid4())
        rid = rid[:64]
        request.state.request_id = rid
    return rid


def extract_token(request: Request, cookie_name: str) -> str | None:
    tok = request.cookies.get(cookie_name)
    if tok:
        return tok
    auth = request.headers.get("authorization", "")
    scheme, _, value = auth.partition(" ")
    if scheme.lower() == "bearer" and value.strip():
        return value.strip()
    return None


def get_principal(request: Request) -> Principal:
    ctx = get_ctx(request)
    auth_header = request.headers.get("authorization", "")
    if is_token_header(auth_header):  # mcp.md §4.2: `pai_` Bearer = API 토큰 경로(쿠키 무시, 대시보드 미호출, CSRF 면제)
        from .auth_tokens import authenticate_token

        principal = authenticate_token(ctx, request, auth_header)
        request.state.principal = principal
        return principal
    token = extract_token(request, ctx.settings.auth.cookie_name)
    principal = ctx.auth.authenticate(token, request_id(request))
    if request.method not in SAFE_METHODS and request.headers.get("x-physicsai-request") != "1":
        raise DomainError("CSRF_HEADER_REQUIRED", "요청 헤더 X-PhysicsAI-Request가 필요합니다", status=403)
    request.state.principal = principal
    if ctx.settings.mcp.enabled:  # §4.3: 세션 인증 성공 → 그 사용자의 API 토큰 역할 스냅숏 갱신
        from .auth_tokens import refresh_from_session

        refresh_from_session(ctx, request, principal)
    return principal


def is_token_header(auth_header: str | None) -> bool:
    scheme, _, value = (auth_header or "").partition(" ")
    return scheme.lower() == "bearer" and value.strip().startswith("pai_")


def api_token_id(request: Request) -> str | None:
    """토큰 요청이면 그 토큰 id(세션 요청은 None)."""
    return getattr(request.state, "api_token_id", None)


def get_token(request: Request) -> str | None:
    return extract_token(request, get_ctx(request).settings.auth.cookie_name)


def client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None
