"""알림 저장소(계약 §6.9, §13)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import and_, delete, func, select, text, update
from sqlalchemy.engine import Connection

from ...job_types import job_label
from ..tables import jobs, notifications, studies, worker_slot

EVENTS = (
    "JOB_STARTED",
    "JOB_SUCCEEDED",
    "JOB_FAILED",
    "JOB_CANCELED",
    "JOB_INTERRUPTED",
    "MY_TURN_NEXT",
    "HPC_COLLECTED",
    "HPC_PARTIAL_FAILED",
    "ENV_CHECK_DONE",
)


def _hpc_counts(result: dict[str, Any] | None) -> tuple[int, int, int] | None:
    """TD_SOLVE 결과의 (제출, 실패, 회수) 수. 없으면 None."""
    r = result or {}
    if "submitted" not in r:
        return None
    return int(r.get("submitted") or 0), int(r.get("failed") or 0), int(r.get("collected") or 0)


def _title(event: str, label: str, study_title: str, failure_code: str | None,
           result: dict[str, Any] | None = None) -> tuple[str, str]:
    st = f"{label} ({study_title})"
    if event == "JOB_STARTED":
        return f"실행 시작: {st}", "작업이 실행을 시작했습니다."
    if event == "JOB_SUCCEEDED":
        return f"완료: {st}", "작업이 완료되었습니다."
    if event == "JOB_FAILED":
        return f"실패: {st} — {failure_code or 'INTERNAL_ERROR'}", "작업이 실패했습니다. 로그를 확인하세요."
    if event == "JOB_CANCELED":
        return "관리자가 작업을 취소했습니다", f"{st} 작업이 취소되었습니다."
    if event == "JOB_INTERRUPTED":
        return "워커 중단으로 작업이 멈췄습니다", f"{st} 작업이 중단되었습니다(WORKER_LOST). 재시도할 수 있습니다."
    if event == "MY_TURN_NEXT":
        return f"다음 차례입니다: {st}", "현재 실행 중인 작업이 끝나면 이 작업이 실행됩니다."
    if event == "HPC_COLLECTED":
        cnt = _hpc_counts(result)
        if cnt is not None:
            return f"PBS 결과 회수 완료 — {cnt[0]}개 중 {cnt[2]}개 회수", f"{st}의 PBS 결과를 회수했습니다."
        return "PBS 결과 회수 완료", f"{st}의 PBS 결과를 회수했습니다."
    if event == "HPC_PARTIAL_FAILED":
        cnt = _hpc_counts(result) or (0, 0, 0)
        return (f"PBS 해석 일부 실패 — {cnt[0]}개 중 {cnt[1]}개 실패, 나머지 회수 진행",
                f"{st}의 일부 run이 실패했습니다. 성공한 run만 회수합니다.")
    return event, ""


def notify_job(conn: Connection, job_id: str, event: str) -> int:
    """작업 등록자에게 알림 1건. 생성된 seq를 돌려준다."""
    assert event in EVENTS
    row = conn.execute(
        select(
            jobs.c.id,
            jobs.c.study_id,
            jobs.c.project_id,
            jobs.c.job_type,
            jobs.c.created_by,
            jobs.c.failure_code,
            jobs.c.result,
            studies.c.title,
        )
        .select_from(jobs.join(studies, studies.c.id == jobs.c.study_id))
        .where(jobs.c.id == job_id)
    ).one()
    title, body = _title(event, job_label(row.job_type), row.title, row.failure_code, row.result)
    return conn.execute(
        notifications.insert()
        .values(
            user_id=row.created_by,
            event=event,
            job_id=row.id,
            study_id=row.study_id,
            project_id=row.project_id,
            title=title[:120],
            body=body[:500],
        )
        .returning(notifications.c.seq)
    ).scalar_one()


def notify_user(conn: Connection, user_id: str, event: str, title: str, body: str = "") -> int:
    """작업과 무관한 알림(ENV_CHECK_DONE 등, job_id·study_id NULL)."""
    assert event in EVENTS
    return conn.execute(
        notifications.insert()
        .values(user_id=user_id, event=event, job_id=None, study_id=None, project_id=None, title=title[:120], body=body[:500])
        .returning(notifications.c.seq)
    ).scalar_one()


def recompute_my_turn(conn: Connection) -> str | None:
    """SLOT 레인 대기 1번이 된 작업에 MY_TURN_NEXT(슬롯 사용 중일 때, 작업당 1회)."""
    holder = conn.execute(select(worker_slot.c.holder_job_id).where(worker_slot.c.id == 1)).scalar()
    if holder is None:
        return None
    first = conn.execute(
        select(jobs.c.id, jobs.c.next_notified_at)
        .where(and_(jobs.c.state == "QUEUED", jobs.c.lane == "SLOT", jobs.c.cancel_requested_at.is_(None)))
        .order_by(jobs.c.queue_seq)
        .limit(1)
    ).first()
    if first is None or first.next_notified_at is not None:
        return None
    conn.execute(update(jobs).where(jobs.c.id == first.id).values(next_notified_at=func.now()))
    notify_job(conn, first.id, "MY_TURN_NEXT")
    return first.id


def _item(r: Any) -> dict[str, Any]:
    return {
        "seq": r.seq,
        "event": r.event,
        "job_id": r.job_id,
        "study_id": r.study_id,
        "project_id": r.project_id,
        "title": r.title,
        "body": r.body,
        "created_at": r.created_at,
        "read_at": r.read_at,
    }


def list_for_user(
    conn: Connection, user_id: str, *, after_seq: int | None, limit: int, before_seq: int | None = None,
    retention_days: int = 30,
) -> list[dict[str, Any]]:
    q = select(notifications).where(notifications.c.user_id == user_id)
    if after_seq is not None:
        q = q.where(notifications.c.seq > after_seq).order_by(notifications.c.seq.asc())
    else:
        q = q.where(notifications.c.created_at >= func.now() - text(f"interval '{int(retention_days)} days'"))
        if before_seq is not None:
            q = q.where(notifications.c.seq < before_seq)
        q = q.order_by(notifications.c.seq.desc())
    return [_item(r) for r in conn.execute(q.limit(limit))]


def unread_count(conn: Connection, user_id: str) -> tuple[int, int]:
    unread = conn.execute(
        select(func.count()).where(and_(notifications.c.user_id == user_id, notifications.c.read_at.is_(None)))
    ).scalar_one()
    max_seq = conn.execute(
        select(func.coalesce(func.max(notifications.c.seq), 0)).where(notifications.c.user_id == user_id)
    ).scalar_one()
    return int(unread), int(max_seq)


def mark_read(conn: Connection, user_id: str, seqs: list[int] | None, all_: bool) -> None:
    q = update(notifications).where(and_(notifications.c.user_id == user_id, notifications.c.read_at.is_(None)))
    if not all_:
        q = q.where(notifications.c.seq.in_(seqs or []))
    conn.execute(q.values(read_at=func.now()))


def purge_older_than(conn: Connection, days: int) -> int:
    res = conn.execute(
        delete(notifications).where(notifications.c.created_at < func.now() - text(f"interval '{int(days)} days'"))
    )
    return res.rowcount or 0
