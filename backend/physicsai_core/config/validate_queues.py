"""작업 대기열 설정 검증(job-queues.md §9). `validate.validate_settings`가 `check(s, add)` 1줄로 부른다(validate_gpu 관례)."""

from __future__ import annotations

from collections.abc import Callable

from ..queues import contract_gpu_step_keys, known_local_step_keys
from .schema import Settings

CPU_CONCURRENT_RANGE = (1, 16)
STEP_RESOURCE_VALUES = ("cpu", "gpu")


def check(s: Settings, add: Callable[[str, str], None]) -> None:
    q = s.worker.queues
    lo, hi = CPU_CONCURRENT_RANGE
    if not lo <= q.cpu.max_concurrent <= hi:
        add("worker.queues.cpu.max_concurrent", f"{lo}~{hi}")
    mem = q.cpu.min_free_memory_gb
    # 기본값(8)은 max_memory_gb가 작은 기존 설정(시연 4 GB 등)을 깨지 않도록 명시한 값에만 상한(max_memory_gb 미만)을 적용한다
    explicit = "min_free_memory_gb" in q.cpu.model_fields_set
    if mem < 0 or (explicit and mem >= s.worker.max_memory_gb):
        add("worker.queues.cpu.min_free_memory_gb", "0(검사 안 함) 이상, worker.max_memory_gb 미만")
    if "gpu" in q.model_fields_set:
        add("worker.queues.gpu", "GPU 작업은 동시에 1개만 실행합니다(설정으로 바꿀 수 없습니다)")
    known = known_local_step_keys()
    gpu_steps = contract_gpu_step_keys()
    for k, v in q.step_resource.items():
        key = f"worker.queues.step_resource.{k}"
        if k not in known:
            add(key, "알려진 LOCAL step 키가 아닙니다(HPC_SUBMIT·HPC_WAIT·COLLECT·INTERNAL step은 바꿀 수 없습니다)")
        elif v not in STEP_RESOURCE_VALUES:
            add(key, "cpu 또는 gpu")
        elif k in gpu_steps and v != "gpu":
            add(key, "GPU 단계(PhysicsAI 추론)는 CPU로 내릴 수 없습니다 — GPU 작업은 동시에 1개만 실행합니다")
