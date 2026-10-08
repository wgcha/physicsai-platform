"""NullLimiter(§11.5): 제한 없이 실행(profile=dev 전용). terminate는 psutil 트리 kill."""

from __future__ import annotations

import subprocess

import psutil

from physicsai_core.limits import EffectiveLimits

from .base import POPEN_TEXT_KW, Accounting, LimitedProcess, LimiterError


class NullLimiter:
    name = "null"
    cpu_cap_enforced = False

    def launch(self, argv: list[str], cwd: str, env: dict[str, str], limits: EffectiveLimits) -> LimitedProcess:
        try:
            return LimitedProcess(subprocess.Popen(argv, cwd=cwd, env=env, **POPEN_TEXT_KW))
        except OSError as exc:
            raise LimiterError("EXECUTABLE_MISSING", f"프로세스를 시작할 수 없습니다: {exc}") from None

    def terminate(self, proc: LimitedProcess, timeout_s: float = 30) -> None:
        try:
            root = psutil.Process(proc.pid)
            procs = [root, *root.children(recursive=True)]
        except psutil.Error:
            return
        for p in procs:
            try:
                p.kill()
            except psutil.Error:
                pass
        psutil.wait_procs(procs, timeout=timeout_s)

    def accounting(self, proc: LimitedProcess) -> Accounting:
        return Accounting(cpu_cap_enforced=False)

    def close(self, proc: LimitedProcess) -> None:
        return None
