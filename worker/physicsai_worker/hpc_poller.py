"""워커 HPC 폴러(§12.4): WAITING_HPC 작업의 PBS 상태 조회·취소·종료 판정(T10·T10b·T13). Worker가 상속한다."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from physicsai_core.db.repositories import hpc as hpc_repo
from physicsai_core.db.repositories import jobs as jobs_repo
from physicsai_core.db.repositories import train as train_repo
from physicsai_core.hpc.gateway import HpcGatewayError
from physicsai_core.state_machine import hpc_terminal_transition

log = logging.getLogger("physicsai_worker")  # 분리 전 runtime과 같은 로거 이름

# hpc_jobs 상태 → train_runs 상태(phase2 §6.5 HPC_WAIT)
RUN_STATE_BY_HPC = {"SUCCEEDED": "SOLVED", "FAILED": "SOLVE_FAILED", "LOST": "SOLVE_FAILED", "CANCELED": "SOLVE_FAILED"}


class HpcPollerMixin:
    """HPC 폴러 메서드 묶음(`poll_hpc_once`). runtime.Worker가 상속한다."""

    # ---- HPC 폴러(§12.4) ----
    def poll_hpc_once(self) -> None:
        hcfg = self.settings.hpc
        with self.engine.connect() as conn:
            waiting = hpc_repo.waiting_jobs(conn)
        for job in waiting:
            with self.engine.connect() as conn:
                hjobs = hpc_repo.for_job(conn, job["id"])
            active = [h for h in hjobs if h["state"] not in hpc_repo.HPC_TERMINAL]
            if job["cancel_requested_at"] is not None:
                cancel_failed = []
                for h in active:
                    try:
                        self.hpc.cancel(h["external_job_id"])
                    except HpcGatewayError as exc:
                        # 취소 명령 실패: CANCELED로 적지 않는다 — CANCEL_REQUESTED 유지, 다음 폴링에서 다시 시도(변경 메모 C18)
                        log.warning("PBS 취소 실패: %s", exc)
                        cancel_failed.append(h["external_job_id"])
                        with self.engine.begin() as conn:
                            hpc_repo.update_hpc(conn, h["id"], h["version"], state="CANCEL_REQUESTED",
                                                error_message=f"취소 명령 실패: {exc}"[:500])
                        continue
                    with self.engine.begin() as conn:
                        hpc_repo.update_hpc(conn, h["id"], h["version"], state="CANCELED", finished_at=datetime.now(timezone.utc))
                        if job["job_type"] == "TD_SOLVE":
                            train_repo.set_run_state_by_hpc(conn, h["id"], RUN_STATE_BY_HPC["CANCELED"])
                with self.engine.begin() as conn:
                    if cancel_failed:
                        job_now = jobs_repo.get_job(conn, job["id"])
                        if job_now is not None and job_now["state"] == "WAITING_HPC" and job_now["attention_code"] != "HPC_CANCEL_FAILED":
                            hpc_repo.set_attention(conn, job_now, "HPC_CANCEL_FAILED")
                            from physicsai_core.db.repositories import (
                                notifications as notif_repo,
                            )

                            notif_repo.notify_job(conn, job["id"], "HPC_CANCEL_FAILED")
                    else:
                        hpc_repo.cancel_waiting(conn, jobs_repo.get_job(conn, job["id"]) or job)
                continue
            result = dict(job["result"] or {})
            gateway_error = False
            for h in active:
                try:
                    st = self.hpc.status(h["external_job_id"])
                except HpcGatewayError as exc:
                    gateway_error = True
                    log.warning("PBS 상태 조회 실패: %s", exc)
                    continue
                vals: dict[str, Any] = {"external_state_raw": st.raw_state}
                seen_running = h["state"] in ("QUEUED", "RUNNING")
                if st.not_found and seen_running and h["external_state_raw"] is not None:
                    vals.update(state="SUCCEEDED", finished_at=datetime.now(timezone.utc), unknown_count=0)
                elif st.state in ("QUEUED", "RUNNING"):
                    vals.update(state=st.state, unknown_count=0)
                elif st.state == "FINISHED":
                    ok = st.exit_code == 0 if st.exit_code is not None else True
                    vals.update(state="SUCCEEDED" if ok else "FAILED", exit_code=st.exit_code,
                                finished_at=datetime.now(timezone.utc), unknown_count=0)
                else:
                    cnt = int(h["unknown_count"]) + 1
                    vals.update(unknown_count=cnt)
                    if cnt >= hcfg.lost_after_polls:
                        vals.update(state="LOST", finished_at=datetime.now(timezone.utc))
                with self.engine.begin() as conn:
                    hpc_repo.update_hpc(conn, h["id"], h["version"], **vals)
                    new_state = vals.get("state")
                    if job["job_type"] == "TD_SOLVE" and new_state in RUN_STATE_BY_HPC and new_state != h["state"]:
                        train_repo.set_run_state_by_hpc(conn, h["id"], RUN_STATE_BY_HPC[new_state])
            with self.engine.begin() as conn:
                job_now = jobs_repo.get_job(conn, job["id"])
                if job_now is None or job_now["state"] != "WAITING_HPC":
                    continue
                if gateway_error:
                    since = result.get("hpc_unreachable_since") or datetime.now(timezone.utc).isoformat()
                    result["hpc_unreachable_since"] = since
                    started = datetime.fromisoformat(since)
                    if (datetime.now(timezone.utc) - started).total_seconds() / 60 > hcfg.max_unreachable_minutes:
                        hpc_repo.fail_waiting(conn, job_now, "HPC_UNREACHABLE", "PBS 게이트웨이에 연결할 수 없습니다")
                        continue
                    hpc_repo.set_attention(conn, job_now, job_now["attention_code"], result)
                    continue
                if result.pop("hpc_unreachable_since", None) is not None:
                    hpc_repo.set_attention(conn, job_now, job_now["attention_code"], result)
                    job_now = jobs_repo.get_job(conn, job["id"])
                hjobs = hpc_repo.for_job(conn, job["id"])
                if job_now["job_type"] == "TD_SOLVE":  # 최신 attempt만(재시도는 새 작업이지만 방어적으로)
                    last = max((h["attempt_no"] for h in hjobs), default=0)
                    hjobs = [h for h in hjobs if h["attempt_no"] == last]
                tno = hpc_terminal_transition(job_now["job_type"], (job_now["params"] or {}).get("on_run_failure"),
                                              [h["state"] for h in hjobs])
                if tno == "T13":
                    hpc_repo.fail_waiting(conn, job_now, "HPC_RUN_FAILED", "PBS 해석이 실패했거나 상태를 잃었습니다")
                elif tno == "T10b":
                    failed = sum(1 for h in hjobs if h["state"] in ("FAILED", "LOST"))
                    hpc_repo.to_collecting_partial(conn, job_now, failed, len(hjobs))
                elif tno == "T10":
                    hpc_repo.to_collecting(conn, job_now)
