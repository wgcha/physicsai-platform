"""워커 런타임(§11.1): slot·light·hpc·heartbeat·housekeeping 스레드.

시험은 `run_once_slot()` 등 1회 함수를 직접 구동한다. HPC 폴러(`poll_hpc_once`)는 hpc_poller.HpcPollerMixin(상속).
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
from physicsai_core.db.repositories import job_lease as lease_repo
from physicsai_core.db.repositories import workers as workers_repo
from physicsai_core.db.repositories.job_lease import ClaimRace
from physicsai_core.hpc.gateway import HpcJobGateway, get_hpc_gateway
from physicsai_core.limits import EffectiveLimits, detect, limits_from_settings
from physicsai_core.paths import register_protected_roots

from . import housekeeping, resources
from .executor import Executor
from .gpu_monitor import GpuMonitor
from .hpc_poller import RUN_STATE_BY_HPC, HpcPollerMixin  # noqa: F401 - RUN_STATE_BY_HPC 기존 경로 재노출
from .limiter import ProcessLimiter, select_limiter

log = logging.getLogger("physicsai_worker")

ALTAIR_KEYS = ("hyperstudy_path", "simlab_path", "edspy_path", "hw_exe_path", "hvtrans_exe_path")


class Worker(HpcPollerMixin):
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
        # GPU 조회는 GpuMonitor 스레드만(phase3 §24.3) — 하트비트는 캐시를 읽는다
        self.gpu_monitor = GpuMonitor(lambda: self.settings, self.child_env)
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
        job = self._claim(lambda c: lease_repo.claim_slot(c, self.worker_id, ttl, self.env_snapshot()))
        if job is None:
            return None
        return Executor(self, job).run()

    def run_once_light(self) -> str | None:
        self.check_config_change()
        if self.claims_paused:
            return None
        ttl = self.settings.worker.lease_ttl_s
        job = self._claim(lambda c: lease_repo.claim_light(c, self.worker_id, ttl, self.env_snapshot()))
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

    def run_once_preview(self) -> str | None:
        """PREVIEW 레인 1건 claim·실행(geometry-view.md §6.2): 전역 슬롯과 무관 — DOE·일괄 예측 실행 중에도 돈다."""
        self.check_config_change()
        if self.claims_paused:
            return None
        ttl = self.settings.worker.lease_ttl_s
        mc = self.settings.geometry.view.max_concurrent
        job = self._claim(lambda c: lease_repo.claim_preview(c, self.worker_id, ttl, mc, self.env_snapshot()))
        if job is None:
            return None
        return Executor(self, job).run()

    def run_once_collect(self) -> str | None:
        ttl = self.settings.worker.lease_ttl_s
        job = self._claim(lambda c: lease_repo.claim_collecting(c, self.worker_id, ttl))
        if job is None:
            return None
        return Executor(self, job).run()

    def claim_only(self) -> dict[str, Any] | None:
        """시험용: claim만 하고 실행하지 않는다(워커 사망 모사)."""
        ttl = self.settings.worker.lease_ttl_s
        return self._claim(lambda c: lease_repo.claim_slot(c, self.worker_id, ttl, self.env_snapshot()))

    # ---- 하트비트·자원 ----
    def heartbeat_once(self, with_resources: bool = True) -> None:
        if with_resources:
            job_acc = None
            ex = self.current_executor
            group = getattr(ex, "current_group", None) if ex is not None else None
            if ex is not None and (ex.current_proc is not None or group is not None):
                try:  # 동시 실행 중이면 그룹(작업 1개분) 회계(phase3 §14.5)
                    acc = self.limiter.accounting(ex.current_proc) if ex.current_proc is not None else \
                        self.limiter.group_accounting(group)
                    job_acc = {"job_id": ex.job_id, "cpu_time_s": acc.cpu_time_s,
                               "peak_memory_gb": round(acc.peak_memory_bytes / 2**30, 3) if acc.peak_memory_bytes else None}
                except Exception:
                    job_acc = {"job_id": ex.job_id}
            mon = self.gpu_monitor
            if not mon.running:  # 스레드 없이 하트비트만 구동(시험·start 전)일 때만 직접 조회 — 기존 동작
                mon.poll_once()
            self._last_resources = resources.sample(None, job_acc, gpu=mon.snapshot())
            self._last_resources["paicad_version"] = resources.paicad_version(self.settings, self.child_env())  # GV §6.4 캐시 키
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
        if force_purge or now - getattr(self, "_last_cache_purge", 0.0) >= self.settings.geometry.view.cache.purge_interval_h * 3600:
            self._last_cache_purge = now  # geometry-view.md §6.6: 서버측 <study>/_cache/ 임시 캐시(기간·총량)
            housekeeping.purge_view_cache(self.engine, self.settings)

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
        self.gpu_monitor.start()
        self.heartbeat_once()
        housekeeping.reap(self.engine)
        self._loop("slot", self.run_once_slot, lambda: self.settings.worker.claim_interval_s)
        self._loop("light", self.run_light_tick, lambda: self.settings.worker.claim_interval_s)
        for i in range(max(1, int(self.settings.geometry.view.max_concurrent))):  # PREVIEW 레인(§6.2, 동시 수 = 스레드 수 상한)
            self._loop(f"preview{i}", self.run_once_preview, lambda: min(0.5, self.settings.worker.claim_interval_s))
        self._loop("hpc", self._hpc_tick, lambda: min(5.0, self.settings.worker.claim_interval_s))
        self._loop("heartbeat", self._heartbeat_tick, lambda: self.settings.worker.heartbeat_interval_s)
        self._loop("housekeeping", self.housekeeping_once, lambda: self.settings.worker.claim_interval_s)
        log.info("워커 시작: %s (limiter=%s, cores=%s, memory=%sGB)", self.worker_id, self.limiter.name,
                 self.limits.cores, self.limits.memory_gb)

    def _hpc_tick(self) -> None:
        if time.time() - self._last_hpc_poll >= self.hpc_poll_interval_s():  # scx: hpc.scx.poll_interval_s(phase3 §16.4)
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
        self.gpu_monitor.stop()
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
