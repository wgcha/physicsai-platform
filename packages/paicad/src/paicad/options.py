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
    # position_range_mm: default value range of position parameters (HOLE_POS_U/V, RIB_POS_U/V) = nominal +- this many mm
    # extract.filter (optional, not a default - extract-filter.md section 4): types to find + conditions, see validate_filter
    "extract": {"draft_max_deg": 3.0, "overlap_min": 0.5, "range_ratio": 0.05, "position_range_mm": 5.0, "sample_grid": 12},
    # paicad map (multi-baseline matching, section 11.4): score weights, position sigma, grade bounds, axis gate
    "map": {"weights": {"pos": 0.35, "dim": 0.30, "ori": 0.15, "nbr": 0.20}, "sigma": 0.1, "accept": 0.7, "warn": 0.5, "axis_deg": 10.0},
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
    m = opts["morph"]
    nu = m.get("poisson")
    if not (isinstance(nu, (int, float)) and not isinstance(nu, bool) and math.isfinite(nu) and 0 <= nu < 0.5):
        p.append("morph.poisson must be in [0, 0.5)")
    if not (_pos(m.get("solver_rtol")) and m["solver_rtol"] < 1):
        p.append("morph.solver_rtol must be in (0, 1)")
    if not (isinstance(m.get("solver_maxiter"), int) and not isinstance(m["solver_maxiter"], bool) and m["solver_maxiter"] >= 1):
        p.append("morph.solver_maxiter must be an integer >= 1")
    q = opts["quality"]
    if not (_pos(q.get("min_stretch")) and q["min_stretch"] <= 1):
        p.append("quality.min_stretch must be in (0, 1]")
    if not (_pos(q.get("max_aspect")) and q["max_aspect"] >= 1):
        p.append("quality.max_aspect must be >= 1")
    me = q.get("min_edge_mm")
    if me is not None and not _pos(me):
        p.append("quality.min_edge_mm must be null or a finite number > 0")
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
    mp = opts["map"]
    w = mp.get("weights")
    if not isinstance(w, dict) or set(w) != {"pos", "dim", "ori", "nbr"}:
        p.append("map.weights must be an object with keys pos, dim, ori, nbr")
    else:
        fin = all(isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) and x >= 0 for x in w.values())
        if not fin or sum(w.values()) <= 0:
            p.append("map.weights must be finite numbers >= 0 with a positive sum")
    if not _pos(mp.get("sigma")):
        p.append("map.sigma must be a finite number > 0")
    if not (_pos(mp.get("warn")) and _pos(mp.get("accept")) and mp["warn"] <= mp["accept"] <= 1):
        p.append("map.warn / map.accept must satisfy 0 < warn <= accept <= 1")
    if not (_pos(mp.get("axis_deg")) and mp["axis_deg"] < 90):
        p.append("map.axis_deg must be in (0, 90)")
    return p


# keys allowed in an options file besides the DEFAULTS tree: platform metadata (section 4.9 / 17.3)
_META_KEYS = ("schema_version", "engine", "engine_version")
# contract section 4.9 places position_range_mm at the top level; paicad keeps it in the extract section
_TOP_ALIASES = {"position_range_mm": ("extract", "position_range_mm")}
# sections whose values are free-form maps (keys = parameter names), not checked against DEFAULTS
_FREE_SECTIONS = ("thickness_ref_overrides",)


# optional ``rib_gap`` section (rib-gap.md section 2.2, RIB_PITCH rows): not merged into the options when absent (outputs
# that copy or hash the options stay byte-identical); read with :func:`rib_gap_options`
RIB_GAP_DEFAULTS = {"anchor": "center", "min_gap_mm": 1.0, "slender_min": 1.5, "overlap_min": 0.5}
RIB_GAP_ANCHORS = ("center", "first", "last")


def validate_rib_gap(sec) -> list[str]:
    if sec is None:
        return []
    if not isinstance(sec, dict):
        return ["rib_gap must be an object"]
    p = [f"rib_gap.{k}: unknown key" for k in sec if k not in RIB_GAP_DEFAULTS]
    if sec.get("anchor", "center") not in RIB_GAP_ANCHORS:
        p.append("rib_gap.anchor must be center, first or last")
    if not _pos(sec.get("min_gap_mm", 1.0)):
        p.append("rib_gap.min_gap_mm must be a finite number > 0")
    v = sec.get("slender_min", 1.5)
    if not (_num(v) and v >= 1):
        p.append("rib_gap.slender_min must be a finite number >= 1")
    v = sec.get("overlap_min", 0.5)
    if not (_pos(v) and v <= 1):
        p.append("rib_gap.overlap_min must be in (0, 1]")
    return p


