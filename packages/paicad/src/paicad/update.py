"""``paicad update`` - apply sample values to the nominal B-rep by push/pull (contract sections 4.6, 6.3).

Every sample starts from the nominal geometry. Feature values are turned into face moves:

* pair features (THICKNESS, RIB_THICKNESS, POCKET_WIDTH): the moving face (reference-face rule
  section 6.2, re-evaluated with ``--tag-dir`` contacts) is offset along its normal;
* RIB_HEIGHT / POCKET_DEPTH: cap / floor offset; the whole rib / pocket (cap or floor + adjacent
  side faces) follows its base / entry face rigidly so that the other parameters keep their values;
* HOLE_RADIUS: new cylinder radius; HOLE_POS_U/V: cylinder shifted along the axis of the coordinate;
  RIB_POS_U/V (extract-filter.md section 3.2): rib cap + lateral faces shifted along the axis (added to the
  rib thickness / height moves of the same sample), base face unchanged (its inner wire follows), same
  reference and iteration rules as HOLE_POS with the rib center (mid plane of the -a / +a lateral faces).
  Reference (``position_ref``): ``nearest_fixed`` (default) keeps the distance to the nearest planar
  face normal to that axis that does not move in this sample (tie: larger area, then lower id), the
  value change moving the hole along +axis; ``proportional`` keeps the position as a fraction of the
  body length along the axis. The resulting value measured from the bbox minimum is reported in
  ``update.json`` ``positions[].expected_measured`` (check (a) compares against it);
* FILLET_RADIUS and every plane/plane blend next to a moved face: blend re-fitted tangent to its
  two (moved) planes with the requested radius.

Before the rebuild, the planned moves are checked for feature collisions (``collision.py``: feature
boundaries overlapping on a face, wall penetration, self-intersecting wires) -> GEOM_FEATURE_COLLISION.
The kernel rebuilds the solid with the same topology; failures map to GEOM_CAD_FAILED /
GEOM_TOPOLOGY_CHANGED. All three are category CAD_FAILED, exit 10, without crashing.
"""

from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from . import cadload, options
from .collision import find_collisions
from .common import (
    CODE_CATEGORY,
    EXIT_CAD,
    EXIT_OK,
    OutDir,
    PaicadError,
    Reporter,
    dumps,
    envelope,
    rnd,
    vec,
)
from .features import RIB_POS_TYPES, choose_ref, rib_sides
from .kernel import BodyGeom, CadInputError, FaceMove, move_faces, save_brep
from .kernel.base import FaceData, Topology

UPDATE_JSON = "update.json"
SAMPLE_BREP = "sample.brep"
FACE_MAP_JSON = "face_map.json"

OP = {
    "THICKNESS": "FACE_OFFSET",
    "RIB_THICKNESS": "FACE_OFFSET",
    "POCKET_WIDTH": "FACE_OFFSET",
    "RIB_HEIGHT": "FACE_OFFSET",
    "POCKET_DEPTH": "FACE_OFFSET",
    "HOLE_RADIUS": "CYLINDER_RADIUS",
    "HOLE_POS_U": "AXIS_SHIFT",
    "HOLE_POS_V": "AXIS_SHIFT",
    "FILLET_RADIUS": "REBLEND",
    "RIB_POS_U": "AXIS_SHIFT",
    "RIB_POS_V": "AXIS_SHIFT",
}
SIG_ANGLE_DEG = 1.0
HOLE_POS_ITER = 3


# ------------------------------------------------------------------ inputs
def read_json(path: str | Path, what: str) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
    except (OSError, ValueError) as ex:
        raise PaicadError("GEOM_INPUT_INVALID", f"cannot read {what}: {ex.__class__.__name__}") from None
    if not isinstance(doc, dict):
        raise PaicadError("GEOM_INPUT_INVALID", f"{what} must be a JSON object")
    return doc


def load_features(path: str | Path) -> dict:
    doc = read_json(path, "features file")
    if doc.get("schema_version") != 1 or not isinstance(doc.get("features"), list) or not isinstance(doc.get("bodies"), list):
        raise PaicadError("GEOM_INPUT_INVALID", "features file: unsupported schema or missing features/bodies")
    return doc


def split_groups(doc: dict, opts: dict) -> set[str]:
    ids = {g["id"] for g in doc.get("groups") or []}
    split = set(opts.get("symmetry_split") or [])
    unknown = sorted(split - ids)
    if unknown:
        raise PaicadError("GEOM_INPUT_INVALID", f"symmetry_split: unknown group ids: {', '.join(unknown[:10])}")
    return split


