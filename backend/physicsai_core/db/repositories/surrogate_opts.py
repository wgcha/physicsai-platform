"""⑤ 플랫폼 내장 최적화 저장소(phase3 §18.3·§18.4·§18.7 S13): surrogate_opts·surrogate_opt_iters 행, 탐색·검증 배치 생성,
반복 작업(SURROGATE_OPT) 투입, 종료 훅, 일괄 취소.

API(생성·조회·취소·이어서 실행), 워커(SO_COLLECT~SO_NEXT), 종료 훅(job_end)이 같이 쓴다. 권한 판단은 호출부 몫.
300줄 분할(R-B): 조회는 `surrogate_opts_read`, 갱신(행·검증 배치 생성)은 `surrogate_opts_write`(여기서 재노출).
종료 훅·일괄 취소와 `enqueue_round`·`complete_final`(시험 monkeypatch 대상)은 이 파일."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from sqlalchemy import func
from sqlalchemy.engine import Connection

from ...state_machine import CANCELED, FAILED, INTERRUPTED, SUCCEEDED, TERMINAL
from . import predict_batches as pb_repo
from .jobs import get_job, insert_job, request_cancel
from .surrogate_opts_read import (  # noqa: F401 - 기존 경로 재노출
    ACTIVE, TERMINAL_OPT, ROUND_JOB_TYPE, ROUND_FAIL_REASONS, opt_label, opt_dir_rel, new_opt_id, next_opt_no, get,
    list_for_study, active_for_study, iters, get_iter, owned_iter_of_batch, batch_owner,
)
from .surrogate_opts_write import (  # noqa: F401 - 기존 경로 재노출
    create_opt, set_opt, add_iter, set_iter, fail, _study, create_opt_batch,
)

log = logging.getLogger("physicsai_core.surrogate_opts")


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
        if it["kind"] in ("REUSE", "EXTRA"):  # 추가 검증 배치는 ④ 일반 배치처럼 따로 취소(S17)
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