def rib_gap_options(opts: dict) -> dict:
    """``rib_gap`` section of loaded options merged over :data:`RIB_GAP_DEFAULTS`."""
    return {**RIB_GAP_DEFAULTS, **(opts.get("rib_gap") or {})}


# optional ``asm_match`` section (asm-match.md section 6.2, ``paicad asm``): not merged into the options (outputs that copy
# the options stay byte-identical); read with :func:`asm_options`
ASM_DEFAULTS = {"max_parts": 5000, "recommend_min_score": 0.6, "worst_nodes": 2000}


def validate_asm(sec) -> list[str]:
    if sec is None:
        return []
    if not isinstance(sec, dict):
        return ["asm_match must be an object"]
    p = [f"asm_match.{k}: unknown key" for k in sec if k not in ASM_DEFAULTS]
    for k in ("max_parts", "worst_nodes"):
        v = sec.get(k, ASM_DEFAULTS[k])
        if not (isinstance(v, int) and not isinstance(v, bool) and v >= 1):
            p.append(f"asm_match.{k} must be an integer >= 1")
    v = sec.get("recommend_min_score", ASM_DEFAULTS["recommend_min_score"])
    if not (_num(v) and 0 <= v <= 1):
        p.append("asm_match.recommend_min_score must be in [0, 1]")
    return p


def asm_options(path: str | Path | None) -> dict:
    """``asm_match`` section of an options file merged over :data:`ASM_DEFAULTS` (validated by :func:`load`)."""
    out = dict(ASM_DEFAULTS)
    if path:
        load(path)
        with open(path, encoding="utf-8") as f:
            sec = json.load(f).get("asm_match")
        out.update(sec or {})
    return out


def unknown_keys(over: dict) -> list[str]:
    """Dotted names of keys that are not options (typos must not be ignored silently)."""
    bad: list[str] = []
    for k, v in over.items():
        if k in _META_KEYS or k in _TOP_ALIASES or k in ("asm_match", "rib_gap"):
            continue
        if k not in DEFAULTS:
            bad.append(k)
        elif isinstance(DEFAULTS[k], dict) and k not in _FREE_SECTIONS and isinstance(v, dict):
            bad += [f"{k}.{s}" for s in v if s not in DEFAULTS[k] and (k, s) not in _OPTIONAL_KEYS]
    return bad


# optional keys outside DEFAULTS (absent = feature off; not merged into the options so outputs that hash or copy
# the options stay byte-identical when the key is absent)
_OPTIONAL_KEYS = {("extract", "filter")}

# extract.filter (extract-filter.md section 4): feature types paicad knows (TYPE_ORDER of features.py, kept here so
# options does not import the recognizer) and the condition keys
FILTER_TYPES = (
    "THICKNESS",
    "POCKET_DEPTH",
    "POCKET_WIDTH",
    "RIB_THICKNESS",
    "RIB_HEIGHT",
    "HOLE_RADIUS",
    "HOLE_POS_U",
    "HOLE_POS_V",
    "FILLET_RADIUS",
    "RIB_POS_U",
    "RIB_POS_V",
    "RIB_PITCH_U",  # rib-gap.md RG-1 (EF-C3: 13 types)
    "RIB_PITCH_V",
)
FILTER_RANGE_KEYS = ("thickness_mm", "height_mm")
FILTER_MIN_KEYS = ("face_area_min_mm2", "position_min_size_mm", "hole_radius_min_mm", "fillet_radius_min_mm")
FILTER_KEYS = ("types",) + FILTER_RANGE_KEYS + FILTER_MIN_KEYS