def param_keys(doc: dict, opts: dict) -> list[str]:
    """values.json key set (section 4.4): group representatives + ungrouped features (+ members of split groups)."""
    split = split_groups(doc, opts)
    grp = {g["id"]: g for g in doc.get("groups") or []}
    keys = []
    for f in doc["features"]:
        g = f.get("group")
        if g is None or g in split or grp.get(g, {}).get("parameter") == f["name"]:
            keys.append(f["name"])
    return keys


def feature_values(doc: dict, opts: dict, values: dict[str, float]) -> dict[str, float]:
    """Value of every feature: members of (unsplit) groups follow the representative; missing = nominal."""
    split = split_groups(doc, opts)
    grp = {g["id"]: g for g in doc.get("groups") or []}
    out = {}
    for f in doc["features"]:
        g = f.get("group")
        key = f["name"]
        if g is not None and g not in split:
            key = grp[g]["parameter"]
        out[f["name"]] = float(values.get(key, _nominal(doc, key)))
    return out


def _nominal(doc: dict, name: str) -> float:
    for f in doc["features"]:
        if f["name"] == name:
            return float(f["nominal"])
    raise PaicadError("GEOM_INPUT_INVALID", f"unknown parameter: {name}")


def load_values(path: str | Path, doc: dict, opts: dict) -> dict[str, float]:
    return values_from(read_json(path, "values file"), doc, opts)


def values_from(v: dict, doc: dict, opts: dict) -> dict[str, float]:
    """Validated values of a parsed values document (``load_values``; ``view grid`` cells use the same rules)."""
    if not isinstance(v, dict) or v.get("schema_version", 1) != 1 or not isinstance(v.get("values"), dict):
        raise PaicadError("GEOM_INPUT_INVALID", "values file must be {schema_version: 1, values: {name: number}}")
    keys = param_keys(doc, opts)
    unknown = sorted(set(v["values"]) - set(keys))
    if unknown:
        raise PaicadError("GEOM_INPUT_INVALID", f"unknown parameter names in values: {', '.join(unknown[:10])}")
    out = {}
    for k in keys:
        x = v["values"].get(k, _nominal(doc, k))
        if isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(float(x)):
            raise PaicadError("GEOM_INPUT_INVALID", f"value of {k} must be a finite number")
        out[k] = float(x)
    return out


def contacts_from_tag(tag_dir: str | Path | None, doc: dict) -> dict[str, set[int]] | None:
    """{body name: contact face ids} from tag.json (None when no tag dir)."""
    if not tag_dir:
        return None
    t = read_json(Path(tag_dir) / "tag.json", "tag.json")
    if t.get("status") != "OK":
        raise PaicadError("GEOM_INPUT_INVALID", "tag.json status is not OK")
    body_of_part = {b["part"]: b["body"] for b in doc["bodies"]}
    out: dict[str, set[int]] = {b["body"]: set() for b in doc["bodies"]}
    for c in t.get("contacts") or []:
        b = body_of_part.get(c.get("part"))
        f = str(c.get("face", ""))
        if b is not None and f[:1] == "F" and f[1:].isdigit():
            out.setdefault(b, set()).add(int(f[1:]))
    return out


def nominal_bodies(cad_path: str | Path, doc: dict, body_map: str | None) -> list[BodyGeom]:
    """Nominal bodies in features ``bodies`` order."""
    return nominal_cad(cad_path, doc, body_map)[1]


def nominal_cad(cad_path: str | Path, doc: dict, body_map: str | None) -> tuple[cadload.CadSet, list[BodyGeom]]:
    """(loaded CAD set with file hashes, nominal bodies in features ``bodies`` order)."""
    cad = cadload.load(cad_path)
    return cad, _bodies_of(cad, doc, body_map)


def _bodies_of(cad: cadload.CadSet, doc: dict, body_map: str | None) -> list[BodyGeom]:
    byname = cad.by_name()
    names = [b["body"] for b in doc["bodies"]]
    if all(n in byname for n in names):
        return [byname[n] for n in names]
    pairs = cadload.correspond(cad, None, body_map)
    by_part = {p: b for b, p, _ in pairs}
    out = []
    for b in doc["bodies"]:
        x = byname.get(b["body"]) or by_part.get(b["part"])
        if x is None:
            raise PaicadError("GEOM_BODY_MAP_FAILED", f"body {b['body']} of the features file is not in the CAD")
        out.append(x)
    return out


# ------------------------------------------------------------------ face resolution
def _fid(s: str) -> int:
    return int(str(s)[1:])


