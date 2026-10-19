"""``paicad shell extract`` - bead parameters of the mid-surface STEP (shell-morph sections 4.4, 6.3).

Outputs ``parameter_extracted.xml`` (GE section 4.3 format, TX_PARSE compatible), ``shell_features.json``
and ``features/<NAME>.png``. Order: component (part title) -> feature type (D, U, V, W) -> bead number;
names ``<COMP>_BEAD_<D|U|V|W>_<k>`` with ``k`` = bead number (same k for the four parameters of a bead).
With ``--assem-dir`` the fixed set (fixed-scan module) gives the fixed-region overlap of every bead.
"""

from __future__ import annotations

import math
import time
from pathlib import Path

import numpy as np

from ..common import EXIT_EXTRACT_EMPTY, EXIT_OK, OutDir, PaicadError, Reporter, dumps, rnd, vec
from ..extract import render_xml
from ..features import component_name, make_name
from . import opts as shopts
from .assem import read_assembly
from .beads import Bead, bead_axes, core_coords, nearest_fixed_edge, recognize, region_distance
from .cad import correspond, load
from .clearance import Obstacles, fixed_clearance, loop_clearance, sample_edges, search_limit
from .common import POSITION_TYPES, TYPE_ABBR, TYPE_ORDER, shell_envelope
from .fixed import compute_fixed

XML_NAME = "parameter_extracted.xml"
JSON_NAME = "shell_features.json"
PNG_DIR = "features"
MEASURE = {"BEAD_DEPTH": "bead_depth", "BEAD_POS_U": "bead_center", "BEAD_POS_V": "bead_center", "BEAD_WIDTH": "bead_width"}


def _fids(xs) -> list[str]:
    return [f"F{x}" for x in xs]


def _range(nom: float, ratio: float, feas: dict) -> dict:
    lo, hi = max(nom * (1 - ratio), feas["min"]), min(nom * (1 + ratio), feas["max"])
    if hi < lo:
        lo = hi = min(max(nom, feas["min"]), feas["max"])
    return {"min": rnd(lo), "max": rnd(hi), "ratio": ratio}


def _range_mm(nom: float, mm: float, feas: dict) -> dict:
    lo, hi = max(nom - mm, feas["min"]), min(nom + mm, feas["max"])
    if hi < lo:
        lo = hi = min(max(nom, feas["min"]), feas["max"])
    return {"min": rnd(lo), "max": rnd(hi), "abs_mm": mm}


class _Ctx:
    """Per-body geometry context for feasible estimates and overlap checks."""

    def __init__(self, body, beads: list[Bead], o: dict, tol: float, fixed_xyz: np.ndarray | None, fixed_cluster: np.ndarray | None):
        self.body = body
        self.topo = body.topology()
        self.beads = beads
        self.o = o
        self.tol = tol
        self.fx = fixed_xyz
        self.fc = fixed_cluster
        self.obst = Obstacles.build(body, self.topo, beads)

    def others(self, bead: Bead, wname: dict[str, str]):
        z = np.zeros(3)
        return [(wname[b.id], b, b.prof, z) for b in self.beads if b is not bead]

    def cluster_near(self, bead: Bead, prof, shift, limit: float) -> int | None:
        if self.fx is None or len(self.fx) == 0:
            return None
        d = region_distance(bead, prof, shift, self.fx, self.tol)
        i = int(np.argmin(d))
        return int(self.fc[i]) if d[i] <= limit else None


def _inside_elements(ctx: _Ctx, bead: Bead) -> set[int]:
    """Profile elements (0..3) holding fixed nodes of this bead's region (nominal)."""
    if ctx.fx is None or len(ctx.fx) == 0:
        return set()
    d = region_distance(bead, bead.prof, np.zeros(3), ctx.fx, ctx.tol)
    sel = np.flatnonzero(d <= ctx.tol)
    out = set()
    if len(sel):
        rho, h, _, _ = core_coords(ctx.fx[sel], bead.core, bead.n, bead.p0, bead.ed)
        for r_, h_ in zip(rho, h):
            if r_ >= bead.prof.rho0 - ctx.tol and abs(h_) <= ctx.tol:
                out.add(-1)  # on the entry loop itself
            else:
                out.add(bead.prof.locate(float(r_), float(h_))[0])
    return out


