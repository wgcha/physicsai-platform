"""GPU 조회 설정 검증(phase3 §24.6 S19). `validate.validate_settings`가 `check(s, add)` 1줄로 부른다."""

from __future__ import annotations

from collections.abc import Callable

from .schema import Settings

# (키, 하한, 상한) — 메시지는 기존 규칙과 같은 "하한~상한"
_WORKER_RANGES: tuple[tuple[str, float, float], ...] = (
    ("gpu_query_timeout_s", 1, 120),
    ("gpu_backoff_after", 1, 100),
)


def _num(v: float) -> str:
    return str(int(v)) if float(v).is_integer() else f"{v:g}"


def check(s: Settings, add: Callable[[str, str], None]) -> None:
    w = s.worker
    for k, lo, hi in _WORKER_RANGES:
        if not lo <= getattr(w, k) <= hi:
            add(f"worker.{k}", f"{_num(lo)}~{_num(hi)}")
    base = w.resource_sample_interval_s
    mx = w.gpu_backoff_max_s
    if mx != 0 and not base <= mx <= 3600:
        add("worker.gpu_backoff_max_s", f"0(늘리지 않음) 또는 resource_sample_interval_s({_num(base)})~3600")
