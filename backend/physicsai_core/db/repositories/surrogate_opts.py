"""⑤ 플랫폼 내장 최적화 저장소(phase3 §18.3·§18.4·§18.7 S13): surrogate_opts·surrogate_opt_iters 행, 탐색·검증 배치 생성,
반복 작업(SURROGATE_OPT) 투입, 종료 훅, 일괄 취소.

API(생성·조회·취소·이어서 실행), 워커(SO_COLLECT~SO_NEXT), 종료 훅(job_end)이 같이 쓴다. 권한 판단은 호출부 몫.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Mapping
from typing import Any

from sqlalchemy import and_, func, select, update
from sqlalchemy.engine import Connection

from ...state_machine import CANCELED, FAILED, INTERRUPTED, SUCCEEDED, TERMINAL
from ...stage4_predict.batch_matrix import BatchMatrix, batch_dir_rel
from ..tables import studies, surrogate_opt_iters, surrogate_opts
from . import predict_batches as pb_repo
from .jobs import get_job, insert_job, request_cancel, row_dict

log = logging.getLogger("physicsai_core.surrogate_opts")
ACTIVE = ("EXPLORING", "FITTING", "VERIFYING", "FINALIZING")
TERMINAL_OPT = ("DONE", "FAILED", "CANCELED")
ROUND_JOB_TYPE = "SURROGATE_OPT"
# 반복 작업 실패 코드 중 정지 사유로 그대로 쓰는 것(그 밖은 ROUND_FAILED)
ROUND_FAIL_REASONS = ("VERIFY_ALL_FAILED", "TOO_FEW_POINTS", "SURROGATE_TIMEOUT", "SURROGATE_FIT_FAILED", "NO_FREE_VARIABLE")


def opt_label(opt_no: int) -> str:
    """opt_no → `SO-001`."""
    return f"SO-{int(opt_no):03d}"


def opt_dir_rel(dir_name: str, opt_no: int) -> str:
    return f"{dir_name.rstrip('/')}/{opt_label(opt_no)}"


def new_opt_id() -> str:
    return str(uuid.uuid4())


# ---- 조회 --------------------------------------------------------------------------------------


def next_opt_no(conn: Connection, study_id: str) -> int:
    """Study별 다음 opt_no(1부터). 호출부가 Study 행을 FOR UPDATE로 잠근 트랜잭션에서 부른다(D3-25)."""
    cur = conn.execute(select(func.max(surrogate_opts.c.opt_no)).where(surrogate_opts.c.study_id == study_id)).scalar()
    return int(cur or 0) + 1


def get(conn: Connection, opt_id: str, *, for_update: bool = False) -> dict[str, Any] | None:
    q = select(surrogate_opts).where(surrogate_opts.c.id == opt_id)
    if for_update:
        q = q.with_for_update()
    return row_dict(conn.execute(q).first())


def list_for_study(conn: Connection, study_id: str, limit: int = 200) -> list[dict[str, Any]]:
    q = (select(surrogate_opts).where(surrogate_opts.c.study_id == study_id)
         .order_by(surrogate_opts.c.opt_no.desc()).limit(limit))
    return [row_dict(r) for r in conn.execute(q)]


def active_for_study(conn: Connection, study_id: str) -> dict[str, Any] | None:
    return row_dict(conn.execute(select(surrogate_opts).where(and_(
        surrogate_opts.c.study_id == study_id, surrogate_opts.c.status.in_(ACTIVE)))).first())


def iters(conn: Connection, opt_id: str) -> list[dict[str, Any]]:
    q = select(surrogate_opt_iters).where(surrogate_opt_iters.c.opt_id == opt_id).order_by(surrogate_opt_iters.c.iter_no)
    return [row_dict(r) for r in conn.execute(q)]


def get_iter(conn: Connection, opt_id: str, iter_no: int) -> dict[str, Any] | None:
    return row_dict(conn.execute(select(surrogate_opt_iters).where(and_(
        surrogate_opt_iters.c.opt_id == opt_id, surrogate_opt_iters.c.iter_no == iter_no))).first())


def owned_iter_of_batch(conn: Connection, batch_id: str) -> dict[str, Any] | None:
    """배치를 소유한(EXPLORE·VERIFY) 반복 행 + opt 열(opt_status·opt_iter_no). 재사용(REUSE) 배치는 소유가 아니다."""
    q = (select(surrogate_opt_iters, surrogate_opts.c.status.label("opt_status"), surrogate_opts.c.iter_no.label("opt_iter_no"),
                surrogate_opts.c.opt_no.label("opt_no"))
         .select_from(surrogate_opt_iters.join(surrogate_opts, surrogate_opts.c.id == surrogate_opt_iters.c.opt_id))
         .where(and_(surrogate_opt_iters.c.batch_id == batch_id, surrogate_opt_iters.c.kind != "REUSE")))
    return row_dict(conn.execute(q).first())


def batch_owner(params: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """PREDICT_BATCH params.surrogate_opt `{id, opt_no, iter_no}`(최적화 소유 배치) 또는 None."""
    so = (params or {}).get("surrogate_opt") if isinstance(params, Mapping) else None
    return dict(so) if isinstance(so, Mapping) and isinstance(so.get("id"), str) else None


# ---- 갱신 --------------------------------------------------------------------------------------


def create_opt(conn: Connection, **values: Any) -> dict[str, Any]:
    conn.execute(surrogate_opts.insert().values(**values))
    return get(conn, values["id"])  # type: ignore[return-value]


def set_opt(conn: Connection, opt_id: str, **values: Any) -> None:
    conn.execute(update(surrogate_opts).where(surrogate_opts.c.id == opt_id).values(**values))


def add_iter(conn: Connection, opt_id: str, iter_no: int, kind: str, batch_id: str, *, round_job_id: str | None = None,
             candidates: list[dict[str, Any]] | None = None, fit: dict[str, Any] | None = None) -> None:
    conn.execute(surrogate_opt_iters.insert().values(opt_id=opt_id, iter_no=iter_no, kind=kind, batch_id=batch_id,
                                                     round_job_id=round_job_id, candidates=candidates, fit=fit))


def set_iter(conn: Connection, opt_id: str, iter_no: int, **values: Any) -> None:
    conn.execute(update(surrogate_opt_iters).where(and_(
        surrogate_opt_iters.c.opt_id == opt_id, surrogate_opt_iters.c.iter_no == iter_no)).values(**values))


def fail(conn: Connection, opt_id: str, reason: str) -> bool:
    """진행 중이면 FAILED + 사유(이미 종료면 그대로). 바꿨으면 True."""
    r = conn.execute(update(surrogate_opts).where(and_(surrogate_opts.c.id == opt_id, surrogate_opts.c.status.in_(ACTIVE)))
                     .values(status="FAILED", stop_reason=reason[:32], finished_at=func.now()))
    return bool(r.rowcount)


def _study(conn: Connection, study_id: str) -> dict[str, Any]:
    return row_dict(conn.execute(select(studies).where(studies.c.id == study_id)).first())  # type: ignore[return-value]


def create_opt_batch(conn: Connection, *, opt: Mapping[str, Any], iter_no: int, kind: str, matrix: BatchMatrix,
                     source_meta: Mapping[str, Any], batch_dir_name: str, simlab_mesh_name: str,
                     round_job_id: str | None = None, candidates: list[dict[str, Any]] | None = None,
                     capture: bool | None = None, display: Mapping[str, Any] | None = None
                     ) -> tuple[dict[str, Any], dict[str, Any]]:
    """최적화 소유 PREDICT_BATCH 부모 작업(QUEUED) + 배치·run 행 + 반복 행(한 트랜잭션, 등록자 = opt 등록자).

    params는 §14 서버 저장 형식 + `surrogate_opt{id, opt_no, iter_no}`(§18.4), 캡처는 opt 설정(`capture.enabled`)."""
    study = _study(conn, opt["study_id"])
    s = opt["settings"]
    batch_no = pb_repo.next_batch_no(conn, study["id"])
    batch_id = pb_repo.new_batch_id()
    dir_rel = batch_dir_rel(batch_dir_name, batch_no)
    params = {
        "batch_id": batch_id, "batch_no": batch_no, "param_set_id": opt["param_set_id"], "model_id": opt["model_id"],
        "multi_execution": int(s["multi_execution"]), "template_kind": opt["input_kind"],
        "source": {"kind": "lhs" if matrix.source_kind == "LHS" else "table", **dict(source_meta)},
        "capture": {"enabled": bool(s.get("capture")) if capture is None else bool(capture)},
        "surrogate_opt": {"id": opt["id"], "opt_no": opt["opt_no"], "iter_no": iter_no},
    }
    if display:  # D3-61 마무리 캡처: 기준안·최적안 같은 범례(fixed)
        params["display"] = dict(display)
    from .param_sets import get as _get_ps

    if (_get_ps(conn, opt["param_set_id"]) or {}).get("engine") == "native":  # geometry-engine.md §7.7: 워커가 엔진으로 분기
        params["engine"] = "native"
    result = {"batch_id": batch_id, "batch_no": batch_no, "run_count": len(matrix.rows), "dir_rel": dir_rel}
    job = insert_job(conn, study=study, job_type="PREDICT_BATCH", params=params, user_id=opt["created_by"],
                     user_name=opt["created_by_name"], result=result)
    batch = pb_repo.create_batch(
        conn, batch_id=batch_id, batch_no=batch_no, study_id=study["id"], job_id=job["id"], param_set_id=opt["param_set_id"],
        model_id=opt["model_id"], input_kind=opt["input_kind"], matrix=matrix, multi_execution=int(s["multi_execution"]),
        dir_rel=dir_rel, simlab_mesh_name=simlab_mesh_name, user_id=opt["created_by"], user_name=opt["created_by_name"],
    )
    add_iter(conn, opt["id"], iter_no, kind, batch_id, round_job_id=round_job_id, candidates=candidates)
    return job, batch


def enqueue_round(conn: Connection, opt: Mapping[str, Any], round_no: int) -> dict[str, Any]:
    """반복 작업 r(QUEUED, 등록자 = opt 등록자) + opt FITTING·current_job_id."""
    job = insert_job(conn, study=_study(conn, opt["study_id"]), job_type=ROUND_JOB_TYPE,
                     params={"surrogate_opt_id": opt["id"], "opt_no": opt["opt_no"], "round": int(round_no)},
                     user_id=opt["created_by"], user_name=opt["created_by_name"])
    set_opt(conn, opt["id"], status="FITTING", current_job_id=job["id"])
    return job


# ---- 종료 훅(job_end) -------------------------------------------------------------------------------


def _job_terminal(conn: Connection, job_id: str | None) -> bool:
    j = get_job(conn, job_id) if job_id else None
    return j is None or j["state"] in TERMINAL


def on_batch_done(conn: Connection, batch: Mapping[str, Any]) -> bool:
    """배치 DONE: 진행 중 opt의 최신 반복(EXPLORE·VERIFY) 배치이고 opt가 EXPLORING·VERIFYING이며 최신 반복 작업이 없거나 끝났으면
    반복 작업 r+1을 넣는다(재시도된 하위로 같은 배치가 다시 DONE이 돼도 두 번 넣지 않음). 최적화 소유 배치면 True
    (호출부가 PREDICT_BATCH_DONE 알림을 생략). 종료 훅 트랜잭션 안이므로 실패는 기록만 하고 올리지 않는다."""
    it = owned_iter_of_batch(conn, batch["id"])
    if it is None:
        return False
    if it["kind"] == "FINAL":  # D3-61: 마무리 캡처 배치 완료 → opt DONE(이미 DONE이면 아무것도 안 함)
        _complete_final_safely(conn, it["opt_id"], "DONE", None)
        return True
    opt = get(conn, it["opt_id"], for_update=True)
    if (opt is None or opt["status"] not in ("EXPLORING", "VERIFYING") or opt["iter_no"] != it["iter_no"]
            or not _job_terminal(conn, opt["current_job_id"])):
        return True
    _enqueue_safely(conn, opt, it["iter_no"] + 1)
    return True


def _enqueue_safely(conn: Connection, opt: Mapping[str, Any], round_no: int) -> dict[str, Any] | None:
    sp = conn.begin_nested()
    try:
        job = enqueue_round(conn, opt, round_no)
        sp.commit()
        return job
    except Exception:  # noqa: BLE001 - 종료 훅(하위 PREDICT 해제)을 되돌리지 않는다
        sp.rollback()
        log.exception("내장 최적화 %s 반복 %s 작업을 넣지 못했습니다(이어서 실행으로 복구)", opt["id"], round_no)
        return None


def restore_verifying(conn: Connection, opt: Mapping[str, Any], round_no: int) -> dict[str, Any] | None:
    """반복 r의 검증 배치가 이미 등록돼 있으면(SO_NEXT 커밋 뒤 작업 실패·lease 상실) opt를 VERIFYING으로 되돌리고,
    배치가 이미 DONE이면 반복 r+1을 바로 넣는다. 등록된 배치가 없으면 None(반복 작업을 다시 실행해야 함)."""
    it = get_iter(conn, opt["id"], round_no)
    if it is None or it["kind"] not in ("VERIFY", "FINAL"):
        return None
    b = pb_repo.get(conn, it["batch_id"])
    if it["kind"] == "FINAL":  # 마무리 캡처까지 등록됐으면 FINALIZING(배치가 끝났으면 바로 DONE)
        set_opt(conn, opt["id"], status="FINALIZING", stop_reason=(opt.get("final") or {}).get("stop_reason") or opt["stop_reason"],
                finished_at=None)
        if b is not None and b["status"] in ("DONE", "FAILED", "CANCELED"):
            complete_final(conn, opt["id"], "DONE" if b["status"] == "DONE" else "FAILED",
                           None if b["status"] == "DONE" else "기준안·최적안 캡처 배치가 끝나지 않았습니다")
        return {"batch_id": it["batch_id"], "round_job_id": None}
    set_opt(conn, opt["id"], status="VERIFYING", iter_no=round_no, stop_reason=None, finished_at=None)
    job = None
    if b is not None and b["status"] == "DONE":
        job = _enqueue_safely(conn, {**opt, "status": "VERIFYING", "iter_no": round_no}, round_no + 1)
    return {"batch_id": it["batch_id"], "round_job_id": job["id"] if job else None}


def on_batch_parent_end(conn: Connection, batch: Mapping[str, Any], state: str) -> None:
    """최적화 소유 배치의 부모 PREDICT_BATCH 실패·중단·취소 → opt FAILED BATCH_FAILED(이미 종료면 무시)."""
    if state not in (FAILED, INTERRUPTED, CANCELED):
        return
    it = owned_iter_of_batch(conn, batch["id"])
    if it is not None and it["kind"] == "FINAL":  # 캡처 배치 실패·취소는 최적화 결과를 지우지 않는다 — DONE + 캡처 없음
        _complete_final_safely(conn, it["opt_id"], "CANCELED" if state == CANCELED else "FAILED",
                       "기준안·최적안 캡처 배치가 " + ("취소되었습니다" if state == CANCELED else "실패했습니다"))
    elif it is not None and it["opt_iter_no"] == it["iter_no"]:
        fail(conn, it["opt_id"], "BATCH_FAILED")


def on_round_end(conn: Connection, job: Mapping[str, Any], state: str) -> None:
    """반복 작업 실패·중단 → opt FAILED(실패 코드가 알려진 정지 사유면 그것, 아니면 ROUND_FAILED), 취소 → CANCELED.
    단 SO_NEXT가 이미 검증 배치를 등록했으면(opt VERIFYING·iter_no = 이 반복) 그대로 두어 배치 완료 훅이 이어 간다.
    opt가 이미 종료이거나 이 작업이 최신 반복 작업이 아니면 무시."""
    oid = (job.get("params") or {}).get("surrogate_opt_id")
    opt = get(conn, oid, for_update=True) if isinstance(oid, str) else None
    if opt is None or opt["status"] not in ACTIVE or opt["current_job_id"] != job["id"]:
        return
    rnd = (job.get("params") or {}).get("round")
    if state != SUCCEEDED and opt["status"] in ("VERIFYING", "FINALIZING") and isinstance(rnd, int) \
            and get_iter(conn, opt["id"], rnd) is not None:
        log.warning("내장 최적화 %s 반복 %s 작업이 %s로 끝났지만 검증 배치가 등록돼 있어 계속합니다", opt["id"], rnd, state)
        return
    if state in (FAILED, INTERRUPTED):
        code = job.get("failure_code") or (get_job(conn, job["id"]) or {}).get("failure_code")  # 해제 경로는 갱신 전 행
        fail(conn, opt["id"], code if code in ROUND_FAIL_REASONS else "ROUND_FAILED")
    elif state == CANCELED:
        set_opt(conn, opt["id"], status="CANCELED", stop_reason="CANCELED", finished_at=func.now())


def _complete_final_safely(conn: Connection, opt_id: str, status: str, reason: str | None) -> bool:
    """종료 훅 안에서 complete_final(savepoint) — 실패는 기록만 하고 하위·부모 종료 트랜잭션을 되돌리지 않는다."""
    sp = conn.begin_nested()
    try:
        done = complete_final(conn, opt_id, status, reason)
        sp.commit()
        return done
    except Exception:  # noqa: BLE001
        sp.rollback()
        log.exception("내장 최적화 %s 마무리(DONE)를 기록하지 못했습니다(이어서 실행·재조회로 복구)", opt_id)
        return False


def complete_final(conn: Connection, opt_id: str, status: str, reason: str | None) -> bool:
    """마무리(D3-61): FINALIZING opt → DONE + final.status(DONE|FAILED|CANCELED|SKIPPED)·사유 + 완료 알림 1건(final.notice).
    이미 DONE 등 FINALIZING이 아니면 아무것도 하지 않는다(멱등). 바꿨으면 True."""
    from . import notifications as notif_repo

    opt = get(conn, opt_id, for_update=True)
    if opt is None or opt["status"] != "FINALIZING":
        return False
    final = {**(opt.get("final") or {}), "status": status, "reason": reason}
    stop = final.get("stop_reason") or opt["stop_reason"]
    set_opt(conn, opt_id, status="DONE", final=final, stop_reason=stop, finished_at=func.now())
    notice = final.get("notice") or {}
    if notice.get("title"):
        notif_repo.notify_opt_done(conn, opt, opt["current_job_id"], notice["title"], notice.get("body") or "")
    return True


# ---- 일괄 취소 --------------------------------------------------------------------------------------


def cancel(conn: Connection, opt: Mapping[str, Any], user_id: str) -> list[str]:
    """opt를 먼저 CANCELED로 두고(훅이 아무것도 하지 않게) 비종료 반복 작업 + 진행 중 배치(부모·비종료 하위 전부) 취소.
    멱등. 취소 요청한 작업 id 목록."""
    if opt["status"] == "FINALIZING":  # 최적화는 끝났다 — 캡처만 취소하고 결과는 DONE으로 남긴다
        complete_final(conn, opt["id"], "CANCELED", "사용자가 캡처를 취소했습니다")
    elif opt["status"] in ACTIVE:
        set_opt(conn, opt["id"], status="CANCELED", stop_reason="CANCELED", finished_at=func.now())
    targets: list[str] = []
    for it in iters(conn, opt["id"]):
        if it["round_job_id"]:
            targets.append(it["round_job_id"])
        if it["kind"] == "REUSE":
            continue
        b = pb_repo.get(conn, it["batch_id"], for_update=True)
        if b is None:
            continue
        pb_repo.cancel_active(conn, b["id"])
        targets += [b["job_id"], *pb_repo.active_child_job_ids(conn, b["id"])]
    if opt.get("current_job_id"):
        targets.append(opt["current_job_id"])
    done: list[str] = []
    for jid in dict.fromkeys(targets):
        j = get_job(conn, jid)
        if j is None or j["state"] in TERMINAL or j["cancel_requested_at"] is not None:
            continue
        request_cancel(conn, jid, user_id)
        done.append(jid)
    return done
