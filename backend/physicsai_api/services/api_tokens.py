"""API 토큰 발급·목록·폐기(mcp.md §4.4). 세션 전용 — 토큰 요청은 라우트 x-mcp(session_only)로 403 SESSION_REQUIRED.

평문은 발급 응답 1회만, 목록·상세에는 해시·평문이 없다(V-MCP-2). 발급·폐기는 audit_events(API_TOKEN_CREATE·API_TOKEN_REVOKE).
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

from physicsai_core.db.repositories import api_tokens as tokens_repo
from physicsai_core.errors import DomainError

from ..auth import Principal
from ..auth_tokens import can_issue, new_token, snapshot_of, status_of
from ..context import AppContext
from ..mcp import clock
from .common import audit, require_global_admin

LIST_REVOKED_DAYS = 90


def require_enabled(ctx: AppContext) -> None:
    if not ctx.settings.mcp.enabled:
        raise DomainError("MCP_DISABLED", "MCP 기능이 꺼져 있습니다(mcp.enabled: false)", status=404)


def token_out(ctx: AppContext, row: dict[str, Any], *, admin: bool = False) -> dict[str, Any]:
    out = {k: row[k] for k in ("id", "name", "scope", "token_prefix", "created_at", "expires_at", "last_used_at",
                               "revoked_at", "revoked_by", "snapshot_at")}
    out["status"] = status_of(row, clock.now(), ctx.settings.mcp.token.snapshot_max_age_days)
    if admin:
        out.update(user_id=row["user_id"], username=row["username"])
    return out


def list_mine(ctx: AppContext, principal: Principal) -> list[dict[str, Any]]:
    require_enabled(ctx)
    since = clock.now() - timedelta(days=LIST_REVOKED_DAYS)
    with ctx.engine.connect() as conn:
        rows = tokens_repo.list_for_user(conn, principal.user_id, since)
    return [token_out(ctx, r) for r in rows]


def create(ctx: AppContext, principal: Principal, body: Any, rid: str, ip: str | None) -> dict[str, Any]:
    require_enabled(ctx)
    tc = ctx.settings.mcp.token
    if not can_issue(principal, body.scope):
        need = "전역 관리자" if body.scope == "admin" else "어느 프로젝트든 power 이상"
        raise DomainError("API_TOKEN_SCOPE", f"{body.scope} 범위 토큰은 {need} 권한이 필요합니다", status=403, required=body.scope)
    days = tc.default_expiry_days if body.expires_in_days is None else body.expires_in_days
    if days > tc.max_expiry_days:  # MR-13: 무기한·장기 없음
        raise DomainError("API_TOKEN_EXPIRY_TOO_LONG", f"토큰 만료는 최대 {tc.max_expiry_days}일입니다 — 만료 전에 새 토큰을 발급해 교체하세요",
                          status=422, max_days=tc.max_expiry_days)
    name = body.name.strip()
    if not name:
        raise DomainError("INVALID_PARAMS", "요청 값이 올바르지 않습니다", status=422,
                          errors=[{"loc": ["body", "name"], "msg": "빈 이름"}])
    now = clock.now()
    plain, prefix, digest = new_token()
    with ctx.engine.begin() as conn:
        if tokens_repo.count_valid(conn, principal.user_id, now) >= tc.max_per_user:
            raise DomainError("API_TOKEN_LIMIT", f"유효한 토큰은 사용자당 {tc.max_per_user}개까지입니다 — 쓰지 않는 토큰을 폐기하세요",
                              status=409, limit=tc.max_per_user)
        if tokens_repo.active_name_exists(conn, principal.user_id, name):
            raise DomainError("API_TOKEN_NAME_EXISTS", "같은 이름의 토큰이 이미 있습니다", status=409)
        tid = str(uuid.uuid4())
        row = tokens_repo.insert(
            conn, id=tid, user_id=principal.user_id, username=principal.username, display_name=principal.display_name,
            name=name, scope=body.scope, token_prefix=prefix, token_hash=digest, principal_snapshot=snapshot_of(principal),
            snapshot_at=now, created_at=now, expires_at=now + timedelta(days=days))
        audit(conn, principal, "API_TOKEN_CREATE", "api_token", tid,
              {"scope": body.scope, "token_prefix": prefix, "expires_in_days": days}, rid, ip)
    return {"token": plain, "api_token": token_out(ctx, row)}


def revoke_mine(ctx: AppContext, principal: Principal, token_id: str, rid: str, ip: str | None) -> None:
    require_enabled(ctx)
    with ctx.engine.begin() as conn:
        row = tokens_repo.get(conn, token_id)
        if row is None or row["user_id"] != principal.user_id:
            raise DomainError("NOT_FOUND", "토큰을 찾을 수 없습니다", status=404)
        if row["revoked_at"] is None:
            tokens_repo.revoke(conn, token_id, principal.user_id, clock.now())
            audit(conn, principal, "API_TOKEN_REVOKE", "api_token", token_id, {"token_prefix": row["token_prefix"]}, rid, ip)


def admin_list(ctx: AppContext, principal: Principal, user_id: str | None, active: bool | None) -> list[dict[str, Any]]:
    require_enabled(ctx)
    require_global_admin(principal)
    with ctx.engine.connect() as conn:
        rows = tokens_repo.list_all(conn, user_id=user_id, active=active, now=clock.now())
    return [token_out(ctx, r, admin=True) for r in rows]


def admin_revoke(ctx: AppContext, principal: Principal, token_id: str, rid: str, ip: str | None) -> dict[str, Any]:
    require_enabled(ctx)
    require_global_admin(principal)
    with ctx.engine.begin() as conn:
        row = tokens_repo.get(conn, token_id)
        if row is None:
            raise DomainError("NOT_FOUND", "토큰을 찾을 수 없습니다", status=404)
        if row["revoked_at"] is None:
            row = tokens_repo.revoke(conn, token_id, f"admin:{principal.user_id}", clock.now())
            audit(conn, principal, "API_TOKEN_REVOKE", "api_token", token_id,
                  {"token_prefix": row["token_prefix"], "by_admin": True}, rid, ip)  # type: ignore[index]
    return token_out(ctx, row, admin=True)  # type: ignore[arg-type]
