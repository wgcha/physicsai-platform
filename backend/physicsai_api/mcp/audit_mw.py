"""토큰 요청 감사 미들웨어(mcp.md §6.1): 응답 뒤 별도 트랜잭션으로 `api_audit` 1행 — 실패한 요청도 남는다.

기록 대상(토큰 요청만): 모든 비GET, 모든 거부(401·403·428·429), plan_job·run_job, `mcp.audit.record_reads`면 GET도.
본문·파라미터 값·쿼리 값·토큰·confirm_token 원문은 저장하지 않는다(오류 응답에서 `detail.code`만 읽는다).
`mcp.enabled: false`면 아무것도 하지 않는다(기존 동작 불변).
`/physicsai/mcp` 마운트가 Bearer 검증에서 거부한 요청은 `record_denied`로 같은 표에 남긴다(§20.1).
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from starlette.concurrency import run_in_threadpool
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from physicsai_core.db.repositories import api_audit as audit_repo

from .route_policy import operation_id_of, x_mcp_of

log = logging.getLogger("physicsai_api.audit")

DENIED = (401, 403, 428, 429)
ALWAYS_TOOLS = ("plan_job", "run_job")
ERROR_BODY_CAP = 8192


def _auth_header(scope: Scope) -> str:
    for k, v in scope.get("headers") or []:
        if k == b"authorization":
            return v.decode("latin-1")
    return ""


def _is_token(scope: Scope) -> bool:
    scheme, _, value = _auth_header(scope).partition(" ")
    return scheme.lower() == "bearer" and value.strip().startswith("pai_")


def _target(path_params: dict[str, Any]) -> tuple[str | None, str | None]:
    """경로 파라미터 중 대표 id: summary는 (entity, id), 그 밖은 첫 `*_id`/`id`/`kind`."""
    if "entity" in path_params and "id" in path_params:
        return str(path_params["entity"])[:32], str(path_params["id"])
    for k, v in path_params.items():
        if k.endswith("_id") or k in ("id", "fid", "key"):
            return (k[:-3] if k.endswith("_id") else k)[:32], str(v)
    if "kind" in path_params:
        return "job_kind", str(path_params["kind"])
    return None, None


class ApiAuditMiddleware:
    def __init__(self, app: ASGIApp, ctx: Any) -> None:
        self.app = app
        self.ctx = ctx

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not self.ctx.settings.mcp.enabled or not _is_token(scope):
            await self.app(scope, receive, send)
            return
        t0 = time.monotonic()
        status: dict[str, Any] = {"code": None, "body": b""}

        async def send_wrap(message: Message) -> None:
            if message["type"] == "http.response.start":
                status["code"] = int(message["status"])
            elif message["type"] == "http.response.body" and (status["code"] or 0) >= 400:
                if len(status["body"]) < ERROR_BODY_CAP:
                    status["body"] += message.get("body", b"")[:ERROR_BODY_CAP]
            await send(message)

        try:
            await self.app(scope, receive, send_wrap)
        except Exception:
            status["code"] = status["code"] or 500
            raise
        finally:
            dur = int((time.monotonic() - t0) * 1000)
            try:
                await run_in_threadpool(self._record, scope, status, dur)
            except Exception:  # noqa: BLE001 — 감사 실패가 응답을 바꾸지 않게
                log.warning("api_audit 기록 실패", exc_info=True)

    def _record(self, scope: Scope, status: dict[str, Any], dur: int) -> None:
        code = int(status["code"] or 500)
        method = str(scope.get("method", "GET")).upper()
        route = scope.get("route")
        x = x_mcp_of(route) or {}
        tool = x.get("tool")
        if not (method != "GET" or code in DENIED or tool in ALWAYS_TOOLS or self.ctx.settings.mcp.audit.record_reads):
            return
        state = scope.get("state") or {}
        tok = state.get("api_token") or {}
        extra = state.get("mcp_audit") or {}
        result_code = None
        if code >= 400 and status["body"]:
            try:
                d = json.loads(status["body"]).get("detail")
                result_code = str(d.get("code"))[:64] if isinstance(d, dict) and d.get("code") else None
            except (ValueError, AttributeError):
                result_code = None
        pp = scope.get("path_params") or {}
        ttype, tid = _target(pp)
        client = scope.get("client")
        values = {
            "user_id": tok.get("user_id"), "username": tok.get("username"), "api_token_id": tok.get("id"),
            "token_prefix": tok.get("prefix") or state.get("api_token_prefix"),
            "operation_id": operation_id_of(route) if route is not None else None, "tool": tool, "method": method[:8],
            "route": getattr(route, "path", None), "target_type": ttype, "target_id": tid,
            "study_id": extra.get("study_id") or pp.get("study_id"), "kind": extra.get("kind"),
            "job_id": extra.get("job_id"), "plan_id": extra.get("plan_id"), "status_code": code,
            "result_code": result_code, "duration_ms": dur, "request_id": state.get("request_id"),
            "client_ip": client[0] if client else None, "params_sha256": extra.get("params_sha256"),
        }
        with self.ctx.engine.begin() as conn:
            audit_repo.record(conn, values)


def record_denied(ctx: Any, *, token_prefix: str | None, status_code: int, result_code: str, route: str,
                  client_ip: str | None, request_id: str | None = None, method: str = "POST",
                  token: dict[str, Any] | None = None) -> None:
    """MCP 마운트가 Bearer 검증에서 거부한 요청 1행(토큰 원문 없음, 접두만). 실패해도 응답은 그대로(로그만)."""
    if not ctx.settings.mcp.enabled:
        return
    try:
        with ctx.engine.begin() as conn:
            tok = token or {}
            audit_repo.record(conn, {"token_prefix": token_prefix, "method": method[:8], "route": route, "tool": None,
                                     "user_id": tok.get("user_id"), "username": tok.get("username"), "api_token_id": tok.get("id"),
                                     "status_code": status_code, "result_code": result_code[:64], "client_ip": client_ip,
                                     "request_id": request_id})
    except Exception:  # noqa: BLE001
        log.warning("api_audit(거부) 기록 실패", exc_info=True)
