"""워커 런타임(§11.1): gpu-slot·cpu-slot0..N-1·light·preview·hpc·heartbeat·housekeeping 스레드(job-queues.md JQ-9).

GPU 구간은 `gpu-slot` 스레드 1개에서만 실행하고(프로세스 안 단일 직렬화 + DB 슬롯 = 이중 보장), CPU 구간은 `cpu-slot*` 스레드가
설정 상한(worker.queues.cpu.max_concurrent)만큼 병렬로 받는다. 구간이 바뀌는 step 경계는 executor가 T17로 반납·재진입한다.
시험은 `run_once_gpu()`·`run_once_cpu()`(구간 1개)나 `run_once_slot()`(작업 1건을 끝까지) 등 1회 함수를 직접 구동한다.
HPC 폴러(`poll_hpc_once`)는 hpc_poller.HpcPollerMixin(상속).
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

import psutil
from sqlalchemy.engine import Engine

from physicsai_core import __version__
from physicsai_core.childenv import child_env
from physicsai_core.config import LoadedConfig, Settings, load_config
from physicsai_core.db.repositories import env_checks as env_repo
from physicsai_core.db.repositories import job_lease as lease_repo
from physicsai_core.db.repositories import workers as workers_repo
from physicsai_core.db.repositories.job_lease import ClaimRace
from physicsai_core.db.retry import DEADLOCK_RETRIES, retry_deadlock
from physicsai_core.hpc.gateway import HpcJobGateway, get_hpc_gateway
from physicsai_core.limits import EffectiveLimits, detect, limits_from_settings, share_limits
from physicsai_core.paths import register_protected_roots
from physicsai_core.queues import gpu_demotions

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
        bad = gpu_demotions(config.settings.worker.queues.step_resource)
        if bad and config.ok:  # (설정 오류면 어차피 claims_paused) 설정 검증을 거치지 않은 경로(시험·직접 생성)도 GPU 동시 1을 우회하지 못하게(JQ-2)
            raise ValueError("GPU 단계를 CPU로 내리는 설정은 쓸 수 없습니다(GPU 작업은 동시에 1개만 실행): "
                             "worker.queues.step_resource." + ", ".join(bad))
        self.config = config
        self.engine = engine
        self.config_path = config_path or config.path
        self.worker_id = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4()}"
        self.limiter = limiter or select_limiter(self.settings.worker, self.settings.profile)
        self.hpc = hpc or get_hpc_gateway(self.settings)
        self.detected = detected or detect()
        self.limits: EffectiveLimits = limits_from_settings(self.settings.worker, self.detected)
        # 실행 중 슬롯 작업(job_id → Executor, 하트비트 회계·종료 시 keeper 정지 — job-queues.md §6.2). PREVIEW는 등록하지 않는다
        self.executors: dict[str, Executor] = {}
        self._exec_lock = threading.Lock()
        self._gpu_lock = threading.Lock()  # GPU 구간은 프로세스 안에서도 1개씩(JQ-9) — DB 슬롯과 이중 보장
        self._thread_lock = threading.Lock()
        self._cpu_threads = 0
        self._started = False
        self.memory_gate: str | None = None  # CPU 수령 시 마지막 여유 메모리 판정 ok|low(하트비트로 GET /queue에 노출)
        self.available_memory_gb = lambda: psutil.virtual_memory().available / 2**30  # 시험이 바꿔 끼운다
        self.claims_paused = not config.ok
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._last_purge = 0.0
        self._last_resources: dict[str, Any] | None = None
        self._last_hpc_poll = 0.0
        # GPU 조회는 GpuMonitor 스레드만(phase3 §24.3) — 하트비트는 캐시를 읽는다
        self.gpu_monitor = GpuMonitor(lambda: self.settings, self.child_env)
        register_protected_roots(self.settings.storage.spdm_roots)
        self.cap_mode: str = self._attach_total_cap()

    @property
    def settings(self) -> Settings:
        return self.config.settings

    # ---- 전체 자원 상한(job-queues.md JQ-7) ----
    def _attach_total_cap(self) -> str:
        """nested = 워커 부모 Job Object 안에 step Job 중첩, share = 작업당 몫(total_cap=false·중첩 불가·POSIX), off = 제한 없음(null 제한기)."""
        if self.limiter.name == "null":
            return "off"
        if not self.settings.worker.queues.total_cap:
            return "share"
        attach = getattr(self.limiter, "attach_parent", None)
        try:
            return str(attach(self.limits)) if attach else "share"
        except Exception:  # noqa: BLE001 - 상한 설정 실패로 워커를 막지 않는다
            log.exception("워커 부모 Job Object 설정 실패 — 작업당 몫으로 폴백")
            return "share"

    def job_limits(self) -> EffectiveLimits:
        """작업 1개에 적용할 한도. nested·off는 전체 한도 그대로(부모 Job이 합계를 막음), share는 코어·메모리를 (CPU N + GPU 1)로 나눈 몫."""
        if self.cap_mode == "share":
            return share_limits(self.limits, int(self.settings.worker.queues.cpu.max_concurrent) + 1)
        return self.limits

    def register_executor(self, ex: Executor) -> None:
        with self._exec_lock:
            self.executors[ex.job_id] = ex

    def unregister_executor(self, ex: Executor) -> None:
        with self._exec_lock:
            if self.executors.get(ex.job_id) is ex:
                del self.executors[ex.job_id]

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
            self._ensure_cpu_threads()  # CPU 상한이 커졌으면 스레드를 더 띄운다(작아지면 수령 문이 걸러냄)
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
        """수령 트랜잭션 1회. 교착(40P01)이면 트랜잭션 전체가 롤백되므로 짧게 다시 시도한다(최대 3회 — 수령 결과는 같다, JQ-C1)."""
        def once() -> dict[str, Any] | None:
            with self.engine.begin() as conn:
                return fn(conn)

        try:
            return retry_deadlock(once, on_retry=lambda n: log.warning("수령 중 교착 감지 — 다시 시도합니다(%d/%d)", n, DEADLOCK_RETRIES))
        except ClaimRace:
            return None

    def _reap_and_check(self) -> bool:
        """공통 수령 준비: 설정 변경 감지·리퍼. 수령해도 되면 True(설정 오류로 멈췄으면 False)."""
        self.check_config_change()
        housekeeping.reap(self.engine)
        return not self.claims_paused

    def run_once_gpu(self) -> str | None:
        """GPU 대기열 1건 claim·실행(구간 1개). 워커 안에서는 한 번에 1개만 — 앞 executor가 끝나기 전에는 새 작업을 받지 않는다(JQ-9)."""
        if not self._gpu_lock.acquire(blocking=False):
            return None
        try:
            if not self._reap_and_check():
                return None
            ttl = self.settings.worker.lease_ttl_s
            job = self._claim(lambda c: lease_repo.claim_gpu(c, self.worker_id, ttl, self.env_snapshot()))
            if job is None:
                return None
            return Executor(self, job).run()
        finally:
            self._gpu_lock.release()

    def _memory_ok(self) -> bool:
        """CPU 수령 문(JQ-6): 시스템 여유 메모리 ≥ cpu.min_free_memory_gb(0이면 검사 안 함). 판정은 하트비트로 화면에 노출한다."""
        need = float(self.settings.worker.queues.cpu.min_free_memory_gb)
        if need <= 0:
            self.memory_gate = "ok"
            return True
        ok = float(self.available_memory_gb()) >= need
        self.memory_gate = "ok" if ok else "low"
        return ok

    def run_once_cpu(self) -> str | None:
        """CPU 대기열 1건 claim·실행(구간 1개). 실행 수 상한은 DB(claim_cpu)가 막는다 — 스레드 수와 무관하게 안전."""
        if not self._reap_and_check() or not self._memory_ok():
            return None
        ttl = self.settings.worker.lease_ttl_s
        limit = self.settings.worker.queues.cpu.max_concurrent
        job = self._claim(lambda c: lease_repo.claim_cpu(c, self.worker_id, ttl, limit, self.env_snapshot()))
        if job is None:
            return None
        return Executor(self, job).run()

    def run_once_slot(self) -> str | None:
        """시험·개발용: 가장 앞선 GPU·CPU 대기 작업 1건을 **끝까지**(또는 WAITING_HPC 등 슬롯 없는 상태까지) 구동한다.
        구간 전환(T17)으로 QUEUED가 되면 같은 작업을 이어서 수령한다. 그 작업의 최종 상태(없으면 None). 운영은 gpu-slot·cpu-slot 스레드."""
        if not self._reap_and_check():
            return None
        first: str | None = None
        last: str | None = None
        for _ in range(64):  # 구간 전환은 job_type당 몇 번 — 무한 반복 방지 상한
            job = self._claim(lambda c: lease_repo.claim_next_slot(c, self.worker_id, self.settings.worker.lease_ttl_s,
                                                                   self.settings.worker.queues.cpu.max_concurrent, self.env_snapshot()))
            if job is None:
                break
            state = Executor(self, job).run()
            if first is None:
                first = job["id"]
            if job["id"] == first:
                last = state
                if state != "QUEUED":
                    break
        return last

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
        """시험용: 가장 앞선 GPU·CPU 대기 작업을 claim만 하고 실행하지 않는다(워커 사망 모사)."""
        self.check_config_change()
        ttl = self.settings.worker.lease_ttl_s
        return self._claim(lambda c: lease_repo.claim_next_slot(c, self.worker_id, ttl, self.settings.worker.queues.cpu.max_concurrent,
                                                                self.env_snapshot()))

    # ---- 하트비트·자원 ----
    def job_accounting(self) -> list[dict[str, Any]]:
        """실행 중 슬롯 작업 전부의 자원 회계(job-queues.md §6.2): 작업별 {job_id, lane, cpu_time_s, peak_memory_gb}.
        동시 실행 중이면 그룹(작업 1개분) 회계(phase3 §14.5). 실행 중인 프로세스가 없는 작업(step 사이)은 건너뛴다."""
        with self._exec_lock:
            exs = list(self.executors.values())
        out: list[dict[str, Any]] = []
        for ex in exs:
            group = getattr(ex, "current_group", None)
            if ex.current_proc is None and group is None:
                continue
            try:
                acc = self.limiter.accounting(ex.current_proc) if ex.current_proc is not None else self.limiter.group_accounting(group)
                out.append({"job_id": ex.job_id, "lane": ex.lane, "cpu_time_s": acc.cpu_time_s,
                            "peak_memory_gb": round(acc.peak_memory_bytes / 2**30, 3) if acc.peak_memory_bytes else None})
            except Exception:
                out.append({"job_id": ex.job_id, "lane": ex.lane})
        return out

    def heartbeat_once(self, with_resources: bool = True) -> None:
        if with_resources:
            jobs_acc = self.job_accounting()
            # 기존 `job` 필드 = GPU 작업 우선 1건(없으면 첫 건)
            job_acc = next((j for j in jobs_acc if j.get("lane") == "GPU"), jobs_acc[0] if jobs_acc else None)
            mon = self.gpu_monitor
            if not mon.running:  # 스레드 없이 하트비트만 구동(시험·start 전)일 때만 직접 조회 — 기존 동작
                mon.poll_once()
            self._last_resources = resources.sample(None, job_acc, gpu=mon.snapshot())
            self._last_resources["jobs"] = jobs_acc
            self._last_resources["paicad_version"] = resources.paicad_version(self.settings, self.child_env())  # GV §6.4 캐시 키
            if not self.config.ok:
                self._last_resources["worker_config_errors"] = self.config.error_keys()
        eff = {**self.limits.as_dict(), "cpu_cap_enforced": bool(self.limiter.cpu_cap_enforced),
               "cpu_max_concurrent": int(self.settings.worker.queues.cpu.max_concurrent), "total_cap": self.cap_mode,
               "memory_gate": self.memory_gate}
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
            housekeeping.purge_stale_uploads(self.engine, self.settings)  # upload-report.md §4: 낡은 업로드 세션 → _backup
        if force_purge or now - getattr(self, "_last_cache_purge", 0.0) >= self.settings.geometry.view.cache.purge_interval_h * 3600:
            self._last_cache_purge = now  # geometry-view.md §6.6: 서버측 <study>/_cache/ 임시 캐시(기간·총량)
            housekeeping.purge_view_cache(self.engine, self.settings)
            housekeeping.purge_mcp(self.engine, self.settings)  # mcp.md §6.2: 미리보기 캐시 정리와 같은 주기

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
        self._loop("gpu-slot", self.run_once_gpu, lambda: self.settings.worker.claim_interval_s)  # GPU 구간은 이 스레드 1개만(JQ-9)
        self._started = True
        self._ensure_cpu_threads()  # CPU 구간: cpu-slot0..N-1(설정 상한)
        self._loop("light", self.run_light_tick, lambda: self.settings.worker.claim_interval_s)
        for i in range(max(1, int(self.settings.geometry.view.max_concurrent))):  # PREVIEW 레인(§6.2, 동시 수 = 스레드 수 상한)
            self._loop(f"preview{i}", self.run_once_preview, lambda: min(0.5, self.settings.worker.claim_interval_s))
        self._loop("hpc", self._hpc_tick, lambda: min(5.0, self.settings.worker.claim_interval_s))
        self._loop("heartbeat", self._heartbeat_tick, lambda: self.settings.worker.heartbeat_interval_s)
        self._loop("housekeeping", self.housekeeping_once, lambda: self.settings.worker.claim_interval_s)
        log.info("워커 시작: %s (limiter=%s, cores=%s, memory=%sGB)", self.worker_id, self.limiter.name,
                 self.limits.cores, self.limits.memory_gb)

    def _ensure_cpu_threads(self) -> None:
        """cpu-slot 스레드를 설정 상한(max_concurrent)까지 채운다. 상한이 작아져도 스레드는 줄이지 않는다 — 남는 스레드는 수령 문
        (DB 실행 수 검사)에서 걸러져 쉰다(실행 중 작업은 끝까지)."""
        if not self._started:
            return
        with self._thread_lock:
            want = max(1, int(self.settings.worker.queues.cpu.max_concurrent))
            while self._cpu_threads < want:
                self._loop(f"cpu-slot{self._cpu_threads}", self.run_once_cpu, lambda: self.settings.worker.claim_interval_s)
                self._cpu_threads += 1

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
        with self._exec_lock:
            exs = list(self.executors.values())
        for ex in exs:  # 실행 중 작업 전부의 lease 갱신을 멈춘다(→ 만료 후 INTERRUPTED)
            if ex.keeper is not None:
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
