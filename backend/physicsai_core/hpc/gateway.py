"""HpcJobGateway 프로토콜과 팩터리(§12.2). API는 availability()만 호출한다."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Protocol

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


def get_hpc_gateway(settings: Any) -> HpcJobGateway:
    mode = settings.hpc.gateway
    if mode == "command":
        from .command import CommandHpcGateway

        return CommandHpcGateway(settings.hpc)
    if mode == "adapter":
        from .adapter import AdapterHpcGateway

        return AdapterHpcGateway()
    from .none import NoneHpcGateway

    return NoneHpcGateway()
