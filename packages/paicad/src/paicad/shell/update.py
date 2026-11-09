"""``paicad shell update`` - apply bead values to the nominal sheet (shell-morph sections 4.7, 6.4).

Every sample starts from the nominal CAD; beads are re-recognized and matched to ``shell_features.json``
by their bottom face. Per bead: depth (``bead.depth_mode``) -> width -> position, collision pre-check
(entry loop clearance, cross-section validity), fixed-region pre-check (``--fixed-dir``), then the kernel
rebuilds the sheet with the nominal topology (face map = identity).
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from ..common import CODE_CATEGORY, EXIT_CAD, EXIT_OK, OutDir, PaicadError, Reporter, dumps, rnd
from ..kernel.base import SurfaceEdit
from ..kernel import CadInputError, rebuild_sheet, save_sheet_brep
from . import opts as shopts
from .beads import Bead, Profile, core_coords, island_points, island_rho_max, island_shift, on_faces, recognize, region_distance, section_doc
from .cad import load
from .clearance import Obstacles, loop_clearance, loop_points
from .common import OP, POSITION_TYPES, feature_values, load_shell_features, load_values, param_keys, shell_envelope
from .edit import EPS, EditPlan, _edge_t, plan_bead

UPDATE_JSON = "shell_update.json"
SAMPLE_BREP = "sample.brep"
FACE_MAP_JSON = "face_map.json"


@dataclass
class BeadChange:
    bead: Bead
    feat: dict  # type -> feature dict
    new: Profile
    shift: np.ndarray
    values: dict  # type -> value

    @property
    def changed(self) -> bool:
        return self.new != self.bead.prof or bool(np.any(np.abs(self.shift) > 0))

    @property
    def moves(self) -> bool:
        return bool(np.any(np.abs(self.shift) > 0)) or abs(self.new.rho0 - self.bead.prof.rho0) > 0


@dataclass
class UpdateResult:
    bodies: list
    names: list[str]
    applied: list[dict]
    positions: list[dict]
    expected: dict[str, float]
    changed: dict[str, dict]
    topology: dict
    fixed_precheck: dict
    collisions: list[dict] = field(default_factory=list)
    warnings: list[dict] = field(default_factory=list)
    beads: list[dict] = field(default_factory=list)


def match_beads(doc: dict, cad_bodies: list, o: dict) -> dict[str, tuple[object, Bead]]:
    """{bead id: (body, recognized nominal bead)} - matched by body and bottom face."""
    out = {}
    by_body = {b.name: b for b in cad_bodies}
    rec_of: dict[str, list[Bead]] = {}
    for bj in doc["beads"]:
        body = by_body.get(bj["body"])
        if body is None:
            raise PaicadError("GEOM_INPUT_INVALID", f"features body {bj['body']!r} is not in the CAD")
        if bj["body"] not in rec_of:
            tol = shopts.body_tol(o, body.summary().bbox)
            ck = (tol, tuple(sorted(o["extract"].items())))
            cache = body.__dict__.setdefault("_bead_cache", {})  # nominal bodies are reused by sweep steps
            if ck not in cache:
                cache[ck] = recognize(body, o["extract"], tol, body.name).beads
            rec_of[bj["body"]] = cache[ck]
        bottom = [int(x[1:]) for x in bj["bottom"]]
        hits = [b for b in rec_of[bj["body"]] if b.faces["bottom"] == bottom]
        if not hits and o["extract"].get("islands") and not bj.get("islands"):
            # features prepared without islands (0.14.1 or islands false): beads now absorbed as islands stay usable
            tol = shopts.body_tol(o, body.summary().bbox)
            ck = (tol, tuple(sorted(dict(o["extract"], islands=False).items())))
            cache = body.__dict__.setdefault("_bead_cache", {})
            if ck not in cache:
                cache[ck] = recognize(body, dict(o["extract"], islands=False), tol, body.name).beads
            hits = [b for b in cache[ck] if b.faces["bottom"] == bottom]
        if len(hits) != 1:
            raise PaicadError("GEOM_INPUT_INVALID", f"bead {bj['id']} (bottom F{bottom[0]}) is not recognized in the CAD (features do not match the CAD)")
        b = hits[0]
        b.id, b.k = bj["id"], int(bj["k"])
        if [i.faces for i in b.islands] != [[int(x[1:]) for x in i["faces"]] for i in bj.get("islands") or []]:
            raise PaicadError("GEOM_INPUT_INVALID", f"bead {bj['id']}: bottom islands differ from the features (re-run shell extract with the same extract options)")
        for i, ij in zip(b.islands, bj.get("islands") or []):
            i.id = ij["id"]
        out[bj["id"]] = (body, b)
    return out


def hold_beads(doc: dict, o: dict) -> set[str]:
    """Bead ids of ``bead.hold.beads`` (section 14.5); every one must be ``hold_eligible`` in the features."""
    ids = shopts.hold_ids(o)
    elig = {b["id"] for b in doc["beads"] if b.get("hold_eligible")}
    bad = [x for x in ids if x not in elig]
    if bad:
        raise PaicadError("GEOM_INPUT_INVALID", f"bead.hold.beads: not hold eligible: {', '.join(bad[:10])}")
    return set(ids)


def held_mask(body, b: Bead, X: np.ndarray, tol: float) -> np.ndarray:
    """bool[n]: fixed node on the bottom pieces or the islands of bead ``b`` (hold anchors, section 14.5)."""
    X = np.asarray(X, dtype=float).reshape(-1, 3)
    out = np.zeros(len(X), dtype=bool)
    if not len(X):
        return out
    d0 = region_distance(b, b.prof, np.zeros(3), X, tol)
    near = np.flatnonzero(d0 <= tol)
    if len(near):
        rho, h, _, _ = core_coords(X[near], b.core, b.n, b.p0, b.ed)
        out[near[(rho <= b.prof.rhob + tol) & (np.abs(h - b.prof.depth) <= tol)]] = True
    if b.islands:
        out |= on_faces(body, [f for i in b.islands for f in i.faces], X, tol)
    return out


def bead_changes(doc: dict, o: dict, vals: dict[str, float], beads: dict[str, tuple[object, Bead]]) -> list[BeadChange]:
    fv = feature_values(doc, o, vals)
    mode = o["bead"]["depth_mode"]
    by_bead: dict[str, dict] = {}
    for f in doc["features"]:
        by_bead.setdefault(f["bead"], {})[f["type"]] = f
    out = []
    for bid in [b["id"] for b in doc["beads"]]:
        body, bead = beads[bid]
        feats = by_bead.get(bid, {})
        values = {t: fv[f["name"]] for t, f in feats.items()}
        prof = bead.prof
        if "BEAD_DEPTH" in feats and abs(values["BEAD_DEPTH"] - float(feats["BEAD_DEPTH"]["nominal"])) > 1e-6:
            prof = prof.with_depth(values["BEAD_DEPTH"], mode)
        if "BEAD_WIDTH" in feats:
            dw = values["BEAD_WIDTH"] - float(feats["BEAD_WIDTH"]["nominal"])
            if abs(dw) > 1e-6:
                prof = prof.with_width_delta(dw)
        shift = np.zeros(3)
        for t in POSITION_TYPES:
            if t in feats:
                d = values[t] - float(feats[t]["nominal"])
                if abs(d) > 1e-6:
                    r = feats[t]["ref"]
                    shift = shift + d * float(r.get("sign", 1.0)) * np.asarray(r["axis"], dtype=float)
        out.append(BeadChange(bead, feats, prof, shift, values))
    return out


def _collisions(changes: list[BeadChange], body_of: dict, o: dict, fixed=None, held: set[str] | None = None) -> list[dict]:
    eo = o["extract"]
    land = float(eo["land_min_mm"])
    out = []
    for c in changes:
        if not c.changed:
            continue
        why = c.new.valid(eo["min_flank_deg"])
        if why is not None:
            out.append({"kind": "SECTION_" + why.upper(), "bead": c.bead.id, "features": sorted(f["name"] for f in c.feat.values()), "detail": f"cross-section {why}"})
            continue
    if out:
        return out
    for c in changes:  # SM-C3 island outline + land_min inside the new bottom outline; SM-C7 hold anchors + ring + land_min
        if not c.changed:
            continue
        feats = sorted(f["name"] for f in c.feat.values())
        for isl in c.bead.islands:
            rm = island_rho_max(c.bead, island_points(body_of[c.bead.body], isl))
            c1, c0 = c.new.rhob - rm, c.bead.prof.rhob - rm
            if c1 < min(land, c0) - 1e-9:
                out.append({"kind": "island", "bead": c.bead.id, "other": isl.id, "features": feats, "detail": f"island clearance {c1:.3f} mm < land_min {land} mm"})
                break
        if held and c.bead.id in held and fixed is not None:
            b = c.bead
            body = body_of[b.body]
            tol = shopts.body_tol(o, body.summary().bbox)
            A = fixed.xyz[held_mask(body, b, fixed.xyz, tol)]
            if len(A):
                ring = float(o["bead"]["hold"]["ring_mm"])
                r0, _, _, _ = core_coords(A, b.core, b.n, b.p0, b.ed)
                r1, _, _, _ = core_coords(A, [x + c.shift for x in b.core], b.n, b.p0 + c.shift, b.ed)
                c1, c0 = float((c.new.rhob - ring - r1).min()), float((b.prof.rhob - ring - r0).min())
                if c1 < min(land, c0) - 1e-9:
                    out.append({"kind": "hold", "bead": b.id, "features": feats, "detail": f"hold anchor clearance {c1:.3f} mm < land_min {land} mm"})
    if out:
        return out
    # loop clearances (changed beads against everything, nominal-near pairs only when they get closer)
    by_body: dict[str, list[BeadChange]] = {}
    for c in changes:
        by_body.setdefault(c.bead.body, []).append(c)
    for name, cs in by_body.items():
        body = body_of[name]
        topo = body.topology()
        obst = Obstacles.build(body, topo, [c.bead for c in cs])
        z = np.zeros(3)
        for c in cs:
            if not c.moves:
                continue
            for label, ob_bead, items in _items(obst, c, cs):
                for pts_now, pts_nom in items:
                    c1 = loop_clearance(c.bead, c.new, c.shift, pts_now)
                    c0 = loop_clearance(c.bead, c.bead.prof, z, pts_nom)
                    if c1 < min(land, c0) - 1e-9:
                        out.append({"kind": "BOUNDARY_OVERLAP", "bead": c.bead.id, "other": label, "features": sorted(f["name"] for f in c.feat.values()),
                                    "detail": f"entry loop clearance {c1:.3f} mm < land_min {land} mm"})
                        break
    return out


def _items(obst: Obstacles, c: BeadChange, cs: list[BeadChange]):
    for label, pts in obst.static.get(c.bead.base_face, []):
        yield label, None, [(pts, pts)]
    for o_ in cs:
        if o_ is c or o_.bead.base_face != c.bead.base_face:
            continue
        now = loop_points(o_.bead, o_.new.rho0, o_.shift)
        nom = loop_points(o_.bead, o_.bead.prof.rho0, np.zeros(3))
        yield o_.bead.id, o_.bead, [(now, nom)]


def fixed_precheck(changes: list[BeadChange], plan_geometry: dict[str, set[int]], fixed, o: dict, tol_of: dict[str, float], body_of: dict | None = None,
                   held: set[str] | None = None) -> tuple[dict, str | None]:
    """Section 6.4-3 (+ SM-C3 island faces, SM-C7 held anchors, SM-C6 ``fixed.policy``). Returns (report, failure message)."""
    if fixed is None:
        return {"status": "NOT_EVALUATED", "violations": 0}, None
    viol = []
    nheld = 0
    for c in changes:
        if not c.changed:
            continue
        b = c.bead
        tol = tol_of[b.body]
        X = fixed.xyz
        d0 = region_distance(b, b.prof, np.zeros(3), X, tol)
        near = np.flatnonzero(d0 <= tol)
        bad = set()
        geo = plan_geometry.get(b.body, set())
        if len(near):
            rho, h, _, _ = core_coords(X[near], b.core, b.n, b.p0, b.ed)
            role_faces = {k: b.faces[r] for k, r in enumerate(("fillets_top", "flanks", "fillets_bottom", "bottom"))}
            for i, r_, h_ in zip(near, rho, h):
                if r_ >= b.prof.rho0 - tol and abs(h_) <= tol:
                    continue  # on the entry loop: base face side, judged by (b)
                k = b.prof.locate(float(r_), float(h_))[0]
                if any(f in geo for f in role_faces[k]):
                    bad.add(int(i))
        if b.islands and body_of is not None:
            isl_faces = [f for i in b.islands for f in i.faces if f in geo]
            if isl_faces:
                bad |= set(int(i) for i in np.flatnonzero(on_faces(body_of[b.body], isl_faces, X, tol)))
        if c.moves:
            d1 = region_distance(b, c.new, c.shift, X, tol)
            bad |= set(int(i) for i in np.flatnonzero(d1 <= tol))
        if held and b.id in held and body_of is not None:
            hm = held_mask(body_of[b.body], b, X, tol)
            nh = len(bad & set(int(i) for i in np.flatnonzero(hm)))
            nheld += nh
            bad -= set(int(i) for i in np.flatnonzero(hm))
        if bad:
            idx = np.array(sorted(bad))
            clusters = sorted(set(int(x) for x in fixed.cluster[idx]))
            names = sorted(f["name"] for t, f in c.feat.items() if abs(c.values[t] - float(f["nominal"])) > 1e-6)
            viol.append((b.id, names, clusters, len(idx)))
    extra = {"held": nheld} if held else {}
    if not viol:
        return {"status": "PASS", "violations": 0, **extra}, None
    n = sum(v[3] for v in viol)
    msg = "; ".join(f"{', '.join(v[1]) or v[0]} moves {v[3]} fixed nodes of cluster {','.join(map(str, v[2]))}" for v in viol[:5])
    warn = o["fixed"]["policy"] == "warn"
    rep = {"status": "WARN" if warn else "FAIL", "violations": n, **extra, "items": [{"bead": v[0], "features": v[1], "clusters": v[2], "nodes": v[3]} for v in viol]}
    return rep, None if warn else "fixed region violation: " + msg


def plan_islands(body, b: Bead, new: Profile, shift: np.ndarray, plan: EditPlan) -> None:
    """SM-C3: island faces, edges and vertices follow the bottom plane rigidly (overrides the bead point map)."""
    if not b.islands:
        return
    topo = body.topology()
    t = island_shift(b, new, shift)
    moving = bool(np.any(np.abs(t) > EPS))
    for isl in b.islands:
        for e in isl.edges:
            if moving:
                plan.edge_points[e] = body.eval_edge(e, _edge_t(topo, e)) + t
            else:
                plan.edge_points.pop(e, None)
        for v in isl.vertices:
            if moving:
                plan.vertex_pos[v] = topo.vertices[v - 1] + t
            else:
                plan.vertex_pos.pop(v, None)
        for f in isl.faces:
            if moving:
                plan.face_edits[f] = SurfaceEdit(translate=t)
                plan.geometry.add(f)
            else:
                plan.face_edits.pop(f, None)
                plan.geometry.discard(f)


def update_core(cad_bodies: list, doc: dict, vals: dict[str, float], o: dict, fixed=None) -> UpdateResult:
    held = hold_beads(doc, o)
    beads = match_beads(doc, cad_bodies, o)
    changes = bead_changes(doc, o, vals, beads)
    body_of = {b.name: b for b in cad_bodies}
    names = [b.name for b in cad_bodies]
    cols = _collisions(changes, body_of, o, fixed, held)
    if cols:
        raise PaicadError("GEOM_FEATURE_COLLISION", "bead collision: " + "; ".join(f"{c['bead']} {c['kind']} {c.get('other', '')}".strip() for c in cols[:5]), EXIT_CAD, {"collisions": cols})
    plans: dict[str, EditPlan] = {n: EditPlan() for n in names}
    for c in changes:
        if c.changed:
            try:
                plan_bead(body_of[c.bead.body], c.bead, c.new, c.shift, plans[c.bead.body])
                plan_islands(body_of[c.bead.body], c.bead, c.new, c.shift, plans[c.bead.body])
            except ValueError as ex:
                raise PaicadError("GEOM_CAD_FAILED", f"{c.bead.id}: {ex}", EXIT_CAD) from None
    tol_of = {n: shopts.body_tol(o, body_of[n].summary().bbox) for n in names}
    pre, msg = fixed_precheck(changes, {n: plans[n].geometry for n in names}, fixed, o, tol_of, body_of, held)
    if msg:
        raise PaicadError("SHELL_FIXED_REGION_VIOLATION", msg, EXIT_CAD, {"fixed_precheck": pre})
    out_bodies = []
    changed = {}
    counts = {}
    for b in cad_bodies:
        p = plans[b.name]
        nb = b
        if p.face_edits or p.edge_points or p.vertex_pos:
            try:
                nb = rebuild_sheet(b, p.face_edits, p.edge_points, p.vertex_pos)
            except CadInputError as e:
                raise PaicadError(e.code, e.message, EXIT_CAD) from None
        out_bodies.append(nb)
        s0, s1 = b.summary(), nb.summary()
        counts[b.name] = {"nominal": [s0.n_faces, s0.n_edges, s0.n_vertices], "sample": [s1.n_faces, s1.n_edges, s1.n_vertices]}
        changed[b.name] = {
            "geometry": [f"F{x}" for x in sorted(p.geometry)],
            "boundary_only": [f"F{x}" for x in sorted(p.boundary_only - p.geometry)],
            "edges": [f"E{x}" for x in sorted(p.edge_points)],
            "vertices": [f"V{x}" for x in sorted(p.vertex_pos)],
        }
    applied, positions, expected = [], [], {}
    grp = {g["id"]: g for g in doc.get("groups") or []}
    for c in changes:
        for t, f in sorted(c.feat.items(), key=lambda kv: kv[1]["name"]):
            nom = float(f["nominal"])
            v = c.values[t]
            if t in POSITION_TYPES:
                exp = v
                r = f["ref"]
                positions.append({"name": f["name"], "body": c.bead.body, "axis": t[-1], "mode": r["rule"], "ref_edge": r.get("edge"), "expected_measured": rnd(exp, 9)})
            elif t == "BEAD_DEPTH":
                exp = c.new.depth
            else:
                exp = c.new.width()
            if c.changed:
                expected[f["name"]] = rnd(exp, 9)
            if abs(v - nom) > 1e-6:
                g = f.get("group")
                members = [m for m in grp[g]["members"] if m != f["name"]] if g in grp else []
                a = {"name": f["name"], "bead": c.bead.id, "nominal": nom, "value": v, "delta": rnd(v - nom, 9), "op": OP[t], "expected": rnd(exp, 9), "members": members}
                if t == "BEAD_DEPTH":
                    a["mode"] = o["bead"]["depth_mode"]
                applied.append(a)
    same = all(c["nominal"] == c["sample"] for c in counts.values())
    if not same:
        raise PaicadError("GEOM_TOPOLOGY_CHANGED", "sample topology differs from the nominal", EXIT_CAD)
    sections = [section_doc(c.bead, c.new, c.shift) for c in changes if c.changed]
    for sec in sections:  # SM-C7: held beads carry their bottom / islands for the morph anchors
        if sec["id"] in held:
            c = next(x for x in changes if x.bead.id == sec["id"])
            sec["hold"] = True
            sec["bottom"] = [f"F{f}" for f in c.bead.faces["bottom"]]
            sec.setdefault("islands", [{"id": i.id, "faces": [f"F{f}" for f in i.faces], "edges": [f"E{e}" for e in i.edges], "vertices": [f"V{v}" for v in i.vertices]}
                                       for i in c.bead.islands])
    return UpdateResult(out_bodies, names, applied, positions, expected, changed, {"same_as_nominal": True, "counts": counts}, pre, beads=sections)


def face_map(bodies: list) -> dict:
    out = {}
    for b in bodies:
        s = b.summary()
        out[b.name] = {k: {str(i): i for i in range(1, n + 1)} for k, n in (("F", s.n_faces), ("E", s.n_edges), ("V", s.n_vertices))}
    return out


def fail_report(e: PaicadError, vals: dict, with_fixed: bool, t0: float) -> dict:
    """``shell_update.json`` of a failed update (also written by ``shell view preview``)."""
    body = dict(status="FAIL", code=e.code, category=CODE_CATEGORY.get(e.code), message=e.message, values=vals)
    body.update(e.detail or {})
    if "fixed_precheck" not in body:
        body["fixed_precheck"] = {"status": "PASS" if with_fixed else "NOT_EVALUATED", "violations": 0}
    body["elapsed_s"] = rnd(time.monotonic() - t0, 3)
    return shell_envelope(**body)


def ok_report(res: UpdateResult, vals: dict, o: dict, t0: float) -> dict:
    """``shell_update.json`` of a successful update (also written by ``shell view preview``)."""
    return shell_envelope(
        status="OK", code=None, category=None, message=None, values=vals, applied=res.applied, positions=res.positions,
        expected_measured=res.expected, changed=res.changed, beads=res.beads, fixed_precheck=res.fixed_precheck, collisions=res.collisions,
        topology=res.topology, options={k: shopts.used(o)[k] for k in ("bead", "extract")}, warnings=res.warnings, elapsed_s=rnd(time.monotonic() - t0, 3),
    )


def run(args, rep: Reporter) -> int:
    t0 = time.monotonic()
    o = shopts.load(args.options)
    out = OutDir(args.out_dir, [UPDATE_JSON, SAMPLE_BREP, FACE_MAP_JSON])
    out.prepare()
    doc = load_shell_features(args.features)
    vals = load_values(args.values, doc, o)
    fixed = None
    if args.fixed_dir:
        from .fixed import load_fixed

        fixed = load_fixed(args.fixed_dir)
    rep.progress(10, "loading mid-surface CAD")
    cad = load(args.cad)
    rep.progress(30, "applying bead values")
    try:
        res = update_core(cad.bodies, doc, vals, o, fixed)
    except PaicadError as e:
        if e.exit_code != EXIT_CAD:
            raise
        out.write_text(UPDATE_JSON, dumps(fail_report(e, vals, fixed is not None, t0)))
        out.commit([UPDATE_JSON])
        rep.warn(f"{e.code}: {e.message}")
        rep.result("FAIL", e.code, UPDATE_JSON)
        return EXIT_CAD
    rep.progress(80, "writing sample B-rep")
    try:
        save_sheet_brep(res.bodies, out.tmp_path(SAMPLE_BREP))
    except CadInputError as e:
        raise PaicadError(e.code, e.message) from None
    out.write_text(FACE_MAP_JSON, dumps(face_map(res.bodies)))
    out.write_text(UPDATE_JSON, dumps(ok_report(res, vals, o, t0)))
    out.commit([SAMPLE_BREP, FACE_MAP_JSON, UPDATE_JSON])
    rep.progress(100, f"update done: {len(res.applied)} parameters changed")
    rep.result("OK", None, UPDATE_JSON)
    return EXIT_OK