def resolve_face(topo: Topology, fid: int, sig: dict | None, tol: float) -> int:
    """Face id in this B-rep: the stored id if its signature matches, else a signature search."""

    def ok(f: FaceData) -> bool:
        if sig is None:
            return True
        if f.surface != sig.get("surface"):
            return False
        c = np.asarray(sig.get("centroid", f.centroid), dtype=float)
        if float(np.linalg.norm(f.centroid - c)) > max(tol, 1e-3 * (1 + float(np.abs(c).max()))):
            return False
        a = float(sig.get("area", f.area))
        if abs(f.area - a) > 0.01 * max(a, f.area) + 1e-9:
            return False
        if sig.get("normal") is not None and f.normal is not None:
            n = np.asarray(sig["normal"], dtype=float)
            if float(np.dot(n, f.normal)) < math.cos(math.radians(SIG_ANGLE_DEG)):
                return False
        return True

    if 1 <= fid <= len(topo.faces) and ok(topo.face(fid)):
        return fid
    hits = [f.id for f in topo.faces if ok(f)]
    if len(hits) == 1:
        return hits[0]
    raise PaicadError("GEOM_INPUT_INVALID", f"face F{fid} of the features file does not match the CAD (re-run extract)")


# ------------------------------------------------------------------ planning
@dataclass
class HolePos:
    name: str
    body: str
    face: int  # cylinder face
    axis: int  # global axis index
    mode: str  # nearest_fixed | proportional
    ref: int | None  # fixed reference face (nearest_fixed)
    offset: float  # nearest_fixed: target axis coordinate - reference plane coordinate
    frac: float  # proportional: target position from the bbox minimum / body length

    sides: tuple[int, int] | None = None  # RIB_POS: (-a, +a) lateral faces; None = hole (cylinder axis point)
    moving: tuple[int, ...] = ()  # RIB_POS: faces shifted together (cap + laterals)

    def target(self, topo: Topology, bbox: np.ndarray) -> float:
        a = self.axis
        if self.mode == "nearest_fixed" and self.ref is not None:
            return float(topo.face(self.ref).centroid[a]) + self.offset
        return float(bbox[a]) + self.frac * float(bbox[3 + a] - bbox[a])

    def current(self, topo: Topology) -> float:
        """Coordinate of the hole axis / rib center plane along the axis."""
        if self.sides is None:
            return float(topo.face(self.face).axis_point[self.axis])
        return 0.5 * (float(topo.face(self.sides[0]).centroid[self.axis]) + float(topo.face(self.sides[1]).centroid[self.axis]))

    def faces_moved(self) -> tuple[int, ...]:
        return self.moving if self.sides is not None else (self.face,)


@dataclass
class BodyPlan:
    moves: dict[int, FaceMove]
    applied: list[dict]
    hole_pos: list[HolePos]
    warnings: list[dict]


def _neighbors(topo: Topology, fid: int) -> list[int]:
    out = []
    for e in topo.face(fid).edges:
        for g in topo.edge(e).faces:
            if g != fid and g not in out:
                out.append(g)
    return out


def _blends(topo: Topology) -> list[tuple[int, int, int]]:
    """(blend face, plane 1, plane 2): cylinders (span < 180 deg) tangent to two planes."""
    out = []
    for f in topo.faces:
        if f.surface != "CYLINDER" or f.span_deg is None or f.span_deg >= 180.0:
            continue
        planes = []
        for e in f.edges:
            ed = topo.edge(e)
            if ed.convexity != "SMOOTH":
                continue
            for g in ed.faces:
                if g != f.id and topo.face(g).surface == "PLANE" and g not in planes:
                    planes.append(g)
        if len(planes) == 2:
            out.append((f.id, planes[0], planes[1]))
    return out


def _bbox_shift(topo: Topology, bbox: np.ndarray, T: dict[int, np.ndarray]) -> tuple[np.ndarray, np.ndarray]:
    """Estimated shift of the body bbox minimum / maximum from the planar face moves (refined after the rebuild)."""
    lo, hi = np.zeros(3), np.zeros(3)
    scale = 1e-6 * (1.0 + float(np.abs(bbox).max()))
    for a in range(3):
        m = [float(T[f.id][a]) for f in topo.faces if f.id in T and f.normal is not None and f.normal[a] < -0.999 and abs(f.bbox[a] - bbox[a]) <= scale]
        if m:
            lo[a] = min(m)
        m = [float(T[f.id][a]) for f in topo.faces if f.id in T and f.normal is not None and f.normal[a] > 0.999 and abs(f.bbox[3 + a] - bbox[3 + a]) <= scale]
        if m:
            hi[a] = max(m)
    return lo, hi


