"""Mesh quality metrics and the section 6.5 (c) judgement (numpy only).

* tetra stretch = 2*sqrt(6) * r_in / L_max (r_in = 3V / sum of face areas; regular tetra = 1),
* boundary-triangle aspect = L_max / (2*sqrt(3) * r_in) (r_in = 2A / perimeter; equilateral = 1),
* minimum edge length, inverted elements (V <= 0), scaled Jacobian (information only),
* time-step estimate: tetra characteristic length h = 3V / max face area (smallest altitude); the
  explicit time step of a part scales with its smallest h (same material before/after morphing).

Minimum-edge and time-step criteria are relative to the undeformed baseline (``min_edge_ratio``,
``dt_ratio_min``); ``min_edge_mm`` is an optional absolute floor (null = off). The baseline itself is
judged only on the absolute shape criteria (inverted, stretch, boundary aspect).
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
    char_len: np.ndarray


def tet_metrics(xyz: np.ndarray, tets: np.ndarray) -> TetMetrics:
    p = [xyz[tets[:, i]] for i in range(4)]
    vol = np.einsum("ij,ij->i", np.cross(p[1] - p[0], p[2] - p[0]), p[3] - p[0]) / 6.0
    fa = [0.5 * np.linalg.norm(np.cross(p[b] - p[a], p[c] - p[a]), axis=1) for a, b, c in _TET_FACES]
    area = sum(fa)
    amax = np.max(fa, axis=0)
    L = np.array([np.linalg.norm(p[a] - p[b], axis=1) for a, b in _TET_EDGES])
    lmax = L.max(axis=0)
    with np.errstate(divide="ignore", invalid="ignore"):
        r_in = np.where(area > 0, 3.0 * vol / area, 0.0)
        stretch = np.where(lmax > 0, SQ24 * r_in / lmax, 0.0)
        char_len = np.where(amax > 0, 3.0 * vol / amax, 0.0)
    corners = ((0, 1, 2, 3), (1, 0, 3, 2), (2, 0, 1, 3), (3, 0, 2, 1))
    sj = np.full(len(tets), np.inf)
    for c, a, b, d in corners:
        e1, e2, e3 = p[a] - p[c], p[b] - p[c], p[d] - p[c]
        den = np.linalg.norm(e1, axis=1) * np.linalg.norm(e2, axis=1) * np.linalg.norm(e3, axis=1)
        with np.errstate(divide="ignore", invalid="ignore"):
            v = np.where(den > 0, np.sqrt(2.0) * np.abs(np.einsum("ij,ij->i", np.cross(e1, e2), e3)) / den, 0.0)
        v = np.where(vol > 0, v, -v)
        sj = np.minimum(sj, v)
    return TetMetrics(vol, stretch, L.min(axis=0), sj, char_len)


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


def _min_ratio(new: np.ndarray, base: np.ndarray, part: np.ndarray | None) -> float:
    """min over parts of (min new / min base); parts may differ in material, so each keeps its own reference.
    Non-finite element values are left out; NaN when no part has finite values on both sides."""
    keys = [None] if part is None else sorted(set(part.tolist()))
    out = np.inf
    for k in keys:
        sel = np.ones(len(new), dtype=bool) if k is None else part == k
        nb, bb = new[sel & np.isfinite(new)], base[sel & np.isfinite(base)]
        if nb.size == 0 or bb.size == 0:
            continue
        b = float(bb.min())
        out = min(out, float(nb.min()) / b if b > 0 else 0.0)
    return float(out) if np.isfinite(out) else float("nan")


def _fmin(a: np.ndarray, default: float = 0.0) -> float:
    f = a[np.isfinite(a)]
    return float(f.min()) if f.size else (default if a.size == 0 else float("nan"))


def _fmax(a: np.ndarray, default: float = 0.0) -> float:
    f = a[np.isfinite(a)]
    return float(f.max()) if f.size else (default if a.size == 0 else float("nan"))


def evaluate(base_xyz: np.ndarray, new_xyz: np.ndarray, tets: np.ndarray, skin: np.ndarray, q: dict, tet_part: np.ndarray | None = None) -> QualityResult:
    """Section 6.5 (c) on all cushion tets (``tets``) and boundary triangles (``skin``), global node rows.

    ``tet_part``: component index per tetra (time-step ratio per part); None = one part.
    Non-finite element values (degenerate elements / triangles) are excluded from the judgement of that
    metric and counted in ``nonfinite_excluded`` (check.json warning QUALITY_METRIC_NONFINITE); a metric
    without any finite value is reported as null. Degenerate tetra still count as inverted (V <= 0).
    """
    b = tet_metrics(base_xyz, tets)
    m = tet_metrics(new_xyz, tets)
    ab = tri_aspect(base_xyz, skin)
    am = tri_aspect(new_xyz, skin)
    smin, amax = float(q["min_stretch"]), float(q["max_aspect"])
    emin = float(q["min_edge_mm"]) if q.get("min_edge_mm") is not None else 0.0
    eratio, dtmin = float(q["min_edge_ratio"]), float(q["dt_ratio_min"])
    rel = bool(q.get("relative_to_baseline", True))
    inverted = int((m.vol <= 0).sum())
    nf_s, nf_a, nf_e = ~np.isfinite(m.stretch), ~np.isfinite(am), ~np.isfinite(m.min_edge)
    ok_s = (m.stretch >= smin) | nf_s
    ok_a = (am <= amax) | nf_a
    ok_e = (m.min_edge >= emin) | nf_e if emin > 0 else np.ones(len(tets), dtype=bool)
    if rel:
        ok_s |= (b.stretch < smin) & (m.stretch >= 0.9 * b.stretch)
        ok_a |= (ab > amax) & (am <= 1.1 * ab)
        if emin > 0:
            ok_e |= (b.min_edge < emin) & (m.min_edge >= 0.9 * b.min_edge)
    bmin_e = _fmin(b.min_edge)
    mmin_e = _fmin(m.min_edge)
    edge_ratio = _min_ratio(m.min_edge, b.min_edge, tet_part)
    dt_ratio = _min_ratio(np.maximum(m.char_len, 0.0), b.char_len, tet_part)
    ok_er = not np.isfinite(edge_ratio) or edge_ratio >= eratio
    ok_dt = not np.isfinite(dt_ratio) or dt_ratio >= dtmin
    fb_s, fb_a = np.isfinite(b.stretch), np.isfinite(ab)
    baseline_ok = bool((b.vol > 0).all() and (b.stretch[fb_s] >= smin).all() and (ab[fb_a] <= amax).all())
    problems = []
    if inverted:
        problems.append(f"{inverted} inverted elements")
    if not ok_s.all():
        problems.append(f"{int((~ok_s).sum())} tetra below min stretch {smin:g} (min {_fmin(m.stretch):.3f})")
    if not ok_a.all():
        problems.append(f"{int((~ok_a).sum())} boundary triangles above max aspect {amax:g} (max {_fmax(am):.2f})")
    if not ok_e.all():
        problems.append(f"{int((~ok_e).sum())} tetra with an edge below {emin:g} mm (min {mmin_e:.3f} mm)")
    if not ok_er:
        problems.append(f"min edge ratio {edge_ratio:.3f} < {eratio:g} (vs baseline)")
    if not ok_dt:
        problems.append(f"time step ratio {dt_ratio:.3f} < {dtmin:g} (vs baseline)")
    status = "PASS" if not problems else "FAIL"
    report = {
        "status": status,
        "inverted": inverted,
        "min_stretch": _r(_fmin(m.stretch)),
        "baseline_min_stretch": _r(_fmin(b.stretch)),
        "min_scaled_jacobian": _r(_fmin(m.scaled_jacobian)),
        "max_aspect": _r(_fmax(am)),
        "baseline_max_aspect": _r(_fmax(ab)),
        "min_edge_mm": _r(mmin_e),
        "baseline_min_edge_mm": _r(bmin_e),
        "edge_ratio": _r(edge_ratio),
        "min_char_len_mm": _r(_fmin(m.char_len)),
        "baseline_min_char_len_mm": _r(_fmin(b.char_len)),
        "dt_ratio": _r(dt_ratio),
        "failed_elements": int((~(ok_s & ok_e & (m.vol > 0))).sum()),
        "failed_triangles": int((~ok_a).sum()),
        "baseline_status": "PASS" if baseline_ok else "FAIL",
    }
    excluded = {
        k: int((~np.isfinite(a)).sum())
        for k, a in (
            ("min_stretch", m.stretch),
            ("baseline_min_stretch", b.stretch),
            ("min_scaled_jacobian", m.scaled_jacobian),
            ("max_aspect", am),
            ("baseline_max_aspect", ab),
            ("min_edge_mm", m.min_edge),
            ("baseline_min_edge_mm", b.min_edge),
            ("min_char_len_mm", m.char_len),
            ("baseline_min_char_len_mm", b.char_len),
        )
    }
    excluded = {k: v for k, v in excluded.items() if v}
    if excluded:
        report["nonfinite_excluded"] = excluded
    return QualityResult(status, report, "quality: " + "; ".join(problems) if problems else None, baseline_ok)


METRIC_KEYS = (
    "min_stretch",
    "baseline_min_stretch",
    "min_scaled_jacobian",
    "max_aspect",
    "baseline_max_aspect",
    "min_edge_mm",
    "baseline_min_edge_mm",
    "edge_ratio",
    "min_char_len_mm",
    "baseline_min_char_len_mm",
    "dt_ratio",
)


def nonfinite_metrics(report: dict) -> list[str]:
    """Metric keys with non-finite element values (excluded from the judgement) or a null value (no finite
    value at all): QUALITY_METRIC_NONFINITE."""
    ex = report.get("nonfinite_excluded") or {}
    return [k for k in METRIC_KEYS if k in report and (report[k] is None or ex.get(k))]


def _r(x) -> float | None:
    """Rounded report value; non-finite (degenerate element) -> None (JSON null)."""
    if not np.isfinite(float(x)):
        return None
    v = round(float(x), 6)
    return 0.0 if v == 0 else v
