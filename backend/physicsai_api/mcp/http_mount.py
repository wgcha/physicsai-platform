"""`/physicsai/mcp` Streamable HTTP 마운트(mcp.md §20.1): `physicsai_mcp.http_app`에 백엔드 함수를 주입해 붙인다.

주입: 토큰 검증(`auth_tokens.verify_bearer` — §4.2 401 단계와 같은 코드)·도구 스펙·활성 여부·거부 감사. `physicsai_mcp`는 이 패키지를 import하지 않는다.
마운트 1곳, 프런트 정적 서빙보다 먼저 등록한다. SDK는 첫 요청 때 지연 import(MCP를 켜지 않은 설치는 비용 0).
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from fastapi import FastAPI
from starlette.responses import JSONResponse
from starlette.types import Receive, Scope, Send

from physicsai_core import __version__
from physicsai_core.errors import DomainError

from ..auth_tokens import verify_bearer
from ..context import AppContext
from ..services import mcp as svc
from .audit_mw import record_denied

log = logging.getLogger("physicsai_api.mcp")
MOUNT_PATH = "/physicsai/mcp"


class McpHttpMount:
    def __init__(self, app: FastAPI, ctx: AppContext) -> None:
        self.app = app
        self.ctx = ctx
        self._inner: Any = None
        self._lock = threading.Lock()

    def enabled(self) -> bool:
        m = self.ctx.settings.mcp
        return bool(m.enabled and m.server.http_enabled)

    def _build(self) -> Any:
        from physicsai_mcp.http_app import TokenRejected, VerifiedToken, build_mcp_asgi

        from . import glossary

        ctx = self.ctx

        def verify(bearer: str) -> VerifiedToken:
            try:
                row = verify_bearer(ctx, bearer)
            except DomainError as e:
                raise TokenRejected(e.code, e.message, status=e.status, prefix=e.extra.get("token_prefix")) from e
            return VerifiedToken(scope=row["scope"], prefix=row["token_prefix"])

        def denied(**kw: Any) -> None:
            record_denied(ctx, route=MOUNT_PATH, **kw)

        hints = dict(glossary.terms().get("error_hints") or {})
        m = ctx.settings.mcp.server
        return build_mcp_asgi(self.app, verify, lambda scope: svc.tool_specs("mcp", with_visible=True, scope=scope),
                              is_enabled=self.enabled, hints=hints, server_version=__version__, call_timeout_s=float(m.call_timeout_s),
                              max_result_bytes=int(m.max_result_bytes), on_denied=denied)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            return
        if not self.enabled():  # SDK를 import하지 않고 404(openapi에는 나타나지 않는다)
            code, msg = "MCP_DISABLED", "MCP HTTP 전송이 꺼져 있습니다(mcp.enabled·mcp.server.http_enabled)"
            body = {"code": code, "message": msg, "detail": {"code": code, "message": msg}}  # mcp.md MR-C2 ②: 최상위 code·message + detail
            await JSONResponse(body, status_code=404)(scope, receive, send)
            return
        if self._inner is None:
            with self._lock:
                if self._inner is None:
                    self._inner = self._build()
        await self._inner(scope, receive, send)


def mount_mcp(app: FastAPI, ctx: AppContext) -> None:
    """`/physicsai/mcp`(끝 슬래시 유무 모두)를 앱에 등록한다. 모든 메서드를 받고(SDK가 405 처리), openapi에는 넣지 않는다."""
    handler = McpHttpMount(app, ctx)
    for path in (MOUNT_PATH, MOUNT_PATH + "/"):
        app.add_route(path, handler, include_in_schema=False)
