from __future__ import annotations

from .gateway import HpcAvailability, HpcGatewayError, HpcStatus, HpcSubmitResult, HpcSubmitSpec


class NoneHpcGateway:
    def availability(self) -> HpcAvailability:
        return HpcAvailability(False, "none", "PBS 연결 안 됨")

    def submit(self, spec: HpcSubmitSpec) -> HpcSubmitResult:
        raise HpcGatewayError("NOT_CONFIGURED", "PBS 연결 안 됨")

    def status(self, external_job_id: str) -> HpcStatus:
        raise HpcGatewayError("NOT_CONFIGURED", "PBS 연결 안 됨")

    def cancel(self, external_job_id: str) -> None:
        raise HpcGatewayError("NOT_CONFIGURED", "PBS 연결 안 됨")
