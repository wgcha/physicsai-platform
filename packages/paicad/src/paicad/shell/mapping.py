"""``paicad map`` for shell features: bead-level matching (shell-morph section 7.2).

Matching unit = bead. Hard gates: same component (part title), same ``shape`` and ``sense``, base normal
angle <= ``map.axis_deg``, linear beads: axis angle <= 10 deg (direction-free). Score
``S = (w_pos S_pos + w_dim S_dim + w_ori S_ori + w_nbr S_nbr) / sum(w)`` (GE section 11.4 weights / sigma /
grades): S_pos = exp(-(d/sigma)^2) of the bead centers normalized by the component bbox, S_dim = mean of the
GE dimension score over depth / width / length, S_ori = cos score of the axis (circular: base normal),
S_nbr = multiset Jaccard of the bead neighbours (beads, holes, fixed clusters within 2 x width).
Rows are built against the first baseline, further baselines are assigned by the Hungarian method; the
D/U/V/W rows of one bead share ``group = "bead:<n>"``. Beads without partner give rows that are N/A in
the other baselines.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import linear_sum_assignment

from ..bodymap import normalize
from ..common import rnd
from .common import TYPE_ORDER

GATED = -1.0
LINEAR_AXIS_DEG = 10.0
TYPE_KIND = {"BEAD_DEPTH": "depth", "BEAD_POS_U": "position", "BEAD_POS_V": "position", "BEAD_WIDTH": "width"}


@dataclass
class BeadUnit:
    baseline: str
    id: str
    comp: str
    shape: str
    sense: str
    pos: np.ndarray
    axis: np.ndarray
    normal: np.ndarray
    dims: tuple[float, float, float]
    nbr: Counter
    feats: dict[str, dict]  # type -> feature
    order: int
    sig: dict


@dataclass
class BeadRow:
    units: dict[str, BeadUnit] = field(default_factory=dict)
    scores: list[float] = field(default_factory=list)
    rejected: float | None = None
    cands: list[tuple[dict, float]] = field(default_factory=list)


def is_shell(doc: dict) -> bool:
    return doc.get("kind") == "shell"


def units_of(bid: str, doc: dict) -> list[BeadUnit]:
    part = {p["body"]: p for p in doc["parts"]}
    feats: dict[str, dict] = {}
    for f in doc["features"]:
        feats.setdefault(f["bead"], {})[f["type"]] = f
    out = []
    for k, b in enumerate(doc["beads"]):
        p = part[b["body"]]
        bb = np.asarray(p["bbox"], dtype=float)
        ext = bb[3:] - bb[:3]
        c = np.asarray(b["center"], dtype=float)
        pos = np.where(ext > 1e-9, (c - bb[:3]) / np.where(ext > 1e-9, ext, 1.0), 0.0)
        nom = b["nominal"]
        comp = normalize(str(p.get("title") or p["body"]))
        sig = {"component": comp, "shape": b["shape"], "sense": b["sense"], "center": [round(float(x), 4) for x in b["center"]],
               "depth": round(float(nom["depth"]), 4), "width": round(float(nom["width"]), 4), "length": round(float(nom["length"]), 4)}
        out.append(BeadUnit(bid, b["id"], comp, b["shape"], b["sense"], pos, np.asarray(b["axis"], dtype=float), np.asarray(b["normal"], dtype=float),
                            (float(nom["depth"]), float(nom["width"]), float(nom["length"])), Counter(b.get("neighbors") or []), feats.get(b["id"], {}), k, sig))
    return out


def bead_score(a: BeadUnit, b: BeadUnit, mo: dict) -> float:
    if a.comp != b.comp or a.shape != b.shape or a.sense != b.sense:
        return GATED
    cn = min(1.0, abs(float(np.dot(a.normal, b.normal))))
    if math.degrees(math.acos(cn)) > float(mo["axis_deg"]) + 1e-9:
        return GATED
    ca = min(1.0, abs(float(np.dot(a.axis, b.axis))))
    if a.shape == "linear" and math.degrees(math.acos(ca)) > LINEAR_AXIS_DEG + 1e-9:
        return GATED
    c0 = math.cos(math.radians(float(mo["axis_deg"])))
    cosv = ca if a.shape == "linear" else cn
    s_ori = min(1.0, max(0.0, (cosv - c0) / (1.0 - c0)))
    d = float(np.linalg.norm(a.pos - b.pos))
    s_pos = math.exp(-((d / float(mo["sigma"])) ** 2))
    sd = []
    for x, y in zip(a.dims, b.dims):
        m = max(abs(x), abs(y))
        sd.append(1.0 - min(1.0, abs(x - y) / m) if m > 0 else 1.0)
    s_dim = float(np.mean(sd))
    inter = sum((a.nbr & b.nbr).values())
    union = sum((a.nbr | b.nbr).values())
    s_nbr = inter / union if union else 1.0
    w = mo["weights"]
    tot = sum(float(x) for x in w.values())
    return (w["pos"] * s_pos + w["dim"] * s_dim + w["ori"] * s_ori + w["nbr"] * s_nbr) / tot


def match(units_by_bl: list[tuple[str, list[BeadUnit]]], mo: dict) -> list[BeadRow]:
    order = [b for b, _ in units_by_bl]
    warn = float(mo["warn"])
    rows = [BeadRow(units={order[0]: u}) for u in units_by_bl[0][1]]

    def ref(r: BeadRow) -> BeadUnit:
        return next(r.units[b] for b in order if b in r.units)

    for bid, units in units_by_bl[1:]:
        if not units:
            continue
        S = np.array([[bead_score(ref(r), u, mo) for u in units] for r in rows]) if rows else np.zeros((0, len(units)))
        joined: dict[int, int] = {}
        rej: dict[int, float] = {}
        if rows:
            ri, ci = linear_sum_assignment(np.where(S < 0, 1e6, 1.0 - S))
            for i, j in zip(ri, ci):
                s = float(S[i, j])
                if s < 0:
                    continue
                if s >= warn:
                    joined[i] = j
                else:
                    rows[i].rejected = max(rows[i].rejected or 0.0, s)
                    rej[j] = max(rej.get(j, 0.0), s)
        for i, r in enumerate(rows):
            alts = sorted(((float(S[i, j]), j) for j in range(len(units)) if S[i, j] >= 0 and joined.get(i) != j), key=lambda t: (-t[0], t[1]))
            r.cands += [({bid: units[j].id}, s) for s, j in alts[:3]]
            if i in joined:
                r.units[bid] = units[joined[i]]
                r.scores.append(float(S[i, joined[i]]))
        taken = set(joined.values())
        for j, u in enumerate(units):
            if j not in taken:
                nr = BeadRow(units={bid: u}, rejected=rej.get(j))
                alts = sorted(((float(S[i, j]), i) for i in range(len(rows)) if S[i, j] >= 0), key=lambda t: (-t[0], t[1]))
                nr.cands += [({b: x.id for b, x in rows[i].units.items()}, s) for s, i in alts[:3]]
                rows.append(nr)
    return rows


def build_rows(bl: list[tuple[str, str | None, dict]], mo: dict, user_map: dict | None, fit_name, grade_of) -> tuple[list[dict], list[dict]]:
    order = [b for b, _, _ in bl]
    rows = match([(b, units_of(b, doc)) for b, _, doc in bl], mo)
    prev = {}
    if user_map:
        for r in user_map.get("common") or []:
            if isinstance(r, dict) and isinstance(r.get("signature"), str):
                prev.setdefault(r["signature"], r.get("decision"))
    used: set[str] = {"baseline"}
    common, warnings = [], []
    n = 0
    for gi, r in enumerate(rows, 1):
        present = [b for b in order if b in r.units]
        complete = len(present) >= 2 and bool(r.scores)
        score = min(r.scores) if complete else (r.rejected or 0.0)
        grade = grade_of(score, complete, mo)
        ref = r.units[present[0]]
        types = [t for t in TYPE_ORDER if any(t in r.units[b].feats for b in present)]
        for t in types:
            n += 1
            names = {b: (r.units[b].feats[t]["name"] if b in r.units and t in r.units[b].feats else None) for b in order}
            nominal = {b: (rnd(float(r.units[b].feats[t]["nominal"]), 9) if names[b] else None) for b in order}
            first = next(names[b] for b in present if names[b])
            name = fit_name(first)
            if name in used:
                k = 2
                while fit_name(f"{name}_{k}") in used:
                    k += 1
                name = fit_name(f"{name}_{k}")
            used.add(name)
            sig_parts = [[b, t, r.units[b].sig] for b in order if b in r.units]
            sig = "sha256:" + hashlib.sha256(json.dumps(sig_parts, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
            row = {
                "row_id": f"r{n}", "type": TYPE_KIND[t], "feature_type": t, "unit": "mm", "signature": sig, "needs_review": False, "group": f"bead:{gi}",
                "proposed": {"name": name, "score": rnd(score, 4), "grade": grade, "map": names, "nominal": nominal, "group_size": 1,
                             "beads": {b: (r.units[b].id if b in r.units else None) for b in order},
                             "candidates": [{"map": m, "score": rnd(s, 4)} for m, s in r.cands]},
                "decision": None,
            }
            if user_map is not None:
                if sig in prev:
                    row["decision"] = prev[sig]
                else:
                    row["needs_review"] = True
            if grade == "check" and t == types[0]:
                warnings.append({"code": "MAP_LOW_SCORE", "row_id": row["row_id"], "group": row["group"], "message": f"bead {ref.id} score {score:.3f} < {mo['accept']}: needs a check"})
            common.append(row)
    return common, warnings
