"""Shell element quality (shell-morph section 6.6): warpage, skew, aspect, Jacobian, inversion, edge / dt ratios.

Definitions (element local plane, HyperMesh 2D convention): warpage = larger normal angle of the two
diagonal splits of a quad (triangles 0); skew = 90 deg - smallest angle between the lines joining opposite
edge midpoints (quad), max deviation from 90 deg of vertex->opposite-midpoint vs the other two midpoints
line (triangle); aspect = longest / shortest edge; Jacobian = min corner det J / center det J of the
bilinear map (triangles 1); characteristic length h = area / longest (edge, diagonal) (quad),
2 area / longest edge (triangle).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..common import rnd


@dataclass
class ShellMetrics:
    warp: np.ndarray
    skew: np.ndarray
    aspect: np.ndarray
    jac: np.ndarray
    normal: np.ndarray  # (m,3) unit
    min_det: np.ndarray  # quad: min corner det (local plane), tri: 2 * area
    min_edge: np.ndarray
    h: np.ndarray


def _ang(a, b):
    na = np.linalg.norm(a, axis=1)
    nb = np.linalg.norm(b, axis=1)
    c = np.einsum("ij,ij->i", a, b) / np.maximum(na * nb, 1e-300)
    return np.degrees(np.arccos(np.clip(c, -1.0, 1.0)))


def metrics(xyz: np.ndarray, conn: np.ndarray, tri: np.ndarray) -> ShellMetrics:
    m = len(conn)
    warp = np.zeros(m)
    skew = np.zeros(m)
    aspect = np.zeros(m)
    jac = np.ones(m)
    normal = np.zeros((m, 3))
    min_det = np.zeros(m)
    min_edge = np.zeros(m)
    h = np.zeros(m)
    q = ~tri
    if q.any():
        a, b, c, d = (xyz[conn[q, i]] for i in range(4))
        n1 = np.cross(b - a, c - a)
        n2 = np.cross(c - a, d - a)
        n3 = np.cross(b - a, d - a)
        n4 = np.cross(c - b, d - b)
        warp[q] = np.maximum(_ang(n1, n2), _ang(n3, n4))
        mab, mbc, mcd, mda = 0.5 * (a + b), 0.5 * (b + c), 0.5 * (c + d), 0.5 * (d + a)
        t = _ang(mcd - mab, mda - mbc)
        skew[q] = 90.0 - np.minimum(t, 180.0 - t)
        e = np.stack([np.linalg.norm(b - a, axis=1), np.linalg.norm(c - b, axis=1), np.linalg.norm(d - c, axis=1), np.linalg.norm(a - d, axis=1)], 1)
        aspect[q] = e.max(1) / np.maximum(e.min(1), 1e-300)
        min_edge[q] = e.min(1)
        N = np.cross(c - a, d - b)
        nn = np.linalg.norm(N, axis=1)
        N = N / np.maximum(nn, 1e-300)[:, None]
        normal[q] = N
        ref = np.where(np.abs(N[:, :1]) < 0.9, np.array([[1.0, 0.0, 0.0]]), np.array([[0.0, 1.0, 0.0]]))
        e1 = np.cross(N, ref)
        e1 /= np.maximum(np.linalg.norm(e1, axis=1), 1e-300)[:, None]
        e2 = np.cross(N, e1)
        P = [np.stack([np.einsum("ij,ij->i", p - a, e1), np.einsum("ij,ij->i", p - a, e2)], 1) for p in (a, b, c, d)]

        def cr(u, v):
            return u[:, 0] * v[:, 1] - u[:, 1] * v[:, 0]

        dets = np.stack([0.25 * cr(P[(i + 1) % 4] - P[i], P[(i + 3) % 4] - P[i]) for i in range(4)], 1)
        dxi = 0.25 * (-P[0] + P[1] + P[2] - P[3])
        deta = 0.25 * (-P[0] - P[1] + P[2] + P[3])
        dc = cr(dxi, deta)
        jac[q] = dets.min(1) / np.where(np.abs(dc) > 1e-300, dc, 1e-300)
        min_det[q] = dets.min(1)
        area = 0.5 * (np.linalg.norm(n1, axis=1) + np.linalg.norm(n2, axis=1))
        diag = np.stack([np.linalg.norm(c - a, axis=1), np.linalg.norm(d - b, axis=1)], 1)
        h[q] = area / np.maximum(np.maximum(e.max(1), diag.max(1)), 1e-300)
    if tri.any():
        a, b, c = (xyz[conn[tri, i]] for i in range(3))
        n = np.cross(b - a, c - a)
        nn = np.linalg.norm(n, axis=1)
        normal[tri] = n / np.maximum(nn, 1e-300)[:, None]
        mab, mbc, mca = 0.5 * (a + b), 0.5 * (b + c), 0.5 * (c + a)
        s = np.stack([np.abs(90.0 - _ang(mbc - a, mca - mab)), np.abs(90.0 - _ang(mca - b, mab - mbc)), np.abs(90.0 - _ang(mab - c, mbc - mca))], 1)
        skew[tri] = s.max(1)
        e = np.stack([np.linalg.norm(b - a, axis=1), np.linalg.norm(c - b, axis=1), np.linalg.norm(a - c, axis=1)], 1)
        aspect[tri] = e.max(1) / np.maximum(e.min(1), 1e-300)
        min_edge[tri] = e.min(1)
        min_det[tri] = nn
        h[tri] = nn / np.maximum(e.max(1), 1e-300)
    return ShellMetrics(warp, skew, aspect, jac, normal, min_det, min_edge, h)


def _f(x):
    return None if x is None or not np.isfinite(x) else rnd(float(x))


def evaluate(base_xyz: np.ndarray, new_xyz: np.ndarray, conn: np.ndarray, tri: np.ndarray, q: dict) -> tuple[dict, str | None, list[dict]]:
    """(quality report, failure message, warnings)."""
    b = metrics(base_xyz, conn, tri)
    n = metrics(new_xyz, conn, tri)
    lim_w, lim_s, lim_a, lim_j = float(q["max_warpage_deg"]), float(q["max_skew_deg"]), float(q["max_aspect"]), float(q["min_jacobian"])
    inv = (np.einsum("ij,ij->i", n.normal, b.normal) <= 0) | (n.min_det <= 0)
    bad_w_abs, bad_s_abs, bad_a_abs, bad_j_abs = n.warp > lim_w, n.skew > lim_s, n.aspect > lim_a, n.jac < lim_j
    if q.get("relative_to_baseline", True):
        bw, bs, ba, bj = b.warp > lim_w, b.skew > lim_s, b.aspect > lim_a, b.jac < lim_j
        Lw = np.where(bw, b.warp + 2.0, lim_w)
        Ls = np.where(bs, 1.1 * b.skew, lim_s)
        La = np.where(ba, 1.1 * b.aspect, lim_a)
        Lj = np.where(bj, 0.9 * b.jac, lim_j)
    else:
        Lw, Ls, La, Lj = (np.full(len(conn), v) for v in (lim_w, lim_s, lim_a, lim_j))
    bad_w, bad_s, bad_a, bad_j = n.warp > Lw, n.skew > Ls, n.aspect > La, n.jac < Lj
    with np.errstate(divide="ignore", invalid="ignore"):
        mw = np.where(n.warp > 0, Lw / n.warp, np.inf)
        ms = np.where(n.skew > 0, Ls / n.skew, np.inf)
        ma = np.where(n.aspect > 0, La / n.aspect, np.inf)
        mj = np.where(Lj > 0, np.maximum(n.jac, 0.0) / Lj, np.inf)

    def _m(a):
        a = a[np.isfinite(a)] if np.any(np.isfinite(a)) else a
        v = float(a.min()) if len(a) else np.inf
        return rnd(v) if np.isfinite(v) else None
    base_bad = (b.warp > lim_w) | (b.skew > lim_s) | (b.aspect > lim_a) | (b.jac < lim_j)
    me_b, me_n = float(b.min_edge.min()), float(n.min_edge.min())
    edge_ratio = me_n / me_b if me_b > 0 else None
    dt_ratio = float(n.h.min()) / float(b.h.min()) if float(b.h.min()) > 0 else None
    rep = {
        "inverted": int(inv.sum()),
        "max_warpage_deg": _f(n.warp.max()), "baseline_max_warpage_deg": _f(b.warp.max()),
        "max_skew_deg": _f(n.skew.max()), "baseline_max_skew_deg": _f(b.skew.max()),
        "max_aspect": _f(n.aspect.max()), "baseline_max_aspect": _f(b.aspect.max()),
        "min_jacobian": _f(n.jac.min()), "baseline_min_jacobian": _f(b.jac.min()),
        "min_edge_mm": _f(me_n), "baseline_min_edge_mm": _f(me_b),
        "edge_ratio": _f(edge_ratio), "dt_ratio": _f(dt_ratio),
        "baseline_status": "FAIL" if base_bad.any() else "PASS",
        "failed_elements": {"warpage": int(bad_w.sum()), "skew": int(bad_s.sum()), "aspect": int(bad_a.sum()), "jacobian": int(bad_j.sum())},
        # min over elements of (effective limit / value) (>= 1 passes; effective limit = relative one for baseline-bad elements)
        "margins": {"warpage": _m(mw), "skew": _m(ms), "aspect": _m(ma), "jacobian": _m(mj)},
    }
    msgs = []
    if inv.any():
        msgs.append(f"{int(inv.sum())} inverted elements")
    for k, bad in (("warpage", bad_w), ("skew", bad_s), ("aspect", bad_a), ("jacobian", bad_j)):
        if bad.any():
            msgs.append(f"{int(bad.sum())} elements beyond the {k} limit")
    if edge_ratio is not None and edge_ratio < float(q["min_edge_ratio"]):
        msgs.append(f"edge_ratio {edge_ratio:.3f} < {q['min_edge_ratio']}")
    if dt_ratio is not None and dt_ratio < float(q["dt_ratio_min"]):
        msgs.append(f"dt_ratio {dt_ratio:.3f} < {q['dt_ratio_min']}")
    if q.get("min_edge_mm") is not None and me_n < float(q["min_edge_mm"]):
        msgs.append(f"min edge {me_n:.3f} mm < {q['min_edge_mm']} mm")
    warnings = []
    if base_bad.any():
        warnings.append({"code": "BASELINE_QUALITY_BELOW", "elements": int(base_bad.sum()), "message": f"{int(base_bad.sum())} baseline elements already exceed the absolute quality limits"})
    rep["status"] = "FAIL" if msgs else "PASS"
    return rep, ("quality: " + "; ".join(msgs)) if msgs else None, warnings
