"""다목적 비지배 판정·초부피(HV)·가중 추천(phase3 §22.5.5·§22.6 S17) — 표준 라이브러리 전용(API·워커 공용).

모든 함수는 **최소화 기준**(호출부가 sense=max 목적의 부호를 뒤집어 넘긴다). 예외: `recommend`·`weighted_scores`는 원 단위
값과 부호(signs: min = +1, max = −1)를 받는다(§22.6 — 전선 안에서 0 = 최선, 1 = 최악으로 맞춘 가중합).
API 프로세스는 numpy를 불러오지 않는다(§18.2) — 점 수백 개면 O(n²)로 충분하다(§22.17 R-8).
"""

from __future__ import annotations

import math
from collections.abc import Sequence

TIE_TOL = 1e-12
FLAT_TOL = 1e-12


def dominates(a: Sequence[float], b: Sequence[float]) -> bool:
    """∀i a_i ≤ b_i 이고 ∃j a_j < b_j."""
    strict = False
    for x, y in zip(a, b):
        if x > y:
            return False
        if x < y:
            strict = True
    return strict


def nondominated(points: Sequence[Sequence[float]]) -> list[int]:
    """비지배 점의 인덱스(입력 순서 유지). 같은 벡터는 앞 인덱스만 남긴다. O(n²m)."""
    out: list[int] = []
    pts = [tuple(float(v) for v in p) for p in points]
    for i, p in enumerate(pts):
        if any(pts[j] == p for j in range(i)):
            continue
        if any(dominates(q, p) for j, q in enumerate(pts) if j != i):
            continue
        out.append(i)
    return out


def _inside(points: Sequence[Sequence[float]], ref: Sequence[float]) -> list[tuple[float, ...]]:
    """기준점을 엄격히 지배하는 점만(어떤 i에서 f_i ≥ R_i면 제외)."""
    return [tuple(float(v) for v in p) for p in points
            if len(p) == len(ref) and all(math.isfinite(float(v)) and float(v) < float(r) for v, r in zip(p, ref))]


def _hv2(pts: Sequence[tuple[float, ...]], r1: float, r2: float) -> float:
    """2D 스윕: f₁ 오름차순(동점 f₂ 오름차순), f₂가 줄어드는 점만. HV = Σ (R₁ − a_k)(b_{k−1} − b_k), b₀ = R₂."""
    total = 0.0
    prev = r2
    for a, b in sorted((p[0], p[1]) for p in pts):
        if b < prev:
            total += (r1 - a) * (prev - b)
            prev = b
    return total


def hypervolume(points: Sequence[Sequence[float]], ref: Sequence[float]) -> float:
    """정확 HV(m = 2·3, 그 밖 ValueError). 기준점 밖·지배된 점은 기여 0."""
    m = len(ref)
    if m not in (2, 3):
        raise ValueError(f"초부피는 2·3목적만 계산합니다(m={m})")
    if any(len(p) != m for p in points):
        raise ValueError("점의 차원이 기준점과 다릅니다")
    pts = _inside(points, ref)
    if not pts:
        return 0.0
    r = [float(v) for v in ref]
    if m == 2:
        return _hv2(pts, r[0], r[1])
    # 3D 슬라이스: f₃ 오름차순, 두께 t_k = (다음 f₃ 또는 R₃) − f₃ₖ, 면적 = 앞 k개 (f₁, f₂) 2D HV
    pts.sort(key=lambda p: p[2])
    total = 0.0
    for k, p in enumerate(pts):
        top = pts[k + 1][2] if k + 1 < len(pts) else r[2]
        t = top - p[2]
        if t > 0:
            total += t * _hv2(pts[: k + 1], r[0], r[1])
    return total


def hv_improvement(front: Sequence[Sequence[float]], p: Sequence[float], ref: Sequence[float]) -> float:
    """HVI(p) = HV(front ∪ {p}) − HV(front)."""
    return hypervolume([*front, p], ref) - hypervolume(front, ref)


