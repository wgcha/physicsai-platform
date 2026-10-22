"""작업 대기열 설정 절 `worker.queues`(job-queues.md §9). 검증은 validate_queues.py."""

from __future__ import annotations

from typing import Any

from pydantic import Field

from ._model import _M


class QueueCpuCfg(_M):
    max_concurrent: int = 4  # CPU 대기열 동시 실행 상한(1~16, 2026-10-22 사용자 결정 — JQ-6)
    min_free_memory_gb: float = 8  # 수령 시 여유 메모리 문(0 = 검사 안 함). GPU 수령에는 적용 안 함


class WorkerQueuesCfg(_M):
    """GPU 동시 수는 1 고정이라 키가 없다. `gpu`는 있으면 검증 오류가 되도록 받기만 한다(알 수 없는 키 대신 이유를 알려 준다)."""

    cpu: QueueCpuCfg = Field(default_factory=QueueCpuCfg)
    total_cap: bool = True  # 워커 부모 Job Object로 전체 자원 상한(false면 작업당 몫)
    step_resource: dict[str, str] = Field(default_factory=dict)  # 현장 보정: LOCAL step 키 → cpu|gpu
    gpu: Any = None  # 금지 키(validate_queues가 거부)
