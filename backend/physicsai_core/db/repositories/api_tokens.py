"""API 토큰 저장소(mcp.md §4·§14). 평문은 저장하지 않는다(token_hash = sha256 hex, token_prefix = "pai_<id8>")."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.engine import Connection

from ..tables import TERMINAL_STATES, api_tokens, jobs
from .jobs import row_dict


def _public(r: Any) -> dict[str, Any] | None:
    """목록·상세 응답용 — 해시는 돌려주지 않는다(V-MCP-2). 인증 경로만 `get_by_hash`로 해시 행 전체를 쓴다."""
    d = row_dict(r)
    if d is None:
        return None
    d.pop("token_hash", None)
    return d


def insert(conn: Connection, **values: Any) -> dict[str, Any]:
    conn.execute(api_tokens.insert().values(**values))
    return get(conn, values["id"])  # type: ignore[return-value]


def get(conn: Connection, token_id: str) -> dict[str, Any] | None:
    return _public(conn.execute(select(api_tokens).where(api_tokens.c.id == token_id)).first())


def get_by_hash(conn: Connection, token_hash: str) -> dict[str, Any] | None:
    return _public(conn.execute(select(api_tokens).where(api_tokens.c.token_hash == token_hash)).first())


def list_for_user(conn: Connection, user_id: str, revoked_since: datetime) -> list[dict[str, Any]]:
    q = (select(api_tokens).where(api_tokens.c.user_id == user_id,
                                   or_(api_tokens.c.revoked_at.is_(None), api_tokens.c.revoked_at >= revoked_since))
         .order_by(api_tokens.c.created_at.desc(), api_tokens.c.id))
    return [_public(r) for r in conn.execute(q)]  # type: ignore[misc]


def list_all(conn: Connection, *, user_id: str | None, active: bool | None, now: datetime,
             limit: int = 500) -> list[dict[str, Any]]:
    q = select(api_tokens)
    if user_id:
        q = q.where(api_tokens.c.user_id == user_id)
    if active is True:
        q = q.where(api_tokens.c.revoked_at.is_(None), api_tokens.c.expires_at > now)
    elif active is False:
        q = q.where(or_(api_tokens.c.revoked_at.is_not(None), api_tokens.c.expires_at <= now))
    q = q.order_by(api_tokens.c.created_at.desc(), api_tokens.c.id).limit(limit)
    return [_public(r) for r in conn.execute(q)]  # type: ignore[misc]


def _valid(now: datetime) -> Any:
    return and_(api_tokens.c.revoked_at.is_(None), api_tokens.c.expires_at > now)


def count_valid(conn: Connection, user_id: str, now: datetime) -> int:
    return int(conn.execute(select(func.count()).select_from(api_tokens)
                            .where(api_tokens.c.user_id == user_id, _valid(now))).scalar() or 0)


def active_name_exists(conn: Connection, user_id: str, name: str) -> bool:
    q = select(api_tokens.c.id).where(api_tokens.c.user_id == user_id, api_tokens.c.name == name,
                                      api_tokens.c.revoked_at.is_(None))
    return conn.execute(q).first() is not None


def revoke(conn: Connection, token_id: str, by: str, now: datetime) -> dict[str, Any] | None:
    """멱등: 이미 폐기된 행은 그대로(처음 폐기 시각·주체 유지)."""
    conn.execute(update(api_tokens).where(api_tokens.c.id == token_id, api_tokens.c.revoked_at.is_(None))
                 .values(revoked_at=now, revoked_by=by))
    return get(conn, token_id)


def touch(conn: Connection, token_id: str, now: datetime, ip: str | None) -> None:
    conn.execute(update(api_tokens).where(api_tokens.c.id == token_id).values(last_used_at=now, last_used_ip=ip))


def refresh_snapshot(conn: Connection, user_id: str, snapshot: dict[str, Any], now: datetime) -> list[str]:
    """같은 사용자의 미폐기·미만료 토큰 스냅숏 갱신(§4.3). 갱신한 토큰 id 목록."""
    rows = conn.execute(update(api_tokens).where(api_tokens.c.user_id == user_id, _valid(now))
                        .values(principal_snapshot=snapshot, snapshot_at=now).returning(api_tokens.c.id)).all()
    return [r[0] for r in rows]


def revoke_admin_scope(conn: Connection, user_id: str, by: str, now: datetime) -> list[str]:
    rows = conn.execute(update(api_tokens).where(api_tokens.c.user_id == user_id, api_tokens.c.scope == "admin",
                                                 api_tokens.c.revoked_at.is_(None))
                        .values(revoked_at=now, revoked_by=by).returning(api_tokens.c.id)).all()
    return [r[0] for r in rows]


def active_job_ids(conn: Connection, token_id: str) -> list[str]:
    """이 토큰이 만든 비종료 작업 id(§11 max_active_jobs_per_token)."""
    q = (select(jobs.c.id).where(jobs.c.api_token_id == token_id, jobs.c.state.not_in(TERMINAL_STATES))
         .order_by(jobs.c.created_at))
    return [r[0] for r in conn.execute(q)]


def expiry(now: datetime, days: int) -> datetime:
    return now + timedelta(days=days)


def prefixes(conn: Connection, ids: list[str]) -> dict[str, str]:
    """토큰 id → 접두(작업 목록의 via_token)."""
    if not ids:
        return {}
    q = select(api_tokens.c.id, api_tokens.c.token_prefix).where(api_tokens.c.id.in_(sorted(set(ids))))
    return {r[0]: r[1] for r in conn.execute(q)}
