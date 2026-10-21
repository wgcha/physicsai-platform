"""⑤ 영향도(upload-report.md §9.1·§9.3.1, V-RP-4): PRCC(순위 편상관)·표준화 회귀계수(SRC)·R² — numpy 구현.

프런트 `frontend/src/analysis/influence.ts`(s14 A5)와 **같은 알고리즘·같은 값**이다(골든 `influenceGolden.json` 허용오차 1e-9):
- PRCC: 모든 열(변수 + 응답)을 평균 순위(동순위 평균)로 바꾼 순위 상관행렬 R의 역행렬 P에서 ρ_j = −P[j][y] / √(P[j][j]·P[y][y]).
- SRC: 표준화 OLS(절편 포함)의 계수 β = R_xx⁻¹ r_xy, R² = r_xyᵀ·β. 유의성은 보고하지 않는다.
행렬이 특이(공선·n 부족)하면 해당 값은 None("계산 불가"), 상수 변수는 행렬에서 빼고 그 변수만 None. numpy는 함수 안에서 불러온다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

SINGULAR_EPS = 1e-10
WEAK_R2 = 0.7
WEAK_R2_TEXT = "선형 근사가 약합니다 — PRCC·지도를 함께 보세요"


@dataclass
class InfluenceResult:
    n: int
    names: list[str]
    prcc: list[float | None]
    src: list[float | None]
    r2: float | None
    unavailable: str | None = None  # 계산 자체를 못 하는 사유(n < p+2, 응답 상수). 있으면 prcc·src는 전부 None
    mismatch: list[str] = field(default_factory=list)


def avg_ranks(v: Any) -> Any:
    """평균 순위(1부터, 동순위는 평균) — 프런트 `avgRanks`와 같은 값."""
    import numpy as np

    a = np.asarray(v, dtype=np.float64)
    order = np.lexsort((np.arange(len(a)), a))
    sa = a[order]
    out = np.empty(len(a), dtype=np.float64)
    i = 0
    n = len(a)
    while i < n:
        j = i
        while j + 1 < n and sa[j + 1] == sa[i]:
            j += 1
        out[order[i:j + 1]] = (i + j) / 2 + 1
        i = j + 1
    return out


def corr_matrix(cols: Sequence[Any]) -> Any | None:
    """열들의 피어슨 상관행렬. 표준편차 0인 열이 있거나 n < 2면 None."""
    import numpy as np

    if not len(cols) or len(cols[0]) < 2:
        return None
    d = np.array([np.asarray(c, dtype=np.float64) - np.mean(c) for c in cols])
    ss = (d * d).sum(axis=1)
    if np.any(~(ss > 0)):
        return None
    return (d @ d.T) / np.sqrt(np.outer(ss, ss))


def invert(M: Any) -> Any | None:
    """Gauss-Jordan(부분 피벗) 역행렬 — 피벗 절댓값 < SINGULAR_EPS면 None(프런트 `invert`와 같은 판정)."""
    import numpy as np

    n = len(M)
    A = np.hstack([np.array(M, dtype=np.float64), np.eye(n)])
    for c in range(n):
        p = c + int(np.argmax(np.abs(A[c:, c])))
        if abs(A[p, c]) < SINGULAR_EPS:
            return None
        if p != c:
            A[[c, p]] = A[[p, c]]
        A[c] /= A[c, c]
        for r in range(n):
            if r != c and A[r, c] != 0:
                A[r] -= A[r, c] * A[c]
    return A[:, n:]


def compute_influence(names: Sequence[str], cols: Sequence[Sequence[float]], y: Sequence[float]) -> InfluenceResult:
    """열(변수) 선택 후 PRCC·SRC. cols[j] = 변수 j의 값(길이 n), y = 응답."""
    import numpy as np

    n, p = len(y), len(names)
    names = list(names)

    def none(why: str) -> InfluenceResult:
        return InfluenceResult(n, names, [None] * p, [None] * p, None, why)

    if n < p + 2:
        return none(f"유효 run이 부족합니다(n {n} < 변수 {p} + 2)")
    ya = np.asarray(y, dtype=np.float64)
    if not (ya.max() > ya.min()):
        return none("응답 값이 모두 같아 계산할 수 없습니다")
    ca = [np.asarray(c, dtype=np.float64) for c in cols]
    live = [j for j, c in enumerate(ca) if c.max() > c.min()]
    prcc: list[float | None] = [None] * p
    src: list[float | None] = [None] * p
    r2: float | None = None
    if live:
        R = corr_matrix([*(avg_ranks(ca[j]) for j in live), avg_ranks(ya)])
        P = invert(R) if R is not None else None
        if P is not None:
            iy = len(live)
            for a, j in enumerate(live):
                d = P[a, a] * P[iy, iy]
                prcc[j] = float(-P[a, iy] / np.sqrt(d)) if d > 0 else None
        C = corr_matrix([*(ca[j] for j in live), ya])
        if C is not None:
            k = len(live)
            inv = invert(C[:k, :k])
            if inv is not None:
                rxy = C[:k, k]
                beta = inv @ rxy
                for a, j in enumerate(live):
                    src[j] = float(beta[a])
                r2 = float(beta @ rxy)
    return InfluenceResult(n, names, prcc, src, r2)


def influence_rows(r: InfluenceResult) -> list[dict[str, Any]]:
    """|PRCC| 내림차순(계산 불가는 뒤, 같으면 원래 순서). mismatch = PRCC와 SRC 부호가 다름."""
    rows = [{"name": nm, "prcc": r.prcc[i], "src": r.src[i], "i": i} for i, nm in enumerate(r.names)]
    rows.sort(key=lambda x: (x["prcc"] is None, -abs(x["prcc"] or 0.0), x["i"]))
    out = []
    for x in rows:
        a, b = x["prcc"], x["src"]
        mm = a is not None and b is not None and a != 0 and b != 0 and (a > 0) != (b > 0)
        out.append({"name": x["name"], "prcc": a, "src": b, "mismatch": mm})
    return out
