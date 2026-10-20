"""``paicad shell view export|preview`` - 3D view of the mid-surface sheet and bead preview (geometry-view.md
sections 4, 5; GV-5).

Same GLB / manifest rules as the solid ``paicad view``: one ``<body>`` node per shell part (mid-surface
tessellation, ``_FACE_ID``, double-sided material) + ``<body>.edges``; ``kind: "shell"`` manifest with every
bead feature (``faces.moving`` = bottom + flanks + fillets, ``faces.fixed`` = [base face]) and its dimension
line (depth / width / position, ``value`` = the feature value). With ``--fixed-dir`` the fixed nodes of every
part are a ``<body>.fixed`` point node (``_CLUSTER_ID``, ``_NODE_ID``) and the manifest carries
``fixed_clusters`` (shell_scan clusters + the body and the B-rep faces under the cluster).

``preview`` runs shell update (and ``--fe morph|check``: shell morph / check) in this process, writes the
stage reports in ``update/``, ``morph/``, ``check/`` (same content as the standalone commands, no solver
include or ``files/`` copy is written) and the changed sheet ``preview.glb`` (``_DISP_MM`` = distance to the
same nominal face) + ``preview_fe.glb`` (shell elements, quads split along n1-n3, node displacement).
Exit: 0 OK, 10 update FAIL, 11 morph/check FAIL, 14 view output failure, 2 missing FE arguments, 3 input.
"""

from __future__ import annotations

import time

import numpy as np

from ..common import (
    CODE_CATEGORY,
    EXIT_ARGS,
    EXIT_CAD,
    EXIT_CHECK,
    EXIT_OK,
    EXIT_VIEW,
    OutDir,
    PaicadError,
    Reporter,
    dumps,
    rnd,
    sha256_file,
)
from ..kernel import CadInputError, distance_to_face
from ..meshgeom import point_triangle_distance
from ..view import (
    PREVIEW_FE_GLB,
    PREVIEW_GLB,
    PREVIEW_MANIFEST,
    VIEW_GLB,
    VIEW_MANIFEST,
    BodyTess,
    body_items,
    generator,
    glb_with_lod,
    gltf,
    load_view_options,
    tess_bodies,
)
from ..view import manifest as mf
from ..view.export import ROOT_EXTRAS, bbox_union, body_rows, glb_info, manifest_doc
from ..view.preview import _nominal_ref
from . import opts as shopts
from .beads import Bead, Profile, bead_axes, bead_from_section
from .common import (
    POSITION_TYPES,
    feature_values,
    load_shell_features,
    load_values,
    split_groups,
)

SUBDIRS = ("update", "morph", "check")
MARKER_CUTOFF_MM = 2.0  # fixed node -> B-rep face marker: nearest view triangle within this distance


# ------------------------------------------------------------------ inputs
def _bodies(cad_path, doc: dict) -> tuple[object, list[str], list]:
    from .cad import load

    cad = load(cad_path)
    by = cad.by_name()
    names = [p["body"] for p in doc["parts"]]
    missing = [n for n in names if n not in by]
    if missing:
        raise PaicadError("GEOM_INPUT_INVALID", f"features bodies not in the CAD: {', '.join(missing[:10])}")
    return cad, names, [by[n] for n in names]


def _fixed(fixed_dir):
    if not fixed_dir:
        return None
    from .fixed import load_fixed

    return load_fixed(fixed_dir)


def _source(cad, features_path, fixed) -> dict:
    return {"cad": cad.files, "features_sha256": sha256_file(features_path), "fixed_digest": fixed.digest if fixed is not None else None}


# ------------------------------------------------------------------ bead geometry / dimensions
def _bead_faces(bj: dict) -> tuple[list[str], list[str]]:
    moving = list(bj.get("bottom") or []) + list(bj.get("flanks") or []) + list(bj.get("fillets_top") or []) + list(bj.get("fillets_bottom") or [])
    return moving, [bj["base_face"]]