def frame_delta(ideal: Sequence[float], nadir: Sequence[float]) -> list[float]:
    """Δ_i = z^nad_i − z*_i, 평평하면(Δ ≤ 1e-12·max(1, |z*|)) max(1e-12, |z*|, 1)(§22.5.1)."""
    out = []
    for lo, hi in zip(ideal, nadir):
        d = float(hi) - float(lo)
        if not d > FLAT_TOL * max(1.0, abs(float(lo))):
            d = max(1e-12, abs(float(lo)), 1.0)
        out.append(d)
    return out


def normalize(f: Sequence[float], ideal: Sequence[float], nadir: Sequence[float]) -> list[float]:
    """f̂_i = (f_i − z*_i)/Δ_i(최소화 기준 값)."""
    return [(float(v) - float(lo)) / d for v, lo, d in zip(f, ideal, frame_delta(ideal, nadir))]


def make_frame(points: Sequence[Sequence[float]]) -> tuple[list[float], list[float]]:
    """(ideal, nadir) = 점들의 목적별 최소·최대(최소화 기준 값). 점이 없으면 ValueError."""
    if not points:
        raise ValueError("정규화 틀을 정할 점이 없습니다")
    m = len(points[0])
    return ([min(float(p[i]) for p in points) for i in range(m)], [max(float(p[i]) for p in points) for i in range(m)])


def _weights(weights: Sequence[float] | None, m: int) -> list[float]:
    w = [max(0.0, float(x)) if isinstance(x, (int, float)) and math.isfinite(x) else 0.0 for x in (weights or [])][:m]
    w += [0.0] * (m - len(w))
    tot = sum(w)
    return [x / tot for x in w] if tot > 0 else [1.0 / m] * m


def front_scale(front_obj: Sequence[Sequence[float]]) -> tuple[list[float], list[float]]:
    """(lo_i, hi_i) = 전선 안 목적별 최소·최대(원 단위)."""
    return make_frame(front_obj)


def weighted_scores(points: Sequence[Sequence[float]], lo: Sequence[float], hi: Sequence[float], signs: Sequence[float],
                    weights: Sequence[float] | None) -> tuple[list[float], list[list[float]]]:
    """(점수 S_j, g_{j,i}) — g = 전선 안 0 = 최선·1 = 최악(min: (f − lo)/(hi − lo), max: (hi − f)/(hi − lo)), 평평하면 0.
    예측 전선 점도 같은 lo·hi로(0~1 밖 허용, §22.6 5)."""
    m = len(lo)
    w = _weights(weights, m)
    gs: list[list[float]] = []
    scores: list[float] = []
    for p in points:
        g = []
        for i in range(m):
            span = float(hi[i]) - float(lo[i])
            if span <= FLAT_TOL * max(1.0, abs(float(lo[i]))):
                g.append(0.0)
            elif float(signs[i]) < 0:
                g.append((float(hi[i]) - float(p[i])) / span)
            else:
                g.append((float(p[i]) - float(lo[i])) / span)
        gs.append(g)
        scores.append(sum(wi * gi for wi, gi in zip(w, g)))
    return scores, gs


def recommend(front_obj: Sequence[Sequence[float]], signs: Sequence[float], weights: Sequence[float] | None
              ) -> tuple[int, list[float]]:
    """§22.6 가중 추천: (argmin S_j, 점수). 동점(|ΔS| ≤ 1e-12)은 g_{j,1} 작은 쪽 → 인덱스 작은 쪽(호출부는 front를
    (iter_no, doe_no) 순으로 넘긴다). 빈 전선이면 ValueError."""
    if not front_obj:
        raise ValueError("추천할 파레토 해가 없습니다")
    lo, hi = front_scale(front_obj)
    scores, gs = weighted_scores(front_obj, lo, hi, signs, weights)
    best = 0
    for j in range(1, len(scores)):
        d = scores[j] - scores[best]
        if d < -TIE_TOL or (abs(d) <= TIE_TOL and gs[j][0] < gs[best][0] - TIE_TOL):
            best = j
    return best, scores
