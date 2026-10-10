"""환경 점검 API(phase2 §9.2, §12.2). API는 실행 파일을 실행하지 않는다 — DB·대시보드·설정·HPC 모드만 즉시 점검."""

from __future__ import annotations

import time
from typing import Any

from physicsai_core.db import MIGRATION_HEAD
from physicsai_core.db.repositories import env_checks as env_repo
from physicsai_core.db.repositories import system as system_repo
from physicsai_core.db.repositories import workers as workers_repo
from physicsai_core.env_check import item, pending_worker_items
from physicsai_core.errors import DomainError

from ..auth import Principal
from ..context import AppContext
from .common import audit, clamp_limit, decode_cursor, encode_cursor, require_global_admin


def _api_items(ctx: AppContext, token: str | None, rid: str) -> list[dict[str, Any]]:
    s = ctx.settings
    out: list[dict[str, Any]] = []
    if ctx.config.ok:
        out.append(item("config.valid", "CONFIG", "OK", "설정 검증 오류 없음", "API"))
    else:
        out.append(item("config.valid", "CONFIG", "FAIL", f"설정 오류 {len(ctx.config.issues)}건", "API",
                        {"keys": ctx.config.error_keys()[:50]}))
    t0 = time.time()
    head = None
    try:
        with ctx.engine.connect() as conn:
            system_repo.ping(conn)
            ms = int((time.time() - t0) * 1000)
            head = system_repo.migration_version(conn)
        out.append(item("db.connection", "DATABASE", "OK", f"{ms} ms", "API", {"latency_ms": ms}))
    except Exception as exc:  # noqa: BLE001
        out.append(item("db.connection", "DATABASE", "FAIL", f"DB 연결 실패: {type(exc).__name__}", "API"))
    if head == MIGRATION_HEAD:
        out.append(item("db.migration_head", "DATABASE", "OK", head, "API", {"current": head, "head": MIGRATION_HEAD}))
    else:
        out.append(item("db.migration_head", "DATABASE", "FAIL", "migration head 불일치", "API",
                        {"current": head, "head": MIGRATION_HEAD}))
    if s.auth.mode != "dashboard" or ctx.auth.client is None:
        out.append(item("auth.dashboard", "AUTH", "SKIP", "개발 모드", "API"))
        out.append(item("auth.projects", "AUTH", "SKIP", "개발 모드", "API"))
    else:
        t0 = time.time()
        try:
            ctx.auth.client.me(token or "", rid)  # 캐시 우회 재호출
            ms = int((time.time() - t0) * 1000)
            out.append(item("auth.dashboard", "AUTH", "OK", f"{ms} ms", "API", {"latency_ms": ms}))
        except DomainError as exc:
            out.append(item("auth.dashboard", "AUTH", "FAIL", f"{exc.code}: {exc.message}", "API", {"code": exc.code}))
        try:
            n = len(ctx.auth.client.projects(token or "", rid))
            out.append(item("auth.projects", "AUTH", "OK", f"프로젝트 {n}개", "API", {"count": n}))
        except DomainError as exc:
            out.append(item("auth.projects", "AUTH", "FAIL", f"{exc.code}: {exc.message}", "API", {"code": exc.code}))
    av = ctx.hpc.availability()
    if av.mode == "none":
        out.append(item("hpc.gateway", "HPC", "WARN", "PBS 연결 안 됨", "API", {"mode": av.mode}))
    elif av.configured:
        out.append(item("hpc.gateway", "HPC", "OK", av.message, "API", {"mode": av.mode}))
    else:
        out.append(item("hpc.gateway", "HPC", "FAIL", av.message, "API", {"mode": av.mode}))
    try:
        with ctx.engine.connect() as conn:
            hb = workers_repo.latest(conn)
    except Exception:  # noqa: BLE001
        hb = None
    if hb and float(hb["age_s"]) <= 3 * s.worker.heartbeat_interval_s:
        out.append(item("worker.heartbeat", "WORKER", "OK", "워커 온라인", "API",
                        {"worker_id": hb["worker_id"], "age_s": round(float(hb["age_s"]), 1), "limiter": hb["limiter"]}))
    else:
        out.append(item("worker.heartbeat", "WORKER", "FAIL", "워커 오프라인 — 워커 항목은 실행되지 않습니다", "API",
                        {"age_s": round(float(hb["age_s"]), 1) if hb else None}))
    return out


