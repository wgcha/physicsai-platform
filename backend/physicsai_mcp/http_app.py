"""Streamable HTTP 마운트(mcp.md §20.1): `/physicsai/mcp`에 붙는 ASGI 앱 — stateless·JSON 응답, Bearer `pai_…` 필수.

백엔드가 주입하는 것(이 패키지는 physicsai_api를 import하지 않는다):
- `verify_token(bearer)`: 백엔드 `auth_tokens.verify_bearer`(§4.2 401 단계와 같은 코드). 실패는 `TokenRejected`.
- `load_specs(scope)`: 생성 도구 스펙 문서(+ 그 범위에 보이는 도구 이름 `visible`) — 표시 필터의 판정은 백엔드 함수.
- `is_enabled()`: `mcp.enabled`·`mcp.server.http_enabled`. 꺼져 있으면 404.
- `on_denied(...)`: 거부된 토큰을 `api_audit`에 남기는 백엔드 함수.
검증된 같은 Bearer로 같은 프로세스 앱을 ASGI로 호출해 도구를 실행한다(권한·감사는 그 요청에서 백엔드가 처리).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable, Mapping

import anyio.to_thread
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from . import sdk_adapter
from .backend_client import AsgiBackendClient
from .toolset import DEFAULT_CALL_TIMEOUT_S, DEFAULT_MAX_RESULT_BYTES, CallCtx, Toolset, ToolService, build_server

log = logging.getLogger("physicsai_mcp")
BEARER_PREFIX = "pai_"
WWW_AUTHENTICATE = 'Bearer realm="physicsai-mcp"'


class TokenRejected(Exception):
    """Bearer 검증 거부(401 계열). `prefix`는 감사용 토큰 접두(원문 아님)."""

    def __init__(self, code: str, message: str, *, status: int = 401, prefix: str | None = None) -> None:
        super().__init__(message)
        self.code, self.message, self.status, self.prefix = code, message, status, prefix


@dataclass(frozen=True)
class VerifiedToken:
    scope: str
    prefix: str | None = None


def _headers(scope: Scope) -> dict[str, str]:
    return {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers") or []}


def _reject(status: int, code: str, message: str, *, challenge: bool) -> JSONResponse:
    body = {"code": code, "message": message, "detail": {"code": code, "message": message}}
    return JSONResponse(body, status_code=status, headers={"WWW-Authenticate": WWW_AUTHENTICATE} if challenge else None)


def build_mcp_asgi(app: ASGIApp, verify_token: Callable[[str], VerifiedToken], load_specs: Callable[[str | None], Mapping[str, Any]], *,
                   is_enabled: Callable[[], bool] = lambda: True, hints: Mapping[str, str] | None = None, server_version: str = "",
                   call_timeout_s: float = DEFAULT_CALL_TIMEOUT_S, max_result_bytes: int = DEFAULT_MAX_RESULT_BYTES,
                   on_denied: Callable[..., None] | None = None) -> ASGIApp:
    client = AsgiBackendClient(app, timeout_s=call_timeout_s)
    toolsets: dict[str, Toolset] = {}

    def source(ctx: CallCtx) -> Toolset:
        key = ctx.scope or ""
        ts = toolsets.get(key)
        if ts is None:
            ts = toolsets[key] = Toolset(load_specs(ctx.scope), client, hints=hints, call_timeout_s=call_timeout_s,
                                         max_result_bytes=max_result_bytes)
        return ts

    server = build_server(ToolService(source), version=server_version)

    async def asgi(scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            return
        if not is_enabled():
            await _reject(404, "MCP_DISABLED", "MCP가 꺼져 있습니다(mcp.enabled)", challenge=False)(scope, receive, send)
            return
        h = _headers(scope)
        scheme, _, value = h.get("authorization", "").partition(" ")
        bearer = value.strip() if scheme.lower() == "bearer" else ""
        client_ip = (scope.get("client") or (None,))[0]
        denied: TokenRejected | None = None
        token: VerifiedToken | None = None
        if not bearer:
            denied = TokenRejected("AUTHENTICATION_REQUIRED", "Authorization: Bearer pai_… 가 필요합니다")
        elif not bearer.startswith(BEARER_PREFIX):
            denied = TokenRejected("API_TOKEN_INVALID", "API 토큰(pai_…)만 쓸 수 있습니다")
        else:
            try:
                token = await anyio.to_thread.run_sync(verify_token, bearer)
            except TokenRejected as e:
                denied = e
        if denied is not None or token is None:
            assert denied is not None
            if on_denied is not None and bearer.startswith(BEARER_PREFIX):
                prefix = denied.prefix or bearer[:12]
                try:
                    await anyio.to_thread.run_sync(lambda: on_denied(token_prefix=prefix, status_code=denied.status, result_code=denied.code,
                                                                       client_ip=client_ip, method=str(scope.get("method", "POST"))))
                except Exception:  # noqa: BLE001 — 감사 실패가 거부 응답을 바꾸지 않게
                    log.warning("MCP 거부 감사 기록 실패", exc_info=True)
            log.info("mcp http rejected status=%s code=%s", denied.status, denied.code)
            await _reject(denied.status, denied.code, denied.message, challenge=denied.status == 401)(scope, receive, send)
            return
        if scope.get("method") != "POST":  # stateless·JSON: 독립 SSE 스트림(GET)·세션 종료(DELETE)가 없다 — GET이 열린 채 매달리지 않게 바로 405
            await JSONResponse({"code": "METHOD_NOT_ALLOWED", "message": "POST만 지원합니다(stateless JSON)",
                                "detail": {"code": "METHOD_NOT_ALLOWED", "message": "POST만 지원합니다(stateless JSON)"}},
                               status_code=405, headers={"Allow": "POST"})(scope, receive, send)
            return
        inner = dict(scope)
        inner[sdk_adapter.SCOPE_KEY] = {"bearer": bearer, "scope": token.scope, "client_ip": client_ip}
        await sdk_adapter.handle_http(server, inner, receive, send)

    return asgi
