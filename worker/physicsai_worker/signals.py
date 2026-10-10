"""step 제어 신호(예외). 실행기와 step 핸들러가 함께 쓴다(step → executor 역참조 제거)."""

from __future__ import annotations


class Cancelled(Exception):
    pass


class StepSkipped(Exception):
    def __init__(self, label: str = "") -> None:
        super().__init__(label)
        self.label = label


class EnterWaitingHpc(Exception):
    """HPC_SUBMIT 성공 → T5."""