def _num(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def validate_filter(flt) -> list[str]:
    """Problems of an ``extract.filter`` object (section 4.4); None = no filter (valid)."""
    if flt is None:
        return []
    if not isinstance(flt, dict):
        return ["extract.filter must be an object or null"]
    p: list[str] = []
    bad = [k for k in flt if k not in FILTER_KEYS]
    if bad:
        p.append("extract.filter: unknown keys: " + ", ".join(f"extract.filter.{k}" for k in bad))
    types = flt.get("types")
    if not isinstance(types, list) or not types:
        p.append("extract.filter.types must be a non-empty list of feature types")
    else:
        unknown = [str(t) for t in types if t not in FILTER_TYPES]
        if unknown:
            p.append("extract.filter.types: unknown feature types: " + ", ".join(unknown))
        if len(set(map(str, types))) != len(types):
            p.append("extract.filter.types must not contain duplicates")
    for k in FILTER_RANGE_KEYS:
        r = flt.get(k)
        if r is None:
            continue
        if not isinstance(r, dict):
            p.append(f"extract.filter.{k} must be an object {{min, max}} or null")
            continue
        badr = [s for s in r if s not in ("min", "max")]
        if badr:
            p.append(f"extract.filter.{k}: unknown keys: " + ", ".join(f"extract.filter.{k}.{s}" for s in badr))
        lo, hi = r.get("min"), r.get("max")
        if lo is not None and not (_num(lo) and lo >= 0):
            p.append(f"extract.filter.{k}.min must be null or a finite number >= 0")
            lo = None
        if hi is not None and not (_num(hi) and hi > 0):
            p.append(f"extract.filter.{k}.max must be null or a finite number > 0")
            hi = None
        if lo is not None and hi is not None and lo > hi:
            p.append(f"extract.filter.{k}: min > max")
    for k in FILTER_MIN_KEYS:
        v = flt.get(k)
        if v is not None and not _pos(v):
            p.append(f"extract.filter.{k} must be null or a finite number > 0")
    return p


def load(path: str | Path | None, keep_filter: bool = False) -> dict:
    """Options with defaults. ``extract.filter`` is validated for every command; it stays in the result
    (``opts["extract"]["filter"]``, absent when not given or null) only with ``keep_filter`` (extract) - the other
    commands read the same file and ignore it (extract-filter.md section 4.4)."""
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
    bad = unknown_keys(over)
    if bad:
        raise PaicadError("GEOM_INPUT_INVALID", "invalid options: unknown keys: " + ", ".join(bad))
    probs = validate_asm(over.get("asm_match")) + validate_rib_gap(over.get("rib_gap"))
    if probs:
        raise PaicadError("GEOM_INPUT_INVALID", "invalid options: " + "; ".join(probs))
    rib_gap = copy.deepcopy(over.get("rib_gap"))
    over = {k: v for k, v in over.items() if k not in ("engine", "engine_version", "asm_match", "rib_gap")}
    for alias, (sec, key) in _TOP_ALIASES.items():
        if alias in over:
            v = over.pop(alias)
            sec_over = over.get(sec)
            if isinstance(sec_over, dict) and key in sec_over and sec_over[key] != v:
                raise PaicadError("GEOM_INPUT_INVALID", f"invalid options: {alias} and {sec}.{key} disagree")
            over[sec] = {**(sec_over if isinstance(sec_over, dict) else {}), key: v}
    probs = [f"{k} must be an object" for k, v in over.items() if isinstance(DEFAULTS.get(k), dict) and k not in _FREE_SECTIONS and not isinstance(v, dict)]
    if probs:
        raise PaicadError("GEOM_INPUT_INVALID", "invalid options: " + "; ".join(probs))
    flt = None
    if isinstance(over.get("extract"), dict) and "filter" in over["extract"]:
        flt = copy.deepcopy(over["extract"]["filter"])
        over = dict(over, extract={k: v for k, v in over["extract"].items() if k != "filter"})
    opts = _merge(DEFAULTS, over)
    probs = validate(opts) + validate_filter(flt)
    if probs:
        raise PaicadError("GEOM_INPUT_INVALID", "invalid options: " + "; ".join(probs))
    if keep_filter and flt is not None:
        opts["extract"]["filter"] = flt
    if rib_gap is not None:  # kept only when given (absent = defaults, options copies unchanged)
        opts["rib_gap"] = rib_gap
    return opts


def body_tol(opts: dict, bbox) -> float:
    """tol = max(tol_abs_mm, tol_rel * L_body) with L_body = bbox diagonal (section 6)."""
    d = math.dist(bbox[:3], bbox[3:])
    return max(float(opts["tag"]["tol_abs_mm"]), float(opts["tag"]["tol_rel"]) * d)
