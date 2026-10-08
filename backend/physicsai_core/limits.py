"""워커 자원 한도 계산(§11.4)."""

from __future__ import annotations

import math
import os
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class EffectiveLimits:
    cores: int
    cpu_rate: int  # 1/100 % 단위(100~10000)
    memory_gb: float
    priority: str
    detected_cores: int
    detected_memory_gb: float

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def detect() -> tuple[int, float]:
    cores = os.cpu_count() or 1
    try:
        import psutil

        mem = psutil.virtual_memory().total / 2**30
    except Exception:  # pragma: no cover - psutil 없음
        mem = 0.0
    return cores, mem


def compute_limits(
    max_logical_cores: int,
    max_memory_gb: float,
    priority: str,
    auto_detect: bool,
    auto_detect_ratio: float,
    detected_cores: int,
    detected_mem_gb: float,
) -> EffectiveLimits:
    if auto_detect:
        eff_cores = min(max_logical_cores, math.floor(detected_cores * auto_detect_ratio))
        eff_mem = min(max_memory_gb, math.floor(detected_mem_gb * auto_detect_ratio * 100) / 100)
    else:
        eff_cores = min(max_logical_cores, detected_cores)
        eff_mem = min(max_memory_gb, detected_mem_gb)
    eff_cores = max(1, eff_cores)
    cpu_rate = max(100, min(10000, math.floor(eff_cores / max(1, detected_cores) * 10000)))
    return EffectiveLimits(eff_cores, cpu_rate, round(eff_mem, 3), priority, detected_cores, round(detected_mem_gb, 3))


def limits_from_settings(worker_cfg: Any, detected: tuple[int, float] | None = None) -> EffectiveLimits:
    dc, dm = detected or detect()
    return compute_limits(
        worker_cfg.max_logical_cores,
        worker_cfg.max_memory_gb,
        worker_cfg.priority,
        worker_cfg.auto_detect,
        worker_cfg.auto_detect_ratio,
        dc,
        dm,
    )
