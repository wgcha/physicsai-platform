"""``paicad view`` - 3D view of the nominal B-rep and parameter preview (geometry-view.md).

* ``view export``  -> ``view.glb`` + ``view_manifest.json`` (nominal B-rep, solid bodies)
* ``view preview`` -> ``preview.glb`` (+ ``preview_fe.glb``) + ``preview_manifest.json`` (update only by
  default; ``--fe morph|check`` adds the morphed FE skin; no solver include is ever written)
* ``view grid``    -> per cell (value set) the ``view preview --fe off`` outputs + ``thumb.png`` (common camera and
  color range), ``grid_manifest.json`` (doe-preview.md section 3)

View options are a separate file ``view_options.json`` (``--view-options``, GV-4); the geometry
``options.json`` schema is unchanged. Tessellation, edge discretization and face distances go through
the ``paicad.kernel`` interface only (contract section 18.9).
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .. import __version__
from ..common import PaicadError
from ..kernel import BodyGeom, CadInputError, edge_polylines, tessellate
from . import gltf

VIEW_GLB = "view.glb"
VIEW_MANIFEST = "view_manifest.json"
PREVIEW_GLB = "preview.glb"
PREVIEW_FE_GLB = "preview_fe.glb"
PREVIEW_MANIFEST = "preview_manifest.json"

DEFAULTS = {
    "schema_version": 1,
    "tess": {"linear_mm": 0.1, "angular_deg": 20.0},
    "max_triangles": 500000,
    "max_glb_bytes": 16777216,
    "coarsen_steps": 3,
    "edges": True,
    "fe_edges": True,
}
_TOP_KEYS = set(DEFAULTS) | {"engine", "engine_version"}
ANGULAR_MAX = 45.0


def generator() -> str:
    return f"paicad {__version__}"


def _is_num(x) -> bool:
    return not isinstance(x, bool) and isinstance(x, (int, float)) and math.isfinite(float(x))


def _is_int(x) -> bool:
    return not isinstance(x, bool) and isinstance(x, int)


def load_view_options(path: str | Path | None) -> dict:
    """``view_options.json`` (section 4.5): unknown keys and out-of-range values -> GEOM_INPUT_INVALID."""
    opts = json.loads(json.dumps(DEFAULTS))
    if not path:
        return opts
    try:
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
    except (OSError, ValueError) as ex:
        raise PaicadError("GEOM_INPUT_INVALID", f"cannot read view options: {ex.__class__.__name__}") from None
    if not isinstance(doc, dict):
        raise PaicadError("GEOM_INPUT_INVALID", "view options must be a JSON object")
    unknown = sorted(set(doc) - _TOP_KEYS)
    if isinstance(doc.get("tess"), dict):
        unknown += sorted(f"tess.{k}" for k in set(doc["tess"]) - set(DEFAULTS["tess"]))
    if unknown:
        raise PaicadError("GEOM_INPUT_INVALID", f"invalid view options: unknown keys: {', '.join(unknown)}")
    if doc.get("schema_version", 1) != 1:
        raise PaicadError("GEOM_INPUT_INVALID", "invalid view options: schema_version must be 1")
    probs = []
    if "tess" in doc:
        if not isinstance(doc["tess"], dict):
            probs.append("tess must be an object")
        else:
            opts["tess"].update(doc["tess"])
    for k in ("max_triangles", "max_glb_bytes", "coarsen_steps", "edges", "fe_edges"):
        if k in doc:
            opts[k] = doc[k]
    lin, ang = opts["tess"]["linear_mm"], opts["tess"]["angular_deg"]
    if not (_is_num(lin) and 0 < float(lin) <= 10):
        probs.append("tess.linear_mm must be in (0, 10]")
    if not (_is_num(ang) and 5 <= float(ang) <= ANGULAR_MAX):
        probs.append("tess.angular_deg must be in [5, 45]")
    if not (_is_int(opts["max_triangles"]) and opts["max_triangles"] >= 1000):
        probs.append("max_triangles must be an integer >= 1000")
    if not (_is_int(opts["max_glb_bytes"]) and opts["max_glb_bytes"] > 0):
        probs.append("max_glb_bytes must be an integer > 0")
    if not (_is_int(opts["coarsen_steps"]) and 0 <= opts["coarsen_steps"] <= 5):
        probs.append("coarsen_steps must be an integer 0..5")
    for k in ("edges", "fe_edges"):
        if not isinstance(opts[k], bool):
            probs.append(f"{k} must be true or false")
    if probs:
        raise PaicadError("GEOM_INPUT_INVALID", "invalid view options: " + "; ".join(probs))
    opts["tess"] = {"linear_mm": float(lin), "angular_deg": float(ang)}
    return opts


# ------------------------------------------------------------------ body tessellation + LOD
@dataclass
class BodyTess:
    name: str
    positions: np.ndarray
    normals: np.ndarray
    triangles: np.ndarray
    face_ids: np.ndarray
    edges: list  # [(edge id, points[k,3])]


def tess_bodies(bodies: list[BodyGeom], names: list[str], linear_mm: float, angular_deg: float, edges: bool) -> list[BodyTess]:
    out = []
    for name, b in zip(names, bodies):
        try:
            p, n, t, f = tessellate(b, linear_mm, angular_deg)
            e = edge_polylines(b, linear_mm, angular_deg) if edges else []
        except CadInputError as ex:
            raise PaicadError("VIEW_TESSELLATION_FAILED" if not ex.code.startswith("VIEW_") else ex.code, f"{name}: {ex.message}") from None
        out.append(BodyTess(name, np.asarray(p, float), np.asarray(n, float), np.asarray(t, np.int64), np.asarray(f, np.int64), e))
    return out


def body_items(tb: BodyTess, extra: dict[str, np.ndarray] | None = None, double_sided: bool = False) -> list:
    """GLB nodes of one body: ``<body>`` (faces, ``_FACE_ID``) and ``<body>.edges`` (``_EDGE_ID``) if edges."""
    attrs = {"_FACE_ID": None}
    vf = np.zeros(len(tb.positions), dtype=np.int64)
    for k in range(3):
        vf[tb.triangles[:, k]] = tb.face_ids
    attrs["_FACE_ID"] = vf.astype(gltf.id_dtype(int(vf.max()) if len(vf) else 0))
    for k, v in (extra or {}).items():
        attrs[k] = v
    items: list = [gltf.TriMesh(tb.name, tb.positions, tb.triangles, tb.normals, attrs, double_sided)]
    if tb.edges:
        pos, seg, ids = gltf.polylines(tb.edges)
        if len(seg):
            items.append(gltf.LineSet(f"{tb.name}.edges", pos, seg, {"_EDGE_ID": ids.astype(gltf.id_dtype(int(ids.max())))}))
    return items


def glb_with_lod(bodies: list[BodyGeom], names: list[str], tess: dict, vopts: dict, build) -> tuple[bytes, list[BodyTess], dict, list[dict]]:
    """Tessellate, build the GLB with ``build(tess list) -> bytes``; over ``max_triangles`` or
    ``max_glb_bytes`` -> double linear/angular (angle capped at 45) up to ``coarsen_steps`` times
    (VIEW_COARSENED), then VIEW_TOO_LARGE. Returns (glb, tessellations, used tess, warnings)."""
    lin, ang = float(tess["linear_mm"]), float(tess["angular_deg"])
    for k in range(int(vopts["coarsen_steps"]) + 1):
        tbs = tess_bodies(bodies, names, lin, ang, bool(vopts["edges"]))
        ntri = sum(len(t.triangles) for t in tbs)
        data = build(tbs) if ntri <= vopts["max_triangles"] else None
        if data is not None and len(data) <= vopts["max_glb_bytes"]:
            used = {"linear_mm": lin, "angular_deg": ang, "coarsened": k}
            warns = []
            if k:
                warns.append({"code": "VIEW_COARSENED", "coarsened": k, "message": f"tessellation tolerances enlarged {k} time(s) to fit the size limits (linear {lin:g} mm, angular {ang:g} deg)"})
            return data, tbs, used, warns
        if k < int(vopts["coarsen_steps"]):
            lin, ang = lin * 2.0, min(ANGULAR_MAX, ang * 2.0)
    size = f"{ntri} triangles" if data is None else f"{len(data)} bytes"
    raise PaicadError("VIEW_TOO_LARGE", f"view exceeds the size limits after {int(vopts['coarsen_steps'])} coarsening step(s): {size} (max_triangles {vopts['max_triangles']}, max_glb_bytes {vopts['max_glb_bytes']})")


def run(args, rep) -> int:
    if args.view_cmd == "export":
        from .export import run as export_run

        return export_run(args, rep)
    if args.view_cmd == "grid":
        from .grid import run as grid_run

        return grid_run(args, rep)
    from .preview import run as preview_run

    return preview_run(args, rep)
