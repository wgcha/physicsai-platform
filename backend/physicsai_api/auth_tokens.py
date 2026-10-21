"""기계 인증 — 사용자별 API 토큰(mcp.md §4). 접두 `pai_` Bearer는 대시보드로 보내지 않고 토큰 테이블로 검증한다.

- 형식 `pai_<id8>_<secret43>`(id8 = 소문자 base32 8자, secret = token_urlsafe(32)). DB에는 sha256(전체 토큰) hex와 `pai_<id8>`만.
- 권한 = min(토큰 범위, 역할 스냅숏). 스냅숏은 소유자의 세션 인증 성공 때 갱신(§4.3), 오래되면 401 API_TOKEN_STALE.
- 오류 메시지·로그에 토큰 원문·일부를 넣지 않는다(접두만 허용).
"""

from __future__ import annotations

import base64
import hashlib
import logging
import re
import secrets
import threading
from datetime import datetime, timedelta
from typing import Any

from fastapi import Request

from physicsai_core.db.repositories import api_tokens as tokens_repo
from physicsai_core.errors import DomainError

from .auth import Principal, auth_required
from .context import AppContext
from .mcp import clock
from .mcp.ratelimit import FixedWindowLimiter
from .mcp.route_policy import RISK_RANK, operation_id_of, token_risk, x_mcp_of

log = logging.getLogger("physicsai_api.auth_tokens")

PREFIX = "pai_"
TOKEN_RE = re.compile(r"^pai_[a-z2-7]{8}_[A-Za-z0-9_-]{43}$")
TOKEN_LEN = 56
SCOPES = ("read", "run", "admin")
STALE_MESSAGE = "토큰 권한 정보가 오래되었습니다 — 웹 화면에 한 번 로그인해 권한을 갱신하세요"


def token_hash(plain: str) -> str:
    return hashlib.sha256(plain.encode("utf-8")).hexdigest()


def new_token() -> tuple[str, str, str]:
    """(평문, 접두 "pai_<id8>", sha256 hex). 평문은 발급 응답 1회만 돌려준다."""
    id8 = base64.b32encode(secrets.token_bytes(5)).decode("ascii").lower()
    plain = f"{PREFIX}{id8}_{secrets.token_urlsafe(32)}"
    assert TOKEN_RE.fullmatch(plain) and len(plain) == TOKEN_LEN
    return plain, f"{PREFIX}{id8}", token_hash(plain)


def snapshot_of(p: Principal) -> dict[str, Any]:
    return {"is_global_admin": bool(p.is_global_admin), "roles": dict(sorted(p.roles.items()))}


def can_issue(p: Principal, scope: str) -> bool:
    """발급 범위(§4.4): read = 로그인, run = 어느 프로젝트든 power+ 또는 전역 관리자, admin = 전역 관리자."""
    if scope == "admin":
        return p.is_global_admin
    if scope == "run":
        return p.is_global_admin or any(r in ("power", "admin") for r in p.roles.values())
    return True


def status_of(row: dict[str, Any], now: datetime, snapshot_max_age_days: int) -> str:
    if row.get("revoked_at") is not None:
        return "revoked"
    if row["expires_at"] <= now:
        return "expired"
    if now - row["snapshot_at"] > timedelta(days=snapshot_max_age_days):
        return "stale"
    return "active"


def scope_allows(scope: str, risk: str) -> bool:
    """토큰 범위가 operation 위험도를 충족하는지(read < run < admin). MCP 서버의 `tools/list` 표시 필터가 주입받아 쓴다."""
    return RISK_RANK.get(scope, -1) >= RISK_RANK.get(risk, 99)


class McpRuntime:
    """프로세스 메모리 상태: 호출 제한 창, 세션 스냅숏 갱신 간격(사용자당 ≤ auth.cache_ttl_s에 1회)."""

    def __init__(self) -> None:
        self.limiter = FixedWindowLimiter()
        self._lock = threading.Lock()
        self._refreshed: dict[str, tuple[float, dict[str, Any]]] = {}

    def should_refresh(self, user_id: str, snap: dict[str, Any], ttl_s: float) -> bool:
        t = clock.monotonic()
        with self._lock:
            last = self._refreshed.get(user_id)
            if last is not None and last[1] == snap and t - last[0] < ttl_s:
                return False
            self._refreshed[user_id] = (t, snap)
            if len(self._refreshed) > 5000:
                self._refreshed.clear()
        return True


def runtime_of(request: Request) -> McpRuntime:
    rt = getattr(request.app.state, "mcp_runtime", None)
    if rt is None:
        rt = request.app.state.mcp_runtime = McpRuntime()
    return rt


def _err(status: int, code: str, message: str, **extra: Any) -> DomainError:
    return DomainError(code, message, status=status, **extra)