AXIS_COS = 0.999  # planar face counts as normal to an axis (about 2.6 deg: drafted walls included)
TIE_MM = 1.0e-6


def nearest_fixed_face(topo: Topology, axis: int, coord: float, T: dict[int, np.ndarray], exclude: set[int] | frozenset = frozenset()) -> int | None:
    """Nearest planar face normal to ``axis`` that does not move along it in this sample (tie: larger area, lower id).
    ``exclude``: faces that cannot be the reference (the rib's own faces, faces a rib position move will shift)."""
    best = None
    for f in topo.faces:
        if f.surface != "PLANE" or f.normal is None or abs(float(f.normal[axis])) < AXIS_COS:
            continue
        if f.id in exclude:
            continue
        if f.id in T and abs(float(T[f.id][axis])) > 0:
            continue
        key = (round(abs(float(f.centroid[axis]) - coord) / TIE_MM), -float(f.area), f.id)
        if best is None or key < best[0]:
            best = (key, f.id)
    return None if best is None else best[1]


def _rib_moving(f: dict, mf: list[int]) -> list[int]:
    """Resolved moving faces (cap + laterals) of a RIB_POS feature: ``faces.moving`` mapped through the resolved
    ``measure.faces`` (same face ids, possibly re-found by signature)."""
    idmap = {_fid(x): g for x, g in zip(f["measure"]["faces"], mf)}
    return [idmap[_fid(x)] for x in (f.get("faces") or {}).get("moving") or [] if _fid(x) in idmap]


