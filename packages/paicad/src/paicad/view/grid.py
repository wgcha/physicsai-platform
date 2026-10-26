"""``paicad view grid`` / ``paicad shell view grid`` - DOE sample thumbnail grid (doe-preview.md section 3).

One process, many value sets ("cells"): the CAD, features and options are read once, the nominal B-rep is
tessellated once (the same GLB as ``view export``, its sha256 in ``grid_manifest.json``) and fixes the common
orthographic camera (center and scale from the nominal B-rep bbox only). Every cell then runs the update of
``view preview --fe off`` (same code, same ``preview_manifest.json`` / ``preview.glb`` bytes apart from
``timing`` and the extra top-level ``thumb`` key) and gets a ``thumb.png`` from the software rasterizer
(``render.render_thumb``: vertex ``_DISP_MM`` colored over the common ``disp_range_mm``; an update FAIL cell
shows the nominal in gray with the faces of ``failure.features`` red). A cell is written in ``cells/.part_<id>``
and renamed to ``cells/<id>`` when complete; one failing cell never stops the next one.

Cell status: OK, FAIL (update failure code, e.g. GEOM_FEATURE_COLLISION - same input = same result), ERROR
(``VIEW_*`` or an internal error of that cell - retried by the platform, never cached).
Exit: 0 every cell processed (whatever the cell status), 3 input errors (``cells.json``, ``thumb_options.json``,
options), 14 nominal tessellation failure (before any cell), 20 internal. ``grid_manifest.json`` exists only on
exit 0.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import time
import traceback
from dataclasses import dataclass
from typing import Callable

import numpy as np

from .. import render
from ..common import CODE_CATEGORY, EXIT_OK, EXIT_VIEW, OutDir, PaicadError, Reporter, dumps, envelope
from . import PREVIEW_MANIFEST, BodyTess, glb_with_lod, tess_bodies
from .export import bbox_union

GRID_MANIFEST = "grid_manifest.json"
CELLS_DIR = "cells"
THUMB_PNG = "thumb.png"
CELL_ID = re.compile(r"[0-9a-z_]{1,64}\Z")

THUMB_DEFAULTS = {
    "schema_version": 1,
    "w": 320,
    "h": 240,
    "view_dir": [1.0, -1.0, 1.0],
    "margin": 1.15,
    "disp_range_mm": [0.0, 1.0],
    "colormap": "turbo16",
    "nominal_ghost": True,
    "edges": False,
}


def _num(x) -> bool:
    return not isinstance(x, bool) and isinstance(x, (int, float)) and math.isfinite(float(x))


def _read(path, what: str):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError) as ex:
        raise PaicadError("GEOM_INPUT_INVALID", f"cannot read {what}: {ex.__class__.__name__}") from None


def load_thumb_options(path) -> dict:
    """``thumb_options.json`` (section 3.3); unknown keys / out-of-range values -> GEOM_INPUT_INVALID."""
    doc = _read(path, "thumb options")
    if not isinstance(doc, dict):
        raise PaicadError("GEOM_INPUT_INVALID", "thumb options must be a JSON object")
    unknown = sorted(set(doc) - set(THUMB_DEFAULTS))
    if unknown:
        raise PaicadError("GEOM_INPUT_INVALID", f"invalid thumb options: unknown keys: {', '.join(unknown)}")
    o = json.loads(json.dumps(THUMB_DEFAULTS))
    o.update(doc)
    probs = []
    if o["schema_version"] != 1:
        probs.append("schema_version must be 1")
    for k in ("w", "h"):
        if not (not isinstance(o[k], bool) and isinstance(o[k], int) and 160 <= o[k] <= 800):
            probs.append(f"{k} must be an integer 160..800")
    vd = o["view_dir"]
    if not (isinstance(vd, list) and len(vd) == 3 and all(_num(x) for x in vd) and math.hypot(*map(float, vd)) > 1e-9):
        probs.append("view_dir must be 3 finite numbers, not all zero")
    if not (_num(o["margin"]) and 1.0 <= float(o["margin"]) <= 2.0):
        probs.append("margin must be in [1.0, 2.0]")
    dr = o["disp_range_mm"]
    if not (isinstance(dr, list) and len(dr) == 2 and all(_num(x) for x in dr) and float(dr[1]) > float(dr[0])):
        probs.append("disp_range_mm must be [lo, hi] with hi > lo")
    if o["colormap"] not in render.COLORMAPS:
        probs.append(f"colormap must be one of {', '.join(sorted(render.COLORMAPS))}")
    for k in ("nominal_ghost", "edges"):
        if not isinstance(o[k], bool):
            probs.append(f"{k} must be true or false")
    if probs:
        raise PaicadError("GEOM_INPUT_INVALID", "invalid thumb options: " + "; ".join(probs))
    o["view_dir"] = [float(x) for x in vd]
    o["margin"] = float(o["margin"])
    o["disp_range_mm"] = [float(x) for x in dr]
    return o


def load_cells(path, validate: Callable[[dict], dict]) -> list[tuple[str, dict]]:
    """``cells.json`` (section 3.2) -> [(id, validated values)]; ``validate`` = the command's ``values_from`` (missing
    names = nominal). Duplicate / malformed ids, unknown names, non-finite values -> GEOM_INPUT_INVALID (exit 3)."""
    doc = _read(path, "cells file")
    if not isinstance(doc, dict) or doc.get("schema_version", 1) != 1 or not isinstance(doc.get("cells"), list) or not doc["cells"]:
        raise PaicadError("GEOM_INPUT_INVALID", "cells file must be {schema_version: 1, cells: [{id, values}, ...]} with at least one cell")
    out, seen = [], set()
    for i, c in enumerate(doc["cells"]):
        cid = c.get("id") if isinstance(c, dict) else None
        if not isinstance(cid, str) or not CELL_ID.match(cid):
            raise PaicadError("GEOM_INPUT_INVALID", f"cell {i}: id must match [0-9a-z_]{{1,64}}")
        if cid in seen:
            raise PaicadError("GEOM_INPUT_INVALID", f"duplicate cell id: {cid}")
        seen.add(cid)
        vals = c.get("values", {})
        if not isinstance(vals, dict):
            raise PaicadError("GEOM_INPUT_INVALID", f"cell {cid}: values must be an object")
        try:
            out.append((cid, validate({"schema_version": 1, "values": vals})))
        except PaicadError as e:
            raise PaicadError(e.code, f"cell {cid}: {e.message}") from None
    return out


class CellReporter(Reporter):
    """Reporter of one cell: everything goes to the grid log only (the grid prints its own progress / RESULT)."""

    def __init__(self, parent: Reporter, cid: str):
        super().__init__(None, stdout=parent.stdout, stderr=parent.stderr)
        self.parent, self.cid = parent, cid

    def log(self, line: str) -> None:
        self.parent.log(f"[{self.cid}] {line}")

    def progress(self, pct: int, msg: str) -> None:
        self.log(f"PAICAD PROGRESS {int(pct)} {msg}")

    def warn(self, msg: str) -> None:
        self.log("WARN " + msg)

    def info(self, msg: str) -> None:
        self.log("INFO " + msg)

    def result(self, status: str, code: str | None, report: str | None) -> None:
        self.log(f"PAICAD RESULT {status} {code or '-'} {report or '-'}")


@dataclass
class GridSpec:
    """The command-specific parts of a grid (solid ``view grid`` / ``shell view grid``)."""

    kind: str
    names: list[str]
    nominal: list  # nominal bodies (features order)
    tess: dict
    vopts: dict
    nominal_build: Callable[[list[BodyTess]], bytes]  # = the ``view export`` GLB of the nominal
    run_cell: Callable  # (values, out, rep, t0, sink) -> exit code (= preview core, fe off)
    fail_faces: Callable[[list[str]], dict[str, set[int]]]  # failing feature names -> {body: face ids}


def camera_digest(cam: render.Camera) -> str:
    key = {"view_dir": cam.view_dir, "center": [float(x) for x in cam.center], "scale": cam.scale, "w": cam.w, "h": cam.h}
    return hashlib.sha256(json.dumps(key, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _lines(tbs: list[BodyTess]) -> list[np.ndarray]:
    return [np.asarray(p, dtype=float) for tb in tbs for _, p in tb.edges]


def _gray_meshes(tbs: list[BodyTess], red: dict[str, set[int]]) -> list[render.ThumbMesh]:
    out = []
    for tb in tbs:
        rgb = np.tile(render.GRAY, (len(tb.triangles), 1))
        bad = red.get(tb.name)
        if bad:
            rgb[np.isin(tb.face_ids, sorted(bad))] = render.FAIL_RED
        out.append(render.ThumbMesh(tb.positions, tb.triangles, rgb=rgb))
    return out


def run_grid(spec: GridSpec, cells: list[tuple[str, dict]], topts: dict, out: OutDir, rep: Reporter, t_start: float) -> int:
    rep.progress(10, "tessellating the nominal")
    try:
        nom_glb, nom_tbs, used, _ = glb_with_lod(spec.nominal, spec.names, spec.tess, spec.vopts, spec.nominal_build)
    except PaicadError as e:
        if not e.code.startswith("VIEW_"):
            raise
        rep.warn(f"{e.code}: {e.message}")
        out.cleanup()
        rep.result("FAIL", e.code, None)
        return EXIT_VIEW
    nominal_bbox = bbox_union([b.summary().bbox for b in spec.nominal])
    cam = render.Camera.fit(nominal_bbox, topts["view_dir"], topts["margin"], topts["w"], topts["h"])
    ghost = None
    if topts["nominal_ghost"]:
        etbs = nom_tbs if spec.vopts["edges"] else tess_bodies(spec.nominal, spec.names, used["linear_mm"], used["angular_deg"], True)
        ghost = _lines(etbs)
    nominal_edges = _lines(nom_tbs) if topts["edges"] else None
    load_s = round(time.monotonic() - t_start, 1)
    cells_dir = out.path / CELLS_DIR
    cells_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for i, (cid, values) in enumerate(cells):
        rep.progress(15 + int(80 * i / len(cells)), f"cell {i + 1}/{len(cells)} {cid}")
        t0 = time.monotonic()
        part = cells_dir / f".part_{cid}"
        crep = CellReporter(rep, cid)
        sink: dict = {}
        try:
            cout = OutDir(part, [PREVIEW_MANIFEST])
            cout.prepare()
            spec.run_cell(values, cout, crep, t0, sink)
            m = sink["manifest"]
            code = m["code"]
            if m["status"] == "OK":
                status = "OK"
                meshes = [render.ThumbMesh(tb.positions, tb.triangles, disp=d) for tb, d in zip(sink["tess"], sink["disp"])]
                edges = _lines(sink["tess"]) if topts["edges"] else None
            else:
                status = "ERROR" if str(code).startswith("VIEW_") else "FAIL"
                red = spec.fail_faces(list((m.get("failure") or {}).get("features") or [])) if status == "FAIL" else {}
                meshes, edges = _gray_meshes(nom_tbs, red), nominal_edges
            img, clipped = render.render_thumb(cam, meshes, topts["disp_range_mm"], topts["colormap"], ghost, edges)
            png = render.png_bytes(img)
            (part / THUMB_PNG).write_bytes(png)
            doc = dict(m, thumb={"file": THUMB_PNG, "sha256": hashlib.sha256(png).hexdigest(), "w": cam.w, "h": cam.h, "clipped": clipped})
            (part / PREVIEW_MANIFEST).write_text(dumps(doc), encoding="utf-8", newline="\n")
            os.replace(part, cells_dir / cid)
            max_disp = (m.get("disp") or {}).get("max_mm") if status == "OK" else None
        except KeyboardInterrupt:
            raise
        except Exception as e:  # noqa: BLE001 - one cell's failure never stops the next cell (section 3.1)
            status, code, max_disp = "ERROR", e.code if isinstance(e, PaicadError) else "GEOM_INTERNAL", None
            rep.warn(f"cell {cid}: {code}: {e.message if isinstance(e, PaicadError) else f'{e.__class__.__name__}: {e}'}")
            rep.log(traceback.format_exc())
            shutil.rmtree(part, ignore_errors=True)
        rows.append({"id": cid, "status": status, "code": code, "category": CODE_CATEGORY.get(code) if code else None, "max_disp_mm": max_disp,
                     "total_s": round(time.monotonic() - t0, 1)})
        rep.info(f"cell {cid}: {status} {code or '-'} ({rows[-1]['total_s']} s)")
    gm = envelope(
        kind=spec.kind,
        camera=dict(cam.doc(), digest=camera_digest(cam)),
        disp_range_mm=list(topts["disp_range_mm"]),
        nominal={"bbox": nominal_bbox, "view_sha256": hashlib.sha256(nom_glb).hexdigest()},
        cells=rows,
        timing={"load_s": load_s, "total_s": round(time.monotonic() - t_start, 1)},
    )
    out.write_text(GRID_MANIFEST, dumps(gm))
    out.commit([GRID_MANIFEST])
    n = {s: sum(r["status"] == s for r in rows) for s in ("OK", "FAIL", "ERROR")}
    rep.progress(100, f"grid done: {n['OK']} OK, {n['FAIL']} FAIL, {n['ERROR']} ERROR")
    rep.result("OK", None, GRID_MANIFEST)
    return EXIT_OK


# ------------------------------------------------------------------ solid entry
def run(args, rep: Reporter) -> int:
    from .. import options
    from ..update import contacts_from_tag, load_features, nominal_cad, values_from
    from . import body_items, generator, gltf, load_view_options
    from .export import ROOT_EXTRAS, source_of
    from .preview import PreviewInputs, _nominal_ref, preview_core

    t_start = time.monotonic()
    vopts = load_view_options(args.view_options)
    gopts = options.load(args.options)
    topts = load_thumb_options(args.thumb_options)
    nominal_ref, tess = _nominal_ref(None, vopts)
    out = OutDir(args.out_dir, [GRID_MANIFEST, CELLS_DIR])
    out.prepare()
    doc = load_features(args.features)
    cells = load_cells(args.cells, lambda v: values_from(v, doc, gopts))
    contacts = contacts_from_tag(args.tag_dir, doc)
    rep.progress(5, "loading nominal CAD")
    cad, nominal = nominal_cad(args.cad, doc, args.body_map)
    names = [b["body"] for b in doc["bodies"]]
    ctx = PreviewInputs("off", vopts, gopts, nominal_ref, tess, doc, contacts, nominal, names, source_of(cad, args.features))
    fm = {f["name"]: f for f in doc["features"]}

    def fail_faces(feats: list[str]) -> dict[str, set[int]]:
        red: dict[str, set[int]] = {}
        for n in feats:
            f = fm.get(n)
            if f is not None:
                red.setdefault(f["body"], set()).update(int(str(x)[1:]) for x in (f.get("faces") or {}).get("moving") or [])
        return red

    def build(tbs: list[BodyTess]) -> bytes:
        return gltf.write_glb([it for tb in tbs for it in body_items(tb)], generator(), root_extras=ROOT_EXTRAS)

    spec = GridSpec("solid", names, nominal, tess, vopts, build, lambda values, o, r, t0, sink: preview_core(ctx, values, o, r, t0, sink), fail_faces)
    return run_grid(spec, cells, topts, out, rep, t_start)