def feasible_all(ctx: _Ctx, bead: Bead, refs: dict, wname: dict[str, str]) -> dict[str, dict]:
    o = ctx.o
    eo = o["extract"]
    mode = o["bead"]["depth_mode"]
    land = float(eo["land_min_mm"])
    trans = float(o["fixed"]["transition_mm"])
    z = np.zeros(3)
    items = ctx.obst.items(bead, ctx.others(bead, wname))
    P = np.concatenate([pts for _, pts in items]) if items else np.zeros((0, 3))
    lab = np.concatenate([np.full(len(pts), i) for i, (_, pts) in enumerate(items)]) if items else np.zeros(0, dtype=int)
    c0 = np.array([loop_clearance(bead, bead.prof, z, pts) for _, pts in items])
    thr = np.minimum(land, c0)[lab] if len(P) else np.zeros(0)
    fc0 = fixed_clearance(bead, bead.prof, z, ctx.fx, ctx.tol) if ctx.fx is not None else math.inf
    fthr = min(trans, fc0)
    inside = _inside_elements(ctx, bead)
    prof = bead.prof

    def slack(p, sh) -> tuple[float, str | None]:
        """min clearance margin (>= 0 ok) and the limiting obstacle label."""
        best, why = math.inf, None
        if len(P):
            rho, _, _, _ = core_coords(P, [c + sh for c in bead.core], bead.n, bead.p0, bead.ed)
            m = rho - p.rho0 - thr
            i = int(np.argmin(m))
            best, why = float(m[i]), items[int(lab[i])][0]
        if ctx.fx is not None and len(ctx.fx):
            fm = fixed_clearance(bead, p, sh, ctx.fx, ctx.tol) - fthr
            if fm < best:
                best, why = fm, f"fixed_region:{ctx.cluster_near(bead, p, sh, trans + 1e-6)}"
        return best, why

    def loop_ok(p, sh) -> str | None:
        m, why = slack(p, sh)
        return why if m < -1e-9 else None

    out = {}
    # depth
    D = prof.depth
    locked_d = bool(inside - ({0, -1} if mode == "keep_angle" else {-1}))

    def ok_d(x, sign):
        p = prof.with_depth(D + sign * x, mode)
        return p.valid(eo["min_flank_deg"]) is None and D + sign * x >= eo["min_depth_mm"]

    if locked_d:
        cl = ctx.cluster_near(bead, prof, z, ctx.tol)
        out["BEAD_DEPTH"] = {"min": rnd(D), "max": rnd(D), "limited_by": f"fixed_region:{cl}", "source": "estimate"}
    else:
        up = search_limit(lambda x: ok_d(x, 1), 3.0 * D, 0.05)
        dn = search_limit(lambda x: ok_d(x, -1), D, 0.05)
        p = prof.with_depth(D + up + 1e-3, mode)
        out["BEAD_DEPTH"] = {"min": rnd(D - dn), "max": rnd(D + up), "limited_by": p.valid(eo["min_flank_deg"]) or "bottom_width", "source": "estimate"}
    # width
    W = prof.width()
    locked = bool(inside)
    if locked:
        cl = ctx.cluster_near(bead, prof, z, ctx.tol)
        out["BEAD_WIDTH"] = {"min": rnd(W), "max": rnd(W), "limited_by": f"fixed_region:{cl}", "source": "estimate"}
    else:
        def ok_w(x, sign):
            p = prof.with_width_delta(sign * x)
            return p.valid(eo["min_flank_deg"]) is None and loop_ok(p, z) is None

        up = search_limit(lambda x: ok_w(x, 1), 2.0 * W, 0.02, lambda x: slack(prof.with_width_delta(x), z)[0], 0.5)
        dn = search_limit(lambda x: ok_w(x, -1), W, 0.05)
        p = prof.with_width_delta(up + 1e-3)
        lim = p.valid(eo["min_flank_deg"]) or loop_ok(p, z) or "base_boundary"
        out["BEAD_WIDTH"] = {"min": rnd(W - dn), "max": rnd(W + up), "limited_by": lim, "source": "estimate"}
    # positions
    for t in POSITION_TYPES:
        r = refs.get(t)
        if r is None:
            continue
        nom = r["nominal"]
        if locked:
            cl = ctx.cluster_near(bead, prof, z, ctx.tol)
            out[t] = {"min": rnd(nom), "max": rnd(nom), "limited_by": f"fixed_region:{cl}", "source": "estimate"}
            continue
        mv = r["move"]
        up = search_limit(lambda x: loop_ok(prof, x * mv) is None, 200.0, 0.02, lambda x: slack(prof, x * mv)[0])
        dn = search_limit(lambda x: loop_ok(prof, -x * mv) is None, min(200.0, nom), 0.02, lambda x: slack(prof, -x * mv)[0])
        lim_up = loop_ok(prof, (up + 1e-3) * mv)
        lim_dn = loop_ok(prof, -(dn + 1e-3) * mv) if dn < nom else "base_boundary"
        lim = lim_up if up <= dn else lim_dn
        out[t] = {"min": rnd(nom - dn), "max": rnd(nom + up), "limited_by": lim or "base_boundary", "source": "estimate"}
    return out


