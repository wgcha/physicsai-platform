"""Mesh quality metrics and the section 6.5 (c) judgement (numpy only).

* tetra stretch = 2*sqrt(6) * r_in / L_max (r_in = 3V / sum of face areas; regular tetra = 1),
* boundary-triangle aspect = L_max / (2*sqrt(3) * r_in) (r_in = 2A / perimeter; equilateral = 1),
* minimum edge length, inverted elements (V <= 0), scaled Jacobian (information only).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

SQ24 = 2.0 * np.sqrt(6.0)
SQ12 = 2.0 * np.sqrt(3.0)
_TET_EDGES = ((0, 1), (0, 2), (0, 3), (1, 2), (1, 3), (2, 3))
_TET_FACES = ((1, 2, 3), (0, 3, 2), (0, 1, 3), (0, 2, 1))


@dataclass
class TetMetrics:
    vol: np.ndarray
    stretch: np.ndarray
    min_edge: np.ndarray
    scaled_jacobian: np.ndarray


def tet_metrics(xyz: np.ndarray, tets: np.ndarray) -> TetMetrics:
    p = [xyz[tets[:, i]] for i in range(4)]
    vol = np.einsum("ij,ij->i", np.cross(p[1] - p[0], p[2] - p[0]), p[3] - p[0]) / 6.0
    area = sum(0.5 * np.linalg.norm(np.cross(p[b] - p[a], p[c] - p[a]), axis=1) for a, b, c in _TET_FACES)
    L = np.array([np.linalg.norm(p[a] - p[b], axis=1) for a, b in _TET_EDGES])
    lmax = L.max(axis=0)
    with np.errstate(divide="ignore", invalid="ignore"):
        r_in = np.where(area > 0, 3.0 * vol / area, 0.0)
        stretch = np.where(lmax > 0, SQ24 * r_in / lmax, 0.0)
    corners = ((0, 1, 2, 3), (1, 0, 3, 2), (2, 0, 1, 3), (3, 0, 2, 1))
    sj = np.full(len(tets), np.inf)
    for c, a, b, d in corners:
        e1, e2, e3 = p[a] - p[c], p[b] - p[c], p[d] - p[c]
        den = np.linalg.norm(e1, axis=1) * np.linalg.norm(e2, axis=1) * np.linalg.norm(e3, axis=1)
        with np.errstate(divide="ignore", invalid="ignore"):
            v = np.where(den > 0, np.sqrt(2.0) * np.abs(np.einsum("ij,ij->i", np.cross(e1, e2), e3)) / den, 0.0)
        v = np.where(vol > 0, v, -v)
        sj = np.minimum(sj, v)
    return TetMetrics(vol, stretch, L.min(axis=0), sj)


def tri_aspect(xyz: np.ndarray, tris: np.ndarray) -> np.ndarray:
    if len(tris) == 0:
        return np.zeros(0)
    a, b, c = (xyz[tris[:, i]] for i in range(3))
    la, lb, lc = np.linalg.norm(b - c, axis=1), np.linalg.norm(c - a, axis=1), np.linalg.norm(a - b, axis=1)
    area = 0.5 * np.linalg.norm(np.cross(b - a, c - a), axis=1)
    per = la + lb + lc
    lmax = np.maximum(np.maximum(la, lb), lc)
    with np.errstate(divide="ignore", invalid="ignore"):
        r_in = np.where(per > 0, 2.0 * area / per, 0.0)
        asp = np.where(r_in > 0, lmax / (SQ12 * r_in), np.inf)
    return asp


@dataclass
class QualityResult:
    status: str
    report: dict
    message: str | None
    baseline_ok: bool


def evaluate(base_xyz: np.ndarray, new_xyz: np.ndarray, tets: np.ndarray, skin: np.ndarray, q: dict) -> QualityResult:
    """Section 6.5 (c) on all cushion tets (``tets``) and boundary triangles (``skin``), global node rows."""
    b = tet_metrics(base_xyz, tets)
    m = tet_metrics(new_xyz, tets)
    ab = tri_aspect(base_xyz, skin)
    am = tri_aspect(new_xyz, skin)
    smin, amax, emin, eratio = float(q["min_stretch"]), float(q["max_aspect"]), float(q["min_edge_mm"]), float(q["min_edge_ratio"])
    rel = bool(q.get("relative_to_baseline", True))
    inverted = int((m.vol <= 0).sum())
    ok_s = m.stretch >= smin
    ok_a = am <= amax
    ok_e = m.min_edge >= emin if emin > 0 else np.ones(len(tets), dtype=bool)
    if rel:
        ok_s |= (b.stretch < smin) & (m.stretch >= 0.9 * b.stretch)
        ok_a |= (ab > amax) & (am <= 1.1 * ab)
        if emin > 0:
            ok_e |= (b.min_edge < emin) & (m.min_edge >= 0.9 * b.min_edge)
    bmin_e = float(b.min_edge.min())
    mmin_e = float(m.min_edge.min())
    dt_ratio = mmin_e / bmin_e if bmin_e > 0 else 0.0
    ok_dt = mmin_e >= eratio * bmin_e
    baseline_ok = bool((b.vol > 0).all() and (b.stretch >= smin).all() and (ab <= amax).all() and (emin <= 0 or (b.min_edge >= emin).all()))
    problems = []
    if inverted:
        problems.append(f"{inverted} inverted elements")
    if not ok_s.all():
        problems.append(f"{int((~ok_s).sum())} tetra below min stretch {smin:g} (min {float(m.stretch.min()):.3f})")
    if not ok_a.all():
        problems.append(f"{int((~ok_a).sum())} boundary triangles above max aspect {amax:g} (max {float(am.max()):.2f})")
    if not ok_e.all():
        problems.append(f"{int((~ok_e).sum())} tetra with an edge below {emin:g} mm (min {mmin_e:.3f} mm)")
    if not ok_dt:
        problems.append(f"min edge ratio {dt_ratio:.3f} < {eratio:g} (time step)")
    status = "PASS" if not problems else "FAIL"
    report = {
        "status": status,
        "inverted": inverted,
        "min_stretch": _r(m.stretch.min()),
        "baseline_min_stretch": _r(b.stretch.min()),
        "min_scaled_jacobian": _r(m.scaled_jacobian.min()),
        "max_aspect": _r(am.max() if am.size else 0.0),
        "baseline_max_aspect": _r(ab.max() if ab.size else 0.0),
        "min_edge_mm": _r(mmin_e),
        "baseline_min_edge_mm": _r(bmin_e),
        "dt_ratio": _r(dt_ratio),
        "failed_elements": int((~(ok_s & ok_e & (m.vol > 0))).sum()),
        "failed_triangles": int((~ok_a).sum()),
        "baseline_status": "PASS" if baseline_ok else "FAIL",
    }
    return QualityResult(status, report, "quality: " + "; ".join(problems) if problems else None, baseline_ok)


def _r(x) -> float:
    v = round(float(x), 6)
    return 0.0 if v == 0 else v
