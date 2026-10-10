"""step 실행기(§11.3). claim된 작업 1건의 step 체인을 실행한다.

- lease는 LeaseKeeper 스레드가 heartbeat_interval_s마다 renew. 실패 → 소유권 상실: 프로세스 트리 종료, 이후 상태 쓰기 없음
- LOCAL step은 제한기 안에서 argv 배열(shell=False)로만 실행
"""

from __future__ import annotations

import logging
import os
import threading
import traceback
from collections.abc import Callable
from typing import Any

from sqlalchemy.engine import Engine

from physicsai_core.commands import TEMPLATE_SPECS
from physicsai_core.config import Settings
from physicsai_core.db.repositories import job_lease as lease_repo
from physicsai_core.db.repositories import jobs as jobs_repo
from physicsai_core.db.repositories import studies as studies_repo
from physicsai_core.db.repositories.job_lease import LeaseLost
from physicsai_core.errors import DomainError, StepFailure
from physicsai_core.job_types import JOB_TYPES
from physicsai_core.limits import EffectiveLimits
from physicsai_core.masking import Masker
from physicsai_core.paths import backup_stamp, real, study_dir

from .limiter.base import LimiterError, ProcessLimiter
from .signals import Cancelled, EnterWaitingHpc, StepSkipped
from .step_context import StepContext

log = logging.getLogger("physicsai_worker.executor")


class LeaseKeeper(threading.Thread):
    def __init__(self, engine: Engine, job_id: str, token: str, ttl: float, interval: float, slot: bool,
                 on_lost: Callable[[], None]) -> None:
        super().__init__(daemon=True, name=f"lease-{job_id[:8]}")
        self.engine, self.job_id, self.token, self.ttl, self.interval, self.slot = engine, job_id, token, ttl, interval, slot
        self.on_lost = on_lost
        self.lost = threading.Event()
        self._stop = threading.Event()
        self.paused = threading.Event()  # 시험: 워커 사망 모사

    def run(self) -> None:
        while not self._stop.wait(self.interval):
            if self.paused.is_set():
                continue
            try:
                with self.engine.begin() as conn:
                    ok = lease_repo.renew(conn, self.job_id, self.token, self.ttl, slot=self.slot)
            except Exception:  # DB 일시 오류: 다음 주기에 재시도(만료 전이면 유지)
                log.exception("lease renew 오류")
                continue
            if not ok:
                self.lost.set()
                self.on_lost()
                return

    def stop(self) -> None:
        self._stop.set()


