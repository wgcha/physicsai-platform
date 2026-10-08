"""사내 어댑터 자리(§12.1). 어댑터 패키지를 import하지 않는다."""

from __future__ import annotations

from .gateway import HpcAvailability, HpcGatewayError, HpcStatus, HpcSubmitResult, HpcSubmitSpec

_MSG = "어댑터 job API 미확인 — 미구현"


class AdapterHpcGateway:
    def availability(self) -> HpcAvailability:
        return HpcAvailability(False, "adapter", _MSG)

    def submit(self, spec: HpcSubmitSpec) -> HpcSubmitResult:
        raise HpcGatewayError("NOT_CONFIGURED", _MSG)

    def status(self, external_job_id: str) -> HpcStatus:
        raise HpcGatewayError("NOT_CONFIGURED", _MSG)

    def cancel(self, external_job_id: str) -> None:
        raise HpcGatewayError("NOT_CONFIGURED", _MSG)
