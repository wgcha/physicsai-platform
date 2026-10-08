"""코어 공통 예외. 사용자 표시 메시지는 한국어."""

from __future__ import annotations

from typing import Any


class DomainError(Exception):
    """API가 HTTP 오류로, 워커가 step 실패로 바꾸는 도메인 오류."""

    status: int = 400

    def __init__(self, code: str, message: str, status: int | None = None, **extra: Any) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        if status is not None:
            self.status = status
        self.extra = extra

    def detail(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, **self.extra}


class StepFailure(Exception):
    """워커 step 실패(§7.4 실패 코드)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message[:500]
