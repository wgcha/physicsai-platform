"""자원 스냅샷(§11.6): CPU/RAM(psutil), GPU(설정 gpu_query argv, 제한기 밖, 타임아웃 5초)."""

from __future__ import annotations

import subprocess
from datetime import datetime, timezone
from typing import Any

import psutil


def query_gpu(argv: list[str] | None) -> list[dict[str, Any]]:
    if not argv:
        return []
    try:
        cp = subprocess.run(argv, shell=False, capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return []
    if cp.returncode != 0:
        return []
    out = []
    for line in cp.stdout.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 4:
            continue
        try:
            out.append({"name": parts[0], "util_pct": float(parts[1]), "mem_used_mb": float(parts[2]),
                        "mem_total_mb": float(parts[3])})
        except ValueError:
            continue
    return out


def sample(gpu_argv: list[str] | None, job: dict[str, Any] | None = None) -> dict[str, Any]:
    vm = psutil.virtual_memory()
    return {
        "sampled_at": datetime.now(timezone.utc).isoformat(),
        "cpu_pct": psutil.cpu_percent(interval=None),
        "ram_used_gb": round((vm.total - vm.available) / 2**30, 3),
        "ram_total_gb": round(vm.total / 2**30, 3),
        "gpu": query_gpu(gpu_argv),
        "job": job,
    }
