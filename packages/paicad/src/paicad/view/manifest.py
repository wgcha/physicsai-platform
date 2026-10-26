"""View manifest content (geometry-view.md sections 4.2-4.4): face table, feature entries, dimension
annotations, displacement statistics. numpy only (neutral kernel types in, plain JSON values out) so
that it is testable with a fake kernel.
"""

from __future__ import annotations

import math

import numpy as np

from ..common import rnd, vec
from ..features import POSITION_TYPES, RIB_PITCH_TYPES, RIB_POS_TYPES, rib_sides
from ..kernel.base import FaceData, Topology

DISP_ZERO_MM = 1.0e-6  # |displacement| at or below this is 0 (GE-C7)
LABEL_OFFSET = 0.05  # label = mid point moved 0.05 * L_body away from the body bbox center
LINEAR_TYPES = ("THICKNESS", "POCKET_DEPTH", "POCKET_WIDTH", "RIB_THICKNESS", "RIB_HEIGHT")
HOSTED_TYPES = ("POCKET_DEPTH", "RIB_HEIGHT")  # moving cap/floor + fixed host face
RADIUS_TYPES = ("HOLE_RADIUS", "FILLET_RADIUS")


def fid(s: str) -> int:
    return int(str(s)[1:])


# ------------------------------------------------------------------ faces
def face_entries(body: str, topo: Topology, face_ids: np.ndarray) -> tuple[list[dict], list[dict]]:
    """``bodies[].faces`` rows (every B-rep face, id order) with the triangle range [first, count] of the
    face in the body mesh (triangles are grouped by ascending face id) + VIEW_FACE_EMPTY warnings."""
    fids = np.asarray(face_ids, dtype=np.int64)
    if len(fids) and np.any(np.diff(fids) < 0):
        raise ValueError("triangles are not grouped by ascending face id")
    nf = len(topo.faces)
    counts = np.bincount(fids, minlength=nf + 1)[: nf + 1] if len(fids) else np.zeros(nf + 1, dtype=np.int64)
    first = np.concatenate([[0], np.cumsum(counts)])
    rows, warnings = [], []
    for f in topo.faces:
        cnt = int(counts[f.id])
        rows.append({"id": f"F{f.id}", "surface": f.surface, "tri": [int(first[f.id]), cnt], "area": rnd(f.area)})
        if cnt == 0:
            warnings.append({"code": "VIEW_FACE_EMPTY", "body": body, "face": f"F{f.id}", "message": "face has no triangle (degenerate face)"})
    return rows, warnings


def vertex_faces(n_vertices: int, triangles: np.ndarray, face_ids: np.ndarray) -> np.ndarray:
    """Face id of every vertex (vertices are never shared between faces)."""
    vf = np.zeros(n_vertices, dtype=np.int64)
    for k in range(3):
        vf[triangles[:, k]] = face_ids
    return vf


# ------------------------------------------------------------------ dimensions
def _unit(v: np.ndarray) -> np.ndarray | None:
    n = float(np.linalg.norm(v))
    return v / n if n > 1e-12 else None


def _axis_point_at(f: FaceData) -> np.ndarray:
    a = np.asarray(f.axis_point, dtype=float)
    d = np.asarray(f.axis_dir, dtype=float)
    return a + float(np.dot(np.asarray(f.centroid, dtype=float) - a, d)) * d


