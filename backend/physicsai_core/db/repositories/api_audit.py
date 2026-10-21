"""토큰 요청 감사 저장소(mcp.md §6). 본문·파라미터 값·쿼리 값·토큰 원문은 저장하지 않는다.

insert 인자는 `AUDIT_COLUMNS`로 고정(정적 시험 V-MCP-5) — 열을 늘리려면 계약(§6.1)부터 바꾼다.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import and_, delete, or_, select
from sqlalchemy.engine import Connection

from ..tables import api_audit
from .jobs import row_dict

AUDIT_COLUMNS = ("user_id", "username", "api_token_id", "token_prefix", "operation_id", "tool", "method", "route",
                 "target_type", "target_id", "study_id", "kind", "job_id", "plan_id", "status_code", "result_code",
                 "duration_ms", "request_id", "client_ip", "params_sha256")


def record(conn: Connection, values: dict[str, Any]) -> str:
    unknown = set(values) - set(AUDIT_COLUMNS)
    if unknown:  # 본문·값이 실수로 들어오지 않게 막는다
        raise ValueError(f"api_audit에 없는 열: {sorted(unknown)}")
    rid = str(uuid.uuid4())
    conn.execute(api_audit.insert().values(id=rid, **{k: values.get(k) for k in AUDIT_COLUMNS}))
    return rid


def list_(conn: Connection, *, user_id: str | None, token_id: str | None, operation_id: str | None,
          status: int | None, since: datetime | None, until: datetime | None, limit: int,
          after: tuple[datetime, str] | None = None) -> list[dict[str, Any]]:
    """최신순(occurred_at desc, id desc). `after` = 직전 페이지 마지막 행의 (occurred_at, id) — 그보다 오래된 행부터."""
    q = select(api_audit)
    if user_id:
        q = q.where(api_audit.c.user_id == user_id)
    if token_id:
        q = q.where(api_audit.c.api_token_id == token_id)
    if operation_id:
        q = q.where(api_audit.c.operation_id == operation_id)
    if status is not None:
        q = q.where(api_audit.c.status_code == status)
    if since is not None:
        q = q.where(api_audit.c.occurred_at >= since)
    if until is not None:
        q = q.where(api_audit.c.occurred_at < until)
    if after is not None:
        ts, rid = after
        q = q.where(or_(api_audit.c.occurred_at < ts, and_(api_audit.c.occurred_at == ts, api_audit.c.id < rid)))
    q = q.order_by(api_audit.c.occurred_at.desc(), api_audit.c.id.desc()).limit(limit)
    return [row_dict(r) for r in conn.execute(q)]  # type: ignore[misc]


def purge_older_than(conn: Connection, before: datetime) -> int:
    return int(conn.execute(delete(api_audit).where(api_audit.c.occurred_at < before)).rowcount or 0)