def plan_body(
    body: BodyGeom,
    feats: list[dict],
    fvalues: dict[str, float],
    contacts: set[int] | None,
    opts: dict,
    members_of: dict[str, list[str]],
    keys: set[str],
) -> BodyPlan:
    topo = body.topology()
    s = body.summary()
    tol = options.body_tol(opts, s.bbox)
    center = 0.5 * (s.bbox[:3] + s.bbox[3:])
    mode = opts.get("thickness_ref", "contact_fixed")
    overrides = opts.get("thickness_ref_overrides") or {}
    warnings: list[dict] = []
    T: dict[int, np.ndarray] = {}
    R: dict[int, float] = {}

    def add(fid: int, v: np.ndarray) -> None:
        T[fid] = T.get(fid, np.zeros(3)) + v

    def normal(fid: int) -> np.ndarray:
        n = topo.face(fid).normal
        if n is None:
            raise PaicadError("GEOM_INPUT_INVALID", f"face F{fid} is not planar")
        return np.asarray(n, dtype=float)

    resolved = []
    for f in feats:
        sigs = f.get("face_signatures") or {}
        mf = [resolve_face(topo, _fid(x), sigs.get(x), tol) for x in f["measure"]["faces"]]
        resolved.append((f, mf))
    applied: list[dict] = []
    primaries, groups_feats, others = [], [], []
    for f, mf in resolved:
        (primaries if f["type"] == "THICKNESS" else groups_feats if f["type"] in ("RIB_HEIGHT", "RIB_THICKNESS", "POCKET_DEPTH", "POCKET_WIDTH") else others).append((f, mf))

    def pair_ref(f: dict, mf: list[int]) -> tuple[int, int, str]:
        fa, fb = topo.face(mf[0]), topo.face(mf[1])
        ov = overrides.get(f["name"])
        ov_id = _fid(ov) if isinstance(ov, str) and ov[:1] == "F" and ov[1:].isdigit() else None
        if ov_id is not None and ov_id not in mf:
            raise PaicadError("GEOM_INPUT_INVALID", f"thickness_ref_overrides[{f['name']}] = {ov} is not a face of the feature")
        r = choose_ref(fa, fb, body_center=center, mode=mode, contacts=contacts, override_fixed=ov_id)
        if mode == "contact_fixed" and contacts is None and r["rule"] == "center_distance":
            warnings.append({"code": "REF_NO_CONTACT_INFO", "feature": f["name"], "message": "no tag contact info: face nearer the body center fixed"})
        if r.get("warning") and abs(fvalues[f["name"]] - float(f["nominal"])) > 0:
            warnings.append({"code": r["warning"], "feature": f["name"], "message": "both faces are contact faces: larger area face fixed"})
        return r["moving"], r["fixed"], r["rule"]

    def record(f: dict, moved: list[int], fixed: list[int], rule: str) -> None:
        if f["name"] not in keys:
            return
        applied.append(
            {
                "name": f["name"],
                "body": f["body"],
                "nominal": float(f["nominal"]),
                "value": rnd(fvalues[f["name"]], 9),
                "delta": rnd(fvalues[f["name"]] - float(f["nominal"]), 9),
                "op": OP[f["type"]],
                "moved": [f"F{i}" for i in moved],
                "fixed": [f"F{i}" for i in fixed],
                "ref_rule": rule,
                "members": members_of.get(f["name"], []),
            }
        )

    # 1. primary thickness moves
    for f, mf in primaries:
        d = fvalues[f["name"]] - float(f["nominal"])
        mv, fx, rule = pair_ref(f, mf)
        if d:
            add(mv, d * normal(mv))
        record(f, [mv], [fx], rule)
    # 2. rigid groups (rib = cap + its neighbours, pocket = floor + its neighbours) follow their host face
    hosted: dict[int, int] = {}
    for f, mf in groups_feats:
        if f["type"] in ("RIB_HEIGHT", "POCKET_DEPTH"):
            cap, host = mf[0], mf[1]
            for g in [cap] + [x for x in _neighbors(topo, cap) if x != host]:
                hosted.setdefault(g, host)
    for g, host in sorted(hosted.items()):
        if host in T and g != host:
            add(g, T[host].copy())
    # 3. group features
    for f, mf in groups_feats:
        d = fvalues[f["name"]] - float(f["nominal"])
        t = f["type"]
        if t in ("RIB_THICKNESS", "POCKET_WIDTH"):
            mv, fx, rule = pair_ref(f, mf)
            if d:
                add(mv, (d if t == "RIB_THICKNESS" else -d) * normal(mv))
            record(f, [mv], [fx], rule)
        else:
            cap, host = mf[0], mf[1]
            if d:
                add(cap, (d if t == "RIB_HEIGHT" else -d) * normal(cap))
            record(f, [cap], [host], "feature_default")
    # 4. holes and fillets (hole position reference: nearest fixed face or proportional, see module doc)
    lo_shift, hi_shift = _bbox_shift(topo, s.bbox, T)
    pos_mode = opts.get("position_ref", "nearest_fixed")
    hole_pos: list[HolePos] = []
    # faces a rib position move of this sample shifts along each axis: never a position reference on that axis
    rib_shifted: list[set[int]] = [set(), set(), set()]
    for f, mf in others:
        if f["type"] in RIB_POS_TYPES and fvalues[f["name"]] - float(f["nominal"]) != 0:
            rib_shifted["xyz".index(f["measure"].get("axis", "x"))].update(_rib_moving(f, mf))
    for f, mf in others:
        d = fvalues[f["name"]] - float(f["nominal"])
        t = f["type"]
        c = mf[0]
        if t in RIB_POS_TYPES:
            ax = "xyz".index(f["measure"].get("axis", "x"))
            sides = rib_sides(topo, mf, ax)
            if sides is None:
                raise PaicadError("GEOM_INPUT_INVALID", f"{f['name']}: rib lateral faces along {'xyz'[ax]} not found (re-run extract)")
            moving = tuple(_rib_moving(f, mf))
            c0 = 0.5 * (float(topo.face(sides[0]).centroid[ax]) + float(topo.face(sides[1]).centroid[ax]))
            pre = 0.5 * sum(float(T[g][ax]) for g in sides if g in T)  # center shift by this sample's rib thickness moves
            ref = nearest_fixed_face(topo, ax, c0, T, exclude=set(mf) | rib_shifted[ax]) if pos_mode == "nearest_fixed" else None
            if pos_mode == "nearest_fixed" and ref is None:
                warnings.append({"code": "POS_REF_NO_FIXED_FACE", "feature": f["name"], "message": "no fixed face normal to the axis: position kept proportional to the body length"})
            L0 = float(s.bbox[3 + ax] - s.bbox[ax])
            # the center shift of this sample's rib thickness move is kept (vector sum: the rib moves by delta on top)
            if ref is not None:
                hp = HolePos(f["name"], f["body"], sides[0], ax, "nearest_fixed", ref, c0 + pre - float(topo.face(ref).centroid[ax]) + d, 0.0, sides, moving)
                est = c0 + pre + d
            else:
                hp = HolePos(f["name"], f["body"], sides[0], ax, "proportional", None, 0.0, (c0 + pre - float(s.bbox[ax]) + d) / L0, sides, moving)
                est = float(s.bbox[ax]) + lo_shift[ax] + hp.frac * (L0 + hi_shift[ax] - lo_shift[ax])
            hole_pos.append(hp)
            if abs(est - (c0 + pre)) > 0:
                e = np.zeros(3)
                e[ax] = est - (c0 + pre)
                for g in moving:
                    add(g, e)
            record(f, list(moving), [g for g in mf if g not in moving], "feature_default")
            continue
        if t == "HOLE_RADIUS":
            if d:
                R[c] = fvalues[f["name"]]
        elif t in ("HOLE_POS_U", "HOLE_POS_V"):
            ax = "xyz".index(f["measure"].get("axis", "x"))
            h0 = float(topo.face(c).axis_point[ax])
            ref = nearest_fixed_face(topo, ax, h0, T, exclude=rib_shifted[ax]) if pos_mode == "nearest_fixed" else None
            if pos_mode == "nearest_fixed" and ref is None:
                warnings.append({"code": "POS_REF_NO_FIXED_FACE", "feature": f["name"], "message": "no fixed face normal to the axis: position kept proportional to the body length"})
            L0 = float(s.bbox[3 + ax] - s.bbox[ax])
            if ref is not None:
                hp = HolePos(f["name"], f["body"], c, ax, "nearest_fixed", ref, h0 - float(topo.face(ref).centroid[ax]) + d, 0.0)
                est = h0 + d
            else:
                hp = HolePos(f["name"], f["body"], c, ax, "proportional", None, 0.0, (h0 - float(s.bbox[ax]) + d) / L0)
                est = float(s.bbox[ax]) + lo_shift[ax] + hp.frac * (L0 + hi_shift[ax] - lo_shift[ax])
            hole_pos.append(hp)
            if abs(est - h0) > 0:
                e = np.zeros(3)
                e[ax] = est - h0
                add(c, e)
        elif t == "FILLET_RADIUS":
            if d:
                if topo.face(c).surface != "CYLINDER":
                    raise PaicadError("GEOM_CAD_FAILED", f"{f['name']}: radius change of a {topo.face(c).surface} blend is not supported")
                R[c] = fvalues[f["name"]]
        record(f, [c], [], "feature_default")
    for fid, r in R.items():
        if not (r > 0 and math.isfinite(r)):
            raise PaicadError("GEOM_CAD_FAILED", f"face F{fid}: radius must be > 0 (got {r!r})")
    # 5. blends tangent to two planes follow the planes (and take a new radius)
    for bf, p1, p2 in _blends(topo):
        if bf not in R and p1 not in T and p2 not in T:
            continue
        fd = topo.face(bf)
        r_old = float(fd.radius)
        r_new = R.get(bf, r_old)
        sg = -1.0 if fd.concave else 1.0
        n1, n2 = normal(p1), normal(p2)
        d1 = float(np.dot(T.get(p1, np.zeros(3)), n1))
        d2 = float(np.dot(T.get(p2, np.zeros(3)), n2))
        ax = np.asarray(fd.axis_dir, dtype=float)
        along = float(np.dot(T.get(bf, np.zeros(3)), ax))
        A = np.vstack([n1, n2, ax])
        rhs = np.array([d1 - sg * (r_new - r_old), d2 - sg * (r_new - r_old), along])
        try:
            T[bf] = np.linalg.solve(A, rhs)
        except np.linalg.LinAlgError:
            raise PaicadError("GEOM_CAD_FAILED", f"blend F{bf}: neighbouring planes are parallel") from None
        if bf in R or r_new != r_old:
            R[bf] = r_new
    moves = {}
    for fid in sorted(set(T) | set(R)):
        t = T.get(fid)
        if t is not None and not np.any(t):
            t = None
        mvv = FaceMove(translate=t, radius=R.get(fid))
        if mvv.is_effective():
            moves[fid] = mvv
    return BodyPlan(moves, applied, hole_pos, warnings)