def dimension_points(ftype: str, topo: Topology, bbox: np.ndarray, moving: list[int], fixed: list[int], measure: list[int], axis: str | None) -> tuple[str, np.ndarray, np.ndarray] | None:
    """(kind, p0, p1) of the dimension line, same reference as the feature's ``measure`` method:
    linear = fixed face centroid and its projection on the opposite (moving) face plane (rib height /
    pocket depth: cap/floor centroid and its foot on the host plane), radius = axis
    point at the face centroid height and a point on the face, position = foot on the bbox-minimum
    plane of the measured axis (``hole_center`` measures from the body bbox minimum) and the axis."""
    if ftype in LINEAR_TYPES:
        mv = moving[0] if moving else (measure[0] if measure else None)
        fx = fixed[0] if fixed else (next((m for m in measure if m != mv), None))
        if mv is None or fx is None:
            return None
        fm, ff = topo.face(mv), topo.face(fx)
        if ftype in HOSTED_TYPES and ff.normal is not None:
            # rib cap / pocket floor on a large host face: the host centroid is not at the feature (and is the
            # same for every rib of the host) -> cap/floor centroid and its foot on the host plane
            p1 = np.asarray(fm.centroid, dtype=float)
            n = np.asarray(ff.normal, dtype=float)
            p0 = p1 - float(np.dot(p1 - np.asarray(ff.centroid, dtype=float), n)) * n
            return "linear", p0, p1
        p0 = np.asarray(ff.centroid, dtype=float)
        if fm.normal is not None:
            n = np.asarray(fm.normal, dtype=float)
            p1 = p0 - float(np.dot(p0 - np.asarray(fm.centroid, dtype=float), n)) * n
        else:
            p1 = np.asarray(fm.centroid, dtype=float)
        return "linear", p0, p1
    if ftype in RADIUS_TYPES:
        c = (moving or measure or [None])[0]
        if c is None:
            return None
        f = topo.face(c)
        if f.axis_point is None or f.axis_dir is None or not f.radius:
            return None
        ax = np.asarray(f.axis_dir, dtype=float)
        p0 = _axis_point_at(f)
        r = np.asarray(f.centroid, dtype=float) - p0
        d = _unit(r - float(np.dot(r, ax)) * ax)
        if d is None:  # full cylinder: centroid on the axis -> fixed perpendicular direction
            d = _unit(np.cross(ax, [0.0, 0.0, 1.0] if abs(ax[2]) < 0.9 else [1.0, 0.0, 0.0]))
        return "radius", p0, p0 + float(f.radius) * d
    if ftype in RIB_PITCH_TYPES:
        return pitch_points(axis, [topo.face(g) for g in measure], [topo.face(g) for g in fixed])
    if ftype in RIB_POS_TYPES:
        # rib position: center plane of the -a / +a lateral faces -> bbox-minimum plane (``rib_center`` reference)
        if axis not in ("x", "y", "z"):
            return None
        a = "xyz".index(axis)
        sides = rib_sides(topo, list(measure or moving), a)
        if sides is None:
            return None
        p1 = 0.5 * (np.asarray(topo.face(sides[0]).centroid, dtype=float) + np.asarray(topo.face(sides[1]).centroid, dtype=float))
        p0 = p1.copy()
        p0[a] = float(bbox[a])
        return "position", p0, p1
    if ftype in POSITION_TYPES:
        c = (measure or moving or [None])[0]
        if c is None or axis not in ("x", "y", "z"):
            return None
        f = topo.face(c)
        if f.axis_point is None or f.axis_dir is None:
            return None
        a = "xyz".index(axis)
        p1 = _axis_point_at(f)
        p0 = p1.copy()
        p0[a] = float(bbox[a])
        return "position", p0, p1
    return None


def pitch_points(axis: str | None, lat: list, base: list) -> tuple[str, np.ndarray, np.ndarray] | None:
    """RIB_PITCH (rib-gap.md section 7): p0 on the center plane of rib k (middle of the overlapped rib length, middle of
    the rib height), p1 = p0 moved along a onto the center plane of rib k+1. ``lat`` = the four measure faces (rib k -a,
    +a, rib k+1 -a, +a: objects with ``centroid`` / ``bbox``), ``base`` = [base face] (its normal gives the height axis)."""
    if axis not in ("x", "y", "z") or len(lat) != 4:
        return None
    a = "xyz".index(axis)
    nb = getattr(base[0], "normal", None) if base else None
    if nb is not None:
        k = int(np.argmax(np.abs(np.asarray(nb, dtype=float))))
    else:  # no base face: height axis = the larger lateral extent of the two other axes is the rib length
        ext = np.asarray(lat[0].bbox[3:], dtype=float) - np.asarray(lat[0].bbox[:3], dtype=float)
        o = [x for x in range(3) if x != a]
        k = o[0] if ext[o[0]] <= ext[o[1]] else o[1]
    b = 3 - a - k
    bb = [np.asarray(f.bbox, dtype=float) for f in lat]
    b0 = max(min(bb[0][b], bb[1][b]), min(bb[2][b], bb[3][b]))
    b1 = min(max(bb[0][3 + b], bb[1][3 + b]), max(bb[2][3 + b], bb[3][3 + b]))
    c = [float(np.asarray(f.centroid, dtype=float)[a]) for f in lat]
    p0 = np.zeros(3)
    p0[a] = 0.5 * (c[0] + c[1])
    p0[b] = 0.5 * (b0 + b1)
    p0[k] = 0.5 * (min(bb[0][k], bb[1][k]) + max(bb[0][3 + k], bb[1][3 + k]))
    p1 = p0.copy()
    p1[a] = 0.5 * (c[2] + c[3])
    return "linear", p0, p1


def dimension(ftype: str, topo: Topology, bbox: np.ndarray, moving: list[int], fixed: list[int], measure: list[int], axis: str | None, value: float, tol: float) -> tuple[dict | None, dict | None]:
    """``features[].dimension`` (value = the feature value, float unchanged) + optional VIEW_DIM_APPROX warning."""
    pts = dimension_points(ftype, topo, bbox, moving, fixed, measure, axis)
    if pts is None:
        return None, None
    return dimension_from_points(*pts, bbox, value, tol)