def bead_geometry(doc: dict, nominal_bodies: list, o: dict, sections: list[dict] | None = None) -> dict[str, tuple[Bead, Profile, np.ndarray]]:
    """{bead id: (nominal bead model, profile, core shift)}: the update's section data for changed beads,
    the recognized nominal bead (same model as ``shell update``) for the others."""
    from .update import match_beads

    out = {bid: (b, b.prof, np.zeros(3)) for bid, (_, b) in match_beads(doc, nominal_bodies, o).items()}
    for sec in sections or []:
        b0, new, shift = bead_from_section(sec)
        nb = out.get(sec["id"], (b0,))[0]
        out[sec["id"]] = (nb, new, shift)
    return out


def bead_dimension(f: dict, bead: Bead, prof: Profile, shift: np.ndarray, body, bbox, value: float, tol: float) -> tuple[dict | None, dict | None]:
    """Dimension line of a bead feature on the (sample) bead: depth = core center on the base plane -> bottom,
    width = across the flanks at half depth, position = foot on the reference edge line (or the proportional
    origin plane) along the axis -> bead center (shell-morph section 6.3 measures)."""
    c = np.asarray(bead.center, dtype=float) + np.asarray(shift, dtype=float)
    ed = np.asarray(bead.ed, dtype=float)
    t = f["type"]
    if t == "BEAD_DEPTH":
        return mf.dimension_from_points("linear", c, c + float(prof.depth) * ed, bbox, value, tol)
    if t == "BEAD_WIDTH":
        try:
            w = float(prof.width())
        except ValueError:
            return None, None
        d = bead.core_dir()
        wd = np.cross(bead.n, d) if d is not None else bead_axes(bead)[1]
        wd = wd / np.linalg.norm(wd)
        mid = c + 0.5 * float(prof.depth) * ed
        return mf.dimension_from_points("linear", mid - 0.5 * w * wd, mid + 0.5 * w * wd, bbox, value, tol)
    if t in POSITION_TYPES:
        r = f.get("ref") or {}
        ax = np.asarray(r.get("axis") or [0.0, 0.0, 0.0], dtype=float)
        if not np.linalg.norm(ax):
            return None, None
        if r.get("rule") == "proportional":
            p0 = c - (float(c @ ax) - float(r.get("origin", 0.0))) * ax
        else:
            q = body.eval_edge(int(str(r["edge"])[1:]), np.array([0.5]))[0]
            p0 = c - float(np.dot(c - q, ax)) * ax
        return mf.dimension_from_points("position", p0, c, bbox, value, tol)
    return None, None


def feature_rows(doc: dict, o: dict, fvalues: dict[str, float], geo: dict | None, body_of: dict, bbox_of: dict) -> tuple[list[dict], list[dict]]:
    param = mf.parameter_of(doc, split_groups(doc, o))
    beads = {b["id"]: b for b in doc["beads"]}
    rows, warns = [], []
    for f in doc["features"]:
        bj = beads.get(f["bead"]) or {}
        moving, fixed = _bead_faces(bj) if bj else ([], [])
        row, _ = mf.feature_entry(f, param[f["name"]], fvalues[f["name"]], moving, fixed, None, None, 0.0)
        if geo is not None and f["bead"] in geo and f["body"] in body_of:
            bead, prof, shift = geo[f["bead"]]
            bb = bbox_of[f["body"]]
            dim, w = bead_dimension(f, bead, prof, shift, body_of[f["body"]], bb, fvalues[f["name"]], shopts.body_tol(o, bb))
            row["dimension"] = dim
            if w:
                warns.append(dict(w, feature=f["name"]))
        rows.append(row)
    return rows, warns


