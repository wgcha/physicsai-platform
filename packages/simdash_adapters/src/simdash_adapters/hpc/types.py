"""HpcJobGateway 프로토콜과 값 형식(platform.md §12.2). 모양·Literal 값·오류 코드는 1차 계약 그대로.

오류 코드(`HpcGatewayError.code`): NOT_CONFIGURED, SUBMIT_FAILED, PARSE_FAILED, TIMEOUT, NOT_FOUND, UNAVAILABLE,
SUBMISSION_UNKNOWN(scx — 제출 결과 모름: 자동 재제출·형제 취소 금지, phase3 §16·platform.md §12.5).
scx 확장(platform.md §12.5): `HpcAvailability.mode`에 "scx", `HpcStatus` 선택 필드(outcome·output_path·output_rel·error_message —
기본값이 있어 기존 생성 코드 불변), `HpcGatewayError`의 선택 속성(relay_code·http_status·retryable·transport).
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
    mode: Literal["none", "command", "adapter", "scx"]
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
    # scx(platform.md §12.5): FINISHED에서 outcome이 있으면 폴러가 그것으로 성공·실패를 판정(없으면 exit_code 규칙)
    outcome: Literal["SUCCEEDED", "FAILED"] | None = None
    output_path: str | None = None
    output_rel: str | None = None
    error_message: str | None = None


class HpcGatewayError(RuntimeError):
    """게이트웨이 오류. `code`는 위 목록. scx는 relay 오류 코드(`relay_code`)·HTTP 상태·재요청 안전 여부·전송 오류 여부를 더한다."""

    def __init__(self, code: str, message: str, *, relay_code: str | None = None, http_status: int | None = None,
                 retryable: bool = False, transport: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.relay_code = relay_code
        self.http_status = http_status
        self.retryable = retryable
        self.transport = transport


class HpcJobGateway(Protocol):
    def availability(self) -> HpcAvailability: ...

    def submit(self, spec: HpcSubmitSpec) -> HpcSubmitResult: ...

    def status(self, external_job_id: str) -> HpcStatus: ...

    def cancel(self, external_job_id: str) -> None: ...
