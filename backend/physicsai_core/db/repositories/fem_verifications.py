"""④ 조립 FEM 검증 저장소(phase3 §21.3.4·§21.3.9 S16): fem_verifications 행, 종료 훅·재시도 훅.

DB에는 경로·상태·수치 요약만 둔다(파일 본문 없음)."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import and_, func, select, tuple_, update
from sqlalchemy.engine import Connection

from ...state_machine import CANCELED, FAILED, INTERRUPTED, SUCCEEDED, TERMINAL
from ..tables import fem_verifications as fv, jobs, notifications, studies
from ..tables.fem_verify import FV_ACTIVE, FV_STATUSES
from .jobs import get_job, insert_job, row_dict

log = logging.getLogger(__name__)

FEM_VERIFY_JOB = "FEM_VERIFY"
PREDICT_FAILED_MESSAGE = "함께 실행한 예측이 실패했습니다"


def label(fv_no: int) -> str:
    return f"FV-{fv_no:03d}"


def next_fv_no(conn: Connection, study_id: str) -> int:
    """Study별 다음 번호(호출자가 Study 행을 FOR UPDATE로 잡은 뒤)."""
    return int(conn.execute(select(func.coalesce(func.max(fv.c.fv_no), 0)).where(fv.c.study_id == study_id)).scalar_one()) + 1


def insert(conn: Connection, **values: Any) -> dict[str, Any]:
    fid = values.pop("id", None) or str(uuid.uuid4())
    conn.execute(fv.insert().values(id=fid, **values))
    return get(conn, fid)  # type: ignore[return-value]


def get(conn: Connection, fid: str, *, for_update: bool = False) -> dict[str, Any] | None:
    q = select(fv).where(fv.c.id == fid)
    if for_update:
        q = q.with_for_update()
    return row_dict(conn.execute(q).first())


def set_row(conn: Connection, fid: str, **values: Any) -> None:
    conn.execute(update(fv).where(fv.c.id == fid).values(**values))


def count_active(conn: Connection, study_id: str) -> int:
    q = select(func.count()).select_from(fv).where(and_(fv.c.study_id == study_id, fv.c.status.in_(FV_ACTIVE)))
    return int(conn.execute(q).scalar_one())


def active_duplicate(conn: Connection, study_id: str, predict_job_id: str | None, assem_kind: str,
                     assem_ref: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """같은 예측·같은 조립 원본의 진행 중 검증(409 FEM_VERIFY_ACTIVE). 예측이 아직 없으면(동반) 검사하지 않는다."""
    if not predict_job_id:
        return None
    q = select(fv).where(and_(fv.c.study_id == study_id, fv.c.predict_job_id == predict_job_id, fv.c.assem_kind == assem_kind,
                              fv.c.status.in_(FV_ACTIVE)))
    for r in conn.execute(q):
        if (r.assem_ref or None) == (dict(assem_ref) if assem_ref else None):
            return row_dict(r)
    return None


def list_for_study(conn: Connection, study_id: str, *, predict_job_ids: Sequence[str] | None = None,
                   batch_id: str | None = None, opt_id: str | None = None, statuses: Sequence[str] | None = None,
                   limit: int = 50, after: tuple[datetime, str] | None = None) -> list[dict[str, Any]]:
    conds = [fv.c.study_id == study_id]
    if predict_job_ids is not None:
        conds.append(fv.c.predict_job_id.in_(list(predict_job_ids)))
    if batch_id:
        conds.append(fv.c.source_ref["batch_id"].astext == batch_id)
    if opt_id:
        conds.append(fv.c.source_ref["opt_id"].astext == opt_id)
    if statuses:
        conds.append(fv.c.status.in_(list(statuses)))
    if after is not None:
        conds.append(tuple_(fv.c.created_at, fv.c.id) < tuple_(after[0], after[1]))
    q = select(fv).where(and_(*conds)).order_by(fv.c.created_at.desc(), fv.c.id.desc()).limit(limit)
    return [row_dict(r) for r in conn.execute(q)]


def by_predict_job(conn: Connection, job_id: str) -> list[dict[str, Any]]:
    return [row_dict(r) for r in conn.execute(select(fv).where(fv.c.predict_job_id == job_id))]


def by_job(conn: Connection, job_id: str) -> dict[str, Any] | None:
    return row_dict(conn.execute(select(fv).where(fv.c.job_id == job_id)).first())


def _study(conn: Connection, study_id: str) -> dict[str, Any]:
    return row_dict(conn.execute(select(studies).where(studies.c.id == study_id)).first())


def enqueue_fem_verify(conn: Connection, row: Mapping[str, Any]) -> dict[str, Any]:
    """FEM_VERIFY(QUEUED, 등록자 = 검증 등록자) + 검증 RUNNING·job_id."""
    hpc = (row.get("options") or {}).get("hpc")
    job = insert_job(conn, study=_study(conn, row["study_id"]), job_type=FEM_VERIFY_JOB,
                     params={"fem_verify_id": row["id"], "fv_no": int(row["fv_no"]), "hpc": hpc},
                     user_id=row["created_by"], user_name=row["created_by_name"])
    set_row(conn, row["id"], status="RUNNING", job_id=job["id"], failure_code=None, failure_message=None, finished_at=None)
    return job


# ---- 종료 훅(job_end) ---------------------------------------------------------------------------


def done_notice(fv_no: int, summary: Mapping[str, Any] | None) -> tuple[str, str]:
    """"FEM 검증 FV-003 완료 — 최대 오차 7.2% (MaxStress)" / "… — 응답 비교 없음"."""
    s = summary or {}
    mx, worst = s.get("max_abs_diff_pct"), s.get("worst")
    if isinstance(mx, (int, float)) and worst:
        title = f"FEM 검증 {label(fv_no)} 완료 — 최대 오차 {mx:.1f}% ({worst})"
    else:
        title = f"FEM 검증 {label(fv_no)} 완료 — 응답 비교 없음"
    return title, "조립 상태 해석과 예측 비교가 끝났습니다."


def _notify_done(conn: Connection, row: Mapping[str, Any], job_id: str) -> int:
    title, body = done_notice(row["fv_no"], row.get("summary"))
    project_id = conn.execute(select(studies.c.project_id).where(studies.c.id == row["study_id"])).scalar()
    return conn.execute(
        notifications.insert()
        .values(user_id=row["created_by"], event="FEM_VERIFY_DONE", job_id=job_id, study_id=row["study_id"],
                project_id=project_id, title=title[:120], body=body[:500])
        .returning(notifications.c.seq)
    ).scalar_one()


def _first_failure(conn: Connection, job_id: str) -> tuple[str, str]:
    j = get_job(conn, job_id) or {}
    return (j.get("failure_code") or "INTERNAL_ERROR"), (j.get("failure_message") or "")[:500]


def on_job_end(conn: Connection, job: Mapping[str, Any], state: str) -> None:
    """동반 PREDICT·FEM_VERIFY 종료(§21.3.9). 검증이 이미 종료 상태면 아무것도 하지 않는다(멱등). savepoint — 실패는 로그만."""
    p = job.get("params") or {}
    fid = p.get("fem_verify_id") if isinstance(p, Mapping) else None
    if not isinstance(fid, str) or job["job_type"] not in ("PREDICT", FEM_VERIFY_JOB):
        return
    sp = conn.begin_nested()
    try:
        _on_job_end(conn, job, state, fid)
        sp.commit()
    except Exception:  # noqa: BLE001 - 종료 훅(작업 해제)을 되돌리지 않는다
        sp.rollback()
        log.exception("FEM 검증 %s 종료 훅 실패(job %s)", fid, job["id"])


def _on_job_end(conn: Connection, job: Mapping[str, Any], state: str, fid: str) -> None:
    row = get(conn, fid, for_update=True)
    if row is None or row["status"] not in FV_ACTIVE:
        return
    if job["job_type"] == "PREDICT":
        if row["predict_job_id"] != job["id"] or row["status"] != "WAITING_PREDICT":
            return
        if state == SUCCEEDED:
            enqueue_fem_verify(conn, row)
        elif state in (FAILED, INTERRUPTED):
            set_row(conn, fid, status="FAILED", failure_code="PREDICT_FAILED", failure_message=PREDICT_FAILED_MESSAGE,
                    finished_at=func.now())
        elif state == CANCELED:
            set_row(conn, fid, status="CANCELED", finished_at=func.now())
        return
    if row["job_id"] != job["id"]:
        return
    if state == SUCCEEDED:
        set_row(conn, fid, status="DONE", finished_at=func.now(), failure_code=None, failure_message=None)
        _notify_done(conn, get(conn, fid), job["id"])  # type: ignore[arg-type]
    elif state in (FAILED, INTERRUPTED):
        code, msg = _first_failure(conn, job["id"])
        set_row(conn, fid, status="FAILED", failure_code=code[:32], failure_message=msg, finished_at=func.now())
    elif state == CANCELED:
        set_row(conn, fid, status="CANCELED", finished_at=func.now())


def on_retry(conn: Connection, old: Mapping[str, Any], new_id: str) -> None:
    """재시도 훅: 동반 PREDICT → predict_job_id 갱신·WAITING_PREDICT, FEM_VERIFY → job_id 갱신·RUNNING."""
    p = old.get("params") or {}
    fid = p.get("fem_verify_id") if isinstance(p, Mapping) else None
    if not isinstance(fid, str):
        return
    row = get(conn, fid, for_update=True)
    if row is None:
        return
    common = {"failure_code": None, "failure_message": None, "finished_at": None, "summary": None}
    if old["job_type"] == "PREDICT" and row["predict_job_id"] == old["id"]:
        set_row(conn, fid, predict_job_id=new_id, status="WAITING_PREDICT", **common)
    elif old["job_type"] == FEM_VERIFY_JOB and row["job_id"] == old["id"]:
        set_row(conn, fid, job_id=new_id, status="RUNNING", **common)


def job_terminal(conn: Connection, job_id: str | None) -> bool:
    j = get_job(conn, job_id) if job_id else None
    return j is None or j["state"] in TERMINAL


__all__ = ["FV_ACTIVE", "FV_STATUSES", "label", "next_fv_no", "insert", "get", "set_row", "count_active", "active_duplicate", "list_for_study",
           "by_predict_job", "by_job", "enqueue_fem_verify", "done_notice", "on_job_end", "on_retry", "job_terminal", "jobs"]


def reusable_predicts(conn: Connection, study_id: str, param_set_id: str, model_id: str, limit: int = 50) -> list[dict[str, Any]]:
    """같은 세트·모델의 성공한 parametric PREDICT(일괄 하위 제외), 최신순(§21.3.2 values 재사용 후보)."""
    im = jobs.c.params["input_mode"].astext
    q = (select(jobs).where(and_(
        jobs.c.study_id == study_id, jobs.c.job_type == "PREDICT", jobs.c.state == SUCCEEDED,
        jobs.c.params["batch_run"].is_(None), (im.is_(None)) | (im == "parametric"),
        jobs.c.params["param_set_id"].astext == param_set_id, jobs.c.params["model_id"].astext == model_id))
        .order_by(jobs.c.created_at.desc(), jobs.c.id.desc()).limit(limit))
    return [row_dict(r) for r in conn.execute(q)]
