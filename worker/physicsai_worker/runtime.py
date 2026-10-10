"""워커 런타임(§11.1): slot·light·hpc·heartbeat·housekeeping 스레드.

시험은 `run_once_slot()` 등 1회 함수를 직접 구동한다.
"""

from __future__ import annotations

import hashlib
import logging
import os
import socket
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.engine import Engine

from physicsai_core import __version__
from physicsai_core.childenv import child_env
from physicsai_core.config import LoadedConfig, Settings, load_config
from physicsai_core.db.repositories import env_checks as env_repo
from physicsai_core.db.repositories import hpc as hpc_repo
from physicsai_core.db.repositories import jobs as jobs_repo
from physicsai_core.db.repositories import train as train_repo
from physicsai_core.db.repositories import workers as workers_repo
from physicsai_core.db.repositories.jobs import ClaimRace
from physicsai_core.hpc.gateway import HpcGatewayError, HpcJobGateway, get_hpc_gateway
from physicsai_core.limits import EffectiveLimits, detect, limits_from_settings
from physicsai_core.paths import register_protected_roots
from physicsai_core.state_machine import hpc_terminal_transition

from . import housekeeping, resources
from .executor import Executor
from .limiter import ProcessLimiter, select_limiter

log = logging.getLogger("physicsai_worker")

ALTAIR_KEYS = ("hyperstudy_path", "simlab_path", "edspy_path", "hw_exe_path", "hvtrans_exe_path")
# hpc_jobs 상태 → train_runs 상태(phase2 §6.5 HPC_WAIT)
RUN_STATE_BY_HPC = {"SUCCEEDED": "SOLVED", "FAILED": "SOLVE_FAILED", "LOST": "SOLVE_FAILED", "CANCELED": "SOLVE_FAILED"}


