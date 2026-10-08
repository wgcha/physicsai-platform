"""PosixLimiter(§11.5): nice(10), 선택적 RLIMIT_AS, CPU hard cap 없음(cpu_cap_enforced=false)."""

from __future__ import annotations

import os
import signal
import subprocess
import threading
import time

import psutil

from physicsai_core.limits import EffectiveLimits

from .base import POPEN_TEXT_KW, Accounting, LimitedProcess, LimiterError

NICE_INC = 10


class _Sampler(threading.Thread):
    def __init__(self, pid: int) -> None:
        super().__init__(daemon=True)
        self.pid = pid
        self.peak_rss = 0
        self.cpu_times: dict[int, float] = {}
        self._stop = threading.Event()

    def run(self) -> None:
        try:
            root = psutil.Process(self.pid)
        except psutil.Error:
            return
        while not self._stop.is_set():
            try:
                procs = [root, *root.children(recursive=True)]
            except psutil.Error:
                break
            rss = 0
            for p in procs:
                try:
                    rss += p.memory_info().rss
                    t = p.cpu_times()
                    self.cpu_times[p.pid] = t.user + t.system
                except psutil.Error:
                    continue
            self.peak_rss = max(self.peak_rss, rss)
            self._stop.wait(0.5)

    def stop(self) -> None:
        self._stop.set()


class PosixLimiter:
    name = "posix"
    cpu_cap_enforced = False

    def __init__(self, rlimit_as: bool = False) -> None:
        self.rlimit_as = rlimit_as

    def launch(self, argv: list[str], cwd: str, env: dict[str, str], limits: EffectiveLimits) -> LimitedProcess:
        mem_bytes = int(limits.memory_gb * 2**30)
        use_rlimit = self.rlimit_as

        def _pre() -> None:  # 자식 프로세스에서 실행
            os.nice(NICE_INC)
            if use_rlimit:
                import resource

                resource.setrlimit(resource.RLIMIT_AS, (mem_bytes, mem_bytes))

        try:
            p = subprocess.Popen(argv, cwd=cwd, env=env, start_new_session=True, preexec_fn=_pre, **POPEN_TEXT_KW)
        except OSError as exc:
            raise LimiterError("EXECUTABLE_MISSING", f"프로세스를 시작할 수 없습니다: {exc}") from None
        s = _Sampler(p.pid)
        s.start()
        return LimitedProcess(p, extra={"sampler": s, "pgid": p.pid})

    def terminate(self, proc: LimitedProcess, timeout_s: float = 30) -> None:
        pgid = proc.extra.get("pgid", proc.pid)
        try:
            children = psutil.Process(proc.pid).children(recursive=True)
        except psutil.Error:
            children = []
        try:
            os.killpg(pgid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        deadline = time.time() + min(5.0, timeout_s)
        while time.time() < deadline and proc.poll() is None:
            time.sleep(0.05)
        for c in children:
            try:
                c.kill()
            except psutil.Error:
                pass
        try:
            os.killpg(pgid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        try:
            proc.wait(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            pass
        psutil.wait_procs(children, timeout=2)

    def accounting(self, proc: LimitedProcess) -> Accounting:
        s: _Sampler = proc.extra["sampler"]
        return Accounting(peak_memory_bytes=s.peak_rss or None, cpu_time_s=round(sum(s.cpu_times.values()), 3),
                          cpu_cap_enforced=False)

    def close(self, proc: LimitedProcess) -> None:
        s = proc.extra.get("sampler")
        if s:
            s.stop()