# ------------------------------------------------------------------ fixed markers
def fixed_markers(doc: dict, fixed, tbs: list[BodyTess]) -> tuple[list, list[dict]]:
    """(GLB point nodes ``<body>.fixed``, manifest ``fixed_clusters``): shell_scan clusters with the body
    and the B-rep faces under their nodes (nearest view triangle within ``MARKER_CUTOFF_MM``)."""
    if fixed is None:
        return [], []
    clusters = {int(c["id"]): c for c in (fixed.doc.get("fixed") or {}).get("clusters") or []}
    items, faces_of, body_of = [], {}, {}
    tb_of = {tb.name: tb for tb in tbs}
    for p in doc["parts"]:
        tb = tb_of.get(p["body"])
        sel = np.flatnonzero(fixed.part == int(p["part_id"])) if p.get("part_id") is not None else np.zeros(0, dtype=np.int64)
        if tb is None or not len(sel):
            continue
        order = sel[np.argsort(fixed.node_id[sel], kind="stable")]
        xyz, cl, nid = fixed.xyz[order], fixed.cluster[order], fixed.node_id[order]
        items.append(gltf.PointSet(f"{tb.name}.fixed", xyz, {
            "_CLUSTER_ID": cl.astype(gltf.id_dtype(int(cl.max()) if len(cl) else 0)),
            "_NODE_ID": nid.astype(np.uint32),
        }))
        ti = nearest_triangles(tb.positions[tb.triangles], xyz, MARKER_CUTOFF_MM)
        for k in np.unique(cl):
            hit = (cl == k) & (ti >= 0)
            faces_of.setdefault(int(k), set()).update(int(x) for x in tb.face_ids[ti[hit]])
            body_of.setdefault(int(k), tb.name)
    out = []
    for k in sorted(clusters):
        c = clusters[k]
        out.append({"id": k, "nodes": c.get("nodes"), "center": c.get("center"), "radius_mm": c.get("radius_mm"), "kinds": c.get("kinds"),
                    "body": body_of.get(k), "node": f"{body_of[k]}.fixed" if k in body_of else None, "faces": [f"F{x}" for x in sorted(faces_of.get(k, set()))]})
    return items, out


def nearest_triangles(T: np.ndarray, pts: np.ndarray, cutoff: float) -> np.ndarray:
    """Index of the nearest triangle of ``T[k,3,3]`` for every point within ``cutoff`` (else -1); bounding-box
    prefilter (large planar view triangles make a center KD-tree useless)."""
    lo, hi = T.min(axis=1) - cutoff, T.max(axis=1) + cutoff
    out = np.full(len(pts), -1, dtype=np.int64)
    for i, p in enumerate(pts):
        cand = np.flatnonzero(np.all((lo <= p) & (p <= hi), axis=1))
        if not len(cand):
            continue
        d = point_triangle_distance(np.repeat(p[None, :], len(cand), axis=0), T[cand, 0], T[cand, 1], T[cand, 2])
        k = int(np.argmin(d))
        if d[k] <= cutoff:
            out[i] = int(cand[k])
    return out


def _glb_items(tbs: list[BodyTess], extra: list[dict] | None, markers: list) -> list:
    items = []
    for i, tb in enumerate(tbs):
        items += body_items(tb, extra[i] if extra else None, double_sided=True)
    return items + markers