class Worker:
    def __init__(
        self,
        config: LoadedConfig,
        engine: Engine,
        *,
        config_path: str | None = None,
        limiter: ProcessLimiter | None = None,
        hpc: HpcJobGateway | None = None,
        detected: tuple[int, float] | None = None,
    ) -> None:
        self.config = config
        self.engine = engine
        self.config_path = config_path or config.path
        self.worker_id = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4()}"
        self.limiter = limiter or select_limiter(self.settings.worker, self.settings.profile)
        self.hpc = hpc or get_hpc_gateway(self.settings)
        self.detected = detected or detect()
        self.limits: EffectiveLimits = limits_from_settings(self.settings.worker, self.detected)
        self.current_executor: Executor | None = None
        self.claims_paused = not config.ok
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._last_purge = 0.0
        self._last_resources: dict[str, Any] | None = None
        self._last_hpc_poll = 0.0
        register_protected_roots(self.settings.storage.spdm_roots)

    @property
    def settings(self) -> Settings:
        return self.config.settings

    def child_env(self) -> dict[str, str]:
        return child_env(self.settings.worker.env_passthrough, deny_names=[self.settings.database.url_env])

    # ---- 설정 변경 감지(§11.1) ----
    def check_config_change(self) -> None:
        if not self.config_path or not os.path.isfile(self.config_path):
            return
        try:
            with open(self.config_path, "rb") as fh:
                sha = hashlib.sha256(fh.read()).hexdigest()
        except OSError:
            return
        if sha == self.config.sha256:
            return
        new = load_config(self.config_path)
        if new.ok:
            log.info("설정 변경 감지 — 다시 읽었습니다")
            self.config = new
            self.claims_paused = False
            self.hpc = get_hpc_gateway(new.settings)
            self.limits = limits_from_settings(new.settings.worker, self.detected)
            register_protected_roots(new.settings.storage.spdm_roots)
        else:
            log.error("설정 변경 후 검증 실패 — 새 claim을 멈춥니다: %s", new.error_keys())
            self.config = LoadedConfig(self.config.settings, new.issues, new.path, new.sha256)
            self.claims_paused = True

    # ---- 환경 스냅샷(§11.7) ----
    def env_snapshot(self) -> dict[str, Any]:
        paths = {}
        for k in ALTAIR_KEYS:
            p = getattr(self.settings.altair, k)
            if p and os.path.isfile(p):
                st = os.stat(p)
                paths[k] = {"path": p, "size": st.st_size,
                            "mtime": datetime.fromtimestamp(st.st_mtime, timezone.utc).isoformat()}
            else:
                paths[k] = {"path": p, "size": None, "mtime": None}
        gpus = (self._last_resources or {}).get("gpu") or []
        return {
            "app_version": __version__,
            "config_sha256": self.config.sha256,
            "altair": {"version_label": self.settings.altair.version_label, "paths": paths},
            "worker": {
                "worker_id": self.worker_id,
                "limiter": self.limiter.name,
                "detected": {"cores": self.detected[0], "memory_gb": round(self.detected[1], 3)},
                "effective": {"cores": self.limits.cores, "cpu_rate": self.limits.cpu_rate,
                              "memory_gb": self.limits.memory_gb, "priority": self.limits.priority},
            },
            "gpu": [{"name": g.get("name"), "memory_total_mb": g.get("mem_total_mb")} for g in gpus],
            "hpc": {"mode": self.hpc.availability().mode},
        }

    # ---- claim + 실행 ----
    def _claim(self, fn: Any) -> dict[str, Any] | None:
        try:
            with self.engine.begin() as conn:
                return fn(conn)
        except ClaimRace:
            return None

    def run_once_slot(self) -> str | None:
        """SLOT 레인 1건 claim·실행. 실행한 작업의 최종 상태(없으면 None)."""
        self.check_config_change()
        housekeeping.reap(self.engine)
        if self.claims_paused:
            return None
        ttl = self.settings.worker.lease_ttl_s
        job = self._claim(lambda c: jobs_repo.claim_slot(c, self.worker_id, ttl, self.env_snapshot()))
        if job is None:
            return None
        return Executor(self, job).run()

    def run_once_light(self) -> str | None:
        self.check_config_change()
        if self.claims_paused:
            return None
        ttl = self.settings.worker.lease_ttl_s
        job = self._claim(lambda c: jobs_repo.claim_light(c, self.worker_id, ttl, self.env_snapshot()))
        if job is None:
            return None
        return Executor(self, job).run()

    def run_light_tick(self) -> None:
        """light 스레드: LIGHT 작업이 없을 때 환경 점검을 claim한다(phase2 §9.1)."""
        if self.run_once_light() is None:
            self.run_env_check_once()

    def run_env_check_once(self) -> str | None:
        if self.claims_paused:
            return None
        with self.engine.begin() as conn:
            chk = env_repo.claim(conn, self.worker_id)
        if chk is None:
            return None
        from .env_check import run_env_check

        return run_env_check(self, chk)

    def run_once_collect(self) -> str | None:
        ttl = self.settings.worker.lease_ttl_s
        job = self._claim(lambda c: jobs_repo.claim_collecting(c, self.worker_id, ttl))
        if job is None:
            return None
        return Executor(self, job).run()

    def claim_only(self) -> dict[str, Any] | None:
        """시험용: claim만 하고 실행하지 않는다(워커 사망 모사)."""
        ttl = self.settings.worker.lease_ttl_s
        return self._claim(lambda c: jobs_repo.claim_slot(c, self.worker_id, ttl, self.env_snapshot()))

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
                            from physicsai_core.db.repositories import notifications as notif_repo

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

    # ---- 하트비트·자원 ----
    def heartbeat_once(self, with_resources: bool = True) -> None:
        if with_resources:
            job_acc = None
            ex = self.current_executor
            if ex is not None and ex.current_proc is not None:
                try:
                    acc = self.limiter.accounting(ex.current_proc)
                    job_acc = {"job_id": ex.job_id, "cpu_time_s": acc.cpu_time_s,
                               "peak_memory_gb": round(acc.peak_memory_bytes / 2**30, 3) if acc.peak_memory_bytes else None}
                except Exception:
                    job_acc = {"job_id": ex.job_id}
            self._last_resources = resources.sample(self.settings.worker.gpu_query, job_acc, self.child_env())
            if not self.config.ok:
                self._last_resources["worker_config_errors"] = self.config.error_keys()
        eff = {**self.limits.as_dict(), "cpu_cap_enforced": bool(self.limiter.cpu_cap_enforced)}
        with self.engine.begin() as conn:
            workers_repo.upsert(conn, worker_id=self.worker_id, host=socket.gethostname(), pid=os.getpid(),
                                app_version=__version__, limiter=self.limiter.name, effective_limits=eff,
                                resources=self._last_resources if with_resources else None)

    def housekeeping_once(self, force_purge: bool = False) -> None:
        housekeeping.reap(self.engine)
        now = time.time()
        if force_purge or now - self._last_purge >= self.settings.notifications.purge_interval_h * 3600:
            self._last_purge = now
            housekeeping.purge_notifications(self.engine, self.settings.notifications.retention_days)

    # ---- 스레드 ----
    def _loop(self, name: str, fn: Any, interval_fn: Any) -> None:
        def body() -> None:
            while not self._stop.is_set():
                try:
                    fn()
                except Exception:
                    log.exception("%s 루프 오류", name)
                self._stop.wait(interval_fn())

        t = threading.Thread(target=body, name=name, daemon=True)
        t.start()
        self._threads.append(t)

    def start(self) -> None:
        self.heartbeat_once()
        housekeeping.reap(self.engine)
        self._loop("slot", self.run_once_slot, lambda: self.settings.worker.claim_interval_s)
        self._loop("light", self.run_light_tick, lambda: self.settings.worker.claim_interval_s)
        self._loop("hpc", self._hpc_tick, lambda: min(5.0, self.settings.worker.claim_interval_s))
        self._loop("heartbeat", self._heartbeat_tick, lambda: self.settings.worker.heartbeat_interval_s)
        self._loop("housekeeping", self.housekeeping_once, lambda: self.settings.worker.claim_interval_s)
        log.info("워커 시작: %s (limiter=%s, cores=%s, memory=%sGB)", self.worker_id, self.limiter.name,
                 self.limits.cores, self.limits.memory_gb)

    def _hpc_tick(self) -> None:
        if time.time() - self._last_hpc_poll >= self.settings.hpc.poll_interval_s:
            self._last_hpc_poll = time.time()
            self.poll_hpc_once()
        self.run_once_collect()

    def _heartbeat_tick(self) -> None:
        last = getattr(self, "_last_res_sample", 0.0)
        due = time.time() - last >= self.settings.worker.resource_sample_interval_s
        if due:
            self._last_res_sample = time.time()
        self.heartbeat_once(with_resources=due)

    def stop(self) -> None:
        """새 claim 중지. 실행 중 step은 그대로 두고 lease 갱신을 멈춘다(→ 만료 후 INTERRUPTED)."""
        self._stop.set()
        ex = self.current_executor
        if ex is not None and ex.keeper is not None:
            ex.keeper.paused.set()
        for t in self._threads:
            t.join(timeout=2)

    def run_forever(self) -> None:
        self.start()
        try:
            while not self._stop.is_set():
                time.sleep(0.5)
        except KeyboardInterrupt:
            log.info("종료 신호 — 새 claim을 멈춥니다")
        finally:
            self.stop()