# ------------------------------------------------------------------ core (also used by the sweep)
@dataclass
class UpdateResult:
    bodies: list[BodyGeom]
    applied: list[dict]
    topology: dict
    face_map: dict
    warnings: list[dict]
    positions: list[dict] = field(default_factory=list)


def update_core(nominal: list[BodyGeom], doc: dict, values: dict[str, float], contacts: dict[str, set[int]] | None, opts: dict) -> UpdateResult:
    """Apply ``values`` (values.json keys) to the nominal bodies (features ``bodies`` order). Raises PaicadError."""
    fvalues = feature_values(doc, opts, values)
    keys = set(param_keys(doc, opts))
    split = split_groups(doc, opts)
    members_of = {}
    for g in doc.get("groups") or []:
        if g["id"] not in split:
            members_of[g["parameter"]] = [m for m in g["members"] if m != g["parameter"]]
    out_bodies, applied, warnings, positions = [], [], [], []
    topo_counts, face_map = {}, {}
    for bdoc, body in zip(doc["bodies"], nominal):
        name = bdoc["body"]
        feats = [f for f in doc["features"] if f["body"] == name]
        plan = plan_body(body, feats, fvalues, None if contacts is None else contacts.get(name, set()), opts, members_of, keys)
        applied += plan.applied
        warnings += plan.warnings
        moves = dict(plan.moves)
        _precheck(body, feats, moves, opts)
        new = _move(body, moves)
        for _ in range(HOLE_POS_ITER):
            if not plan.hole_pos:
                break
            bb = new.summary().bbox
            topo = new.topology()
            fix = {}
            for hp in plan.hole_pos:
                got = hp.current(topo)
                target = hp.target(topo, bb)
                if abs(got - target) > 1e-9:
                    for g in hp.faces_moved():
                        fix.setdefault(g, np.zeros(3))[hp.axis] += target - got
            if not fix:
                break
            for c, v in fix.items():
                old = moves.get(c, FaceMove())
                t = (old.translate if old.translate is not None else np.zeros(3)) + v
                moves[c] = FaceMove(translate=t, radius=old.radius)
            new = _move(body, moves)
        if plan.hole_pos:
            bb, topo = new.summary().bbox, new.topology()
            for hp in plan.hole_pos:
                positions.append(
                    {
                        "name": hp.name,
                        "body": hp.body,
                        "axis": "xyz"[hp.axis],
                        "mode": hp.mode,
                        "ref_face": None if hp.ref is None else f"F{hp.ref}",
                        "expected_measured": rnd(hp.target(topo, bb) - float(bb[hp.axis]), 9),
                    }
                )
        tn, ts = body.topology(), new.topology()
        cn = [len(tn.faces), len(tn.edges), len(tn.vertices)]
        cs = [len(ts.faces), len(ts.edges), len(ts.vertices)]
        if cn != cs:
            raise PaicadError("GEOM_TOPOLOGY_CHANGED", f"{name}: topology changed: faces {cn[0]}->{cs[0]}")
        topo_counts[name] = {"nominal": cn, "sample": cs}
        _check_faces(name, tn, ts, moves)
        face_map[name] = {
            "F": {str(i): i for i in range(1, cn[0] + 1)},
            "E": {str(i): i for i in range(1, cn[1] + 1)},
            "V": {str(i): i for i in range(1, cn[2] + 1)},
        }
        uvf = sorted(set(getattr(new, "uv_changed", set()) or []) | _inner_wires_moved(body, new))
        if uvf:
            face_map[name]["uv_fallback"] = uvf  # faces where the normalized (u,v) mapping is not valid (section 6.4 fallback)
        out_bodies.append(new)
    return UpdateResult(out_bodies, applied, {"same_as_nominal": True, "counts": topo_counts}, face_map, warnings, positions)


