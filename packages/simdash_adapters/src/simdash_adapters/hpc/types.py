"""HpcJobGateway 프로토콜과 값 형식(platform.md §12.2). 모양·Literal 값·오류 코드는 1차 계약 그대로.

오류 코드(`HpcGatewayError.code`): NOT_CONFIGURED, SUBMIT_FAILED, PARSE_FAILED, TIMEOUT, UNAVAILABLE.
`HpcGatewayError` 메시지와 `HpcSubmitResult.raw_stdout`은 마스킹하지 않은 원문이다 — 저장·로그 전에 호출자가 마스킹한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

__all__ = ["HpcState", "HpcAvailability", "HpcSubmitSpec", "HpcSubmitResult", "HpcStatus", "HpcGatewayError", "HpcJobGateway"]

HpcState = Literal["QUEUED", "RUNNING", "FINISHED", "UNKNOWN"]


@dataclass(frozen=True)
class HpcAvailability:
    configured: bool
    mode: Literal["none", "command", "adapter"]
    message: str


@dataclass(frozen=True)
class HpcSubmitSpec:
    job_name: str
    run_key: str
    study: str
    input_file: str
    input_dir: str
    result_dir: str
    queue: str | None
    ncpus: int | None
    walltime: str | None


@dataclass(frozen=True)
class HpcSubmitResult:
    external_job_id: str
    raw_stdout: str


@dataclass(frozen=True)
class HpcStatus:
    state: HpcState
    raw_state: str | None
    exit_code: int | None
    not_found: bool


class HpcGatewayError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class HpcJobGateway(Protocol):
    def availability(self) -> HpcAvailability: ...

    def submit(self, spec: HpcSubmitSpec) -> HpcSubmitResult: ...

    def status(self, external_job_id: str) -> HpcStatus: ...

    def cancel(self, external_job_id: str) -> None: ...
