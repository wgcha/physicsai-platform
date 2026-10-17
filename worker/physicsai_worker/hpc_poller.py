"""워커 HPC 폴러(§12.4): WAITING_HPC 작업의 PBS 상태 조회·취소·종료 판정(T10·T10b·T13). Worker가 상속한다.

scx(phase3 §16.5·§16.6): 상태 문자열 매핑(HpcStatus.outcome), Aborted(취소 요청 행 → CANCELED, 아니면 FAILED "SCX에서 중단됨"),
`external_job_id IS NULL`인 결과 모름(UNKNOWN) 행은 상태 조회·LOST 계수를 하지 않고, 취소 시 원격 호출 없이 CANCELED.
사용자 조치(`hpc_jobs.resolve_request` — recheck·attach·mark_not_submitted)는 API가 적고 여기서 처리한다(API는 게이트웨이를 부르지 않음).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import null as sa_null

from physicsai_core.db.repositories import hpc as hpc_repo
from physicsai_core.db.repositories import jobs as jobs_repo
from physicsai_core.db.repositories import notifications as notif_repo
from physicsai_core.db.repositories import train as train_repo
from physicsai_core.hpc.gateway import HpcGatewayError
from physicsai_core.masking import bundle_masker
from physicsai_core.state_machine import hpc_terminal_transition

log = logging.getLogger("physicsai_worker")  # 분리 전 runtime과 같은 로거 이름

# hpc_jobs 상태 → train_runs 상태(phase2 §6.5 HPC_WAIT)
RUN_STATE_BY_HPC = {"SUCCEEDED": "SOLVED", "FAILED": "SOLVE_FAILED", "LOST": "SOLVE_FAILED", "CANCELED": "SOLVE_FAILED"}
UNKNOWN_CANCEL_MESSAGE = "원격 잡 확인 불가 — SCX에서 직접 확인하세요"
STILL_UNKNOWN_MESSAGE = "아직 확인 불가 — SCX 화면에서 잡을 찾아 '잡 ID 연결' 또는 '제출 안 됨'을 고르세요"
NOT_SUBMITTED_MESSAGE = "제출되지 않음(사용자 확인)"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _is_unknown_unsubmitted(h: dict[str, Any]) -> bool:
    return h["external_job_id"] is None and h["state"] in ("UNKNOWN", "SUBMITTING")


class HpcPollerMixin:
    """HPC 폴러 메서드 묶음(`poll_hpc_once`). runtime.Worker가 상속한다."""

    def hpc_poll_interval_s(self) -> float:
        """폴링 주기: scx는 `hpc.scx.poll_interval_s`(null이면 `hpc.poll_interval_s`)."""
        h = self.settings.hpc
        if h.gateway == "scx" and h.scx.poll_interval_s is not None:
            return float(h.scx.poll_interval_s)
        return float(h.poll_interval_s)

    def _mask(self, text: str) -> str:
        return bundle_masker(self.settings)(str(text))[:500]

    # ---- HPC 폴러(§12.4) ----
    def poll_hpc_once(self) -> None:
        hcfg = self.settings.hpc
        self.process_hpc_resolves()
        with self.engine.connect() as conn:
            waiting = hpc_repo.waiting_jobs(conn)
        scx = hcfg.gateway == "scx"
        for job in waiting:
            with self.engine.connect() as conn:
                hjobs = hpc_repo.for_job(conn, job["id"])
            active = [h for h in hjobs if h["state"] not in hpc_repo.HPC_TERMINAL]
            if job["cancel_requested_at"] is not None:
                self._cancel_rows(job, active)
                continue
            result = dict(job["result"] or {})
            gateway_error = False
            for h in active:
                if _is_unknown_unsubmitted(h):
                    continue  # 결과 모름: 사용자 조치 전까지 조회·LOST 계수 없음(§16.5)
                try:
                    st = self.hpc.status(h["external_job_id"])
                except HpcGatewayError as exc:
                    gateway_error = True
                    log.warning("%s 상태 조회 실패: %s", "SCX" if h["gateway_mode"] == "scx" else "PBS", self._mask(str(exc)))
                    if getattr(exc, "relay_code", None) == "JOB_NOT_FOUND":
                        with self.engine.begin() as conn:
                            hpc_repo.update_hpc(conn, h["id"], h["version"], error_message=self._mask(str(exc)))
                    continue
                vals = self._status_values(h, st, hcfg.lost_after_polls)
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
                    since = result.get("hpc_unreachable_since") or _now().isoformat()
                    result["hpc_unreachable_since"] = since
                    started = datetime.fromisoformat(since)
                    if (_now() - started).total_seconds() / 60 > hcfg.max_unreachable_minutes:
                        msg = ("대시보드 SCX relay에 연결할 수 없습니다(대시보드 SCX 연결 확인)" if scx
                               else "PBS 게이트웨이에 연결할 수 없습니다")
                        hpc_repo.fail_waiting(conn, job_now, "HPC_UNREACHABLE", msg)
                        continue
                    hpc_repo.set_attention(conn, job_now, job_now["attention_code"], result)
                    continue
                if result.pop("hpc_unreachable_since", None) is not None:
                    hpc_repo.set_attention(conn, job_now, job_now["attention_code"], result)
                    job_now = jobs_repo.get_job(conn, job["id"])
                self._terminal_transition(conn, job_now)

    def _status_values(self, h: dict[str, Any], st: Any, lost_after_polls: int) -> dict[str, Any]:
        vals: dict[str, Any] = {"external_state_raw": st.raw_state}
        if getattr(st, "output_rel", None) or getattr(st, "output_path", None):
            vals.update(output_rel=st.output_rel, output_path=st.output_path)
        seen_running = h["state"] in ("QUEUED", "RUNNING")
        outcome = getattr(st, "outcome", None)
        if st.not_found and seen_running and h["external_state_raw"] is not None:
            vals.update(state="SUCCEEDED", finished_at=_now(), unknown_count=0)
        elif st.state in ("QUEUED", "RUNNING"):
            vals.update(state=st.state, unknown_count=0)
        elif st.state == "FINISHED" and outcome is not None:  # scx(§16.6): outcome으로 판정
            vals.update(finished_at=_now(), unknown_count=0)
            if outcome == "SUCCEEDED":
                vals["state"] = "SUCCEEDED"
            elif (st.raw_state or "").strip().casefold() == "aborted":
                vals.update(state="CANCELED" if h["state"] == "CANCEL_REQUESTED" else "FAILED", error_message="SCX에서 중단됨")
            else:
                vals.update(state="FAILED", error_message=self._mask(st.error_message) if st.error_message else "SCX 해석 실패")
        elif st.state == "FINISHED":
            ok = st.exit_code == 0 if st.exit_code is not None else True
            vals.update(state="SUCCEEDED" if ok else "FAILED", exit_code=st.exit_code, finished_at=_now(), unknown_count=0)
        else:
            cnt = int(h["unknown_count"]) + 1
            vals.update(unknown_count=cnt)
            if cnt >= lost_after_polls:
                vals.update(state="LOST", finished_at=_now())
        return vals

    def _terminal_transition(self, conn: Any, job_now: dict[str, Any]) -> None:
        hjobs = hpc_repo.for_job(conn, job_now["id"])
        if job_now["job_type"] == "TD_SOLVE":  # 최신 attempt만(재시도는 새 작업이지만 방어적으로)
            last = max((h["attempt_no"] for h in hjobs), default=0)
            hjobs = [h for h in hjobs if h["attempt_no"] == last]
        tno = hpc_terminal_transition(job_now["job_type"], (job_now["params"] or {}).get("on_run_failure"),
                                      [h["state"] for h in hjobs])
        if tno == "T13":
            hpc_repo.fail_waiting(conn, job_now, "HPC_RUN_FAILED", "PBS 해석이 실패했거나 상태를 잃었습니다")
        elif tno == "T10b":
            failed = sum(1 for h in hjobs if h["state"] in ("FAILED", "LOST"))
            total = sum(1 for h in hjobs if (h.get("staged") or {}).get("phase") != "not_submitted")  # scx 미제출 행 제외
            hpc_repo.to_collecting_partial(conn, job_now, failed, total)
        elif tno == "T10":
            hpc_repo.to_collecting(conn, job_now)

    def _cancel_rows(self, job: dict[str, Any], active: list[dict[str, Any]]) -> None:
        cancel_failed = []
        unknown_canceled = 0
        for h in active:
            if _is_unknown_unsubmitted(h):
                # 결과 모름 행: 원격 호출 없이 CANCELED(submission_unknown은 남김) + 작업 경고(§16.4 취소)
                with self.engine.begin() as conn:
                    hpc_repo.update_hpc(conn, h["id"], h["version"], state="CANCELED", finished_at=_now(),
                                        error_message=UNKNOWN_CANCEL_MESSAGE)
                    if job["job_type"] == "TD_SOLVE":
                        train_repo.set_run_state_by_hpc(conn, h["id"], RUN_STATE_BY_HPC["CANCELED"])
                unknown_canceled += 1
                continue
            try:
                self.hpc.cancel(h["external_job_id"])
            except HpcGatewayError as exc:
                # 취소 명령 실패: CANCELED로 적지 않는다 — CANCEL_REQUESTED 유지, 다음 폴링에서 다시 시도(변경 메모 C18)
                log.warning("PBS 취소 실패: %s", self._mask(str(exc)))
                cancel_failed.append(h["external_job_id"])
                with self.engine.begin() as conn:
                    hpc_repo.update_hpc(conn, h["id"], h["version"], state="CANCEL_REQUESTED",
                                        error_message=self._mask(f"취소 명령 실패: {exc}"))
                continue
            with self.engine.begin() as conn:
                hpc_repo.update_hpc(conn, h["id"], h["version"], state="CANCELED", finished_at=_now())
                if job["job_type"] == "TD_SOLVE":
                    train_repo.set_run_state_by_hpc(conn, h["id"], RUN_STATE_BY_HPC["CANCELED"])
        with self.engine.begin() as conn:
            if unknown_canceled:
                job_now = jobs_repo.get_job(conn, job["id"])
                if job_now is not None and job_now["state"] == "WAITING_HPC":
                    hpc_repo.add_waiting_warning(conn, job_now, "SCX_UNKNOWN_CANCELED",
                                                 f"결과 모름 행 {unknown_canceled}개는 SCX에서 직접 확인하세요(원격 잡 확인 불가)")
            if cancel_failed:
                job_now = jobs_repo.get_job(conn, job["id"])
                if job_now is not None and job_now["state"] == "WAITING_HPC" and job_now["attention_code"] != "HPC_CANCEL_FAILED":
                    hpc_repo.set_attention(conn, job_now, "HPC_CANCEL_FAILED")
                    notif_repo.notify_job(conn, job["id"], "HPC_CANCEL_FAILED")
            else:
                hpc_repo.cancel_waiting(conn, jobs_repo.get_job(conn, job["id"]) or job)

    # ---- 결과 모름 조치(phase3 §16.5) ----
    def process_hpc_resolves(self) -> int:
        """API가 기록한 resolve_request를 처리한다. 처리한 행 수."""
        with self.engine.connect() as conn:
            rows = hpc_repo.pending_resolves(conn)
        n = 0
        for h in rows:
            try:
                self._resolve_one(h)
            except Exception:  # noqa: BLE001 - 한 행 실패가 폴러를 멈추지 않게
                log.exception("SCX 결과 모름 조치 처리 실패: %s", h["id"])
                continue
            n += 1
        return n

    def _resolve_one(self, h: dict[str, Any]) -> None:
        req = dict(h["resolve_request"] or {})
        action = req.get("action")
        by = str(req.get("by") or "")
        gw = self.hpc
        # JSONB 열을 SQL NULL로(파이썬 None은 JSON 'null'이 되어 IS NULL 조건에 걸리지 않음)
        vals: dict[str, Any] = {"resolve_request": sa_null(), "resolved_by": by or None, "resolved_at": _now()}
        run_state: str | None = None
        warning: tuple[str, str] | None = None
        notify_body: str | None = None
        with self.engine.connect() as conn:
            job0 = jobs_repo.get_job(conn, h["job_id"])
        if not (h["state"] == "UNKNOWN" and h["submission_unknown"]):
            vals["error_message"] = "조치 대상이 아닙니다(결과 모름 상태가 아님)"
        elif action != "mark_not_submitted" and (job0 is None or job0["state"] != "WAITING_HPC"):
            vals["error_message"] = "대기 중이 아닌 작업은 '제출 안 됨' 조치만 처리합니다"
        elif not hasattr(gw, "submit_radioss"):
            vals["error_message"] = "scx 게이트웨이가 아니어서 조치를 처리할 수 없습니다(hpc.gateway 확인)"
        elif action == "recheck":
            from simdash_adapters.hpc.scx import ScxRadiossRequest

            body = (h["staged"] or {}).get("request")
            if not body:
                vals["error_message"] = "제출 요청 기록이 없어 다시 확인할 수 없습니다 — '잡 ID 연결' 또는 '제출 안 됨'을 고르세요"
            else:
                out = gw.submit_radioss(ScxRadiossRequest.from_json(body))
                if out.state == "SUBMITTED":
                    vals.update(state="QUEUED", external_job_id=out.job_id, submission_unknown=False, error_message=None,
                                output_path=out.output_path, output_rel=out.output_rel, unknown_count=0)
                else:
                    vals["error_message"] = STILL_UNKNOWN_MESSAGE if out.state == "UNKNOWN" else self._mask(
                        f"다시 확인 실패({out.code}): {out.message}")
                    notify_body = STILL_UNKNOWN_MESSAGE
        elif action == "attach":
            ext = str(req.get("external_job_id") or "")
            try:
                d = gw.resolve(h["request_id"], "attach", ext)
                job = d.get("job") or {}
                raw = str(job.get("status") or "")
                vals.update(state="RUNNING" if raw.strip().casefold() == "running" else "QUEUED", external_job_id=ext,
                            submission_unknown=False, error_message=None, external_state_raw=raw or None, unknown_count=0,
                            output_path=job.get("output_path"), output_rel=job.get("output_rel"))
            except HpcGatewayError as exc:
                vals["error_message"] = self._mask(f"잡 ID 연결 실패: {exc}")
        elif action == "mark_not_submitted":
            try:
                gw.resolve(h["request_id"], "abandon")
            except HpcGatewayError as exc:
                warning = ("SCX_RESOLVE_RELAY_FAILED", self._mask(f"relay 기록 정리(abandon) 실패 — PhysicsAI 쪽은 진행: {exc}"))
            vals.update(state="FAILED", finished_at=_now(), error_message=NOT_SUBMITTED_MESSAGE)
            run_state = "SOLVE_FAILED"
        else:
            vals["error_message"] = f"알 수 없는 조치: {action}"
        with self.engine.begin() as conn:
            cur = hpc_repo.get(conn, h["id"], for_update=True)
            if cur is None or cur["version"] != h["version"]:
                return  # 그 사이 바뀜 — 다음 주기에 다시
            hpc_repo.update_hpc(conn, h["id"], h["version"], **vals)
            job = jobs_repo.get_job(conn, h["job_id"])
            if job is None:
                return
            if run_state and job["job_type"] == "TD_SOLVE":
                train_repo.set_run_state_by_hpc(conn, h["id"], run_state)
            if job["state"] != "WAITING_HPC":
                return
            if warning:
                hpc_repo.add_waiting_warning(conn, job, *warning)
                job = jobs_repo.get_job(conn, h["job_id"]) or job
            if notify_body:
                notif_repo.notify_job(conn, job["id"], "HPC_SUBMISSION_UNKNOWN", body=notify_body)
            if job["attention_code"] == "HPC_SUBMISSION_UNKNOWN" and hpc_repo.unknown_open(conn, job["id"]) == 0:
                hpc_repo.set_attention(conn, job, None)
        log.info("SCX 결과 모름 조치 %s 처리: %s → %s", action, h["id"], vals.get("state", h["state"]))
