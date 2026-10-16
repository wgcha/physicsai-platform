"""제한기 인터페이스(§11.5). 동시 실행 그룹(phase3 §14.5 `run_parallel`): 여러 프로세스가 작업 1개분 한도를 나눠 쓴다."""

from __future__ import annotations

import dataclasses
import subprocess
import threading
from dataclasses import dataclass, field
from typing import Any, Protocol

from physicsai_core.limits import EffectiveLimits


class LimiterError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class Accounting:
    peak_memory_bytes: int | None = None
    cpu_time_s: float | None = None
    cpu_cap_enforced: bool = False
    memory_limit_hit: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {"peak_memory_bytes": self.peak_memory_bytes, "cpu_time_s": self.cpu_time_s,
                "cpu_cap_enforced": self.cpu_cap_enforced}


@dataclass
class LimitedProcess:
    popen: subprocess.Popen
    handle: Any = None  # Windows Job 핸들 등
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def pid(self) -> int:
        return self.popen.pid

    @property
    def stdout(self) -> Any:
        return self.popen.stdout

    def poll(self) -> int | None:
        return self.popen.poll()

    def wait(self, timeout: float | None = None) -> int:
        return self.popen.wait(timeout)


@dataclass
class ProcGroup:
    """동시 실행 그룹(phase3 §14.5): `run_parallel`의 프로세스 묶음.

    Windows = Job Object 1개(handle)를 모든 프로세스가 공유(hstbatch `-multiexec`와 같은 방식) — 한도는 작업 1개분 그대로.
    POSIX·null = 공유 커널 객체가 없으므로 프로세스별 한도(메모리 = 한도/size, `limits`), 취소는 등록된 프로세스 트리 전부.
    """

    size: int
    limits: EffectiveLimits  # 프로세스 1개에 적용할 한도(POSIX = 메모리/size, Windows = 작업 한도 그대로)
    handle: Any = None  # Windows Job 핸들
    procs: list[LimitedProcess] = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)
    launched: int = 0
    closed: bool = False

    def add(self, proc: LimitedProcess) -> None:
        with self.lock:
            self.procs.append(proc)
            self.launched += 1

    def alive(self) -> list[LimitedProcess]:
        with self.lock:
            return [p for p in self.procs if p.poll() is None]


def per_process_limits(limits: EffectiveLimits, size: int) -> EffectiveLimits:
    """POSIX·null 그룹: 메모리 한도를 동시 수로 나눈다(작업 1개분 합계 유지, phase3 §14.5)."""
    return dataclasses.replace(limits, memory_gb=limits.memory_gb / max(1, int(size)))


class ProcessLimiter(Protocol):
    name: str
    cpu_cap_enforced: bool

    def launch(self, argv: list[str], cwd: str, env: dict[str, str], limits: EffectiveLimits,
               group: ProcGroup | None = None) -> LimitedProcess: ...

    def open_group(self, limits: EffectiveLimits, size: int) -> ProcGroup: ...

    def terminate_group(self, group: ProcGroup, timeout_s: float = 30) -> None: ...

    def group_accounting(self, group: ProcGroup) -> Accounting: ...

    def close_group(self, group: ProcGroup) -> None: ...

    def terminate(self, proc: LimitedProcess, timeout_s: float = 30) -> None: ...

    def accounting(self, proc: LimitedProcess) -> Accounting: ...

    def close(self, proc: LimitedProcess) -> None: ...


POPEN_TEXT_KW: dict[str, Any] = dict(
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    stdin=subprocess.DEVNULL,
    encoding="utf-8",
    errors="replace",
    bufsize=1,
    shell=False,
)


class ProcGroupMixin:
    """POSIX·null 공용 그룹 동작: 프로세스별 한도(메모리/size), 그룹 종료 = 살아 있는 프로세스 트리 전부 종료."""

    def open_group(self, limits: EffectiveLimits, size: int) -> ProcGroup:
        return ProcGroup(size=max(1, int(size)), limits=per_process_limits(limits, size))

    def terminate_group(self, group: ProcGroup, timeout_s: float = 30) -> None:
        for p in group.alive():
            self.terminate(p, timeout_s=timeout_s)  # type: ignore[attr-defined]

    def group_accounting(self, group: ProcGroup) -> Accounting:
        peak = cpu = None
        with group.lock:
            procs = list(group.procs)
        for p in procs:
            a = self.accounting(p)  # type: ignore[attr-defined]
            if a.peak_memory_bytes is not None:
                peak = max(peak or 0, a.peak_memory_bytes)
            if a.cpu_time_s is not None:
                cpu = (cpu or 0.0) + a.cpu_time_s
        return Accounting(peak_memory_bytes=peak, cpu_time_s=cpu, cpu_cap_enforced=bool(getattr(self, "cpu_cap_enforced", False)))

    def close_group(self, group: ProcGroup) -> None:
        group.closed = True
