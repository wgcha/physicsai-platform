"""환경 점검 저장소(phase2 §5.7, §9.4). 상태 CAS: PENDING → RUNNING → DONE/FAILED, 만료 → EXPIRED."""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import and_, func, select, update
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError

from ...errors import DomainError
from ..tables import env_checks
from . import notifications as notif_repo
from .jobs import row_dict

ACTIVE = ("PENDING", "RUNNING")
FINAL = ("DONE", "FAILED", "EXPIRED")


def summarize(items: list[dict[str, Any]]) -> dict[str, int]:
    out = {"ok": 0, "warn": 0, "fail": 0, "skip": 0}
    for it in items:
        k = {"OK": "ok", "WARN": "warn", "FAIL": "fail", "SKIP": "skip"}.get(it.get("status", ""))
        if k:
            out[k] += 1
    return out


def create(conn: Connection, *, user_id: str, user_name: str, api_items: list[dict[str, Any]], expire_s: float) -> dict[str, Any]:
    cid = str(uuid.uuid4())
    sp = conn.begin_nested()
    try:
        conn.execute(env_checks.insert().values(
            id=cid, state="PENDING", requested_by=user_id, requested_by_name=user_name,
            expires_at=func.now() + timedelta(seconds=float(expire_s)), api_items=api_items, summary=summarize(api_items),
        ))
        sp.commit()
    except IntegrityError as exc:
        sp.rollback()
        if "ux_env_checks_active" in str(exc.orig):
            raise DomainError("ENV_CHECK_BUSY", "진행 중인 환경 점검이 있습니다", status=409) from None
        raise
    return get(conn, cid)  # type: ignore[return-value]


def get(conn: Connection, cid: str) -> dict[str, Any] | None:
    q = select(env_checks, (env_checks.c.expires_at < func.now()).label("is_expired")).where(env_checks.c.id == cid)
    return row_dict(conn.execute(q).first())


def latest(conn: Connection, state: str | None = None) -> dict[str, Any] | None:
    q = select(env_checks, (env_checks.c.expires_at < func.now()).label("is_expired"))
    if state:
        q = q.where(env_checks.c.state == state)
    return row_dict(conn.execute(q.order_by(env_checks.c.created_at.desc()).limit(1)).first())


def list_(conn: Connection, limit: int, offset: int) -> list[dict[str, Any]]:
    q = (
        select(env_checks, (env_checks.c.expires_at < func.now()).label("is_expired"))
        .order_by(env_checks.c.created_at.desc(), env_checks.c.id)
        .limit(limit)
        .offset(offset)
    )
    return [row_dict(r) for r in conn.execute(q)]


def claim(conn: Connection, worker_id: str) -> dict[str, Any] | None:
    """가장 오래된 PENDING(미만료) 1건을 RUNNING으로."""
    row = conn.execute(
        select(env_checks.c.id)
        .where(and_(env_checks.c.state == "PENDING", env_checks.c.expires_at > func.now()))
        .order_by(env_checks.c.created_at)
        .limit(1)
        .with_for_update(skip_locked=True)
    ).first()
    if row is None:
        return None
    r = conn.execute(
        update(env_checks)
        .where(and_(env_checks.c.id == row.id, env_checks.c.state == "PENDING", env_checks.c.expires_at > func.now()))
        .values(state="RUNNING", worker_id=worker_id, started_at=func.now())
    )
    if r.rowcount != 1:
        return None
    return get(conn, row.id)


def finish(conn: Connection, cid: str, worker_id: str, *, state: str, worker_items: list[dict[str, Any]] | None,
           summary: dict[str, int] | None, report_rel: str | None, failure_message: str | None = None) -> bool:
    """워커 완료·예외(§9.4). 만료 후·다른 워커면 거부(False)."""
    assert state in ("DONE", "FAILED")
    vals: dict[str, Any] = {"state": state, "finished_at": func.now(), "report_rel": report_rel}
    if worker_items is not None:
        vals["worker_items"] = worker_items
    if summary is not None:
        vals["summary"] = summary
    if failure_message:
        vals["failure_message"] = failure_message[:500]
    r = conn.execute(
        update(env_checks)
        .where(and_(env_checks.c.id == cid, env_checks.c.state == "RUNNING", env_checks.c.worker_id == worker_id,
                    env_checks.c.expires_at > func.now()))
        .values(**vals)
    )
    if r.rowcount != 1:
        return False
    notify_done(conn, cid)
    return True


def expire_due(conn: Connection) -> list[str]:
    """housekeeping: PENDING·RUNNING 이고 expires_at < now() → EXPIRED + 알림."""
    rows = conn.execute(
        update(env_checks)
        .where(and_(env_checks.c.state.in_(ACTIVE), env_checks.c.expires_at < func.now()))
        .values(state="EXPIRED", finished_at=func.now())
        .returning(env_checks.c.id)
    ).all()
    for r in rows:
        notify_done(conn, r.id)
    return [r.id for r in rows]


def notify_done(conn: Connection, cid: str) -> None:
    c = get(conn, cid)
    if c is None:
        return
    s = c["summary"] or {}
    if c["state"] == "EXPIRED":
        title = "환경 점검 만료 — 워커 항목이 실행되지 않았습니다"
    elif c["state"] == "FAILED":
        title = "환경 점검 실패 — 워커 오류"
    else:
        title = f"환경 점검 완료 — 실패 {s.get('fail', 0)} · 경고 {s.get('warn', 0)}"
    notif_repo.notify_user(conn, c["requested_by"], "ENV_CHECK_DONE", title, "관리 > 환경 점검에서 결과를 확인하세요.")
