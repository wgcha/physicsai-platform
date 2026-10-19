"""Shell ``options.json`` (shell-morph section 4.10): defaults, deep merge, range checks, unknown keys rejected."""

from __future__ import annotations

import copy
import json
import math
from pathlib import Path

from ..common import PaicadError

FIXED_KINDS = ("INTER_TYPE2", "RBE2", "RBE3", "RBODY", "BCS", "SHARED")
REQUIRED_KINDS = ("INTER_TYPE2", "RBE2")

DEFAULTS: dict = {
    "schema_version": 1,
    "kind": "shell",
    "tag": {"tol_abs_mm": 0.05, "tol_rel": 1.0e-4, "min_match_ratio": 0.98},
    "fixed": {"kinds": list(FIXED_KINDS), "required": True, "transition_mm": 6.0, "tol_mm": 0.001},
    "morph": {"smoother": "elastic", "poisson": 0.3, "relax_iters": 3, "solver_rtol": 1.0e-8, "solver_maxiter": 5000},
    "quality": {
        "max_warpage_deg": 15.0,
        "max_skew_deg": 60.0,
        "max_aspect": 5.0,
        "min_jacobian": 0.6,
        "min_edge_ratio": 0.8,
        "dt_ratio_min": 0.8,
        "min_edge_mm": None,
        "relative_to_baseline": True,
    },
    "deviation": {"boundary_max_mm": 0.05, "param_abs_mm": 0.05, "param_rel": 0.01},
    "interference": {"product_mm": 0.05},
    "tie": {"default_dsearch_mm": None, "required": True},
    "extract": {
        "range_ratio": 0.05,
        "position_range_mm": 5.0,
        "draft_max_deg": 3.0,
        "min_flank_deg": 10.0,
        "min_depth_mm": 0.5,
        "land_min_mm": 2.0,
        "linear_aspect": 1.2,
    },
    "bead": {"depth_mode": "keep_angle", "position_ref": "nearest_fixed_edge"},
    "symmetry_split": [],
}

_META_KEYS = ("schema_version", "engine", "engine_version", "kind")