def dimension_from_points(kind: str, p0: np.ndarray, p1: np.ndarray, bbox: np.ndarray, value: float, tol: float) -> tuple[dict, dict | None]:
    """Dimension annotation from its two points: label = mid point moved ``0.05 * L_body`` away from the bbox
    center, ``value`` unchanged (the feature value), ``geom_len`` = |p1 - p0| (VIEW_DIM_APPROX beyond ``tol``)."""
    p0 = np.asarray(p0, dtype=float)
    p1 = np.asarray(p1, dtype=float)
    bb = np.asarray(bbox, dtype=float)
    L = float(np.max(bb[3:] - bb[:3]))
    mid = 0.5 * (p0 + p1)
    d = _unit(mid - 0.5 * (bb[:3] + bb[3:]))
    if d is None:
        d = np.array([0.0, 0.0, 1.0])
    label = mid + LABEL_OFFSET * L * d
    geom_len = float(np.linalg.norm(p1 - p0))
    dim = {"kind": kind, "p0": vec(p0), "p1": vec(p1), "label": vec(label), "value": value, "unit": "mm", "geom_len": rnd(geom_len)}
    warn = None
    if not math.isfinite(geom_len) or abs(geom_len - float(value)) > tol:
        warn = {"code": "VIEW_DIM_APPROX", "message": f"dimension line length {geom_len:.6g} differs from the value {float(value):.6g} (draft or curved faces)"}
    return dim, warn


def feature_entry(f: dict, parameter: str, value: float, moving: list[str], fixed: list[str], topo: Topology | None, bbox: np.ndarray | None, tol: float) -> tuple[dict, list[dict]]:
    """One ``features[]`` row: nominal/range/feasible copied from the features file (same floats)."""
    meas = [str(x) for x in (f.get("measure") or {}).get("faces") or []]
    other = [x for x in meas if x not in moving and x not in fixed]
    feas = dict(f.get("feasible") or {})
    if feas:
        feas.setdefault("source", "estimate")
    row = {
        "name": f["name"],
        "parameter": parameter,
        "type": f["type"],
        "body": f["body"],
        "nominal": f["nominal"],
        "value": value,
        "unit": f.get("unit", "mm"),
        "range": f.get("range"),
        "feasible": feas or None,
        "faces": {"moving": list(moving), "fixed": list(fixed), "other": other},
        "dimension": None,
    }
    if f.get("row") is not None:  # RIB_PITCH (rib-gap.md section 7)
        row["row"] = dict(f["row"])
    warnings = []
    if topo is not None and bbox is not None:
        try:
            dim, w = dimension(f["type"], topo, bbox, [fid(x) for x in moving], [fid(x) for x in fixed], [fid(x) for x in meas], (f.get("measure") or {}).get("axis"), value, tol)
        except (IndexError, ValueError, TypeError):
            dim, w = None, None
        row["dimension"] = dim
        if w:
            warnings.append(dict(w, feature=f["name"]))
    return row, warnings


def parameter_of(doc: dict, split: set[str] | frozenset = frozenset()) -> dict[str, str]:
    """Parameter-table row name of every feature: group representative unless the group is split."""
    grp = {g["id"]: g for g in doc.get("groups") or []}
    out = {}
    for f in doc["features"]:
        g = f.get("group")
        out[f["name"]] = grp[g]["parameter"] if g is not None and g in grp and g not in split else f["name"]
    return out


# ------------------------------------------------------------------ displacement (section 4.4)
def clean_disp(d: np.ndarray) -> np.ndarray:
    d = np.abs(np.asarray(d, dtype=float))
    d[~np.isfinite(d)] = 0.0
    d[d <= DISP_ZERO_MM] = 0.0
    return d


def face_disp_stats(topo: Topology, vface: np.ndarray, disp: np.ndarray, moved: set[int], boundary: set[int]) -> dict[str, dict]:
    """{F<k>: {max, mean, change}}: change = geometry (surface moved: displacement > 0 or an applied
    non-zero move), boundary (only its boundary changed), none."""
    out = {}
    for f in topo.faces:
        d = disp[vface == f.id]
        mx = float(d.max()) if d.size else 0.0
        mean = float(d.mean()) if d.size else 0.0
        if mx > 0 or f.id in moved:
            ch = "geometry"
        elif f.id in boundary:
            ch = "boundary"
        else:
            ch = "none"
        out[f"F{f.id}"] = {"max": rnd(mx), "mean": rnd(mean), "change": ch}
    return out


def boundary_changed(nominal: Topology, sample: Topology, tol: float = 1.0e-7) -> set[int]:
    """Faces whose extent changed (area or bbox) between the nominal and the sample B-rep (same numbering)."""
    out = set()
    for a, b in zip(nominal.faces, sample.faces):
        if abs(a.area - b.area) > tol * max(1.0, a.area) or float(np.abs(np.asarray(a.bbox) - np.asarray(b.bbox)).max()) > tol * (1.0 + float(np.abs(a.bbox).max())):
            out.add(a.id)
    return out
