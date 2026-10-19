"""``paicad map`` - multi-baseline parameter matching draft (contract sections 4.10, 11.4, stage 4B).

Input is the ``parameter_features.json`` of every baseline (no mesh, no assembly folder). Output is
``param_map.json`` with ``status: draft``: each row carries the engine proposal (``proposed``) only;
``decision`` stays null unless inherited from ``--user-map`` (same ``signature``). Nothing is confirmed here.

Matching unit = symmetry group (all members) or ungrouped feature. Score of two features (section 11.4):
hard gates (same type, same component, principal direction angle <= ``axis_deg``), then
``S = (w_pos*S_pos + w_dim*S_dim + w_ori*S_ori + w_nbr*S_nbr) / sum(w)`` with
``S_pos = exp(-(d/sigma)^2)`` (d = distance of the feature centers in coordinates normalized per axis by
the component bounding box), ``S_dim = 1 - min(1, |v1-v2| / max(|v1|,|v2|))``,
``S_ori = (cos(angle) - cos(axis_deg)) / (1 - cos(axis_deg))``, ``S_nbr`` = multiset Jaccard of the 1-hop
adjacent surface kinds (``adjacent_surfaces``; files without it fall back to the feature's own face kinds).
Groups match only groups of the same size: members are paired by an inner assignment, the group score
is the mean member score (any gated member pair gates the group). Rows are built against the first
baseline, then each further baseline is assigned to the existing rows by the Hungarian method
(``scipy.optimize.linear_sum_assignment``). Pairs below ``warn`` are not joined (separate rows, N/A).
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from scipy.optimize import linear_sum_assignment

from . import options
from .bodymap import normalize
from .common import EXIT_OK, OutDir, PaicadError, Reporter, dumps, envelope, rnd
from .update import load_features, read_json

PARAM_MAP_JSON = "param_map.json"
ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
RESERVED = ("baseline",)
GATED = -1.0
N_CANDIDATES = 3
TYPE_KIND = {
    "THICKNESS": "thickness",
    "POCKET_DEPTH": "depth",
    "POCKET_WIDTH": "width",
    "RIB_THICKNESS": "thickness",
    "RIB_HEIGHT": "height",
    "HOLE_RADIUS": "radius",
    "HOLE_POS_U": "position",
    "HOLE_POS_V": "position",
    "FILLET_RADIUS": "radius",
}


@dataclass
class Member:
    name: str
    type: str
    comp: str
    pos: np.ndarray  # center normalized by the component bbox
    dir: np.ndarray | None
    nominal: float
    nbr: Counter
    sig: dict  # canonical signature part


@dataclass
class Unit:
    baseline: str
    name: str  # parameter name (group representative or ungrouped feature)
    type: str
    nominal: float
    members: list[Member]
    order: int


@dataclass
class Row:
    units: dict[str, Unit] = field(default_factory=dict)
    scores: list[float] = field(default_factory=list)  # join scores
    rejected: float | None = None  # best score of a pairing below warn (not joined)
    cands: list[tuple[dict, float]] = field(default_factory=list)

    def ref(self, order: list[str]) -> Unit:
        return next(self.units[b] for b in order if b in self.units)


# ------------------------------------------------------------------ inputs
def load_baselines(path: str | Path) -> list[tuple[str, str | None, dict]]:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as ex:
        raise PaicadError("GEOM_INPUT_INVALID", f"cannot read baselines file: {ex.__class__.__name__}") from None
    if isinstance(data, dict):
        data = data.get("baselines")
    if not isinstance(data, list) or len(data) < 2:
        raise PaicadError("GEOM_INPUT_INVALID", 'baselines file must be a list [{"id", "features"}] of 2 or more baselines')
    out, seen = [], set()
    base = Path(path).parent
    for e in data:
        if not isinstance(e, dict) or not isinstance(e.get("id"), str) or not isinstance(e.get("features"), str):
            raise PaicadError("GEOM_INPUT_INVALID", 'each baseline entry needs string "id" and "features"')
        bid = e["id"]
        if not ID_RE.match(bid) or bid in seen:
            raise PaicadError("GEOM_INPUT_INVALID", f"baseline id must match [A-Za-z0-9_-]{{1,32}} and be unique: {bid!r}")
        seen.add(bid)
        fp = Path(e["features"])
        if not fp.is_absolute():
            fp = base / fp
        rel = e.get("rel")
        out.append((bid, rel if isinstance(rel, str) else None, load_features(fp)))
    return out


def _center(f: dict) -> np.ndarray:
    sig = f.get("face_signatures") or {}
    pts = [np.asarray(s["centroid"], dtype=float) for s in sig.values() if s.get("centroid") is not None]
    return np.mean(pts, axis=0) if pts else np.zeros(3)


def _direction(f: dict) -> np.ndarray | None:
    sig = f.get("face_signatures") or {}
    faces = (f.get("faces") or {}).get("moving", []) + (f.get("faces") or {}).get("fixed", []) + (f.get("measure") or {}).get("faces", []) + sorted(sig)
    for k in faces:
        s = sig.get(k)
        if not s:
            continue
        v = s.get("normal") if s.get("normal") is not None else s.get("axis_dir")
        if v is not None:
            v = np.asarray(v, dtype=float)
            n = float(np.linalg.norm(v))
            if n > 0:
                return v / n
    return None


def _neighbors(f: dict) -> Counter:
    if isinstance(f.get("adjacent_surfaces"), list):
        return Counter(str(x) for x in f["adjacent_surfaces"])
    return Counter(str(s.get("surface")) for s in (f.get("face_signatures") or {}).values())


def _sig_part(f: dict, comp: str) -> dict:
    faces = []
    for s in (f.get("face_signatures") or {}).values():
        faces.append({k: ([round(float(x), 4) for x in v] if isinstance(v, list) else (round(float(v), 4) if isinstance(v, float) else v)) for k, v in sorted(s.items())})
    faces.sort(key=lambda d: json.dumps(d, sort_keys=True))
    return {"type": f["type"], "component": comp, "faces": faces}


def build_units(bid: str, doc: dict) -> list[Unit]:
    comp_of = {b["body"]: normalize(str(b.get("part") or b["body"])) for b in doc["bodies"]}
    bbox_of = {b["body"]: np.asarray(b["bbox"], dtype=float) for b in doc["bodies"]}
    feats = {f["name"]: f for f in doc["features"]}
    order = {f["name"]: i for i, f in enumerate(doc["features"])}

    def member(f: dict) -> Member:
        bb = bbox_of[f["body"]]
        ext = bb[3:] - bb[:3]
        c = _center(f)
        pos = np.where(ext > 1e-9, (c - bb[:3]) / np.where(ext > 1e-9, ext, 1.0), 0.0)
        comp = comp_of[f["body"]]
        return Member(f["name"], f["type"], comp, pos, _direction(f), float(f["nominal"]), _neighbors(f), _sig_part(f, comp))

    units, used = [], set()
    for g in doc.get("groups") or []:
        mem = [feats[m] for m in g["members"] if m in feats]
        if not mem:
            continue
        rep = feats.get(g["parameter"], mem[0])
        units.append(Unit(bid, rep["name"], rep["type"], float(rep["nominal"]), [member(f) for f in sorted(mem, key=lambda x: x["name"])], order[rep["name"]]))
        used.update(m["name"] for m in mem)
    for f in doc["features"]:
        if f["name"] not in used:
            units.append(Unit(bid, f["name"], f["type"], float(f["nominal"]), [member(f)], order[f["name"]]))
    units.sort(key=lambda u: u.order)
    return units


# ------------------------------------------------------------------ scores
def member_score(a: Member, b: Member, mo: dict) -> float:
    """Section 11.4 score in [0, 1], or GATED (-1) when a hard gate fails."""
    if a.type != b.type or a.comp != b.comp:
        return GATED
    axis = float(mo["axis_deg"])
    if (a.dir is None) != (b.dir is None):
        return GATED
    if a.dir is not None:
        cosv = min(1.0, abs(float(np.dot(a.dir, b.dir))))
        if math.degrees(math.acos(cosv)) > axis + 1e-9:
            return GATED
        c0 = math.cos(math.radians(axis))
        s_ori = min(1.0, max(0.0, (cosv - c0) / (1.0 - c0)))
    else:
        s_ori = 1.0
    d = float(np.linalg.norm(a.pos - b.pos))
    s_pos = math.exp(-((d / float(mo["sigma"])) ** 2))
    m = max(abs(a.nominal), abs(b.nominal))
    s_dim = 1.0 - min(1.0, abs(a.nominal - b.nominal) / m) if m > 0 else 1.0
    inter = sum((a.nbr & b.nbr).values())
    union = sum((a.nbr | b.nbr).values())
    s_nbr = inter / union if union else 1.0
    w = mo["weights"]
    tot = sum(float(x) for x in w.values())
    return (w["pos"] * s_pos + w["dim"] * s_dim + w["ori"] * s_ori + w["nbr"] * s_nbr) / tot


def unit_score(a: Unit, b: Unit, mo: dict) -> float:
    if a.type != b.type or len(a.members) != len(b.members):
        return GATED
    n = len(a.members)
    M = np.array([[member_score(x, y, mo) for y in b.members] for x in a.members])
    if n == 1:
        return float(M[0, 0])
    cost = np.where(M < 0, 1e6, 1.0 - M)
    r, c = linear_sum_assignment(cost)
    if np.any(M[r, c] < 0):
        return GATED
    return float(np.mean(M[r, c]))


# ------------------------------------------------------------------ rows
def match(units_by_bl: list[tuple[str, list[Unit]]], mo: dict) -> list[Row]:
    order = [b for b, _ in units_by_bl]
    warn = float(mo["warn"])
    rows = [Row(units={order[0]: u}) for u in units_by_bl[0][1]]
    for bid, units in units_by_bl[1:]:
        if not units:
            continue
        S = np.array([[unit_score(r.ref(order), u, mo) for u in units] for r in rows]) if rows else np.zeros((0, len(units)))
        joined: dict[int, int] = {}
        best_rej: dict[int, float] = {}
        if rows:
            cost = np.where(S < 0, 1e6, 1.0 - S)
            ri, ci = linear_sum_assignment(cost)
            for i, j in zip(ri, ci):
                s = float(S[i, j])
                if s < 0:
                    continue
                if s >= warn:
                    joined[i] = j
                else:  # below the grade bound: proposed as separate variables (N/A in the other baseline)
                    rows[i].rejected = max(rows[i].rejected or 0.0, s)
                    best_rej[j] = max(best_rej.get(j, 0.0), s)
        taken = set(joined.values())
        for i, r in enumerate(rows):
            alts = sorted(((float(S[i, j]), j) for j in range(len(units)) if S[i, j] >= 0 and joined.get(i) != j), key=lambda t: (-t[0], t[1]))
            for s, j in alts[:N_CANDIDATES]:
                r.cands.append(({bid: units[j].name}, s))
            if i in joined:
                r.units[bid] = units[joined[i]]
                r.scores.append(float(S[i, joined[i]]))
        for j, u in enumerate(units):
            if j in taken:
                continue
            nr = Row(units={bid: u}, rejected=best_rej.get(j))
            alts = sorted(((float(S[i, j]), i) for i in range(len(rows)) if S[i, j] >= 0), key=lambda t: (-t[0], t[1]))
            for s, i in alts[:N_CANDIDATES]:
                nr.cands.append(({b: x.name for b, x in rows[i].units.items()}, s))
            rows.append(nr)
    return rows


def signature(row: Row, order: list[str]) -> str:
    parts = [[b, sorted((m.sig for m in row.units[b].members), key=lambda d: json.dumps(d, sort_keys=True))] for b in order if b in row.units]
    return "sha256:" + hashlib.sha256(json.dumps(parts, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _fit_name(name: str) -> str:
    n = re.sub(r"[^A-Za-z0-9_]", "_", name)
    if not n or not (n[0].isalpha() or n[0] == "_"):
        n = "_" + n
    if len(n) > 64:
        h = hashlib.sha1(n.encode()).hexdigest()[:4].upper()
        n = f"{n[:59]}_{h}"
    return n


def grade_of(score: float, complete: bool, mo: dict) -> str:
    if not complete:
        return "unmatched"
    if score >= float(mo["accept"]):
        return "recommend"
    if score >= float(mo["warn"]):
        return "check"
    return "unmatched"


def build_doc(bl: list[tuple[str, str | None, dict]], opts: dict, usage: str, split_param: str | None, user_map: dict | None) -> dict:
    mo = opts["map"]
    order = [b for b, _, _ in bl]
    units_by_bl = [(b, build_units(b, doc)) for b, _, doc in bl]
    rows = match(units_by_bl, mo)
    prev = {}
    if user_map:
        for r in user_map.get("common") or []:
            if isinstance(r, dict) and isinstance(r.get("signature"), str):
                prev.setdefault(r["signature"], r.get("decision"))
    used: set[str] = set(RESERVED)
    common, warnings = [], []
    for k, r in enumerate(rows, 1):
        present = [b for b in order if b in r.units]
        names = [r.units[b].name for b in present]
        name = names[0] if len(set(names)) == 1 else r.units[present[0]].name
        name = _fit_name(name)
        if name in used:
            cand = _fit_name(f"{name}_{present[0]}")
            i = 2
            while cand in used:
                cand = _fit_name(f"{name}_{i}")
                i += 1
            name = cand
        used.add(name)
        complete = len(present) == len(order) or (len(present) >= 2 and bool(r.scores))
        if len(present) >= 2 and r.scores:
            score = min(r.scores)
        else:
            score = r.rejected if r.rejected is not None else 0.0
        grade = grade_of(score, complete and len(present) >= 2, mo)
        ref = r.units[present[0]]
        sig = signature(r, order)
        row = {
            "row_id": f"r{k}",
            "type": TYPE_KIND.get(ref.type, ref.type.lower()),
            "feature_type": ref.type,
            "unit": "mm",
            "signature": sig,
            "needs_review": False,
            "proposed": {
                "name": name,
                "score": rnd(score, 4),
                "grade": grade,
                "map": {b: (r.units[b].name if b in r.units else None) for b in order},
                "nominal": {b: (rnd(r.units[b].nominal, 9) if b in r.units else None) for b in order},
                "group_size": len(ref.members),
                "candidates": [{"map": m, "score": rnd(s, 4)} for m, s in r.cands],
            },
            "decision": None,
        }
        if user_map is not None:
            if sig in prev:
                row["decision"] = prev[sig]
            else:
                row["needs_review"] = True
        if grade == "check":
            warnings.append({"code": "MAP_LOW_SCORE", "row_id": row["row_id"], "message": f"row {row['row_id']} ({name}) score {score:.3f} < {mo['accept']}: needs a check"})
        common.append(row)
    _check_decisions(common)
    range_split = None
    if usage == "range" and split_param:
        row = next((c for c in common if c["proposed"]["name"] == split_param), None)
        if row is None or any(v is None for v in row["proposed"]["map"].values()):
            raise PaicadError("GEOM_INPUT_INVALID", f"--split-param {split_param}: no proposed row of that name present in every baseline")
        iv = sorted(({"baseline": b, "nominal": row["proposed"]["nominal"][b]} for b in order), key=lambda d: (d["nominal"], d["baseline"]))
        range_split = {"param": split_param, "intervals": iv}
    return envelope(
        map_status="OK",
        status="draft",
        confirmed_by=None,
        confirmed_at=None,
        usage=usage,
        baselines=[{"id": b, "rel": rel} for b, rel, _ in bl],
        discrete={"name": "baseline", "values": order} if usage == "topology" else None,
        range_split=range_split,
        common=common,
        map_options={"weights": dict(mo["weights"]), "sigma": mo["sigma"], "accept": mo["accept"], "warn": mo["warn"], "axis_deg": mo["axis_deg"]},
        warnings=warnings,
    )


def _check_decisions(common: list[dict]) -> None:
    """Inherited decisions must keep names unique, valid and not reserved (PARAM_NAME_CONFLICT)."""
    seen: dict[str, str] = {}
    for c in common:
        d = c.get("decision")
        if not isinstance(d, dict) or d.get("name") is None:
            continue
        n = str(d["name"])
        if n in RESERVED or not NAME_RE.match(n):
            raise PaicadError("PARAM_NAME_CONFLICT", f"decision name {n!r} of row {c['row_id']} is reserved or invalid")
        if n in seen and d.get("action") != "split":
            raise PaicadError("PARAM_NAME_CONFLICT", f"decision name {n!r} is used by rows {seen[n]} and {c['row_id']}")
        seen[n] = c["row_id"]


# ------------------------------------------------------------------ CLI
def run(args, rep: Reporter) -> int:
    t0 = time.monotonic()
    opts = options.load(args.options)
    if args.usage == "topology" and args.split_param:
        raise PaicadError("GEOM_INPUT_INVALID", "--split-param is only valid with --usage range (topology and range usage cannot be mixed)")
    out = OutDir(args.out_dir, [PARAM_MAP_JSON])
    out.prepare()
    bl = load_baselines(args.baselines)
    user_map = None
    if args.user_map:
        user_map = read_json(args.user_map, "user map")
        if user_map.get("schema_version") != 1 or not isinstance(user_map.get("common"), list):
            raise PaicadError("GEOM_INPUT_INVALID", "user map: unsupported schema or missing common rows")
        if user_map.get("usage") not in (None, args.usage):
            raise PaicadError("GEOM_INPUT_INVALID", f"user map usage {user_map.get('usage')!r} differs from --usage {args.usage}")
    rep.progress(10, f"matching {len(bl)} baselines")
    doc = build_doc(bl, opts, args.usage, args.split_param, user_map)
    doc["elapsed_s"] = rnd(time.monotonic() - t0, 3)
    out.write_text(PARAM_MAP_JSON, dumps(doc))
    out.commit([PARAM_MAP_JSON])
    g = Counter(c["proposed"]["grade"] for c in doc["common"])
    rep.progress(100, f"map done: {len(doc['common'])} rows (recommend {g['recommend']}, check {g['check']}, unmatched {g['unmatched']})")
    rep.result("OK", None, PARAM_MAP_JSON)
    return EXIT_OK
