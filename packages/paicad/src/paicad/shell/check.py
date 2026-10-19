"""``paicad shell check`` - checks of the morphed shell mesh (shell-morph sections 4.9, 6.6).

(f) fixed node lines byte-identical, (a) bead parameters re-measured on the morphed nodes against the
update's expected values, (b) classified node <-> sample entity distance, (c) shell quality, (d) new
penetration of moved nodes into other parts (mid-surface +- t/2), (e) ``/INTER/TYPE2`` projection.
Only on PASS the morph file copies are written to ``--out-files-dir`` (same relative paths).
"""

from __future__ import annotations

import math
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from ..common import CODE_CATEGORY, EXIT_CHECK, EXIT_OK, OutDir, PaicadError, Reporter, dumps, rnd
from ..mesh.radioss import parse_text
from ..meshgeom import TriangleSet
from ..tag import KIND_EDGE, KIND_FACE, KIND_VERTEX
from ..tie import AssemblySets, TieDef, check_ties
from ..update import read_json
from . import opts as shopts
from .assem import SHELL_KW, Assembly, SetError, resolve_grnod, resolve_surf, seg_triangles
from .beads import Bead, core_coords, recognize
from .common import load_shell_features, load_values, shell_envelope
from .morph import FILES_DIR, MORPH_JSON, ShellMesh, _element_faces, load_inputs
from .quality import evaluate as quality_eval

CHECK_JSON = "shell_check.json"
PRIORITY = ("SHELL_FIXED_REGION_VIOLATION", "GEOM_INTERFERENCE", "GEOM_QUALITY", "GEOM_DEVIATION", "GEOM_PARAM_MISMATCH", "GEOM_TIE_PROJECTION")


@dataclass
class CheckResult:
    status: str
    code: str | None
    message: str | None
    checks: dict
    warnings: list[dict] = field(default_factory=list)
    summary: dict = field(default_factory=dict)


def node_lines(data: bytes) -> dict[int, bytes]:
    out = {}
    in_node = False
    for line in data.splitlines(keepends=True):
        if line.startswith(b"/"):
            in_node = line.rstrip(b"\r\n").strip().upper() == b"/NODE" or line.upper().startswith(b"/NODE/")
            continue
        if not in_node or line.startswith((b"#", b"$")) or not line.strip():
            continue
        tok = line.split()
        try:
            out[int(tok[0])] = line
        except (ValueError, IndexError):
            continue
    return out