class Executor:
    def __init__(self, worker: Any, job: dict[str, Any]) -> None:
        self.w = worker
        self.engine: Engine = worker.engine
        self.settings: Settings = worker.settings
        self.limiter: ProcessLimiter = worker.limiter
        self.limits: EffectiveLimits = worker.limits
        self.job = job
        self.job_id: str = job["id"]
        self.token: str = job["lease_token"]
        self.jt = JOB_TYPES[job["job_type"]]
        with self.engine.connect() as conn:
            self.study = studies_repo.require(conn, job["study_id"])
            self.workspace_id = jobs_repo.root_job_id(conn, job)
        self.study_root = real(study_dir(self.settings.storage.ai_root, self.study["folder_name"]))
        self.stamp = backup_stamp()
        self.current_proc: Any = None
        self._proc_lock = threading.Lock()
        self.keeper: LeaseKeeper | None = None
        self.masker = Masker(self.settings.logging.mask_patterns)
        self.log_dir = os.path.join(self.study_root, "logs", self.job_id)
        os.makedirs(self.log_dir, exist_ok=True)

    # ---- DB 도우미 ----
    def db(self, fn: Callable[[Any], Any]) -> Any:
        if self.keeper is not None and self.keeper.lost.is_set():
            raise LeaseLost(self.job_id)
        with self.engine.begin() as conn:
            return fn(conn)

    def result(self) -> dict[str, Any]:
        with self.engine.connect() as conn:
            j = jobs_repo.get_job(conn, self.job_id)
        return dict((j or {}).get("result") or {})

    def patch_result(self, patch: dict[str, Any]) -> dict[str, Any]:
        return self.db(lambda c: lease_repo.patch_result(c, self.job_id, self.token, patch))

    def add_warning(self, code: str, message: str) -> None:
        self.db(lambda c: lease_repo.add_warning(c, self.job_id, self.token, code, message))

    def _on_lost(self) -> None:
        log.warning("lease 소유권 상실: %s", self.job_id)
        with self._proc_lock:
            p = self.current_proc
        if p is not None:
            try:
                self.limiter.terminate(p)
            except Exception:
                log.exception("lease 상실 후 프로세스 종료 실패")

    def cancel_requested(self) -> bool:
        with self.engine.connect() as conn:
            return jobs_repo.is_cancel_requested(conn, self.job_id)

    # ---- 실행 ----
    def run(self) -> str | None:
        """작업을 끝까지(또는 상태 전이까지) 실행. 최종 상태 또는 None(lease 상실)."""
        slot = bool(self.job.get("holds_slot"))
        ws = self.settings.worker
        self.keeper = LeaseKeeper(self.engine, self.job_id, self.token, ws.lease_ttl_s, ws.heartbeat_interval_s, slot, self._on_lost)
        self.w.current_executor = self
        self.keeper.start()
        try:
            return self._run_steps()
        except LeaseLost:
            log.warning("작업 %s: lease 상실로 중단(상태 쓰기 없음)", self.job_id)
            return None
        finally:
            self.keeper.stop()
            self.w.current_executor = None

    def _release(self, state: str, code: str | None = None, msg: str | None = None) -> str:
        self.db(lambda c: lease_repo.release(c, self.job_id, self.token, state, failure_code=code, failure_message=msg))
        return state

    def _job_log(self, text: str) -> None:
        with open(os.path.join(self.log_dir, "job.log"), "a", encoding="utf-8") as fh:
            fh.write(text if text.endswith("\n") else text + "\n")

    def _run_steps(self) -> str | None:
        from .steps import HANDLERS

        collecting = self.job["state"] == "COLLECTING"
        with self.engine.connect() as conn:
            steps = jobs_repo.get_steps(conn, self.job_id)
        total_w = sum(self.jt.weight_of(s["step_key"]) for s in steps) or 1
        done_w = sum(self.jt.weight_of(s["step_key"]) for s in steps if s["state"] in ("SUCCEEDED", "SKIPPED"))
        for s in steps:
            if s["state"] != "PENDING":
                continue
            if collecting and s["kind"] != "COLLECT":
                return self._release("QUEUED")  # T14: 다음 step이 슬롯 필요
            if not collecting and s["kind"] in ("HPC_WAIT", "COLLECT"):
                raise StepFailure("INTERNAL_ERROR", "HPC 대기 step을 슬롯 실행기에서 만났습니다")
            if self.cancel_requested():
                return self._release("CANCELED")
            if not collecting:
                self.db(lambda c: lease_repo.continue_running(c, self.job_id, self.token))
            ctx = StepContext(self, s, done_w, total_w)
            ctx.start()
            try:
                handler = HANDLERS[(self.job["job_type"], s["step_key"])]
                handler(ctx)
            except StepSkipped as sk:
                ctx.finish("SKIPPED", label=sk.label or None)
            except EnterWaitingHpc:
                ctx.finish("SUCCEEDED")
                return self._release("WAITING_HPC")
            except Cancelled:
                ctx.finish("CANCELED")
                return self._release("CANCELED")
            except LeaseLost:
                raise
            except (StepFailure, DomainError, LimiterError) as exc:
                code = getattr(exc, "code", "INTERNAL_ERROR")
                if isinstance(exc, DomainError):
                    code = "INPUT_INVALID"
                msg = getattr(exc, "message", str(exc))
                ctx.log(f"[FAIL] {code}: {msg}")
                ctx.finish("FAILED", code=code, message=msg)
                return self._release("FAILED", code, msg)
            except Exception as exc:  # noqa: BLE001
                ctx.log("[FAIL] INTERNAL_ERROR\n" + traceback.format_exc())
                ctx.finish("FAILED", code="INTERNAL_ERROR", message=f"내부 오류: {exc}")
                return self._release("FAILED", "INTERNAL_ERROR", f"내부 오류: {exc}")
            else:
                ctx.finish("SUCCEEDED")
            done_w += self.jt.weight_of(s["step_key"])
        return self._release("SUCCEEDED")


__all__ = ["Executor", "StepContext", "Cancelled", "StepSkipped", "EnterWaitingHpc", "TEMPLATE_SPECS"]
