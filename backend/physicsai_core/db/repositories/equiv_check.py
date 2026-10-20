"""⑤ 해석 등가성 판정 저장소(equiv-check.md §5.1): eq_recipes(버전 행·소프트 삭제)·eq_checks(이력)·종료 훅.

DB에는 정의·경로·상태·수치 요약만(파일 본문 없음)."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import and_, func, or_, select, tuple_, update
from sqlalchemy.engine import Connection

from ...state_machine import CANCELED, FAILED, INTERRUPTED, SUCCEEDED, TERMINAL
from ..tables import eq_checks as ec, eq_recipes as er, notifications, studies
from ..tables.equiv_check import EQ_ACTIVE
from .jobs import get_job, insert_job, row_dict

log = logging.getLogger(__name__)

EQ_CHECK_JOB = "EQ_CHECK"


def label(eq_no: int) -> str:
    return f"EQ-{eq_no:03d}"


# ---- 레시피 -----------------------------------------------------------------------------------------


def latest_versions(conn: Connection, *, study_id: str | None, include_deleted: bool = False) -> list[dict[str, Any]]:
    """global + 그 Study 레시피의 최신 버전 행(key마다 1행). include_deleted=False면 삭제된 key 제외."""
    vis = or_(er.c.scope == "global", er.c.study_id == study_id) if study_id else er.c.scope == "global"
    sub = (select(er.c.recipe_key, func.max(er.c.version).label("v")).where(vis).group_by(er.c.recipe_key).subquery())
    q = select(er).join(sub, and_(er.c.recipe_key == sub.c.recipe_key, er.c.version == sub.c.v))
    if not include_deleted:
        q = q.where(er.c.deleted_at.is_(None))
    return [row_dict(r) for r in conn.execute(q.order_by(er.c.scope.desc(), func.lower(er.c.name)))]


def get_version(conn: Connection, key: str, version: int | None = None, *, for_update: bool = False) -> dict[str, Any] | None:
    q = select(er).where(er.c.recipe_key == key)
    q = q.where(er.c.version == version) if version is not None else q.order_by(er.c.version.desc()).limit(1)
    if for_update:
        q = q.with_for_update()
    return row_dict(conn.execute(q).first())


def versions(conn: Connection, key: str) -> list[dict[str, Any]]:
    return [row_dict(r) for r in conn.execute(select(er).where(er.c.recipe_key == key).order_by(er.c.version.desc()))]


def name_taken(conn: Connection, scope: str, study_id: str | None, name: str, *, exclude_key: str | None = None) -> bool:
    """활성(삭제되지 않은) 최신 버전 중 같은 범위·같은 이름(대소문자 무시)이 있는지."""
    for r in latest_versions(conn, study_id=study_id):
        if r["scope"] != scope or (scope == "study" and r["study_id"] != study_id):
            continue
        if r["recipe_key"] != exclude_key and r["name"].casefold() == name.casefold():
            return True
    return False


def insert_version(conn: Connection, *, key: str | None, version: int, scope: str, study_id: str | None, name: str,
                   description: str, definition: Mapping[str, Any], parent: tuple[str, int] | None, user_id: str,
                   user_name: str) -> dict[str, Any]:
    rid, key = str(uuid.uuid4()), key or str(uuid.uuid4())
    conn.execute(er.insert().values(
        id=rid, recipe_key=key, version=version, scope=scope, study_id=study_id, name=name, description=description or "",
        definition=dict(definition), parent_key=parent[0] if parent else None, parent_version=parent[1] if parent else None,
        created_by=user_id, created_by_name=user_name))
    return get_version(conn, key, version)  # type: ignore[return-value]


def soft_delete(conn: Connection, key: str, user_id: str) -> None:
    conn.execute(update(er).where(and_(er.c.recipe_key == key, er.c.deleted_at.is_(None)))
                 .values(deleted_at=func.now(), deleted_by=user_id))


def restore(conn: Connection, key: str) -> None:
    conn.execute(update(er).where(er.c.recipe_key == key).values(deleted_at=None, deleted_by=None))


# ---- 판정 이력 ---------------------------------------------------------------------------------------


def next_eq_no(conn: Connection, study_id: str) -> int:
    return int(conn.execute(select(func.coalesce(func.max(ec.c.eq_no), 0)).where(ec.c.study_id == study_id)).scalar_one()) + 1


def insert_check(conn: Connection, **values: Any) -> dict[str, Any]:
    eid = values.pop("id", None) or str(uuid.uuid4())
    conn.execute(ec.insert().values(id=eid, **values))
    return get_check(conn, eid)  # type: ignore[return-value]


def get_check(conn: Connection, eid: str, *, for_update: bool = False) -> dict[str, Any] | None:
    q = select(ec).where(ec.c.id == eid)
    if for_update:
        q = q.with_for_update()
    return row_dict(conn.execute(q).first())


def set_check(conn: Connection, eid: str, **values: Any) -> None:
    conn.execute(update(ec).where(ec.c.id == eid).values(**values))


def count_active(conn: Connection, study_id: str) -> int:
    return int(conn.execute(select(func.count()).select_from(ec).where(and_(ec.c.study_id == study_id, ec.c.status.in_(EQ_ACTIVE)))).scalar_one())


def list_for_study(conn: Connection, study_id: str, *, side_kind: str | None = None, side_ref: str | None = None,
                   verdict: str | None = None, recipe_key: str | None = None, limit: int = 50,
                   after: tuple[datetime, str] | None = None) -> list[dict[str, Any]]:
    conds = [ec.c.study_id == study_id]
    if side_kind:
        conds.append(or_(ec.c.side_a["kind"].astext == side_kind, ec.c.side_b["kind"].astext == side_kind))
    if side_ref:
        conds.append(or_(ec.c.side_a["ref"].astext == side_ref, ec.c.side_b["ref"].astext == side_ref))
    if verdict:
        conds.append(ec.c.verdict == verdict)
    if recipe_key:
        conds.append(ec.c.recipe_key == recipe_key)
    if after is not None:
        conds.append(tuple_(ec.c.created_at, ec.c.id) < tuple_(after[0], after[1]))
    q = select(ec).where(and_(*conds)).order_by(ec.c.created_at.desc(), ec.c.id.desc()).limit(limit)
    return [row_dict(r) for r in conn.execute(q)]


def by_job(conn: Connection, job_id: str) -> dict[str, Any] | None:
    return row_dict(conn.execute(select(ec).where(ec.c.job_id == job_id)).first())


def _study(conn: Connection, study_id: str) -> dict[str, Any]:
    return row_dict(conn.execute(select(studies).where(studies.c.id == study_id)).first())


def enqueue(conn: Connection, row: Mapping[str, Any]) -> dict[str, Any]:
    """EQ_CHECK(QUEUED, 등록자 = 판정 등록자) + 이력 RUNNING·job_id."""
    job = insert_job(conn, study=_study(conn, row["study_id"]), job_type=EQ_CHECK_JOB,
                     params={"eq_id": row["id"], "eq_no": int(row["eq_no"])},
                     user_id=row["created_by"], user_name=row["created_by_name"])
    set_check(conn, row["id"], status="RUNNING", job_id=job["id"], failure_code=None, failure_message=None, finished_at=None)
    return job


# ---- 종료 훅(job_end) -------------------------------------------------------------------------------


def done_notice(eq_no: int, verdict: str | None, summary: Mapping[str, Any] | None) -> tuple[str, str]:
    """"등가성 판정 EQ-003 통과 — 필수 6/6 · 참고 미달 1 · 쌍 12"."""
    from ...equiv.metrics import VERDICT_TEXT

    s = summary or {}
    v = s.get("verdict") or {}
    title = (f"등가성 판정 {label(eq_no)} {VERDICT_TEXT.get(verdict or '', verdict or '-')} — "
             f"필수 {v.get('required_pass', 0)}/{v.get('required_total', 0)} · 참고 미달 {v.get('reference_fail', 0)} · 쌍 {s.get('n_pairs', 0)}")
    return title, "해석 등가성 판정이 끝났습니다. ⑤ 결과분석 › 등가성 판정 탭에서 확인하세요."


def _notify_done(conn: Connection, row: Mapping[str, Any], job_id: str) -> None:
    title, body = done_notice(row["eq_no"], row.get("verdict"), row.get("summary"))
    project_id = conn.execute(select(studies.c.project_id).where(studies.c.id == row["study_id"])).scalar()
    conn.execute(notifications.insert().values(user_id=row["created_by"], event="EQ_CHECK_DONE", job_id=job_id,
                                               study_id=row["study_id"], project_id=project_id, title=title[:120], body=body[:500]))


def on_job_end(conn: Connection, job: Mapping[str, Any], state: str) -> None:
    p = job.get("params") or {}
    eid = p.get("eq_id") if isinstance(p, Mapping) else None
    if not isinstance(eid, str) or job["job_type"] != EQ_CHECK_JOB:
        return
    sp = conn.begin_nested()
    try:
        row = get_check(conn, eid, for_update=True)
        if row is None or row["status"] not in EQ_ACTIVE or row["job_id"] != job["id"]:
            sp.commit()
            return
        if state == SUCCEEDED:
            set_check(conn, eid, status="DONE", finished_at=func.now(), failure_code=None, failure_message=None)
            _notify_done(conn, get_check(conn, eid), job["id"])  # type: ignore[arg-type]
        elif state in (FAILED, INTERRUPTED):
            j = get_job(conn, job["id"]) or {}
            set_check(conn, eid, status="FAILED", failure_code=(j.get("failure_code") or "INTERNAL_ERROR")[:32],
                      failure_message=(j.get("failure_message") or "")[:500], finished_at=func.now())
        elif state == CANCELED:
            set_check(conn, eid, status="CANCELED", finished_at=func.now())
        sp.commit()
    except Exception:  # noqa: BLE001 - 종료 훅(작업 해제)을 되돌리지 않는다
        sp.rollback()
        log.exception("등가성 판정 %s 종료 훅 실패(job %s)", eid, job["id"])


def on_retry(conn: Connection, old: Mapping[str, Any], new_id: str) -> None:
    p = old.get("params") or {}
    eid = p.get("eq_id") if isinstance(p, Mapping) else None
    if not isinstance(eid, str) or old["job_type"] != EQ_CHECK_JOB:
        return
    row = get_check(conn, eid, for_update=True)
    if row is not None and row["job_id"] == old["id"]:
        set_check(conn, eid, job_id=new_id, status="RUNNING", verdict=None, summary=None, failure_code=None,
                  failure_message=None, finished_at=None)


def job_terminal(conn: Connection, job_id: str | None) -> bool:
    j = get_job(conn, job_id) if job_id else None
    return j is None or j["state"] in TERMINAL


__all__: Sequence[str] = ["label", "latest_versions", "get_version", "versions", "name_taken", "insert_version", "soft_delete",
                          "restore", "next_eq_no", "insert_check", "get_check", "set_check", "count_active", "list_for_study",
                          "by_job", "enqueue", "done_notice", "on_job_end", "on_retry", "job_terminal"]
