"""``paicad view preview`` - parameter preview (geometry-view.md sections 4.3, 4.4, 5.2).

update (push/pull, same code as ``paicad update``) -> changed B-rep ``preview.glb`` with ``_DISP_MM``
(distance of every vertex to the same nominal face, section 4.4); ``--fe morph|check`` adds morph (and
check) on the baseline mesh and ``preview_fe.glb`` (tetra skin, morphed coordinates). Everything runs
in this process. Stage reports keep their usual format in ``update/``, ``morph/``, ``check/``;
no solver include (``morphed.inc``, ``--out-inc``, ``files/``) is ever written. Failure codes of the
stages are passed through unchanged (``GEOM_*``). Exit: 0 OK, 10 update FAIL, 11 morph/check FAIL,
14 view output failure, 2 missing FE arguments, 3 input errors.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np

from .. import options
from ..check import CHECK_JSON, check_core, expected_measures
from ..check import report as check_report
from ..common import CODE_CATEGORY, EXIT_ARGS, EXIT_CAD, EXIT_CHECK, EXIT_OK, EXIT_VIEW, OutDir, PaicadError, Reporter, dumps, rnd
from ..kernel import CadInputError, distance_to_face, save_brep
from ..mesh.radioss import _TET_FACES, read_renum_csv
from ..meshdata import components_from_tag, load_tag
from ..meshsrc import mesh_args, open_source
from ..morph import MORPH_JSON, MorphFailed, load_sample, morph_core, read_baseline
from ..morph import fail_report as morph_fail_report
from ..morph import ok_report as morph_ok_report
from ..update import (
    FACE_MAP_JSON,
    SAMPLE_BREP,
    UPDATE_JSON,
    contacts_from_tag,
    feature_values,
    load_features,
    load_values,
    nominal_cad,
    split_groups,
    update_core,
)
from ..update import fail_report as update_fail_report
from ..update import ok_report as update_ok_report
from . import PREVIEW_FE_GLB, PREVIEW_GLB, PREVIEW_MANIFEST, BodyTess, body_items, generator, glb_with_lod, gltf, load_view_options
from . import manifest as mf
from .export import ROOT_EXTRAS, bbox_union, body_rows, glb_info, manifest_doc, source_of

SUBDIRS = ("update", "morph", "check")


def _nominal_ref(path: str | None, vopts: dict) -> tuple[dict, dict]:
    """(``nominal_ref``, tessellation tolerances): from the nominal ``view_manifest.json`` when given."""
    if not path:
        t = dict(vopts["tess"])
        return {"view_sha256": None, "tess": t}, t
    try:
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
        t = {"linear_mm": float(doc["tess"]["linear_mm"]), "angular_deg": float(doc["tess"]["angular_deg"])}
        sha = (doc.get("glb") or {}).get("sha256")
    except (OSError, ValueError, KeyError, TypeError) as ex:
        raise PaicadError("GEOM_INPUT_INVALID", f"cannot read the nominal view manifest: {ex.__class__.__name__}") from None
    if doc.get("status") != "OK" or not (t["linear_mm"] > 0 and t["angular_deg"] > 0):
        raise PaicadError("GEOM_INPUT_INVALID", "nominal view manifest is not an OK manifest with tessellation tolerances")
    return {"view_sha256": sha, "tess": t}, t


def skin_elements(c) -> np.ndarray:
    """Element id of every skin triangle of a component (same order as ``Comp.skin``)."""
    if len(c.tets) == 0:
        return np.zeros(0, dtype=np.int64)
    faces = c.tets[:, _TET_FACES].reshape(-1, 3)
    _, inv, cnt = np.unique(np.sort(faces, axis=1), axis=0, return_inverse=True, return_counts=True)
    keep = cnt[inv.ravel()] == 1
    if not np.array_equal(faces[keep], c.skin):
        raise PaicadError("GEOM_INTERNAL", f"{c.part}: skin triangles do not match the tag components")
    return c.elem_ids[np.flatnonzero(keep) // 4]


def fe_items(comps, xyz_base: np.ndarray, xyz_new: np.ndarray, edges: bool) -> list:
    """FE skin GLB nodes: ``<part>`` (vertex = node, shared; NORMAL = area-weighted vertex average,
    ``_DISP_MM`` = node displacement, ``_ELEM_ID`` = smallest skin element id at the node) and
    ``<part>.edges`` (skin element edges)."""
    items: list = []
    for c in comps:
        if len(c.skin) == 0:
            continue
        elem = skin_elements(c)
        used, tri = np.unique(c.skin, return_inverse=True)
        tri = tri.reshape(-1, 3)
        g = c.gidx[used]
        P = xyz_new[g]
        D = mf.clean_disp(np.linalg.norm(xyz_new[g] - xyz_base[g], axis=1))
        w = np.cross(P[tri[:, 1]] - P[tri[:, 0]], P[tri[:, 2]] - P[tri[:, 0]])
        N = np.zeros_like(P)
        for k in range(3):
            np.add.at(N, tri[:, k], w)
        nn = np.linalg.norm(N, axis=1)
        N = np.where(nn[:, None] > 0, N / np.where(nn > 0, nn, 1.0)[:, None], np.array([0.0, 0.0, 1.0]))
        E = np.full(len(used), np.iinfo(np.int64).max, dtype=np.int64)
        for k in range(3):
            np.minimum.at(E, tri[:, k], elem)
        items.append(gltf.TriMesh(c.part, P, tri, N, {"_DISP_MM": D.astype(np.float32), "_ELEM_ID": E.astype(np.uint32)}, False))
        if edges:
            seg = np.unique(np.sort(np.concatenate([tri[:, [0, 1]], tri[:, [1, 2]], tri[:, [2, 0]]]), axis=1), axis=0)
            items.append(gltf.LineSet(f"{c.part}.edges", P, seg, {}))
    return items


def _changed_features(doc: dict, fvalues: dict[str, float]) -> list[str]:
    return [f["name"] for f in doc["features"] if float(fvalues[f["name"]]) != float(f["nominal"])]


def _collision_features(doc: dict, fvalues: dict[str, float], names: list[str]) -> list[str]:
    """Features of the collision report reduced to one entry per colliding feature geometry: features that
    share the same faces (a hole's radius / U / V) are represented by the changed one(s)."""
    fm = {f["name"]: f for f in doc["features"]}
    groups: dict[tuple, list[str]] = {}
    for n in dict.fromkeys(names):
        f = fm.get(n)
        key = (f["body"], frozenset((f.get("measure") or {}).get("faces") or [])) if f else (n,)
        groups.setdefault(key, []).append(n)
    out = []
    for ns in groups.values():
        ch = [n for n in ns if n in fm and float(fvalues[n]) != float(fm[n]["nominal"])]
        out += ch or ns
    return out


def _faces_of(f: dict, applied: dict[str, dict]) -> tuple[list[str], list[str]]:
    a = applied.get(f["name"])
    if a is not None:
        return list(a.get("moved") or []), list(a.get("fixed") or [])
    fc = f.get("faces") or {}
    return list(fc.get("moving") or []), list(fc.get("fixed") or [])


def run(args, rep: Reporter) -> int:
    t_start = time.monotonic()
    fe = args.fe
    asm = bool(getattr(args, "asm_match", None))
    if fe != "off":
        need = (("--asm-match", args.asm_match),) if asm else (("--baseline-inc", args.baseline_inc), ("--renum-csv", args.renum_csv))
        missing = [n for n, v in (*need, ("--assem-dir", args.assem_dir), ("--tag-dir", args.tag_dir)) if not v]
        if missing:
            rep.warn(f"--fe {fe} requires {', '.join(missing)}")
            return EXIT_ARGS
    vopts = load_view_options(args.view_options)
    gopts = options.load(args.options)
    nominal_ref, tess = _nominal_ref(args.nominal_manifest, vopts)
    out = OutDir(args.out_dir, [PREVIEW_MANIFEST, PREVIEW_GLB, PREVIEW_FE_GLB, *SUBDIRS])
    out.prepare()
    doc = load_features(args.features)
    values = load_values(args.values, doc, gopts)
    contacts = contacts_from_tag(args.tag_dir, doc)
    src = None
    if fe != "off":  # every FE input is read before any work (input errors -> exit 3)
        if mesh_args(args, ("baseline_inc", "renum_csv")) == "M":
            src = open_source(args)
            mesh = src.mesh
            comps = components_from_tag(mesh, load_tag(args.tag_dir))
            if sorted(r["body"] for r in src.match.rows) != sorted(c.part for c in comps):
                raise PaicadError("GEOM_INPUT_INVALID", "assembly match rows do not match the tag parts")
        else:
            _, mesh = read_baseline(args.baseline_inc)
            comps = components_from_tag(mesh, load_tag(args.tag_dir))
            renum = read_renum_csv(args.renum_csv)
            if sorted(r.part for r in renum) != sorted(c.part for c in comps):
                raise PaicadError("GEOM_INPUT_INVALID", "renumber table parts do not match the tag parts")
    rep.progress(10, "loading nominal CAD")
    cad, nominal = nominal_cad(args.cad, doc, args.body_map)
    names = [b["body"] for b in doc["bodies"]]
    source = source_of(cad, args.features)
    fvalues = feature_values(doc, gopts, values)
    param = mf.parameter_of(doc, split_groups(doc, gopts))
    timing = {"update_s": None, "tess_s": None, "morph_s": None, "check_s": None, "total_s": None}
    reports = {"update": f"update/{UPDATE_JSON}", "morph": None, "check": None}
    rels: list[str] = []

    def features_rows(topo_of: dict | None, bbox_of: dict | None, applied: dict[str, dict]) -> tuple[list, list]:
        rows, warns = [], []
        for f in doc["features"]:
            mv, fx = _faces_of(f, applied)
            topo = topo_of.get(f["body"]) if topo_of else None
            bb = bbox_of.get(f["body"]) if bbox_of else None
            row, w = mf.feature_entry(f, param[f["name"]], fvalues[f["name"]], mv, fx, topo, bb, options.body_tol(gopts, bb) if bb is not None else 0.0)
            rows.append(row)
            warns += w
        return rows, warns

    def finish(status, code, message, glb, used_tess, bbox, bodies, features, warnings, disp, fe_doc, failure, exit_code) -> int:
        timing["total_s"] = round(time.monotonic() - t_start, 1)
        d = manifest_doc("preview", status, code, message, source, glb, used_tess, bbox, bodies, features, warnings)
        d.update(values=dict(values), nominal_ref=nominal_ref, disp=disp, fe=fe_doc, reports=reports, failure=failure, timing=timing)
        out.write_text(PREVIEW_MANIFEST, dumps(d))
        out.commit(rels + [PREVIEW_MANIFEST])
        rep.progress(100, f"preview {status}")
        rep.result(status, code, PREVIEW_MANIFEST)
        return exit_code

    # ---------------- update
    rep.progress(20, "applying push/pull")
    t0 = time.monotonic()
    try:
        res = update_core(nominal, doc, values, contacts, gopts)
    except PaicadError as e:
        if e.exit_code != EXIT_CAD:
            raise
        rep.warn(f"{e.code}: {e.message}")
        timing["update_s"] = round(time.monotonic() - t0, 1)
        out.write_text(f"update/{UPDATE_JSON}", dumps(update_fail_report(e, values, t0)))
        rels.append(f"update/{UPDATE_JSON}")
        coll = [n for c in (e.detail or {}).get("collisions") or [] for n in c.get("features") or []]
        feats_fail = _collision_features(doc, fvalues, coll) if coll else _changed_features(doc, fvalues)
        rows, w = features_rows(None, None, {})
        fe_doc = {"mode": "off"} if fe == "off" else {"mode": fe, "status": None, "code": None, "category": None, "glb": None, "max_disp_mm": None, "quality": None}
        return finish(
            "FAIL", e.code, e.message, None, dict(tess, coarsened=None), bbox_union([b.summary().bbox for b in nominal]), [], rows, w, None, fe_doc,
            {"features": feats_fail, "clusters": [], "points": []}, EXIT_CAD,
        )
    try:
        save_brep(res.bodies, out.tmp_path(f"update/{SAMPLE_BREP}"))
    except CadInputError as e:
        raise PaicadError(e.code, e.message) from None
    out.write_text(f"update/{FACE_MAP_JSON}", dumps(res.face_map))
    out.write_text(f"update/{UPDATE_JSON}", dumps(update_ok_report(res, doc, values, t0)))
    rels += [f"update/{SAMPLE_BREP}", f"update/{FACE_MAP_JSON}", f"update/{UPDATE_JSON}"]
    timing["update_s"] = round(time.monotonic() - t0, 1)

    # ---------------- changed B-rep GLB with displacement
    rep.progress(50, "tessellating the changed B-rep")
    t0 = time.monotonic()
    nom_of = dict(zip(names, nominal))
    state: dict = {}

    def disp_of(tb: BodyTess) -> np.ndarray:
        vface = mf.vertex_faces(len(tb.positions), tb.triangles, tb.face_ids)
        fmap = res.face_map[tb.name]["F"]
        inv = {int(v): int(k) for k, v in fmap.items()}
        d = np.zeros(len(tb.positions))
        for f in np.unique(vface):
            sel = vface == f
            try:
                d[sel] = distance_to_face(tb.positions[sel], nom_of[tb.name], inv.get(int(f), int(f)))
            except CadInputError as ex:
                raise PaicadError("VIEW_TESSELLATION_FAILED", f"{tb.name}: displacement of F{int(f)}: {ex.message}") from None
        return mf.clean_disp(d)

    def build(tbs: list[BodyTess]) -> bytes:
        disps = [disp_of(tb) for tb in tbs]
        state["disp"] = disps
        items = [it for tb, d in zip(tbs, disps) for it in body_items(tb, {"_DISP_MM": d.astype(np.float32)})]
        return gltf.write_glb(items, generator(), root_extras=ROOT_EXTRAS)

    topo_of = {n: b.topology() for n, b in zip(names, res.bodies)}
    bbox_of = {n: b.summary().bbox for n, b in zip(names, res.bodies)}
    applied = {a["name"]: a for a in res.applied}
    try:
        data, tbs, used, warnings = glb_with_lod(res.bodies, names, tess, vopts, build)
    except PaicadError as e:
        if not e.code.startswith("VIEW_"):
            raise
        rep.warn(f"{e.code}: {e.message}")
        timing["tess_s"] = round(time.monotonic() - t0, 1)
        rows, w = features_rows(topo_of, bbox_of, applied)
        fe_doc = {"mode": "off"} if fe == "off" else {"mode": fe, "status": None, "code": None, "category": None, "glb": None, "max_disp_mm": None, "quality": None}
        return finish("FAIL", e.code, e.message, None, dict(tess, coarsened=None), bbox_union(list(bbox_of.values())), [], rows, w, None, fe_doc, None, EXIT_VIEW)
    rows_b, w = body_rows(tbs, [topo_of[n] for n in names])
    warnings += w
    moved: dict[str, set[int]] = {n: set() for n in names}
    for a in res.applied:
        if a.get("delta"):
            moved.setdefault(a["body"], set()).update(mf.fid(x) for x in a.get("moved") or [])
    by_face = {}
    for tb, d in zip(tbs, state["disp"]):
        vface = mf.vertex_faces(len(tb.positions), tb.triangles, tb.face_ids)
        by_face[tb.name] = mf.face_disp_stats(topo_of[tb.name], vface, d, moved.get(tb.name, set()), mf.boundary_changed(nom_of[tb.name].topology(), topo_of[tb.name]))
    max_mm = max((float(d.max()) for d in state["disp"] if d.size), default=0.0)
    disp = {"attribute": "_DISP_MM", "max_mm": rnd(max_mm), "by_face": by_face}
    feats, fw = features_rows(topo_of, bbox_of, applied)
    warnings += fw
    with open(out.tmp_path(PREVIEW_GLB), "wb") as fh:
        fh.write(data)
    rels.append(PREVIEW_GLB)
    glb = glb_info(PREVIEW_GLB, data, tbs)
    timing["tess_s"] = round(time.monotonic() - t0, 1)
    bbox = bbox_union(list(bbox_of.values()))
    if fe == "off":
        return finish("OK", None, None, glb, used, bbox, rows_b, feats, warnings, disp, {"mode": "off"}, None, EXIT_OK)

    # ---------------- FE: morph (+ check), coordinates kept in memory, no include written
    rep.progress(65, "morphing the baseline mesh")
    t0 = time.monotonic()
    fe_doc: dict = {"mode": fe, "status": None, "code": None, "category": None, "glb": None, "max_disp_mm": None, "quality": None}
    sample = load_sample(out.tmp / "update", doc)
    reports["morph"] = f"morph/{MORPH_JSON}"
    try:
        mres = morph_core(mesh, comps, sample, gopts)
    except MorphFailed as e:
        rep.warn(f"{e.code}: {e.message}")
        out.write_text(f"morph/{MORPH_JSON}", dumps(morph_fail_report(e, t0)))
        rels.append(f"morph/{MORPH_JSON}")
        timing["morph_s"] = round(time.monotonic() - t0, 1)
        fe_doc.update(status="FAIL", code=e.code, category=CODE_CATEGORY.get(e.code))
        return finish("FAIL", e.code, e.message, glb, used, bbox, rows_b, feats, warnings, disp, fe_doc, {"features": _changed_features(doc, fvalues), "clusters": [], "points": []}, EXIT_CHECK)
    out.write_text(f"morph/{MORPH_JSON}", dumps(morph_ok_report(mres, t0)))
    rels.append(f"morph/{MORPH_JSON}")
    timing["morph_s"] = round(time.monotonic() - t0, 1)
    fe_doc.update(status="OK", max_disp_mm=rnd(mres.max_disp))
    status, code, message, exit_code, failure = "OK", None, None, EXIT_OK, None
    if fe == "check":
        rep.progress(80, "checking the morphed mesh")
        t0 = time.monotonic()
        cres = check_core(
            mesh, mres.xyz, comps, sample, doc, values, gopts, args.assem_dir, None if src is not None else Path(args.baseline_inc), expected=expected_measures(out.tmp / "update"), src=src
        )
        out.write_text(f"check/{CHECK_JSON}", dumps(check_report(cres, gopts, None, t0)))
        rels.append(f"check/{CHECK_JSON}")
        reports["check"] = f"check/{CHECK_JSON}"
        timing["check_s"] = round(time.monotonic() - t0, 1)
        s = cres.summary
        fe_doc.update(
            status=cres.status, code=cres.code, category=CODE_CATEGORY.get(cres.code) if cres.code else None,
            quality={"min_stretch": s["min_stretch"], "max_aspect": s["max_aspect"], "edge_ratio": s["edge_ratio"], "dt_ratio": s["dt_ratio"]},
        )
        if cres.status != "PASS":
            status, code, message, exit_code = "FAIL", cres.code, cres.message, EXIT_CHECK
            bad = [it["name"] for it in cres.checks["param"]["items"] if it.get("status") == "FAIL"]
            failure = {"features": bad or _changed_features(doc, fvalues), "clusters": [], "points": []}
    rep.progress(90, "writing the FE skin GLB")
    fe_data = None
    for edges in ([True, False] if vopts["fe_edges"] else [False]):
        cand = gltf.write_glb(fe_items(comps, mesh.xyz, mres.xyz, edges), generator(), root_extras=ROOT_EXTRAS)
        if len(cand) <= vopts["max_glb_bytes"]:
            fe_data = cand
            break
    if fe_data is None:
        msg = f"FE skin GLB exceeds max_glb_bytes {vopts['max_glb_bytes']}"
        rep.warn(f"VIEW_TOO_LARGE: {msg}")
        if status == "OK":  # the geometry GLB is kept; the FE view alone fails (a check failure keeps its own code)
            status, code, message, exit_code = "FAIL", "VIEW_TOO_LARGE", msg, EXIT_VIEW
            fe_doc.update(status="FAIL", code="VIEW_TOO_LARGE", category="VIEW")
    else:
        with open(out.tmp_path(PREVIEW_FE_GLB), "wb") as fh:
            fh.write(fe_data)
        rels.append(PREVIEW_FE_GLB)
        fe_doc["glb"] = glb_info(PREVIEW_FE_GLB, fe_data, None)
    return finish(status, code, message, glb, used, bbox, rows_b, feats, warnings, disp, fe_doc, failure, exit_code)