# ------------------------------------------------------------------ export
def export_run(args, rep: Reporter) -> int:
    vopts = load_view_options(args.view_options)
    o = shopts.load(None)
    out = OutDir(args.out_dir, [VIEW_MANIFEST, VIEW_GLB])
    out.prepare()
    doc = load_shell_features(args.features)
    fixed = _fixed(args.fixed_dir)
    rep.progress(10, "loading mid-surface CAD")
    cad, names, bodies = _bodies(args.cad, doc)
    source = _source(cad, args.features, fixed)
    topos = [b.topology() for b in bodies]
    bbs = [b.summary().bbox for b in bodies]
    rep.progress(30, "tessellating")
    state: dict = {}

    def build(tbs: list[BodyTess]) -> bytes:
        markers, clusters = fixed_markers(doc, fixed, tbs)
        state["clusters"] = clusters
        return gltf.write_glb(_glb_items(tbs, None, markers), generator(), root_extras=ROOT_EXTRAS)

    try:
        data, tbs, used, warnings = glb_with_lod(bodies, names, vopts["tess"], vopts, build)
    except PaicadError as e:
        if not e.code.startswith("VIEW_"):
            raise
        rep.warn(f"{e.code}: {e.message}")
        d = manifest_doc("nominal", "FAIL", e.code, e.message, source, None, dict(vopts["tess"], coarsened=None), bbox_union(bbs), [], [], [], kind="shell")
        out.write_text(VIEW_MANIFEST, dumps(d))
        out.commit([VIEW_MANIFEST])
        rep.result("FAIL", e.code, VIEW_MANIFEST)
        return EXIT_VIEW
    rep.progress(80, "writing manifest")
    rows, w = body_rows(tbs, topos)
    warnings += w
    fvalues = feature_values(doc, o, {})
    geo = bead_geometry(doc, bodies, o)
    feats, fw = feature_rows(doc, o, fvalues, geo, dict(zip(names, bodies)), dict(zip(names, bbs)))
    warnings += fw
    with open(out.tmp_path(VIEW_GLB), "wb") as fh:
        fh.write(data)
    d = manifest_doc("nominal", "OK", None, None, source, glb_info(VIEW_GLB, data, tbs), used, bbox_union(bbs), rows, feats, warnings, kind="shell",
                     fixed_clusters=state.get("clusters"))
    out.write_text(VIEW_MANIFEST, dumps(d))
    out.commit([VIEW_GLB, VIEW_MANIFEST])
    rep.progress(100, f"shell view export done: {d['glb']['triangles']} triangles, {len(data)} bytes")
    rep.result("OK", None, VIEW_MANIFEST)
    return EXIT_OK


# ------------------------------------------------------------------ preview
def fe_items(meshes, elem_ids: dict[int, np.ndarray], titles: dict[int, str], xyz_new: dict[int, np.ndarray], edges: bool) -> list:
    """FE GLB nodes per shell part: ``<title>`` (vertex = node, quads split along n1-n3, n3 = n4 / SH3N = one
    triangle; NORMAL = area-weighted vertex average, ``_DISP_MM`` = node displacement, ``_ELEM_ID`` = smallest
    element id at the node) and ``<title>.edges`` (element edges, no diagonal)."""
    from .tag import mesh_edges

    items: list = []
    for m in meshes:
        if len(m.conn) == 0:
            continue
        q = ~m.tri
        tri = np.concatenate([m.conn[:, [0, 1, 2]], m.conn[q][:, [0, 2, 3]]])
        eid = np.concatenate([elem_ids[m.index], elem_ids[m.index][q]])
        order = np.argsort(np.concatenate([np.arange(len(m.conn)), np.flatnonzero(q)]), kind="stable")  # element order
        tri, eid = tri[order], eid[order]
        used, tl = np.unique(tri, return_inverse=True)
        tl = tl.reshape(-1, 3)
        P = xyz_new[m.index][used]
        D = mf.clean_disp(np.linalg.norm(P - m.xyz[used], axis=1))
        w = np.cross(P[tl[:, 1]] - P[tl[:, 0]], P[tl[:, 2]] - P[tl[:, 0]])
        N = np.zeros_like(P)
        for k in range(3):
            np.add.at(N, tl[:, k], w)
        nn = np.linalg.norm(N, axis=1)
        N = np.where(nn[:, None] > 0, N / np.where(nn > 0, nn, 1.0)[:, None], np.array([0.0, 0.0, 1.0]))
        E = np.full(len(used), np.iinfo(np.int64).max, dtype=np.int64)
        for k in range(3):
            np.minimum.at(E, tl[:, k], eid)
        name = titles[m.index]
        items.append(gltf.TriMesh(name, P, tl, N, {"_DISP_MM": D.astype(np.float32), "_ELEM_ID": E.astype(np.uint32)}, True))
        if edges:
            loc = np.searchsorted(used, m.conn)
            seg = mesh_edges(loc, m.tri)
            items.append(gltf.LineSet(f"{name}.edges", P, seg, {}))
    return items


