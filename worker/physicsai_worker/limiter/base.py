"""제한기 인터페이스(§11.5)."""

from __future__ import annotations

import subprocess
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


class ProcessLimiter(Protocol):
    name: str
    cpu_cap_enforced: bool

    def launch(self, argv: list[str], cwd: str, env: dict[str, str], limits: EffectiveLimits) -> LimitedProcess: ...

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
