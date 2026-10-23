"""피크 보존 대표 원 노드 격자 군집 LOD(contour3d-field.md §7.2, C3F-8). numpy만, 결정적.

1. 키 = (격자 셀 floor((p − bbox_min) / h), 정점 법선 주축 방향 6버킷) — 얇은 판의 윗면·아랫면이 합쳐지지 않는다.
2. h = 군집 수 ≤ target을 만족하는 가장 작은 셀 크기(bbox 대각선 기준 이분 탐색 20회).
3. 대표 = 군 안에서 피크(전체 프레임 |값| 최대)가 가장 큰 원 정점, 같으면 작은 노드 ID(값 없는 정점은 피크 −∞).
4. LOD 삼각형 = 원 삼각형 정점을 대표로 바꾼 것, 퇴화·중복(같은 정점 집합) 제거. LOD 정점 = 쓰인 대표(원 정점 번호 오름차순 = `_SRC`).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

BISECT_STEPS = 20
MIN_CELL_RATIO = 1.0 / (1 << 17)  # 셀 크기 하한 = 대각선 × 2^-17(키 정수 범위)


@dataclass
class Lod:
    src: np.ndarray  # uint32 [M] 원 정점 번호(오름차순)
    triangles: np.ndarray  # uint32 [K,3] LOD 정점 번호
    cell: float  # 셀 크기 mm


def vertex_normal_bucket(xyz: np.ndarray, tris: np.ndarray) -> np.ndarray:
    """면적 가중 정점 법선 → 주축 방향 버킷 0..5(2·축 + 음수). 법선 0이면 0."""
    n = xyz.shape[0]
    a, b, c = xyz[tris[:, 0]], xyz[tris[:, 1]], xyz[tris[:, 2]]
    fn = np.cross(b - a, c - a)
    acc = np.zeros((n, 3), dtype=np.float64)
    for k in range(3):
        for col in range(3):
            acc[:, k] += np.bincount(tris[:, col], weights=fn[:, k], minlength=n)
    ax = np.argmax(np.abs(acc), axis=1)
    neg = acc[np.arange(n), ax] < 0
    return (2 * ax + neg).astype(np.int64)


def _keys(xyz: np.ndarray, lo: np.ndarray, h: float, bucket: np.ndarray, dims: np.ndarray) -> np.ndarray:
    cell = np.floor((xyz - lo) / h).astype(np.int64)
    cell = np.minimum(cell, dims - 1)
    return ((cell[:, 0] * dims[1] + cell[:, 1]) * dims[2] + cell[:, 2]) * 6 + bucket


def _dims(span: np.ndarray, h: float) -> np.ndarray:
    return np.floor(span / h).astype(np.int64) + 1


def build(xyz: np.ndarray, tris: np.ndarray, peak: np.ndarray, node_ids: np.ndarray, target: int) -> Lod:
    """xyz float64 [N,3](정점 순서), tris int [T,3], peak float64 [N](NaN·−inf = 값 없음), node_ids [N], target = 최대 정점 수."""
    tris = np.asarray(tris, dtype=np.int64)
    used = np.zeros(xyz.shape[0], dtype=bool)
    used[tris.ravel()] = True
    uidx = np.flatnonzero(used)
    p = xyz[uidx]
    bucket = vertex_normal_bucket(xyz, tris)[uidx]
    lo, hi = p.min(axis=0), p.max(axis=0)
    span = hi - lo
    diag = float(np.sqrt((span ** 2).sum())) or 1.0

    def count(h: float) -> int:
        return int(np.unique(_keys(p, lo, h, bucket, _dims(span, h))).size)

    h_lo, h_hi = diag * MIN_CELL_RATIO, diag
    if count(h_lo) <= target:
        h = h_lo
    else:
        for _ in range(BISECT_STEPS):
            mid = (h_lo + h_hi) / 2.0
            if count(mid) <= target:
                h_hi = mid
            else:
                h_lo = mid
        h = h_hi
    key = _keys(p, lo, h, bucket, _dims(span, h))
    pk = np.where(np.isfinite(peak[uidx]), peak[uidx], -np.inf)
    order = np.lexsort((np.asarray(node_ids, dtype=np.int64)[uidx], -pk, key))  # 키 → 피크 큰 순 → 노드 ID 작은 순
    ks = key[order]
    first = np.ones(ks.size, dtype=bool)
    first[1:] = ks[1:] != ks[:-1]
    grp = np.cumsum(first) - 1  # 정렬 위치 → 군 번호
    rep_of_group = uidx[order[first]]
    rep = np.empty(xyz.shape[0], dtype=np.int64)
    rep[:] = -1
    rep[uidx[order]] = rep_of_group[grp]
    t = rep[tris]
    ok = (t[:, 0] != t[:, 1]) & (t[:, 1] != t[:, 2]) & (t[:, 0] != t[:, 2])
    t = t[ok]
    if t.size:
        srt = np.sort(t, axis=1)
        _u, keep = np.unique(srt, axis=0, return_index=True)
        t = t[np.sort(keep)]
    src = np.unique(t.ravel()) if t.size else np.zeros(0, dtype=np.int64)
    local = np.searchsorted(src, t) if t.size else np.zeros((0, 3), dtype=np.int64)
    return Lod(src=src.astype(np.uint32), triangles=canonical_triangles(local).astype(np.uint32), cell=float(h))


def canonical_triangles(t: np.ndarray) -> np.ndarray:
    """삼각형을 최소 정점이 앞에 오도록 회전(감김 방향 유지)하고 (v0, v1, v2) 순으로 정렬한다(결정적)."""
    t = np.asarray(t, dtype=np.int64).reshape(-1, 3)
    if not t.size:
        return t
    r = np.argmin(t, axis=1)
    rows = np.arange(t.shape[0])[:, None]
    rot = t[rows, (r[:, None] + np.arange(3)[None, :]) % 3]
    return rot[np.lexsort((rot[:, 2], rot[:, 1], rot[:, 0]))]
