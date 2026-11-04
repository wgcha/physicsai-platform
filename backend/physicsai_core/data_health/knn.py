"""③ 파라미터 공간 kNN 국소 중앙값 잔차(data-health.md §3.4, DH-6). numpy만, O(n²p).

정규화 u = (p − min)/(max − min)(min·max = DOE `parameters_snapshot`, 없으면 표본 범위, max = min인 파라미터는 뺌).
지표마다 유효 run끼리 유클리드 거리, 이웃 = 자기 제외 가까운 k = min(knn_k, n−1)개(거리 동률 = run 순서 인덱스, 즉 입력 목록 순서 — 부동소수 잡음은 DIST_DECIMALS 자리로 반올림해 같은 거리로 본다).
잔차 r_i = x_i − med(x_N(i)), 점수 s_i = r_i / (1.4826·MAD(r))(MAD 0 대체 규칙은 stats와 같음).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from .stats import finite, robust_scale

DIST_DECIMALS = 12  # 이 자리까지 같으면 동률(결정적 정렬)


@dataclass
class ParamSpace:
    names: list[str]                     # 쓰는 파라미터(정렬)
    u: dict[str, np.ndarray]             # run 이름 → 정규화 벡터(파라미터 결측 run은 없음)
    mixed: bool = False                  # run마다 파라미터 이름 집합이 다름(여러 DOE 혼합) → kNN 전부 생략


def build_space(params_by_run: Mapping[str, Mapping[str, float] | None], snapshot: Sequence[Mapping[str, Any]] | None) -> ParamSpace:
    have = {k: {n: f for n, v in p.items() if (f := finite(v)) is not None} for k, p in params_by_run.items() if p}
    have = {k: p for k, p in have.items() if p}
    if not have:
        return ParamSpace([], {})
    name_sets = {frozenset(p) for p in have.values()}
    if len(name_sets) > 1:
        return ParamSpace([], {}, mixed=True)
    names = sorted(next(iter(name_sets)))
    snap = {str(s.get("name")): s for s in (snapshot or []) if isinstance(s, Mapping)}
    lo: dict[str, float] = {}
    hi: dict[str, float] = {}
    for n in names:
        s = snap.get(n) or {}
        a, b = finite(s.get("min")), finite(s.get("max"))
        if a is None or b is None or not b > a:
            col = [p[n] for p in have.values()]
            a, b = min(col), max(col)
        lo[n], hi[n] = a, b
    names = [n for n in names if hi[n] > lo[n]]
    u = {k: np.array([(p[n] - lo[n]) / (hi[n] - lo[n]) for n in names], dtype=np.float64) for k, p in have.items()}
    return ParamSpace(names, u)


@dataclass
class KnnResult:
    skipped: bool
    s: dict[str, float | None] = field(default_factory=dict)         # run 이름 → 점수
    mean_dist: dict[str, float | None] = field(default_factory=dict)  # run 이름 → 이웃 평균 거리(정규화)
    k: int = 0


def knn_scores(space: ParamSpace, values: Mapping[str, object], *, knn_k: int, knn_min_n: int) -> KnnResult:
    """values = {run 이름: 지표 값}. 유효 = 값이 유한하고 파라미터 벡터가 있는 run. n < knn_min_n·파라미터 없음·혼합 → 생략."""
    if space.mixed or not space.names:
        return KnnResult(skipped=True)
    names = [k for k, v in values.items() if finite(v) is not None and k in space.u]  # 입력 순서 = run 순서 인덱스(동률 정렬 기준)
    n = len(names)
    if n < knn_min_n or n < 2:
        return KnnResult(skipped=True)
    k = max(1, min(knn_k, n - 1))
    x = np.array([float(values[nm]) for nm in names], dtype=np.float64)  # type: ignore[arg-type]
    pts = np.stack([space.u[nm] for nm in names])
    d = np.sqrt(((pts[:, None, :] - pts[None, :, :]) ** 2).sum(axis=2))
    np.fill_diagonal(d, np.inf)
    dr = np.round(d, DIST_DECIMALS)
    order = np.argsort(dr, axis=1, kind="stable")[:, :k]  # 안정 정렬 → 거리 동률은 run 순서 인덱스(낮은 쪽 먼저)
    resid = np.array([x[i] - float(np.median(x[order[i]])) for i in range(n)])
    _mad, scale, _kind = robust_scale(resid, float(np.median(resid)))
    res = KnnResult(skipped=False, k=k)
    for i, nm in enumerate(names):
        res.s[nm] = 0.0 if scale == 0 else float(resid[i] / scale)
        res.mean_dist[nm] = float(np.mean(d[i, order[i]]))
    return res