def _num(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def _pos(x) -> bool:
    return _num(x) and x > 0


def _merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def unknown_keys(over: dict) -> list[str]:
    bad: list[str] = []
    for k, v in over.items():
        if k in _META_KEYS:
            continue
        if k not in DEFAULTS:
            bad.append(k)
        elif isinstance(DEFAULTS[k], dict) and isinstance(v, dict):
            bad += [f"{k}.{s}" for s in v if s not in DEFAULTS[k]]
    return bad


def validate(o: dict) -> list[str]:
    p: list[str] = []
    t = o["tag"]
    for k in ("tol_abs_mm", "tol_rel"):
        if not _pos(t.get(k)):
            p.append(f"tag.{k} must be a finite number > 0")
    if not (_pos(t.get("min_match_ratio")) and t["min_match_ratio"] <= 1):
        p.append("tag.min_match_ratio must be in (0, 1]")
    f = o["fixed"]
    kinds = f.get("kinds")
    if not isinstance(kinds, list) or any(k not in FIXED_KINDS for k in kinds) or len(set(kinds)) != len(kinds):
        p.append("fixed.kinds must be a list of distinct values from " + ", ".join(FIXED_KINDS))
    elif any(k not in kinds for k in REQUIRED_KINDS):
        p.append("fixed.kinds must include INTER_TYPE2 and RBE2")
    if not isinstance(f.get("required"), bool):
        p.append("fixed.required must be true or false")
    if not (_num(f.get("transition_mm")) and f["transition_mm"] >= 0):
        p.append("fixed.transition_mm must be a finite number >= 0")
    if not _pos(f.get("tol_mm")):
        p.append("fixed.tol_mm must be a finite number > 0")
    m = o["morph"]
    if m.get("smoother") not in ("elastic", "laplacian"):
        p.append("morph.smoother must be elastic or laplacian")
    nu = m.get("poisson")
    if not (_num(nu) and 0 <= nu < 0.5):
        p.append("morph.poisson must be in [0, 0.5)")
    ri = m.get("relax_iters")
    if not (isinstance(ri, int) and not isinstance(ri, bool) and 0 <= ri <= 50):
        p.append("morph.relax_iters must be an integer in [0, 50]")
    if not (_pos(m.get("solver_rtol")) and m["solver_rtol"] < 1):
        p.append("morph.solver_rtol must be in (0, 1)")
    mi = m.get("solver_maxiter")
    if not (isinstance(mi, int) and not isinstance(mi, bool) and mi >= 1):
        p.append("morph.solver_maxiter must be an integer >= 1")
    q = o["quality"]
    if not (_num(q.get("max_warpage_deg")) and 0 <= q["max_warpage_deg"] <= 45):
        p.append("quality.max_warpage_deg must be in [0, 45]")
    if not (_num(q.get("max_skew_deg")) and 0 <= q["max_skew_deg"] <= 90):
        p.append("quality.max_skew_deg must be in [0, 90]")
    if not (_num(q.get("max_aspect")) and q["max_aspect"] >= 1):
        p.append("quality.max_aspect must be >= 1")
    if not (_pos(q.get("min_jacobian")) and q["min_jacobian"] <= 1):
        p.append("quality.min_jacobian must be in (0, 1]")
    for k in ("min_edge_ratio", "dt_ratio_min"):
        if not (_pos(q.get(k)) and q[k] <= 1):
            p.append(f"quality.{k} must be in (0, 1]")
    me = q.get("min_edge_mm")
    if me is not None and not _pos(me):
        p.append("quality.min_edge_mm must be null or a finite number > 0")
    if not isinstance(q.get("relative_to_baseline"), bool):
        p.append("quality.relative_to_baseline must be true or false")
    d = o["deviation"]
    for k in ("boundary_max_mm", "param_abs_mm"):
        if not _pos(d.get(k)):
            p.append(f"deviation.{k} must be a finite number > 0")
    if not (_pos(d.get("param_rel")) and d["param_rel"] <= 1):
        p.append("deviation.param_rel must be in (0, 1]")
    if not (_num(o["interference"].get("product_mm")) and o["interference"]["product_mm"] >= 0):
        p.append("interference.product_mm must be a finite number >= 0")
    tie = o["tie"]
    if tie.get("default_dsearch_mm") is not None and not _pos(tie.get("default_dsearch_mm")):
        p.append("tie.default_dsearch_mm must be null or a finite number > 0")
    if not isinstance(tie.get("required"), bool):
        p.append("tie.required must be true or false")
    e = o["extract"]
    if not (_pos(e.get("range_ratio")) and e["range_ratio"] < 1):
        p.append("extract.range_ratio must be in (0, 1)")
    for k in ("position_range_mm", "min_depth_mm", "land_min_mm"):
        if not _pos(e.get(k)):
            p.append(f"extract.{k} must be a finite number > 0")
    if not (_pos(e.get("draft_max_deg")) and e["draft_max_deg"] <= 90):
        p.append("extract.draft_max_deg must be in (0, 90]")
    if not (_pos(e.get("min_flank_deg")) and e["min_flank_deg"] <= 90):
        p.append("extract.min_flank_deg must be in (0, 90]")
    if not (_num(e.get("linear_aspect")) and e["linear_aspect"] >= 1):
        p.append("extract.linear_aspect must be >= 1")
    b = o["bead"]
    if b.get("depth_mode") not in ("keep_angle", "keep_bottom"):
        p.append("bead.depth_mode must be keep_angle or keep_bottom")
    if b.get("position_ref") not in ("nearest_fixed_edge", "proportional"):
        p.append("bead.position_ref must be nearest_fixed_edge or proportional")
    if not isinstance(o.get("symmetry_split"), list):
        p.append("symmetry_split must be a list")
    return p


def load(path: str | Path | None) -> dict:
    over: dict = {}
    if path:
        try:
            with open(path, encoding="utf-8") as fh:
                over = json.load(fh)
        except (OSError, ValueError) as ex:
            raise PaicadError("GEOM_INPUT_INVALID", f"cannot read options file: {ex.__class__.__name__}") from None
        if not isinstance(over, dict):
            raise PaicadError("GEOM_INPUT_INVALID", "options file must be a JSON object")
        if over.get("schema_version", 1) != 1:
            raise PaicadError("GEOM_INPUT_INVALID", f"unsupported options schema_version: {over.get('schema_version')}")
        if over.get("kind", "shell") != "shell":
            raise PaicadError("GEOM_INPUT_INVALID", f"options kind must be shell, got {over.get('kind')!r}")
    bad = unknown_keys(over)
    if bad:
        raise PaicadError("GEOM_INPUT_INVALID", "invalid options: unknown keys: " + ", ".join(bad))
    over = {k: v for k, v in over.items() if k not in ("engine", "engine_version")}
    probs = [f"{k} must be an object" for k, v in over.items() if isinstance(DEFAULTS.get(k), dict) and not isinstance(v, dict)]
    if probs:
        raise PaicadError("GEOM_INPUT_INVALID", "invalid options: " + "; ".join(probs))
    o = _merge(DEFAULTS, over)
    probs = validate(o)
    if probs:
        raise PaicadError("GEOM_INPUT_INVALID", "invalid options: " + "; ".join(probs))
    return o


def used(o: dict) -> dict:
    """Options as recorded in reports (section 4.10: used values)."""
    return {k: copy.deepcopy(v) for k, v in o.items() if k != "schema_version"}


def body_tol(o: dict, bbox) -> float:
    d = math.dist(bbox[:3], bbox[3:])
    return max(float(o["tag"]["tol_abs_mm"]), float(o["tag"]["tol_rel"]) * d)