def _clusters_of(fixed, node_ids) -> list[int]:
    if fixed is None or not len(node_ids):
        return []
    hit = np.isin(fixed.node_id, np.asarray(node_ids, dtype=np.int64))
    return sorted(set(int(x) for x in fixed.cluster[hit]))


def preview_run(args, rep: Reporter) -> int:
    from ..kernel import save_sheet_brep
    from .check import check_core, morphed_coords, tag_distances, thickness_map
    from .check import report as check_report
    from .fixed import part_mesh
    from .morph import MorphFailed, load_mesh_inputs, morph_core, write_files
    from .morph import fail_report as morph_fail_report
    from .morph import ok_report as morph_ok_report
    from .update import FACE_MAP_JSON, SAMPLE_BREP, UPDATE_JSON, face_map, update_core
    from .update import fail_report as update_fail_report
    from .update import ok_report as update_ok_report

    t_start = time.monotonic()
    fe = args.fe
    if fe != "off":
        missing = [n for n, v in (("--assem-dir", args.assem_dir), ("--tag-dir", args.tag_dir), ("--fixed-dir", args.fixed_dir)) if not v]
        if missing:
            rep.warn(f"--fe {fe} requires {', '.join(missing)}")
            return EXIT_ARGS
    vopts = load_view_options(args.view_options)
    o = shopts.load(args.options)
    nominal_ref, tess = _nominal_ref(args.nominal_manifest, vopts)
    out = OutDir(args.out_dir, [PREVIEW_MANIFEST, PREVIEW_GLB, PREVIEW_FE_GLB, *SUBDIRS])
    out.prepare()
    doc = load_shell_features(args.features)
    values = load_values(args.values, doc, o)
    fixed = _fixed(args.fixed_dir)
    if fe != "off":  # every FE input is read before any work (input errors -> exit 3)
        _, tag, fixed, asm, meshes = load_mesh_inputs(args.tag_dir, args.fixed_dir, args.assem_dir)
        thick = thickness_map(asm, args.thickness)
        tag_dist = tag_distances(meshes, tag)
        titles, elem_ids = {}, {}
        title_of = {int(p["part_id"]): p.get("title") for p in doc["parts"] if p.get("part_id") is not None}
        for m in meshes:
            pm = part_mesh(asm, m.part_id)
            if len(pm.elem_ids) != len(m.conn):
                raise PaicadError("GEOM_INPUT_INVALID", f"shell part {m.part_id}: element table differs from the tag mesh")
            elem_ids[m.index] = np.asarray(pm.elem_ids, dtype=np.int64)
            titles[m.index] = title_of.get(m.part_id) or pm.title or f"PART:{m.part_id}"
    rep.progress(10, "loading mid-surface CAD")
    cad, names, nominal = _bodies(args.cad, doc)
    source = _source(cad, args.features, fixed)
    fvalues = feature_values(doc, o, values)
    timing = {"update_s": None, "tess_s": None, "morph_s": None, "check_s": None, "total_s": None}
    reports = {"update": f"update/{UPDATE_JSON}", "morph": None, "check": None}
    rels: list[str] = []
    nominal_bbox = bbox_union([b.summary().bbox for b in nominal])

    def finish(status, code, message, glb, used_tess, bbox, bodies, features, warnings, disp, fe_doc, failure, exit_code, clusters) -> int:
        timing["total_s"] = round(time.monotonic() - t_start, 1)
        d = manifest_doc("preview", status, code, message, source, glb, used_tess, bbox, bodies, features, warnings, kind="shell", fixed_clusters=clusters)
        d.update(values=dict(values), nominal_ref=nominal_ref, disp=disp, fe=fe_doc, reports=reports, failure=failure, timing=timing)
        out.write_text(PREVIEW_MANIFEST, dumps(d))
        out.commit(rels + [PREVIEW_MANIFEST])
        rep.progress(100, f"shell preview {status}")
        rep.result(status, code, PREVIEW_MANIFEST)
        return exit_code

    def fe_off() -> dict:
        return {"mode": "off"} if fe == "off" else {"mode": fe, "status": None, "code": None, "category": None, "glb": None, "max_disp_mm": None, "quality": None}

    changed_feats = [f["name"] for f in doc["features"] if float(fvalues[f["name"]]) != float(f["nominal"])]
    # ---------------- update
    rep.progress(20, "applying bead values")
    t0 = time.monotonic()
    try:
        res = update_core(cad.bodies, doc, values, o, fixed)  # every CAD body, like ``shell update``
    except PaicadError as e:
        if e.exit_code != EXIT_CAD:
            raise
        rep.warn(f"{e.code}: {e.message}")
        timing["update_s"] = round(time.monotonic() - t0, 1)
        out.write_text(f"update/{UPDATE_JSON}", dumps(update_fail_report(e, values, fixed is not None, t0)))
        rels.append(f"update/{UPDATE_JSON}")
        det = e.detail or {}
        coll = [n for c in det.get("collisions") or [] for n in c.get("features") or []]
        items = (det.get("fixed_precheck") or {}).get("items") or []
        feats_fail = sorted(dict.fromkeys(coll)) if coll else (sorted({n for it in items for n in it.get("features") or []}) or changed_feats)
        clusters = sorted({int(c) for it in items for c in it.get("clusters") or []})
        rows, w = feature_rows(doc, o, fvalues, None, {}, {})
        return finish("FAIL", e.code, e.message, None, dict(tess, coarsened=None), nominal_bbox, [], rows, w, None, fe_off(),
                      {"features": feats_fail, "clusters": clusters, "points": []}, EXIT_CAD, [])
    try:
        save_sheet_brep(res.bodies, out.tmp_path(f"update/{SAMPLE_BREP}"))
    except CadInputError as e:
        raise PaicadError(e.code, e.message) from None
    out.write_text(f"update/{FACE_MAP_JSON}", dumps(face_map(res.bodies)))
    out.write_text(f"update/{UPDATE_JSON}", dumps(update_ok_report(res, values, o, t0)))
    rels += [f"update/{SAMPLE_BREP}", f"update/{FACE_MAP_JSON}", f"update/{UPDATE_JSON}"]
    timing["update_s"] = round(time.monotonic() - t0, 1)

    # ---------------- changed sheet GLB with displacement
    rep.progress(50, "tessellating the changed sheet")
    t0 = time.monotonic()
    nom_of = dict(zip(names, nominal))
    # the sample as written and read back (``update/sample.brep``): morph / check see the same B-rep as the
    # standalone commands, which read the update folder
    from .cad import load_sample

    sample = load_sample(out.tmp_path(f"update/{SAMPLE_BREP}"), names)
    sample_of = dict(zip(names, sample))
    state: dict = {}

    def disp_of(tb: BodyTess) -> np.ndarray:
        vface = mf.vertex_faces(len(tb.positions), tb.triangles, tb.face_ids)
        d = np.zeros(len(tb.positions))
        for f in np.unique(vface):
            sel = vface == f
            try:
                d[sel] = distance_to_face(tb.positions[sel], nom_of[tb.name], int(f))  # face map = identity
            except CadInputError as ex:
                raise PaicadError("VIEW_TESSELLATION_FAILED", f"{tb.name}: displacement of F{int(f)}: {ex.message}") from None
        return mf.clean_disp(d)

    markers, clusters = [], []
    if fixed is not None:  # fixed nodes do not move: markers / cluster faces on the nominal sheet (same as export)
        markers, clusters = fixed_markers(doc, fixed, tess_bodies(nominal, names, tess["linear_mm"], tess["angular_deg"], False))

    def build(tbs: list[BodyTess]) -> bytes:
        disps = [disp_of(tb) for tb in tbs]
        state["disp"] = disps
        return gltf.write_glb(_glb_items(tbs, [{"_DISP_MM": d.astype(np.float32)} for d in disps], markers), generator(), root_extras=ROOT_EXTRAS)

    topo_of = {n: b.topology() for n, b in sample_of.items()}
    bbox_of = {n: b.summary().bbox for n, b in sample_of.items()}
    geo = bead_geometry(doc, nominal, o, res.beads)
    try:
        data, tbs, used, warnings = glb_with_lod(sample, names, tess, vopts, build)
    except PaicadError as e:
        if not e.code.startswith("VIEW_"):
            raise
        rep.warn(f"{e.code}: {e.message}")
        timing["tess_s"] = round(time.monotonic() - t0, 1)
        rows, w = feature_rows(doc, o, fvalues, geo, sample_of, bbox_of)
        return finish("FAIL", e.code, e.message, None, dict(tess, coarsened=None), bbox_union(list(bbox_of.values())), [], rows, w, None, fe_off(), None, EXIT_VIEW, [])
    rows_b, w = body_rows(tbs, [topo_of[n] for n in names])
    warnings += w
    by_face = {}
    for tb, d in zip(tbs, state["disp"]):
        ch = res.changed.get(tb.name) or {}
        vface = mf.vertex_faces(len(tb.positions), tb.triangles, tb.face_ids)
        by_face[tb.name] = mf.face_disp_stats(topo_of[tb.name], vface, d, {mf.fid(x) for x in ch.get("geometry") or []}, {mf.fid(x) for x in ch.get("boundary_only") or []})
    max_mm = max((float(d.max()) for d in state["disp"] if d.size), default=0.0)
    disp = {"attribute": "_DISP_MM", "max_mm": rnd(max_mm), "by_face": by_face}
    feats, fw = feature_rows(doc, o, fvalues, geo, sample_of, bbox_of)
    warnings += fw
    with open(out.tmp_path(PREVIEW_GLB), "wb") as fh:
        fh.write(data)
    rels.append(PREVIEW_GLB)
    glb = glb_info(PREVIEW_GLB, data, tbs)
    timing["tess_s"] = round(time.monotonic() - t0, 1)
    bbox = bbox_union(list(bbox_of.values()))
    if fe == "off":
        return finish("OK", None, None, glb, used, bbox, rows_b, feats, warnings, disp, {"mode": "off"}, None, EXIT_OK, clusters)

    # ---------------- FE: shell morph (+ check), coordinates kept in memory, no include written
    rep.progress(65, "morphing the shell mesh")
    t0 = time.monotonic()
    fe_doc: dict = {"mode": fe, "status": None, "code": None, "category": None, "glb": None, "max_disp_mm": None, "quality": None}
    reports["morph"] = "morph/shell_morph.json"
    try:
        mres = morph_core(meshes, sample_of, {"changed": res.changed, "beads": res.beads}, o)
    except MorphFailed as e:
        rep.warn(f"{e.code}: {e.message}")
        out.write_text("morph/shell_morph.json", dumps(morph_fail_report(e, t0)))
        rels.append("morph/shell_morph.json")
        timing["morph_s"] = round(time.monotonic() - t0, 1)
        fe_doc.update(status="FAIL", code=e.code, category=CODE_CATEGORY.get(e.code))
        return finish("FAIL", e.code, e.message, glb, used, bbox, rows_b, feats, warnings, disp, fe_doc,
                      {"features": changed_feats, "clusters": _clusters_of(fixed, e.nodes), "points": []}, EXIT_CHECK, clusters)
    files = write_files(asm, mres.moved, None)  # bytes in memory only (report sha256 / check (f)), never written
    out.write_text("morph/shell_morph.json", dumps(morph_ok_report(mres, files, t0)))
    rels.append("morph/shell_morph.json")
    timing["morph_s"] = round(time.monotonic() - t0, 1)
    fe_doc.update(status="OK", max_disp_mm=rnd(mres.max_disp))
    fdata = [(rel, data_) for rel, data_, _, _, _ in files]
    morphed = morphed_coords(meshes, asm, fdata)  # = coordinates written by the standalone morph
    status, code, message, exit_code, failure = "OK", None, None, EXIT_OK, None
    if fe == "check":
        rep.progress(80, "checking the morphed shell mesh")
        t0 = time.monotonic()
        cres = check_core(meshes, morphed, sample_of, doc, values, res.expected, res.changed, o, asm, thick, {"dist_of": tag_dist}, fdata)
        out.write_text("check/shell_check.json", dumps(check_report(cres, o, [], t0)))
        rels.append("check/shell_check.json")
        reports["check"] = "check/shell_check.json"
        timing["check_s"] = round(time.monotonic() - t0, 1)
        s = cres.summary
        fe_doc.update(
            status=cres.status, code=cres.code, category=CODE_CATEGORY.get(cres.code) if cres.code else None,
            quality={k: s[k] for k in ("max_warpage_deg", "max_skew_deg", "max_aspect", "min_jacobian", "edge_ratio", "dt_ratio")},
        )
        if cres.status != "PASS":
            status, code, message, exit_code = "FAIL", cres.code, cres.message, EXIT_CHECK
            bad = [it["name"] for it in cres.checks["param"]["items"] if it.get("err") is None or it["err"] > it["tol"]]
            pts = []
            wn = cres.checks["deviation"].get("worst_node")
            if cres.code == "GEOM_DEVIATION" and wn is not None:
                for m in meshes:
                    k = np.flatnonzero(m.node_ids == int(wn))
                    if len(k):
                        pts.append({"xyz": [rnd(float(v)) for v in morphed[m.index][k[0]]], "label": f"deviation node {int(wn)}"})
            fids = [int(m.node_ids[i]) for m in meshes for i in np.flatnonzero(m.fixed & np.any(morphed[m.index] != m.xyz, axis=1))]
            failure = {"features": bad or changed_feats, "clusters": _clusters_of(fixed, fids), "points": pts}
    rep.progress(90, "writing the FE GLB")
    fe_data = None
    for edges in ([True, False] if vopts["fe_edges"] else [False]):
        cand = gltf.write_glb(fe_items(meshes, elem_ids, titles, morphed, edges), generator(), root_extras=ROOT_EXTRAS)
        if len(cand) <= vopts["max_glb_bytes"]:
            fe_data = cand
            break
    if fe_data is None:
        msg = f"FE GLB exceeds max_glb_bytes {vopts['max_glb_bytes']}"
        rep.warn(f"VIEW_TOO_LARGE: {msg}")
        if status == "OK":  # the sheet GLB is kept; the FE view alone fails (a check failure keeps its own code)
            status, code, message, exit_code = "FAIL", "VIEW_TOO_LARGE", msg, EXIT_VIEW
            fe_doc.update(status="FAIL", code="VIEW_TOO_LARGE", category="VIEW")
    else:
        with open(out.tmp_path(PREVIEW_FE_GLB), "wb") as fh:
            fh.write(fe_data)
        rels.append(PREVIEW_FE_GLB)
        fe_doc["glb"] = glb_info(PREVIEW_FE_GLB, fe_data, None)
    return finish(status, code, message, glb, used, bbox, rows_b, feats, warnings, disp, fe_doc, failure, exit_code, clusters)


def run(args, rep: Reporter) -> int:
    if args.view_cmd == "export":
        return export_run(args, rep)
    return preview_run(args, rep)