def verify_bearer(ctx: AppContext, plain: str) -> dict[str, Any]:
    """§4.2 401 단계(형식·해시·폐기·만료·stale)만 — 토큰 행(해시 제외)을 돌려준다. API 경로와 `/physicsai/mcp` 마운트가 함께 쓴다.
    mcp.enabled=false면 401 AUTHENTICATION_REQUIRED(대시보드로 보내지 않음). 오류에는 접두만 싣는다."""
    cfg = ctx.settings.mcp
    if not cfg.enabled:
        raise auth_required()
    if len(plain) != TOKEN_LEN or not TOKEN_RE.fullmatch(plain):
        raise _err(401, "API_TOKEN_INVALID", "API 토큰이 올바르지 않습니다")
    with ctx.engine.connect() as conn:
        row = tokens_repo.get_by_hash(conn, token_hash(plain))
    if row is None:
        raise _err(401, "API_TOKEN_INVALID", "API 토큰이 올바르지 않습니다")
    st = status_of(row, clock.now(), cfg.token.snapshot_max_age_days)
    if st == "revoked":
        raise _err(401, "API_TOKEN_REVOKED", "폐기된 API 토큰입니다", token_prefix=row["token_prefix"])
    if st == "expired":
        raise _err(401, "API_TOKEN_EXPIRED", "만료된 API 토큰입니다", token_prefix=row["token_prefix"])
    if st == "stale":
        raise _err(401, "API_TOKEN_STALE", STALE_MESSAGE, token_prefix=row["token_prefix"])
    return row


def token_info(row: dict[str, Any]) -> dict[str, Any]:
    return {"id": row["id"], "prefix": row["token_prefix"], "user_id": row["user_id"], "username": row["username"],
            "scope": row["scope"]}


def authenticate_token(ctx: AppContext, request: Request, auth_header: str) -> Principal:
    """§4.2 토큰 경로: 인증(401) → 허용 operation·범위(403) → 호출 제한(429). 성공하면 스냅숏 Principal."""
    cfg = ctx.settings.mcp
    plain = auth_header.partition(" ")[2].strip()
    request.state.api_token_prefix = plain[:12] if plain.startswith(PREFIX) else None  # 감사용 접두(원문 아님)
    row = verify_bearer(ctx, plain)
    request.state.api_token = token_info(row)
    route = request.scope.get("route")
    x = x_mcp_of(route)
    request.state.mcp_tool = (x or {}).get("tool")
    request.state.mcp_operation_id = operation_id_of(route)
    need, denied = token_risk(x)
    if denied == "SESSION_REQUIRED":
        raise _err(403, "SESSION_REQUIRED", "이 기능은 웹 화면(로그인 세션)에서만 쓸 수 있습니다")
    if denied:
        raise _err(403, "API_TOKEN_OPERATION_NOT_ALLOWED", "API 토큰으로 호출할 수 없는 기능입니다")
    assert need is not None
    snap = row["principal_snapshot"] or {}
    if not scope_allows(row["scope"], need) or (need == "admin" and not snap.get("is_global_admin")):
        raise _err(403, "API_TOKEN_SCOPE", f"토큰 범위가 부족합니다(필요: {need})", required=need)
    rl = cfg.rate_limit
    runtime = runtime_of(request)
    runtime.limiter.hit(row["id"], "req", rl.requests_per_min)
    if request.state.mcp_tool == "plan_job":
        runtime.limiter.hit(row["id"], "plan", rl.plans_per_min)
    now = clock.now()
    last = row.get("last_used_at")
    if last is None or (now - last).total_seconds() >= cfg.token.last_used_update_s:
        with ctx.engine.begin() as conn:
            tokens_repo.touch(conn, row["id"], now, request.client.host if request.client else None)
    request.state.api_token_id = row["id"]
    roles = snap.get("roles") if isinstance(snap.get("roles"), dict) else {}
    return Principal(user_id=row["user_id"], username=row["username"], display_name=row["display_name"],
                     is_global_admin=bool(snap.get("is_global_admin")), roles={str(k): str(v) for k, v in roles.items()})


def refresh_from_session(ctx: AppContext, request: Request, principal: Principal) -> None:
    """§4.3: 세션 인증 성공 → 그 사용자의 유효 토큰 스냅숏 갱신(같은 값이면 snapshot_at만). 전역 관리자 해제 시 admin 토큰 자동 폐기.
    실패해도 세션 요청은 막지 않는다(로그만)."""
    snap = snapshot_of(principal)
    if not runtime_of(request).should_refresh(principal.user_id, snap, ctx.settings.auth.cache_ttl_s):
        return
    try:
        now = clock.now()
        with ctx.engine.begin() as conn:
            tokens_repo.refresh_snapshot(conn, principal.user_id, snap, now)
            if not principal.is_global_admin:
                revoked = tokens_repo.revoke_admin_scope(conn, principal.user_id, "system:role_change", now)
                if revoked:
                    log.info("전역 관리자 해제로 admin 범위 API 토큰 %d개 자동 폐기(user=%s)", len(revoked), principal.user_id)
    except Exception:  # noqa: BLE001 — 세션 요청은 그대로 진행
        log.warning("API 토큰 스냅숏 갱신 실패(user=%s)", principal.user_id, exc_info=True)
