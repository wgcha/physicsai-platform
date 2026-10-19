"""``paicad check`` - judge the morphed mesh and write the include on PASS (contract sections 4.8, 6.5).

Items (all evaluated, no short-circuit): (a) parameter re-measurement on the morphed mesh,
(b) boundary-node deviation from the sample B-rep, (c) quality (tetra stretch, boundary-triangle
aspect, minimum edge, inverted, time-step ratio; baseline evaluated with the same criteria ->
BASELINE_QUALITY_BELOW warning), (d) body-body / product interference, (e) tie projection.
Top-level code priority: INTERFERENCE -> QUALITY -> DEVIATION (GEOM_DEVIATION, GEOM_PARAM_MISMATCH) -> TIE.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from scipy.spatial import cKDTree

from . import options, quality
from .common import CODE_CATEGORY, EXIT_CHECK, EXIT_OK, OutDir, PaicadError, Reporter, dumps, envelope, rnd
from .measure import FaceIndex, measure_feature
from .mesh.radioss import RadMesh, collect_assembly_surface, parse_text, read_mesh, read_renum_csv
from .meshdata import KIND_EDGE, KIND_FACE, KIND_VERTEX, Comp, components_from_tag, load_tag
from .meshgeom import TriangleSet
from .morph import MORPHED_INC, SampleSet, load_sample, read_baseline
from .update import feature_values, load_features, load_values

CHECK_JSON = "check.json"
PRIORITY = ("GEOM_INTERFERENCE", "GEOM_QUALITY", "GEOM_DEVIATION", "GEOM_PARAM_MISMATCH", "GEOM_TIE_PROJECTION")


@dataclass
class CheckResult:
    status: str
    code: str | None
    message: str | None
    checks: dict
    warnings: list[dict]
    summary: dict  # envelope metrics


# ------------------------------------------------------------------ (a) parameters
def check_params(doc: dict, fvalues: dict[str, float], comps: list[Comp], fis: dict[str, FaceIndex], sample: SampleSet, X: np.ndarray, dev: dict) -> tuple[dict, str | None, dict]:
    items = []
    worst_abs = worst_rel = 0.0
    bad = []
    comp_of = {c.body: c for c in comps}
    for f in doc["features"]:
        c = comp_of.get(f["body"])
        inp = float(fvalues[f["name"]])
        tol = max(float(dev["param_abs_mm"]), float(dev["param_rel"]) * abs(inp))
        meas = None
        if c is not None:
            meas = measure_feature(f, fis[c.body], sample.face_map[c.body]["F"], X[c.gidx])
        if meas is None:
            items.append({"name": f["name"], "input": rnd(inp, 9), "measured": None, "err": None, "tol": rnd(tol), "status": "FAIL"})
            bad.append(f"{f['name']} cannot be measured")
            worst_abs = worst_rel = float("inf")
            continue
        err = abs(meas - inp)
        worst_abs = max(worst_abs, err)
        worst_rel = max(worst_rel, err / abs(inp) if inp else err)
        ok = err <= tol
        items.append({"name": f["name"], "input": rnd(inp, 9), "measured": rnd(meas), "err": rnd(err), "tol": rnd(tol), "status": "PASS" if ok else "FAIL"})
        if not ok:
            bad.append(f"{f['name']} measured {meas:.4f} vs input {inp:.4f}")
    rep = {"status": "FAIL" if bad else "PASS", "items": items}
    msg = "parameter re-measurement: " + "; ".join(bad[:3]) + (f" (+{len(bad) - 3} more)" if len(bad) > 3 else "") if bad else None
    return rep, msg, {"abs": _fin(worst_abs), "rel": _fin(worst_rel)}


def _fin(x: float):
    return rnd(x) if np.isfinite(x) else None


# ------------------------------------------------------------------ (b) deviation
def check_deviation(comps: list[Comp], sample: SampleSet, X: np.ndarray, mesh: RadMesh, tol: float) -> tuple[dict, str | None]:
    worst, worst_node = 0.0, None
    for c in comps:
        body = sample.bodies[c.body]
        topo = body.topology()
        fm = sample.face_map[c.body]
        own = c.owner == c.index
        d = np.zeros(len(c.node_ids))
        for i in np.flatnonzero(own & (c.kind == KIND_VERTEX)):
            v = int(fm["V"][str(int(c.entity[i]))])
            d[i] = float(np.linalg.norm(X[c.gidx[i]] - topo.vertices[v - 1]))
        sel = np.flatnonzero(own & (c.kind == KIND_EDGE))
        for e in np.unique(c.entity[sel]):
            idx = sel[c.entity[sel] == e]
            de, _, _ = body.project_to_edge(int(fm["E"][str(int(e))]), X[c.gidx[idx]])
            d[idx] = de
        sel = np.flatnonzero(own & (c.kind == KIND_FACE))
        for f in np.unique(c.entity[sel]):
            idx = sel[c.entity[sel] == f]
            sf = int(fm["F"][str(int(f))])
            P = X[c.gidx[idx]]
            df, _, inside, _ = body.project_to_face(sf, P)
            out = np.flatnonzero(~inside)
            if out.size:
                best = np.full(out.size, np.inf)
                for e in topo.face(sf).edges:
                    de, _, _ = body.project_to_edge(e, P[out])
                    best = np.minimum(best, de)
                df[out] = best
            d[idx] = df
        if d.size and float(d.max()) > worst:
            worst = float(d.max())
            worst_node = int(c.node_ids[int(np.argmax(d))])
    ok = worst <= tol
    rep = {"status": "PASS" if ok else "FAIL", "max_mm": rnd(worst), "tol_mm": tol, "worst_node": worst_node}
    return rep, None if ok else f"boundary deviation {worst:.4f} mm > {tol:g} mm (node {worst_node})"


# ------------------------------------------------------------------ (d) interference
def _points_in_tets(P: np.ndarray, X: np.ndarray, tets: np.ndarray) -> np.ndarray:
    """bool[len(P)]: point strictly inside one of the tetrahedra (barycentric test via a centroid KD-tree)."""
    if len(P) == 0 or len(tets) == 0:
        return np.zeros(len(P), dtype=bool)
    T = X[tets]
    cen = T.mean(axis=1)
    rmax = float(np.linalg.norm(T - cen[:, None, :], axis=2).max())
    tree = cKDTree(cen)
    cand = tree.query_ball_point(P, r=rmax)
    pi = np.repeat(np.arange(len(P)), [len(c) for c in cand])
    ti = np.fromiter((t for c in cand for t in c), dtype=np.int64, count=len(pi))
    inside = np.zeros(len(P), dtype=bool)
    if len(pi) == 0:
        return inside
    A = T[ti]
    M = np.stack([A[:, 1] - A[:, 0], A[:, 2] - A[:, 0], A[:, 3] - A[:, 0]], axis=2)
    det = np.linalg.det(M)
    ok = np.abs(det) > 1e-18
    lam = np.zeros((len(pi), 3))
    lam[ok] = np.linalg.solve(M[ok], (P[pi[ok]] - A[ok, 0])[..., None])[..., 0]
    l0 = 1.0 - lam.sum(axis=1)
    eps = 1e-9
    hit = ok & (lam > eps).all(axis=1) & (l0 > eps)
    inside[pi[hit]] = True
    return inside


def _vertex_normals(X: np.ndarray, skin_g: np.ndarray, flip: bool) -> dict[int, np.ndarray]:
    n = np.cross(X[skin_g[:, 1]] - X[skin_g[:, 0]], X[skin_g[:, 2]] - X[skin_g[:, 0]])
    if flip:
        n = -n
    acc: dict[int, np.ndarray] = {}
    for k in range(3):
        for g, v in zip(skin_g[:, k], n):
            acc[int(g)] = acc.get(int(g), 0) + v
    return {g: v / (np.linalg.norm(v) or 1.0) for g, v in acc.items()}


def check_interference(comps: list[Comp], Xb: np.ndarray, Xm: np.ndarray, assem_dir: str | None, baseline: Path, opts: dict) -> tuple[dict, str | None]:
    io = opts["interference"]
    body_mm, prod_mm = float(io["body_mm"]), float(io["product_mm"])
    pairs = []
    body_max = 0.0
    skins = {c.index: c.gidx[c.skin] for c in comps}
    for a in comps:
        sa = np.unique(skins[a.index])
        for b in comps:
            if a.index == b.index:
                continue
            pts_rows = np.setdiff1d(sa, b.gidx)
            if pts_rows.size == 0:
                continue
            lo = Xm[b.gidx].min(axis=0) - body_mm
            hi = Xm[b.gidx].max(axis=0) + body_mm
            near = pts_rows[np.all((Xm[pts_rows] >= lo) & (Xm[pts_rows] <= hi), axis=1)]
            if near.size == 0:
                continue
            inside = _points_in_tets(Xm[near], Xm, b.gidx[b.tets])
            if not inside.any():
                continue
            d, _ = TriangleSet(Xm[skins[b.index]]).distance(Xm[near[inside]], 1e30)
            deep = d > body_mm
            if deep.any():
                body_max = max(body_max, float(d.max()))
                pairs.append({"a": a.part, "b": b.part, "nodes": int(deep.sum()), "max_depth_mm": rnd(float(d.max()))})
    prod_max = 0.0
    if assem_dir:
        allg = np.unique(np.concatenate([c.gidx for c in comps]))
        lo, hi = Xm[allg].min(axis=0), Xm[allg].max(axis=0)
        tris = collect_assembly_surface(assem_dir, [baseline], np.concatenate([lo, hi]), margin=10.0)
        if len(tris):
            ts = TriangleSet(tris)
            nrm_t = np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0])
            nrm_t /= np.maximum(np.linalg.norm(nrm_t, axis=1), 1e-300)[:, None]
            for c in comps:
                vol_sign = np.sign(np.einsum("ij,ij->i", np.cross(Xb[c.gidx[c.tets[:, 1]]] - Xb[c.gidx[c.tets[:, 0]]], Xb[c.gidx[c.tets[:, 2]]] - Xb[c.gidx[c.tets[:, 0]]]), Xb[c.gidx[c.tets[:, 3]]] - Xb[c.gidx[c.tets[:, 0]]]).sum())
                vn = _vertex_normals(Xb, skins[c.index], vol_sign < 0)
                rows = np.array(sorted(vn), dtype=np.int64)
                p1, p0 = Xm[rows], Xb[rows]
                cut = float(np.linalg.norm(p1 - p0, axis=1).max()) + prod_mm
                d1, ti = ts.distance(p1, cut)
                hitn = np.flatnonzero(ti >= 0)
                count, dmax = 0, 0.0
                for k in hitn:
                    t = ti[k]
                    n = nrm_t[t]
                    a0 = tris[t, 0]
                    s1 = float(np.dot(p1[k] - a0, n))
                    s0 = float(np.dot(p0[k] - a0, n))
                    foot = p1[k] - s1 * n
                    if not _in_triangle(foot, tris[t]):
                        continue
                    ref = np.sign(s0) if abs(s0) > prod_mm else np.sign(-float(np.dot(n, vn[int(rows[k])])))
                    depth = -ref * s1
                    if depth > prod_mm:
                        count += 1
                        dmax = max(dmax, depth)
                if count:
                    prod_max = max(prod_max, dmax)
                    pairs.append({"a": c.part, "b": "PRODUCT", "nodes": count, "max_depth_mm": rnd(dmax)})
    ok = not pairs
    rep = {"status": "PASS" if ok else "FAIL", "body_body_max_mm": rnd(body_max), "product_max_mm": rnd(prod_max), "pairs": pairs}
    msg = None if ok else "interference: " + ", ".join(f"{p['a']} into {p['b']} ({p['nodes']} nodes, {p['max_depth_mm']:.3f} mm)" for p in pairs[:3])
    return rep, msg


def _in_triangle(p: np.ndarray, t: np.ndarray, eps: float = 1e-9) -> bool:
    a, b, c = t
    v0, v1, v2 = b - a, c - a, p - a
    d00, d01, d11 = v0 @ v0, v0 @ v1, v1 @ v1
    d20, d21 = v2 @ v0, v2 @ v1
    den = d00 * d11 - d01 * d01
    if den <= 0:
        return False
    v = (d11 * d20 - d01 * d21) / den
    w = (d00 * d21 - d01 * d20) / den
    return v >= -eps and w >= -eps and v + w <= 1 + eps


# ------------------------------------------------------------------ (e) tie
def check_tie(comps: list[Comp], mesh: RadMesh, Xm: np.ndarray, assem_dir: str, opts: dict) -> tuple[dict, str | None, list[dict]]:
    from .tie import check_ties, parse_sets

    d = Path(assem_dir)
    files = sorted(p for p in d.iterdir() if p.is_file() and p.suffix.lower() in (".rad", ".inc"))
    sets = parse_sets(files)
    if not sets.ties and not sets.errors:
        return {"status": "SKIPPED", "interfaces": [], "reason": "no_tie_on_component"}, None, []
    cushion = {int(n) for c in comps for n in c.node_ids}
    coords_new, coords_base = {}, {}
    for f in files:
        m = read_mesh(f)
        for n, p in zip(m.node_ids, m.xyz):
            coords_new.setdefault(int(n), p)
            coords_base.setdefault(int(n), p)
    for r, n in enumerate(mesh.node_ids):
        coords_new[int(n)] = Xm[r]
        coords_base[int(n)] = mesh.xyz[r]
    return check_ties(sets, cushion, coords_new, coords_base, opts)


# ------------------------------------------------------------------ core
def check_core(
    mesh: RadMesh,
    Xm: np.ndarray,
    comps: list[Comp],
    sample: SampleSet,
    doc: dict,
    values: dict[str, float],
    opts: dict,
    assem_dir: str | None,
    baseline_path: Path,
    full: bool = True,
) -> CheckResult:
    """``full=False`` (sweep): (a)(b)(c) only, (d)(e) NOT_EVALUATED."""
    Xb = mesh.xyz
    fvalues = feature_values(doc, opts, values)
    fis = {c.body: FaceIndex(c, sample.bodies[c.body].topology(), sample.face_map[c.body], Xb) for c in comps}
    fails: dict[str, str] = {}
    warnings: list[dict] = []
    p_rep, p_msg, p_err = check_params(doc, fvalues, comps, fis, sample, Xm, opts["deviation"])
    if p_msg:
        fails["GEOM_PARAM_MISMATCH"] = p_msg
    d_rep, d_msg = check_deviation(comps, sample, Xm, mesh, float(opts["deviation"]["boundary_max_mm"]))
    if d_msg:
        fails["GEOM_DEVIATION"] = d_msg
    tets = np.concatenate([c.gidx[c.tets] for c in comps])
    skin = np.concatenate([c.gidx[c.skin] for c in comps])
    q = quality.evaluate(Xb, Xm, tets, skin, opts["quality"])
    if q.message:
        fails["GEOM_QUALITY"] = q.message
    if not q.baseline_ok:
        warnings.append(
            {
                "code": "BASELINE_QUALITY_BELOW",
                "message": (
                    f"baseline mesh is below the quality criteria (min stretch {q.report['baseline_min_stretch']}, "
                    f"max aspect {q.report['baseline_max_aspect']}, min edge {q.report['baseline_min_edge_mm']} mm)"
                ),
            }
        )
    if full:
        i_rep, i_msg = check_interference(comps, Xb, Xm, assem_dir, baseline_path, opts)
        if i_msg:
            fails["GEOM_INTERFERENCE"] = i_msg
        t_rep, t_msg, t_warn = check_tie(comps, mesh, Xm, assem_dir, opts) if assem_dir else ({"status": "NOT_EVALUATED", "interfaces": []}, None, [])
        warnings += t_warn
        if t_msg:
            fails["GEOM_TIE_PROJECTION"] = t_msg
    else:
        i_rep = {"status": "NOT_EVALUATED", "body_body_max_mm": None, "product_max_mm": None, "pairs": []}
        t_rep = {"status": "NOT_EVALUATED", "interfaces": []}
    checks = {"param": p_rep, "deviation": d_rep, "quality": q.report, "interference": i_rep, "tie": t_rep}
    codes = [c for c in PRIORITY if c in fails]
    code = codes[0] if codes else None
    msg = None
    if code:
        msg = fails[code] + (f" (+{len(codes) - 1} more)" if len(codes) > 1 else "")
    summary = {
        "min_stretch": q.report["min_stretch"],
        "max_aspect": q.report["max_aspect"],
        "min_edge_ratio": q.report["dt_ratio"],
        "boundary_dev_max_mm": d_rep["max_mm"],
        "param_remeasure_err": p_err,
        "inverted_elems": q.report["inverted"],
    }
    return CheckResult("FAIL" if code else "PASS", code, msg, checks, warnings, summary)


# ------------------------------------------------------------------ CLI
def run(args, rep: Reporter) -> int:
    t0 = time.monotonic()
    opts = options.load(args.options)
    out_inc = Path(args.out_inc)
    if out_inc.exists():
        raise PaicadError("GEOM_OUTPUT_EXISTS", f"output already exists: {out_inc.name}")
    out = OutDir(args.out_dir, [CHECK_JSON])
    out.prepare()
    doc = load_features(args.features)
    values = load_values(args.values, doc, opts)
    rep.progress(5, "reading meshes")
    base_bytes, mesh = read_baseline(args.baseline_inc)
    mpath = Path(args.morph_dir) / MORPHED_INC
    if not mpath.is_file():
        raise PaicadError("GEOM_INPUT_INVALID", f"morphed include not found in morph dir: {mpath.name}")
    mdata = mpath.read_bytes()
    mm = parse_text(mdata.decode("latin-1"))
    if not np.array_equal(mm.node_ids, mesh.node_ids) or len(mm.blocks) != len(mesh.blocks):
        raise PaicadError("GEOM_INPUT_INVALID", "morphed include does not match the baseline (node ids / blocks)")
    tag = load_tag(args.tag_dir)
    comps = components_from_tag(mesh, tag)
    renum = read_renum_csv(args.renum_csv)
    if sorted(r.part for r in renum) != sorted(c.part for c in comps):
        raise PaicadError("GEOM_INPUT_INVALID", "renumber table parts do not match the tag parts")
    sample = load_sample(args.update_dir, doc)
    rep.progress(20, "checking")
    res = check_core(mesh, mm.xyz, comps, sample, doc, values, opts, args.assem_dir, Path(args.baseline_inc))
    d = envelope(
        status=res.status,
        code=res.code,
        category=CODE_CATEGORY.get(res.code) if res.code else None,
        message=res.message,
        checks=res.checks,
        warnings=res.warnings,
        options={k: v for k, v in opts.items() if k != "schema_version"},
        out_inc=out_inc.name if res.status == "PASS" else None,
        elapsed_s=rnd(time.monotonic() - t0, 3),
    )
    out.write_text(CHECK_JSON, dumps(d))
    if res.status == "PASS":
        out_inc.parent.mkdir(parents=True, exist_ok=True)
        tmp = out_inc.with_name(f".{out_inc.name}.tmp{os.getpid()}")
        with open(tmp, "wb") as f:
            f.write(mdata)
        os.replace(tmp, out_inc)
    out.commit([CHECK_JSON])
    rep.progress(100, f"check {res.status}")
    rep.result(res.status, res.code, CHECK_JSON)
    return EXIT_OK if res.status == "PASS" else EXIT_CHECK