def _mirror_groups(beads: list[Bead], bbox: np.ndarray, tol: float) -> list[list[Bead]]:
    """Beads related by the body's bbox mid-planes x / y / z (same shape, sense and cross-section)."""
    mid = 0.5 * (bbox[:3] + bbox[3:])
    parent = list(range(len(beads)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i, a in enumerate(beads):
        for j in range(i + 1, len(beads)):
            b = beads[j]
            if a.body != b.body or a.shape != b.shape or a.sense != b.sense:
                continue
            if abs(a.prof.depth - b.prof.depth) > tol or abs(a.prof.width() - b.prof.width()) > tol or abs(a.length() - b.length()) > tol:
                continue
            for ax in range(3):
                m = a.center.copy()
                m[ax] = 2 * mid[ax] - m[ax]
                if float(np.linalg.norm(m - b.center)) <= tol and abs(float(np.dot(a.n, b.n))) > 1 - 1e-6:
                    parent[find(j)] = find(i)
                    break
    groups: dict[int, list[Bead]] = {}
    for i, b in enumerate(beads):
        groups.setdefault(find(i), []).append(b)
    return [g for g in groups.values() if len(g) > 1]


def _neighbors(ctx: _Ctx, bead: Bead, holes: list[np.ndarray]) -> list[str]:
    r = 2.0 * bead.prof.width()
    out = []
    for b in ctx.beads:
        if b is not bead and float(np.linalg.norm(b.center - bead.center)) <= r + b.prof.rho0:
            out.append("BEAD")
    for h in holes:
        if len(h) and float(np.min(np.linalg.norm(h - bead.center, axis=1))) <= r:
            out.append("HOLE")
    if ctx.fx is not None and len(ctx.fx):
        d = np.linalg.norm(ctx.fx - bead.center, axis=1)
        for c in sorted(set(int(x) for x in ctx.fc[d <= r])):
            out.append("FIXED")
    return sorted(out)


def run(args, rep: Reporter) -> int:
    t0 = time.monotonic()
    o = shopts.load(args.options)
    out = OutDir(args.out_dir, [XML_NAME, JSON_NAME] + ([] if args.no_png else [PNG_DIR]))
    out.prepare()
    rep.progress(5, "loading mid-surface CAD")
    cad = load(args.cad)
    asm = read_assembly(args.assem_dir) if args.assem_dir else None
    names = [b.name for b in cad.bodies]
    corr = correspond(names, asm, args.body_map)
    fx = None
    warnings: list[dict] = []
    if asm is not None:
        rep.progress(15, "fixed node sets")
        fx = compute_fixed(asm, sorted({p for p, _ in corr.values() if p is not None}), o)
        warnings += fx.warnings
    else:
        warnings.append({"code": "FIXED_INFO_MISSING", "message": "no --assem-dir: fixed-region overlap of the beads is unknown"})
    bodies = sorted(cad.bodies, key=lambda b: (component_name(corr[b.name][1]), b.name))
    parts_json, beads_json, feats_json, groups_json = [], [], [], []
    ctx_of: dict[str, _Ctx] = {}
    all_feats: list[dict] = []
    bead_list: list[tuple[Bead, str]] = []
    for bi, body in enumerate(bodies):
        rep.progress(20 + int(50 * bi / max(1, len(bodies))), f"recognizing beads: {body.name}")
        pid, title = corr[body.name]
        s = body.summary()
        tol = shopts.body_tol(o, s.bbox)
        parts_json.append({"body": body.name, "part_id": pid, "title": title, "faces": s.n_faces, "edges": s.n_edges, "vertices": s.n_vertices,
                           "area": rnd(s.extra.get("area", 0.0)), "bbox": vec(s.bbox)})
        rec = recognize(body, o["extract"], tol, body.name)
        warnings += rec.warnings
        comp = component_name(title)
        beads = sorted(rec.beads, key=lambda b: tuple(np.round(b.center, 4)))
        fxyz = fcl = None
        if fx is not None:
            sel = fx.part == pid
            fxyz, fcl = fx.xyz[sel], fx.cluster[sel]
        ctx = _Ctx(body, beads, o, tol, fxyz, fcl)
        ctx_of[body.name] = ctx
        holes = [sample_edges(body, ctx.topo, w) for w in rec.holes]
        for k, b in enumerate(beads, 1):
            b.k = k
            b.id = f"{comp}_B{k}"
        wname = {b.id: make_name(comp, TYPE_ABBR["BEAD_WIDTH"], b.k) for b in beads}
        topo = ctx.topo
        cand_edges = sorted({e for b in beads for e in topo.face(b.base_face).outer_edges} | {e for w in rec.holes for e in w})
        for b in beads:
            U, V = bead_axes(b)
            refs = {}
            for t, ax in (("BEAD_POS_U", U), ("BEAD_POS_V", V)):
                if o["bead"]["position_ref"] == "proportional":
                    bb = topo.face(b.base_face).bbox
                    corners = np.array([[x, y, zz] for x in (bb[0], bb[3]) for y in (bb[1], bb[4]) for zz in (bb[2], bb[5])])
                    lo = float(np.min(corners @ ax))
                    refs[t] = {"rule": "proportional", "edge": None, "axis": ax, "sign": 1.0, "nominal": float(b.center @ ax - lo), "move": ax, "origin": lo}
                    continue
                cand = [e for e in cand_edges if e in topo.face(b.base_face).edges]
                r = nearest_fixed_edge(body, topo, b, ax, cand)
                if r is None:
                    warnings.append({"code": "BEAD_POS_UNSUPPORTED", "bead": b.id, "message": f"{b.id}: no straight fixed edge normal to the {t[-1]} axis"})
                    continue
                refs[t] = {"rule": "nearest_fixed_edge", "edge": r["edge"], "axis": ax, "sign": r["sign"], "nominal": r["dist"], "move": r["sign"] * ax}
            feas = feasible_all(ctx, b, refs, wname)
            # fixed overlap
            if fxyz is None:
                overlap, clearance = "unknown", None
            else:
                d = region_distance(b, b.prof, np.zeros(3), fxyz, tol) if len(fxyz) else np.array([math.inf])
                clearance = float(np.min(d)) if len(d) else math.inf
                overlap = "inside" if clearance <= tol else ("transition" if clearance <= float(o["fixed"]["transition_mm"]) else "none")
            names_b = {t: make_name(comp, TYPE_ABBR[t], b.k) for t in TYPE_ORDER}
            if overlap == "inside":
                cl = ctx.cluster_near(b, b.prof, np.zeros(3), tol)
                warnings.append({"code": "BEAD_FIXED_OVERLAP", "bead": b.id, "feature": names_b["BEAD_DEPTH"], "cluster": cl,
                                 "message": f"bead region of {b.id} holds fixed nodes of cluster {cl}: its parameters are not used by default"})
            elif overlap == "transition":
                cl = ctx.cluster_near(b, b.prof, np.zeros(3), float(o["fixed"]["transition_mm"]))
                warnings.append({"code": "BEAD_NEAR_FIXED", "bead": b.id, "feature": names_b["BEAD_WIDTH"], "cluster": cl,
                                 "message": f"bead region of {b.id} within the transition zone of fixed cluster {cl}"})
            pts = b.prof.points()
            beads_json.append(
                {
                    "id": b.id, "k": b.k, "body": b.body, "shape": b.shape, "sense": b.sense, "base_face": f"F{b.base_face}",
                    "bottom": _fids(b.faces["bottom"]), "flanks": _fids(b.faces["flanks"]), "fillets_top": _fids(b.faces["fillets_top"]),
                    "fillets_bottom": _fids(b.faces["fillets_bottom"]), "loop": [f"E{e}" for e in b.loop_edges],
                    "center": vec(b.center), "axis": vec(U), "normal": vec(b.n), "depth_dir": vec(b.ed),
                    "core": [vec(c) for c in b.core],
                    "nominal": {"depth": rnd(b.prof.depth), "width": rnd(b.prof.width()), "length": rnd(b.length()), "flank_deg": rnd(math.degrees(pts["theta"])),
                                "r_top": rnd(b.prof.rt), "r_bottom": rnd(b.prof.rb), "entry_radius": rnd(b.prof.rho0), "bottom_radius": rnd(b.prof.rhob)},
                    "neighbors": _neighbors(ctx, b, holes),
                    "fixed_overlap": overlap,
                    "fixed_clearance_mm": None if clearance is None or not math.isfinite(clearance) else rnd(clearance),
                }
            )
            nominal = {"BEAD_DEPTH": b.prof.depth, "BEAD_WIDTH": b.prof.width()}
            for t in POSITION_TYPES:
                if t in refs:
                    nominal[t] = refs[t]["nominal"]
            for t in TYPE_ORDER:
                if t not in nominal:
                    continue
                f = {"name": names_b[t], "type": t, "bead": b.id, "body": b.body, "nominal": rnd(nominal[t]), "unit": "mm"}
                fe = feas[t]
                f["range"] = _range_mm(nominal[t], float(o["extract"]["position_range_mm"]), fe) if t in POSITION_TYPES else _range(nominal[t], float(o["extract"]["range_ratio"]), fe)
                f["feasible"] = fe
                if t == "BEAD_DEPTH":
                    f["op"] = {"mode": o["bead"]["depth_mode"]}
                elif t == "BEAD_WIDTH":
                    f["op"] = {"mode": "symmetric"}
                else:
                    r = refs[t]
                    f["op"] = {"mode": "translate"}
                    f["ref"] = {"rule": r["rule"], "edge": f"E{r['edge']}" if r["edge"] is not None else None, "axis": vec(r["axis"], 12), "sign": r["sign"]}
                    if "origin" in r:
                        f["ref"]["origin"] = rnd(r["origin"], 9)
                f["measure"] = {"method": MEASURE[t]}
                f["group"] = None
                f["use_default"] = overlap != "inside"
                f["png"] = None
                f["_order"] = (component_name(title), TYPE_ORDER.index(t), b.k)
                all_feats.append(f)
            bead_list.append((b, comp))
        # symmetry groups (bead level, per parameter type)
        for grp in _mirror_groups(beads, s.bbox, tol):
            for t in TYPE_ORDER:
                mem = [make_name(comp, TYPE_ABBR[t], b.k) for b in sorted(grp, key=lambda x: x.k)]
                fm = [f for f in all_feats if f["name"] in mem]
                if len(fm) != len(mem) or max(f["nominal"] for f in fm) - min(f["nominal"] for f in fm) > tol:
                    continue
                gid = f"G{len(groups_json) + 1}"
                groups_json.append({"id": gid, "type": t, "parameter": mem[0], "members": mem})
                for f in fm:
                    f["group"] = gid
    all_feats.sort(key=lambda f: f["_order"])
    for f in all_feats:
        del f["_order"]
    pngs: list[str] = []
    if all_feats and not args.no_png:
        rep.progress(85, "rendering bead highlights")
        pngs = _render(all_feats, beads_json, {b.name: b for b in cad.bodies}, fx, corr, out, warnings)
    doc = shell_envelope(
        unit_system="mm-ton-s",
        cad={"mode": cad.mode, "files": cad.files, "body_map": "body_map" if args.body_map else ("xde" if cad.mode == "single" else "file_stem")},
        parts=parts_json,
        beads=beads_json,
        features=all_feats,
        groups=groups_json,
        fixed={"available": fx is not None, "digest": fx.digest if fx is not None else None, "transition_mm": o["fixed"]["transition_mm"]},
        options={"extract": o["extract"], "bead": o["bead"]},
        warnings=warnings,
    )
    if not all_feats:
        out.write_text(JSON_NAME, dumps(doc))
        out.commit([JSON_NAME])
        rep.result("FAIL", "GEOM_EXTRACT_EMPTY", JSON_NAME)
        return EXIT_EXTRACT_EMPTY
    grouped = {g["parameter"] for g in groups_json}
    members = {m for g in groups_json for m in g["members"]}
    params = [(f["name"], f["nominal"]) for f in all_feats if f["name"] in grouped or f["name"] not in members]
    doc["elapsed_s"] = rnd(time.monotonic() - t0, 3)
    out.write_text(JSON_NAME, dumps(doc))
    out.write_text(XML_NAME, render_xml(Path(args.cad).name, params))
    out.commit([JSON_NAME, XML_NAME] + pngs)
    rep.progress(100, f"extract done: {len(beads_json)} beads, {len(all_feats)} features, {len(params)} parameters")
    rep.result("OK", None, JSON_NAME)
    return EXIT_OK


def _render(feats: list[dict], beads_json: list[dict], bodies: dict, fx, corr, out: OutDir, warnings: list[dict]) -> list[str]:
    from .. import render
    from .render import render_bead

    meshes: dict[str, object] = {}
    bead_of = {b["id"]: b for b in beads_json}
    written = []
    for f in feats:
        rel = f"{PNG_DIR}/{f['name']}.png"
        try:
            mesh = meshes.get(f["body"])
            if mesh is None:
                mesh = meshes[f["body"]] = render.BodyMesh(bodies[f["body"]].triangulate())
            b = bead_of[f["bead"]]
            pid = corr[f["body"]][0]
            pts = fx.xyz[fx.part == pid] if fx is not None else np.zeros((0, 3))
            img = render_bead(mesh, b, f, pts, bodies[f["body"]])
            render.write_png(out.tmp_path(rel), img)
        except Exception as ex:  # noqa: BLE001 - rendering never fails extract
            warnings.append({"code": "PNG_RENDER_FAILED", "feature": f["name"], "message": f"bead highlight rendering failed: {ex.__class__.__name__}: {ex}"})
            continue
        f["png"] = rel
        written.append(rel)
    return written