def _state(c: dict[str, Any]) -> str:
    if c["state"] in env_repo.ACTIVE and c.get("is_expired"):
        return "EXPIRED"
    return c["state"]


def summary_out(c: dict[str, Any]) -> dict[str, Any]:
    return {"id": c["id"], "state": _state(c), "requested_by_name": c["requested_by_name"], "created_at": c["created_at"],
            "finished_at": c["finished_at"], "summary": c["summary"] or {}}


def check_out(ctx: AppContext, c: dict[str, Any]) -> dict[str, Any]:
    from physicsai_core.paths import display_path

    items = list(c["api_items"] or [])
    items += c["worker_items"] if c["worker_items"] is not None else pending_worker_items(ctx.settings)
    out = summary_out(c)
    rdp = None
    if c["report_rel"]:
        parts = c["report_rel"].split("/")
        rdp = display_path(ctx.settings.storage.ai_root, parts[0], "/".join(parts[1:]))
    out.update({"started_at": c["started_at"], "expires_at": c["expires_at"], "worker_id": c["worker_id"], "items": items,
                "failure_message": c["failure_message"], "report_display_path": rdp})
    return out


def create(ctx: AppContext, principal: Principal, token: str | None, rid: str, ip: str | None) -> dict[str, Any]:
    require_global_admin(principal)
    items = _api_items(ctx, token, rid)
    with ctx.engine.begin() as conn:
        c = env_repo.create(conn, user_id=principal.user_id, user_name=principal.display_name, api_items=items,
                            expire_s=ctx.settings.env_check.expire_s)
        audit(conn, principal, "ENV_CHECK_RUN", "env_check", c["id"], None, rid, ip)
    return check_out(ctx, c)


def list_(ctx: AppContext, principal: Principal, limit: int | None, cursor: str | None) -> tuple[list[dict[str, Any]], str | None]:
    require_global_admin(principal)
    lim, off = clamp_limit(limit, 20), decode_cursor(cursor)
    with ctx.engine.connect() as conn:
        rows = env_repo.list_(conn, lim + 1, off)
    return [summary_out(c) for c in rows[:lim]], (encode_cursor(off + lim) if len(rows) > lim else None)


def latest(ctx: AppContext, principal: Principal) -> dict[str, Any]:
    require_global_admin(principal)
    with ctx.engine.connect() as conn:
        c = env_repo.latest(conn)
    if c is None:
        raise DomainError("NOT_FOUND", "환경 점검 기록이 없습니다", status=404)
    return check_out(ctx, c)


def get(ctx: AppContext, principal: Principal, cid: str) -> dict[str, Any]:
    require_global_admin(principal)
    with ctx.engine.connect() as conn:
        c = env_repo.get(conn, cid)
    if c is None:
        raise DomainError("NOT_FOUND", "환경 점검을 찾을 수 없습니다", status=404)
    return check_out(ctx, c)


def status_block(ctx: AppContext, principal: Principal) -> dict[str, Any] | None:
    """/status.env_check — 전역 관리자에게만 값, 그 외 null."""
    if not principal.is_global_admin:
        return None
    with ctx.engine.connect() as conn:
        c = env_repo.latest(conn)
    if c is None:
        return {"latest_id": None, "latest_state": None, "finished_at": None, "fail": None, "warn": None}
    s = c["summary"] or {}
    return {"latest_id": c["id"], "latest_state": _state(c), "finished_at": c["finished_at"], "fail": s.get("fail"),
            "warn": s.get("warn")}