# ------------------------------------------------------------------ measurements
def _plane_fit(P: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    c = P.mean(axis=0)
    _, _, vt = np.linalg.svd(P - c, full_matrices=False)
    return c, vt[2]


def measure_bead(m: ShellMesh, xyz: np.ndarray, elem_face: np.ndarray, bead: Bead, feats: dict, body, o: dict) -> dict[str, float]:
    """Section 6.3 table measurements on the morphed nodes (``bead`` = recognized sample bead)."""
    out: dict[str, float] = {}
    kind, ent = m.kind, m.ent
    bottom = bead.faces["bottom"][0]
    bn = np.flatnonzero((kind == KIND_FACE) & (ent == bottom))
    base = np.flatnonzero((kind == KIND_FACE) & (ent == bead.base_face))
    if len(base) == 0:
        return out
    rho, _, _, _ = core_coords(xyz[base], bead.core, bead.n, bead.p0, bead.ed)
    # ring of ~2 elements outside the entry loop (fixed / transition nodes excluded)
    els = np.flatnonzero(elem_face == bead.base_face)
    e = xyz[m.conn[els]]
    hsz = float(np.median(np.linalg.norm(e[:, 1] - e[:, 0], axis=1))) if len(els) else 3.0
    trans = float(o["fixed"]["transition_mm"])
    ring = (rho >= bead.prof.rho0 - 1e-9) & (rho <= bead.prof.rho0 + 2.0 * hsz + 1e-9)
    keep = ring & ~m.fixed[base] & ~((m.geo[base] > 0) & (m.geo[base] < trans))
    sel = base[keep] if keep.sum() >= 3 else base[ring]
    if len(sel) < 3:
        sel = base
    c, nr = _plane_fit(xyz[sel])
    if float(np.dot(nr, bead.ed)) < 0:
        nr = -nr
    depth = None
    if len(bn):
        depth = float(np.mean((xyz[bn] - c) @ nr))
        out["BEAD_DEPTH"] = depth
    # position: area-weighted centroid of the bottom elements, onto the base plane
    be = np.flatnonzero(elem_face == bottom)
    if len(be):
        P = xyz[m.conn[be]]
        t1 = P[:, [0, 1, 2]]
        t2 = P[:, [0, 2, 3]]
        A1 = 0.5 * np.linalg.norm(np.cross(t1[:, 1] - t1[:, 0], t1[:, 2] - t1[:, 0]), axis=1)
        A2 = np.where(m.tri[be], 0.0, 0.5 * np.linalg.norm(np.cross(t2[:, 1] - t2[:, 0], t2[:, 2] - t2[:, 0]), axis=1))
        cen = (A1[:, None] * t1.mean(1) + A2[:, None] * t2.mean(1)).sum(0) / max(float((A1 + A2).sum()), 1e-300)
        cen = cen - float(np.dot(cen - c, nr)) * nr
        for t in ("BEAD_POS_U", "BEAD_POS_V"):
            f = feats.get(t)
            if f is None:
                continue
            r = f["ref"]
            ax = np.asarray(r["axis"], dtype=float)
            if r["rule"] == "proportional":
                out[t] = float(cen @ ax - float(r["origin"]))
            else:
                q = body.eval_edge(int(r["edge"][1:]), np.array([0.5]))[0]
                out[t] = float(r.get("sign", 1.0)) * float(np.dot(cen - q, ax))
    # width: flank element edges crossing the half-depth plane
    if depth is not None and "BEAD_WIDTH" in feats:
        hh = 0.5 * depth
        flank = bead.faces["flanks"]
        fe = np.flatnonzero(np.isin(elem_face, flank))
        pts, side_planar = [], []
        planar = {f for f in flank if body.topology().face(f).surface == "PLANE"}
        for i in fe:
            el = m.conn[i][:3] if m.tri[i] else m.conn[i]
            k = len(el)
            for a, b in ((el[j], el[(j + 1) % k]) for j in range(k)):
                ha, hb = float((xyz[a] - c) @ nr), float((xyz[b] - c) @ nr)
                if (ha - hh) * (hb - hh) < 0:
                    t = (hh - ha) / (hb - ha)
                    pts.append(xyz[a] + t * (xyz[b] - xyz[a]))
                    side_planar.append(int(elem_face[i]) in planar)
        if pts:
            P = np.array(pts)
            sp = np.array(side_planar)
            if len(bead.core) == 1:
                e1 = np.cross(nr, [1.0, 0.0, 0.0] if abs(nr[0]) < 0.9 else [0.0, 1.0, 0.0])
                e1 /= np.linalg.norm(e1)
                e2 = np.cross(nr, e1)
                x2 = np.stack([(P - c) @ e1, (P - c) @ e2], 1)
                A = np.column_stack([2 * x2, np.ones(len(x2))])
                sol, *_ = np.linalg.lstsq(A, (x2**2).sum(1), rcond=None)
                R = math.sqrt(max(0.0, sol[2] + sol[0] ** 2 + sol[1] ** 2))
                out["BEAD_WIDTH"] = 2.0 * R
            elif sp.any():
                u = bead.core_dir()
                w = np.cross(nr, u)
                w /= np.linalg.norm(w)
                s = (P[sp] - bead.core[0]) @ w
                if (s > 0).any() and (s < 0).any():
                    out["BEAD_WIDTH"] = float(s[s > 0].mean() - s[s < 0].mean())
    return out


def deviation(m: ShellMesh, xyz: np.ndarray, body, changed: dict, moved: np.ndarray, tag_dist: np.ndarray) -> tuple[float, int]:
    topo = body.topology()
    G = {int(x[1:]) for x in changed.get("geometry", []) + changed.get("boundary_only", [])}
    Ec = {int(x[1:]) for x in changed.get("edges", [])}
    Vc = {int(x[1:]) for x in changed.get("vertices", [])}
    dev = np.where(tag_dist >= 0, tag_dist, 0.0).astype(float)
    kind, ent = m.kind, m.ent
    sel_f = (kind == KIND_FACE) & (np.isin(ent, sorted(G)) | moved)
    for f in sorted(set(int(x) for x in ent[sel_f])):
        idx = np.flatnonzero(sel_f & (ent == f))
        fd = topo.face(f)
        if fd.surface == "PLANE" and fd.normal is not None:
            dev[idx] = np.abs((xyz[idx] - np.asarray(fd.centroid)) @ np.asarray(fd.normal))
        else:
            d, _, _, _ = body.project_to_face(f, xyz[idx])
            dev[idx] = d
    sel_e = (kind == KIND_EDGE) & (np.isin(ent, sorted(Ec)) | moved)
    for e in sorted(set(int(x) for x in ent[sel_e])):
        idx = np.flatnonzero(sel_e & (ent == e))
        d, _, _ = body.project_to_edge(e, xyz[idx])
        dev[idx] = d
    sel_v = (kind == KIND_VERTEX) & (np.isin(ent, sorted(Vc)) | moved)
    for i in np.flatnonzero(sel_v):
        dev[i] = float(np.linalg.norm(xyz[i] - topo.vertices[int(ent[i]) - 1]))
    i = int(np.argmax(dev)) if len(dev) else 0
    return (float(dev[i]) if len(dev) else 0.0), i


def interference(asm: Assembly, meshes: list[ShellMesh], new_xyz: dict[int, np.ndarray], thick: dict[int, float], o: dict) -> tuple[dict, str | None]:
    target = {m.part_id for m in meshes}
    tnodes = set()
    for m in meshes:
        tnodes.update(int(x) for x in m.node_ids)
    pmm = float(o["interference"]["product_mm"])
    tris_by_part: dict[int, np.ndarray] = {}
    for b in asm.blocks:
        if b.part in target or b.keyword not in SHELL_KW:
            continue
        segs = [[int(x) for x in c if x > 0] for c in b.conn]
        t, _ = seg_triangles(segs)
        if len(t):
            keep = ~np.isin(t, list(tnodes)).any(axis=1)
            tris_by_part[b.part] = np.concatenate([tris_by_part.get(b.part, np.zeros((0, 3), dtype=np.int64)), t[keep]])
    pairs, worst = [], 0.0
    for m in meshes:
        d = new_xyz[m.index] - m.xyz
        mv = np.flatnonzero(np.linalg.norm(d, axis=1) > 0)
        if len(mv) == 0:
            continue
        lo = m.xyz.min(0) - 10.0
        hi = m.xyz.max(0) + 10.0
        ts = thick.get(m.part_id, 0.0)
        for pid, T in sorted(tris_by_part.items()):
            rows = asm.index(T.ravel())
            if np.any(rows < 0):
                continue
            C = asm.xyz[rows].reshape(-1, 3, 3)
            inb = ((C.max(1) >= lo) & (C.min(1) <= hi)).all(1)
            C = C[inb]
            if not len(C):
                continue
            req = 0.5 * (ts + thick.get(pid, 0.0)) - pmm
            if req <= 0:
                continue
            tset = TriangleSet(C)
            d1, _ = tset.distance(new_xyz[m.index][mv], req)
            d0, _ = tset.distance(m.xyz[mv], req)
            bad = (d1 < req) & ~(d0 < req)
            if bad.any():
                pen = float((req - d1[bad]).max())
                worst = max(worst, pen)
                pairs.append({"part_id": m.part_id, "with_part": pid, "nodes": int(bad.sum()), "max_penetration_mm": rnd(pen)})
    rep = {"status": "FAIL" if pairs else "PASS", "max_penetration_mm": rnd(worst), "pairs": pairs}
    return rep, ("interference: " + ", ".join(f"part {p['part_id']} into {p['with_part']} ({p['nodes']} nodes)" for p in pairs[:5])) if pairs else None


def tie_check(asm: Assembly, meshes: list[ShellMesh], new_xyz: dict[int, np.ndarray], o: dict) -> tuple[dict, str | None, list[dict]]:
    sets = AssemblySets()
    for fd in asm.fixdefs:
        if fd.kind != "INTER_TYPE2":
            continue
        g = fd.grnods[0] if fd.grnods else None
        sets.ties.append(TieDef(fd.id, g, fd.surf, fd.dsearch, fd.rel))
        try:
            if g is not None:
                sets.grnod_node[g] = sorted(resolve_grnod(asm, g))
        except SetError:
            sets.other_sets.add(("GRNOD", g))
        try:
            if fd.surf is not None:
                sets.surf_seg[fd.surf] = [s + [s[-1]] * (4 - len(s)) for s in resolve_surf(asm, fd.surf)]
        except SetError:
            sets.other_sets.add(("SURF", fd.surf))
    shell_nodes = set()
    base = {int(n): asm.xyz[i] for i, n in enumerate(asm.node_ids)}
    new = dict(base)
    for m in meshes:
        shell_nodes.update(int(x) for x in m.node_ids)
        for k, nid in enumerate(m.node_ids):
            new[int(nid)] = new_xyz[m.index][k]
    return check_ties(sets, shell_nodes, new, base, o)


def check_core(meshes, morphed: dict[int, np.ndarray], samples: dict, doc: dict, vals: dict, expected: dict, changed_all: dict, o: dict, asm: Assembly | None,
               thick: dict[int, float], tag: dict, files: list[tuple[str, bytes]] | None, full: bool = True) -> CheckResult:
    checks: dict = {}
    warnings: list[dict] = []
    fails: dict[str, str] = {}
    # (f) fixed
    moved_fixed, fmax = 0, 0.0
    for m in meshes:
        dd = np.linalg.norm(morphed[m.index][m.fixed] - m.xyz[m.fixed], axis=1)
        moved_fixed += int((dd > 0).sum())
        fmax = max(fmax, float(dd.max()) if dd.size else 0.0)
    if files is not None and asm is not None:
        fixed_ids = set()
        for m in meshes:
            fixed_ids.update(int(x) for x in m.node_ids[m.fixed])
        for rel, data in files:
            a = node_lines((asm.root / rel).read_bytes())
            b = node_lines(data)
            moved_fixed += sum(1 for k in fixed_ids if k in a and a[k] != b.get(k))
    checks["fixed"] = {"status": "FAIL" if moved_fixed else "PASS", "moved_fixed_nodes": moved_fixed, "max_mm": rnd(fmax)}
    if moved_fixed:
        fails["SHELL_FIXED_REGION_VIOLATION"] = f"fixed: {moved_fixed} fixed nodes changed"
    # (a) parameters
    by_bead: dict[str, dict] = {}
    for f in doc["features"]:
        by_bead.setdefault(f["bead"], {})[f["type"]] = f
    items = []
    errs_abs, errs_rel, margin = [], [], []
    dv = o["deviation"]
    for m in meshes:
        body = samples[m.body]
        topo = body.topology()
        ef = getattr(m, "_elem_face", None)
        if ef is None:
            ef = m._elem_face = _element_faces(m, topo)
        tol = shopts.body_tol(o, body.summary().bbox)
        rec = {tuple(b.faces["bottom"]): b for b in recognize(body, o["extract"], tol, body.name).beads}
        for bj in doc["beads"]:
            if bj["body"] != m.body:
                continue
            feats = by_bead.get(bj["id"], {})
            want = {t: f for t, f in feats.items() if f["name"] in vals or f["name"] in expected}
            if not want:
                continue
            bead = rec.get(tuple(int(x[1:]) for x in bj["bottom"]))
            meas = measure_bead(m, morphed[m.index], ef, bead, feats, body, o) if bead is not None else {}
            for t, f in sorted(want.items(), key=lambda kv: kv[1]["name"]):
                inp = float(vals.get(f["name"], f["nominal"]))
                exp = float(expected.get(f["name"], inp))
                tl = max(float(dv["param_abs_mm"]), float(dv["param_rel"]) * abs(exp))
                v = meas.get(t)
                it = {"name": f["name"], "input": rnd(inp, 9), "expected": rnd(exp, 9), "measured": None if v is None else rnd(v), "err": None, "tol": rnd(tl)}
                if v is None:
                    fails.setdefault("GEOM_PARAM_MISMATCH", f"param: {f['name']} could not be measured")
                else:
                    err = abs(v - exp)
                    it["err"] = rnd(err)
                    errs_abs.append(err)
                    errs_rel.append(err / abs(exp) if exp else 0.0)
                    margin.append(tl / err if err > 0 else math.inf)
                    if err > tl:
                        fails.setdefault("GEOM_PARAM_MISMATCH", f"param: {f['name']} measured {v:.4f}, expected {exp:.4f} (tol {tl:.4f})")
                items.append(it)
    checks["param"] = {"status": "FAIL" if "GEOM_PARAM_MISMATCH" in fails else "PASS", "items": items}
    # (b) deviation
    worst, worst_node = 0.0, None
    for m in meshes:
        moved = np.any(morphed[m.index] != m.xyz, axis=1)
        dmax, i = deviation(m, morphed[m.index], samples[m.body], changed_all.get(m.body, {}), moved, tag["dist_of"][m.index])
        if dmax >= worst:
            worst, worst_node = dmax, int(m.node_ids[i]) if len(m.node_ids) else None
    tolb = float(dv["boundary_max_mm"])
    checks["deviation"] = {"status": "FAIL" if worst > tolb else "PASS", "max_mm": rnd(worst), "tol_mm": tolb, "worst_node": worst_node}
    if worst > tolb:
        fails["GEOM_DEVIATION"] = f"deviation: {worst:.4f} mm > {tolb} mm at node {worst_node}"
    # (c) quality
    qreps = []
    qmsg = None
    for m in meshes:
        rep, msg, w = quality_eval(m.xyz, morphed[m.index], m.conn, m.tri, o["quality"])
        qreps.append(rep)
        warnings += w
        qmsg = qmsg or msg
    q = qreps[0] if len(qreps) == 1 else _merge_quality(qreps)
    checks["quality"] = q
    if qmsg:
        fails["GEOM_QUALITY"] = qmsg
    summary = {
        "max_warpage_deg": q["max_warpage_deg"], "max_skew_deg": q["max_skew_deg"], "max_aspect": q["max_aspect"], "min_jacobian": q["min_jacobian"],
        "edge_ratio": q["edge_ratio"], "dt_ratio": q["dt_ratio"], "inverted_elems": q["inverted"], "boundary_dev_max_mm": rnd(worst),
        "param_remeasure_err": {"abs": rnd(max(errs_abs)) if errs_abs else None, "rel": rnd(max(errs_rel)) if errs_rel else None},
        "param_margin": rnd(min(margin)) if margin and math.isfinite(min(margin)) else None,
        "quality_margins": q.get("margins"),
    }
    if full and asm is not None:
        rep, msg = interference(asm, meshes, morphed, thick, o)
        checks["interference"] = rep
        if msg:
            fails["GEOM_INTERFERENCE"] = msg
        rep, msg, w = tie_check(asm, meshes, morphed, o)
        checks["tie"] = rep
        warnings += w
        if msg:
            fails["GEOM_TIE_PROJECTION"] = msg
    else:
        checks["interference"] = {"status": "NOT_EVALUATED"}
        checks["tie"] = {"status": "NOT_EVALUATED"}
    code = next((c for c in PRIORITY if c in fails), None)
    return CheckResult("FAIL" if code else "PASS", code, fails.get(code) if code else None, checks, warnings, summary)


def _merge_quality(reps: list[dict]) -> dict:
    out = dict(reps[0])
    for r in reps[1:]:
        for k in ("max_warpage_deg", "max_skew_deg", "max_aspect", "baseline_max_warpage_deg", "baseline_max_skew_deg", "baseline_max_aspect"):
            out[k] = max(x for x in (out[k], r[k]) if x is not None) if out[k] is not None or r[k] is not None else None
        for k in ("min_jacobian", "baseline_min_jacobian", "min_edge_mm", "baseline_min_edge_mm", "edge_ratio", "dt_ratio"):
            vals = [x for x in (out[k], r[k]) if x is not None]
            out[k] = min(vals) if vals else None
        out["inverted"] += r["inverted"]
        out["margins"] = {k: min((x for x in (out["margins"][k], r["margins"][k]) if x is not None), default=None) for k in out["margins"]}
        out["baseline_status"] = "FAIL" if "FAIL" in (out["baseline_status"], r["baseline_status"]) else "PASS"
        out["status"] = "FAIL" if "FAIL" in (out["status"], r["status"]) else "PASS"
    return out


def thickness_map(asm: Assembly, path: str | None) -> dict[int, float]:
    out = {}
    for pid, p in asm.parts.items():
        pr = asm.props.get(p.get("prop")) if p.get("prop") is not None else None
        if pr and pr.get("thickness"):
            out[pid] = float(pr["thickness"])
    if path:
        d = read_json(path, "thickness file")
        if d.get("schema_version") != 1 or not isinstance(d.get("parts"), dict):
            raise PaicadError("GEOM_INPUT_INVALID", 'thickness file must be {"schema_version":1,"parts":{"<part_id>":t}}')
        for k, v in d["parts"].items():
            try:
                pid = int(k)
            except ValueError:
                raise PaicadError("GEOM_INPUT_INVALID", f"thickness file: bad part id {k!r}") from None
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not (v > 0 and math.isfinite(v)):
                raise PaicadError("GEOM_INPUT_INVALID", f"thickness of part {k} must be a finite number > 0")
            out[pid] = float(v)
    return out


def morphed_coords(meshes: list[ShellMesh], asm: Assembly, files: list[tuple[str, bytes]]) -> dict[int, np.ndarray]:
    """Shell node coordinates as written in the morph file copies (unchanged files: assembly values)."""
    new = {}
    over: dict[int, np.ndarray] = {}
    for rel, data in files:
        mesh = parse_text(data.decode("latin-1"))
        for nid, p in zip(mesh.node_ids, mesh.xyz):
            over[int(nid)] = p
    for m in meshes:
        x = m.xyz.copy()
        for k, nid in enumerate(m.node_ids):
            p = over.get(int(nid))
            if p is not None:
                x[k] = p
        new[m.index] = x
    return new


def run(args, rep: Reporter) -> int:
    t0 = time.monotonic()
    o = shopts.load(args.options)
    out = OutDir(args.out_dir, [CHECK_JSON])
    out.prepare()
    ns = argparse_like(args)
    doc, tag_doc, fixed, asm, u, samples, meshes = load_inputs(ns, o)
    vals = load_values(args.values, doc, o)
    md = Path(args.morph_dir)
    mj = read_json(md / MORPH_JSON, MORPH_JSON)
    if mj.get("status") != "OK" or mj.get("kind") != "shell":
        raise PaicadError("GEOM_INPUT_INVALID", "shell_morph.json status is not OK")
    files = []
    for f in mj.get("files") or []:
        p = md / FILES_DIR / f["rel"]
        if not p.is_file():
            raise PaicadError("GEOM_INPUT_INVALID", f"morph file copy missing: {f['rel']}")
        files.append((f["rel"], p.read_bytes()))
    ofd = Path(args.out_files_dir)
    exists = [rel for rel, _ in files if (ofd / rel).exists()]
    if exists:
        raise PaicadError("GEOM_OUTPUT_EXISTS", f"output already exists: {', '.join(exists[:10])}")
    thick = thickness_map(asm, args.thickness)
    from .tag import load_shell_tag

    _, tag = load_shell_tag(args.tag_dir)
    tag_dist = {}
    look = {int(n): i for i, n in enumerate(tag["node_id"])}
    for m in meshes:
        tag_dist[m.index] = np.array([tag["dist"][look[int(n)]] for n in m.node_ids])
    rep.progress(20, "checking the morphed shell mesh")
    morphed = morphed_coords(meshes, asm, files)
    res = check_core(meshes, morphed, samples, doc, vals, u.get("expected_measured") or {}, u.get("changed") or {}, o, asm, thick, {"dist_of": tag_dist}, files)
    out_files = []
    if res.status == "PASS":
        for rel, data in files:
            dst = ofd / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            tmp = dst.with_name(f".{dst.name}.{os.getpid()}.tmp")
            tmp.write_bytes(data)
            os.replace(tmp, dst)
            out_files.append(rel)
    d = shell_envelope(
        status=res.status, code=res.code, category=CODE_CATEGORY.get(res.code) if res.code else None, message=res.message,
        checks=res.checks, warnings=res.warnings, options=shopts.used(o), out_files=out_files, elapsed_s=rnd(time.monotonic() - t0, 3),
    )
    out.write_text(CHECK_JSON, dumps(d))
    out.commit([CHECK_JSON])
    rep.progress(100, f"shell check {res.status}")
    rep.result(res.status, res.code, CHECK_JSON)
    return EXIT_OK if res.status == "PASS" else EXIT_CHECK


def argparse_like(args):
    import argparse

    return argparse.Namespace(features=args.features, tag_dir=args.tag_dir, fixed_dir=args.fixed_dir, assem_dir=args.assem_dir, update_dir=args.update_dir)
