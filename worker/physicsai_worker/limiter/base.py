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
    # 회계를 그룹 전체가 공유(Windows Job 1개) — 메모리 한도 도달이 어느 run 때문인지 시간대로 가린다(D3-53)
    shared_accounting: bool = False
    mem_ok_at: float | None = None  # 한도 미도달을 마지막으로 확인한 시각(perf_counter, 조회 전 시각)
    mem_hit_at: float | None = None  # 한도 도달을 처음 확인한 시각(perf_counter, 조회 후 시각)
    windows: list[list[Any]] = field(default_factory=list)  # 실행 구간 [시작, 끝|None]

    def add(self, proc: LimitedProcess) -> None:
        with self.lock:
            self.procs.append(proc)
            self.launched += 1

    def alive(self) -> list[LimitedProcess]:
        with self.lock:
            return [p for p in self.procs if p.poll() is None]

    def note_memory(self, hit: bool, t: float) -> None:
        """그룹 회계 표본 1개. 최고 사용량은 줄지 않으므로 도달 시각은 (mem_ok_at, mem_hit_at] 안이다."""
        with self.lock:
            if self.mem_hit_at is not None:
                return
            if hit:
                self.mem_hit_at = t
            elif self.mem_ok_at is None or t > self.mem_ok_at:
                self.mem_ok_at = t

    def run_started(self, t: float) -> int:
        with self.lock:
            self.windows.append([t, None])
            return len(self.windows) - 1

    def run_ended(self, idx: int, t: float) -> None:
        with self.lock:
            if self.windows[idx][1] is None:
                self.windows[idx][1] = t

    def memory_verdict(self, idx: int) -> str | None:
        """실행 구간 idx와 그룹 메모리 한도 도달 기록의 관계(D3-53).

        None = 도달 기록 없음 또는 이 구간과 겹치지 않음(이 run 탓이 아님) · "exact" = 도달 구간이 이 실행 안에 있고
        그 사이 다른 run이 돌지 않음 · "uncertain" = 겹치지만 다른 run도 함께 돌았거나 실행 전에 도달했을 수 있음."""
        inf = float("inf")
        with self.lock:
            hit, ok = self.mem_hit_at, self.mem_ok_at
            wins = [(w[0], inf if w[1] is None else w[1]) for w in self.windows]
        if hit is None:
            return None
        lo = -inf if ok is None else ok
        start, end = wins[idx]
        if not (start < hit and end > lo):  # 도달 확인 시각 ≤ 시작이면 시작 전 도달 → 이 run 탓 아님
            return None
        others = any(s < hit and e > lo for j, (s, e) in enumerate(wins) if j != idx)
        return "exact" if start <= lo and hit <= end and not others else "uncertain"


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
