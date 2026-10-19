"""options.json (contract section 4.9): defaults, deep merge, range checks used by paicad."""

from __future__ import annotations

import copy
import json
import math
from pathlib import Path

from .common import PaicadError

DEFAULTS: dict = {
    "schema_version": 1,
    "tag": {"tol_abs_mm": 0.05, "tol_rel": 1.0e-4, "min_match_ratio": 0.98, "contact_mm": 0.1, "contact_min_ratio": 0.2},
    "morph": {"poisson": 0.3, "solver_rtol": 1.0e-8, "solver_maxiter": 5000},
    # min_edge_mm: optional absolute floor (None = off); min_edge_ratio / dt_ratio_min are relative to the baseline mesh
    "quality": {"min_stretch": 0.1, "max_aspect": 10.0, "min_edge_mm": None, "min_edge_ratio": 0.8, "dt_ratio_min": 0.8, "relative_to_baseline": True},
    "deviation": {"boundary_max_mm": 0.05, "param_abs_mm": 0.05, "param_rel": 0.01},
    "interference": {"body_mm": 0.01, "product_mm": 0.05},
    "tie": {"default_dsearch_mm": None, "required": True},
    "thickness_ref": "contact_fixed",
    "thickness_ref_overrides": {},
    "symmetry_split": [],
    # hole position parameters keep their distance to the nearest fixed face (or scale with the body length)
    "position_ref": "nearest_fixed",
    # extract tuning (section 6.2 defaults; optional section, absent in platform-written files is fine)
    # position_range_mm: default value range of position parameters (HOLE_POS_U/V) = nominal +- this many mm
    "extract": {"draft_max_deg": 3.0, "overlap_min": 0.5, "range_ratio": 0.05, "position_range_mm": 5.0, "sample_grid": 12},
}


def _merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def _pos(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) and x > 0


def validate(opts: dict) -> list[str]:
    p: list[str] = []
    t = opts["tag"]
    for k in ("tol_abs_mm", "tol_rel", "contact_mm"):
        if not _pos(t.get(k)):
            p.append(f"tag.{k} must be a finite number > 0")
    for k in ("min_match_ratio", "contact_min_ratio"):
        v = t.get(k)
        if not (_pos(v) and v <= 1):
            p.append(f"tag.{k} must be in (0, 1]")
    if opts.get("thickness_ref") not in ("contact_fixed", "larger_area_fixed"):
        p.append("thickness_ref must be contact_fixed or larger_area_fixed")
    if not isinstance(opts.get("thickness_ref_overrides"), dict):
        p.append("thickness_ref_overrides must be an object")
    if not isinstance(opts.get("symmetry_split"), list):
        p.append("symmetry_split must be a list")
    q = opts["quality"]
    if not (_pos(q.get("min_stretch")) and q["min_stretch"] <= 1):
        p.append("quality.min_stretch must be in (0, 1]")
    if not (_pos(q.get("max_aspect")) and q["max_aspect"] >= 1):
        p.append("quality.max_aspect must be >= 1")
    me = q.get("min_edge_mm")
    if me is not None and not (_pos(me) or (isinstance(me, (int, float)) and not isinstance(me, bool) and me == 0)):
        p.append("quality.min_edge_mm must be null or a finite number >= 0")
    for k in ("min_edge_ratio", "dt_ratio_min"):
        if not (_pos(q.get(k)) and q[k] <= 1):
            p.append(f"quality.{k} must be in (0, 1]")
    if not isinstance(q.get("relative_to_baseline"), bool):
        p.append("quality.relative_to_baseline must be true or false")
    if opts.get("position_ref") not in ("nearest_fixed", "proportional"):
        p.append("position_ref must be nearest_fixed or proportional")
    e = opts["extract"]
    if not (_pos(e.get("draft_max_deg")) and e["draft_max_deg"] < 45):
        p.append("extract.draft_max_deg must be in (0, 45)")
    if not (_pos(e.get("overlap_min")) and e["overlap_min"] <= 1):
        p.append("extract.overlap_min must be in (0, 1]")
    if not (_pos(e.get("range_ratio")) and e["range_ratio"] < 1):
        p.append("extract.range_ratio must be in (0, 1)")
    if not _pos(e.get("position_range_mm")):
        p.append("extract.position_range_mm must be a finite number > 0")
    if not (isinstance(e.get("sample_grid"), int) and 4 <= e["sample_grid"] <= 64):
        p.append("extract.sample_grid must be an integer in [4, 64]")
    return p


def load(path: str | Path | None) -> dict:
    over: dict = {}
    if path:
        try:
            with open(path, encoding="utf-8") as f:
                over = json.load(f)
        except (OSError, ValueError) as ex:
            raise PaicadError("GEOM_INPUT_INVALID", f"cannot read options file: {ex.__class__.__name__}") from None
        if not isinstance(over, dict):
            raise PaicadError("GEOM_INPUT_INVALID", "options file must be a JSON object")
        if over.get("schema_version", 1) != 1:
            raise PaicadError("GEOM_INPUT_INVALID", f"unsupported options schema_version: {over.get('schema_version')}")
    opts = _merge(DEFAULTS, {k: v for k, v in over.items() if k not in ("engine", "engine_version")})
    probs = validate(opts)
    if probs:
        raise PaicadError("GEOM_INPUT_INVALID", "invalid options: " + "; ".join(probs))
    return opts


def body_tol(opts: dict, bbox) -> float:
    """tol = max(tol_abs_mm, tol_rel * L_body) with L_body = bbox diagonal (section 6)."""
    d = math.dist(bbox[:3], bbox[3:])
    return max(float(opts["tag"]["tol_abs_mm"]), float(opts["tag"]["tol_rel"]) * d)