def _precheck(body: BodyGeom, feats: list[dict], moves: dict[int, FaceMove], opts: dict) -> None:
    """Feature collision pre-check on the planned moves (raises GEOM_FEATURE_COLLISION)."""
    owner: dict[int, list[str]] = {}
    for f in feats:
        for x in list(f["measure"]["faces"]) + list((f.get("faces") or {}).get("moving") or []):
            owner.setdefault(_fid(x), [])
            if f["name"] not in owner[_fid(x)]:
                owner[_fid(x)].append(f["name"])
    hits = find_collisions(body, moves, owner, options.body_tol(opts, body.summary().bbox))
    if hits:
        first = hits[0]
        more = f" (+{len(hits) - 1} more)" if len(hits) > 1 else ""
        who = ", ".join(first.features[:4]) or "-"
        raise PaicadError(
            "GEOM_FEATURE_COLLISION",
            f"{body.name}: feature collision {first.kind}: {first.detail} [{who}]{more}",
            detail={"collisions": [dict(h.as_dict(), body=body.name) for h in hits]},
        )


UV_MOVED_TOL = 1.0e-7


def _inner_wires_moved(nominal: BodyGeom, sample: BodyGeom) -> set[int]:
    """Faces whose inner wires (hole boundaries) moved in normalized (u,v) of the face (section 6.4 fallback rule)."""
    out = set()
    tn = nominal.topology()
    ts = sample.topology()
    tt = np.linspace(0.0, 1.0, 5)
    for fa, fb in zip(tn.faces, ts.faces):
        if not fa.inner_wires:
            continue
        if fa.uv_bounds == fb.uv_bounds and all(np.allclose(tn.vertices[v - 1], ts.vertices[v - 1], atol=0, rtol=0) for w in fa.inner_wires for e in w for v in tn.edge(e).vertices):
            continue
        for e in {e for w in fa.inner_wires for e in w}:
            _, uv_n, _, _ = nominal.project_to_face(fa.id, nominal.eval_edge(e, tt))
            _, uv_s, _, _ = sample.project_to_face(fb.id, sample.eval_edge(e, tt))
            if float(np.abs(uv_n - uv_s).max()) > UV_MOVED_TOL:
                out.add(fa.id)
                break
    return out


