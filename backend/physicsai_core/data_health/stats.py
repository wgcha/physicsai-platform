"""일반 z·견고 z(data-health.md §3.2). numpy float64. 결측(None·NaN·무한)은 분포 계산에서 제외한다."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field

import numpy as np

MAD_K = 1.4826        # 정규분포 σ에 맞춘 MAD 배율
MEANAD_K = 1.2533     # MAD가 0일 때 평균 절대 편차 배율(σ ≈ 1.2533 · MeanAD)
SKIP_SMALL_N = "SKIP_SMALL_N"


def finite(v: object) -> float | None:
    """유한 실수면 float, 아니면 None(bool·문자열 제외)."""
    if isinstance(v, bool) or not isinstance(v, (int, float, np.integer, np.floating)):
        return None
    f = float(v)
    return f if math.isfinite(f) else None


def robust_scale(x: np.ndarray, med: float) -> tuple[float, float, str]:
    """(MAD, 척도, 방식). 척도 = 1.4826·MAD, MAD=0이면 1.2533·MeanAD, 그것도 0이면 0(전부 같은 값). x는 비어 있지 않아야 한다."""
    dev = np.abs(x - med)
    mad = float(np.median(dev))
    if mad > 0:
        return mad, MAD_K * mad, "MAD"
    mean_ad = float(np.mean(dev))
    if mean_ad > 0:
        return mad, MEANAD_K * mean_ad, "MEANAD"
    return mad, 0.0, "ZERO"


@dataclass
class MetricStats:
    n: int
    skipped: bool
    mean: float | None = None
    std: float | None = None
    median: float | None = None
    mad: float | None = None
    scale: float | None = None
    scale_kind: str | None = None
    z: list[float | None] = field(default_factory=list)    # 입력과 같은 길이(결측·생략 = None)
    zr: list[float | None] = field(default_factory=list)


def summarize(values: Sequence[object], min_n: int) -> MetricStats:
    """지표 1개의 일반 z·견고 z. n(유효 값 수) < min_n → 생략(z·zr 전부 None, SKIP_SMALL_N)."""
    fv = [finite(v) for v in values]
    idx = [i for i, v in enumerate(fv) if v is not None]
    n = len(idx)
    out = MetricStats(n=n, skipped=n < min_n, z=[None] * len(fv), zr=[None] * len(fv))
    if n == 0 or out.skipped:
        return out
    x = np.array([fv[i] for i in idx], dtype=np.float64)
    mean = float(np.mean(x))
    std = float(np.std(x, ddof=1)) if n > 1 else 0.0
    med = float(np.median(x))
    mad, scale, kind = robust_scale(x, med)
    out.mean, out.std, out.median, out.mad, out.scale, out.scale_kind = mean, std, med, mad, scale, kind
    for i in idx:
        v = fv[i]
        assert v is not None
        out.z[i] = 0.0 if std == 0 else (v - mean) / std
        out.zr[i] = 0.0 if scale == 0 else (v - med) / scale
    return out