def _move(body: BodyGeom, moves: dict[int, FaceMove]) -> BodyGeom:
    try:
        return move_faces(body, moves)
    except CadInputError as e:
        raise PaicadError(e.code, f"{body.name}: {e.message}") from None


def _check_faces(name: str, tn: Topology, ts: Topology, moves: dict[int, FaceMove]) -> None:
    """Section 6.3 step 3: every nominal face has its sample face (same surface kind, normal within 1 deg, centroid moved <= |delta| + tol)."""
    cosmax = math.cos(math.radians(SIG_ANGLE_DEG))
    for fa, fb in zip(tn.faces, ts.faces):
        if fa.surface != fb.surface:
            raise PaicadError("GEOM_TOPOLOGY_CHANGED", f"{name}: face F{fa.id} changed surface type {fa.surface}->{fb.surface}")
        if fa.normal is not None and fb.normal is not None and float(np.dot(fa.normal, fb.normal)) < cosmax:
            raise PaicadError("GEOM_TOPOLOGY_CHANGED", f"{name}: face F{fa.id} flipped or rotated")
        if fb.area <= 1e-9:
            raise PaicadError("GEOM_TOPOLOGY_CHANGED", f"{name}: face F{fa.id} vanished (area {fb.area:.3g})")


# ------------------------------------------------------------------ reports (also written by ``paicad view preview``)
def fail_report(e: PaicadError, values: dict[str, float], t0: float) -> dict:
    """``update.json`` of a CAD failure (exit 10)."""
    return envelope(
        status="FAIL", code=e.code, category=CODE_CATEGORY.get(e.code), message=e.message, values=dict(values), applied=[], topology=None, **(e.detail or {}), elapsed_s=rnd(time.monotonic() - t0, 3)
    )


def ok_report(res: UpdateResult, doc: dict, values: dict[str, float], t0: float) -> dict:
    return envelope(
        status="OK",
        code=None,
        category=None,
        message=None,
        values=dict(values),
        applied=res.applied,
        topology=res.topology,
        bodies=[{"body": b["body"], "volume": rnd(x.summary().volume), "bbox": vec(x.summary().bbox)} for b, x in zip(doc["bodies"], res.bodies)],
        positions=res.positions,
        warnings=res.warnings,
        elapsed_s=rnd(time.monotonic() - t0, 3),
    )


# ------------------------------------------------------------------ CLI
def run(args, rep: Reporter) -> int:
    t0 = time.monotonic()
    opts = options.load(args.options)
    out = OutDir(args.out_dir, [UPDATE_JSON, SAMPLE_BREP, FACE_MAP_JSON])
    out.prepare()
    doc = load_features(args.features)
    values = load_values(args.values, doc, opts)
    contacts = contacts_from_tag(args.tag_dir, doc)
    rep.progress(10, "loading nominal CAD")
    nominal = nominal_bodies(args.cad, doc, args.body_map)
    rep.progress(30, "applying push/pull")
    try:
        res = update_core(nominal, doc, values, contacts, opts)
    except PaicadError as e:
        if e.exit_code != EXIT_CAD:
            raise
        rep.warn(f"{e.code}: {e.message}")
        out.write_text(UPDATE_JSON, dumps(fail_report(e, values, t0)))
        out.commit([UPDATE_JSON])
        rep.result("FAIL", e.code, UPDATE_JSON)
        return EXIT_CAD
    rep.progress(85, "writing sample B-rep")
    try:
        save_brep(res.bodies, out.tmp_path(SAMPLE_BREP))
    except CadInputError as e:
        raise PaicadError(e.code, e.message) from None
    out.write_text(FACE_MAP_JSON, dumps(res.face_map))
    out.write_text(UPDATE_JSON, dumps(ok_report(res, doc, values, t0)))
    out.commit([SAMPLE_BREP, FACE_MAP_JSON, UPDATE_JSON])
    rep.progress(100, "update done")
    rep.result("OK", None, UPDATE_JSON)
    return EXIT_OK
