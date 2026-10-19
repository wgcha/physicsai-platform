"""native 형상 옵션 `options.json`(geometry-engine.md §4.9): 기본값 병합·범위 검사·사용값 문서.

유효 옵션 = `geometry.defaults`(설정) ← `param_sets.geom_options`(세트 덮어쓰기, 부분 객체) 깊은 병합.
범위 위반은 API 422 `GEOM_OPTIONS_INVALID`(problems 목록). paicad도 같은 범위를 다시 검사한다(모르는 키 거부 포함).
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from typing import Any

# 코드 기본값 = 계약 §7.1 예시 + paicad 0.5.0이 받는 나머지 키(extract·position_ref·thickness_ref_overrides·symmetry_split).
# 설정 `geometry.defaults`는 이 위에 깊은 병합된다.
DEFAULT_OPTIONS: dict[str, Any] = {
    "tag": {"tol_abs_mm": 0.05, "tol_rel": 1.0e-4, "min_match_ratio": 0.98, "contact_mm": 0.1, "contact_min_ratio": 0.2},
    "morph": {"poisson": 0.3, "solver_rtol": 1.0e-8, "solver_maxiter": 5000},
    "quality": {"min_stretch": 0.1, "max_aspect": 10.0, "min_edge_ratio": 0.8, "dt_ratio_min": 0.8, "min_edge_mm": None,
                "relative_to_baseline": True},
    "deviation": {"boundary_max_mm": 0.05, "param_abs_mm": 0.05, "param_rel": 0.01},
    "interference": {"body_mm": 0.01, "product_mm": 0.05},
    "tie": {"default_dsearch_mm": None, "required": True},
    "extract": {"draft_max_deg": 3.0, "overlap_min": 0.5, "range_ratio": 0.05, "position_range_mm": 5.0, "sample_grid": 12},
    # 단계 4B 매칭 점수(§11.4, paicad 0.6.0 `map` 절): 가중치·σ·표시 등급 경계(accept·warn)·주축 각도
    "map": {"weights": {"pos": 0.35, "dim": 0.30, "ori": 0.15, "nbr": 0.20}, "sigma": 0.1, "accept": 0.7, "warn": 0.5, "axis_deg": 10.0},
    "thickness_ref": "contact_fixed",
    "position_ref": "nearest_fixed",
    "thickness_ref_overrides": {},
    "symmetry_split": [],
}
OPTION_SECTIONS = ("tag", "morph", "quality", "deviation", "interference", "tie", "extract", "map")
OPTION_SCALARS = ("thickness_ref", "position_ref", "thickness_ref_overrides", "symmetry_split")
FREE_SECTIONS = ("thickness_ref_overrides",)
META_KEYS = ("schema_version", "engine", "engine_version")
TOP_ALIASES = {"position_range_mm": ("extract", "position_range_mm")}  # 계약 §4.9 위치(최상위) → paicad 0.5.0 위치(extract 하위)
# 고급 옵션 UI에서 바꾸는 절(§4.9) — 화면 안내용 상수
UI_SECTIONS = ("quality", "position_ref", "extract.position_range_mm", "interference", "deviation", "tie.required")
FACE_RE = re.compile(r"F[0-9]+")


def deep_merge(base: dict[str, Any], over: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict) and k not in FREE_SECTIONS:
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def _problem(key: str, message: str) -> dict[str, str]:
    return {"code": "GEOM_OPTIONS_INVALID", "key": key, "message": message}


def _pos(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) and x > 0


def _is_int(x: Any) -> bool:
    return isinstance(x, int) and not isinstance(x, bool)


def normalize_override(over: Any) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """부분 객체(`param_sets.geom_options`·설정 defaults) 모양 검사·정규화. (정규화 dict, problems).
    최상위 `position_range_mm`은 `extract.position_range_mm`으로 옮긴다(둘이 다르면 problem). engine·engine_version·
    schema_version은 입력에 올 수 없다(사용값 문서에만 둔다 — §4.9)."""
    probs: list[dict[str, str]] = []
    if over is None:
        return {}, probs
    if not isinstance(over, dict):
        return {}, [_problem("(root)", "옵션은 객체여야 합니다")]
    out: dict[str, Any] = {}
    for k, v in over.items():
        if k in META_KEYS:
            probs.append(_problem(k, f"'{k}'는 옵션으로 보낼 수 없습니다(사용값 기록 전용)"))
        elif k in TOP_ALIASES:
            sec, key = TOP_ALIASES[k]
            cur = out.setdefault(sec, {})
            if key in cur and cur[key] != v:
                probs.append(_problem(k, f"{k}와 {sec}.{key}가 서로 다릅니다"))
            cur[key] = v
        elif k in OPTION_SECTIONS:
            if not isinstance(v, dict):
                probs.append(_problem(k, f"'{k}'는 객체여야 합니다"))
                continue
            bad = [s for s in v if s not in DEFAULT_OPTIONS[k]]
            probs += [_problem(f"{k}.{s}", "알 수 없는 옵션 키입니다") for s in bad]
            out[k] = {**out.get(k, {}), **v}
        elif k in OPTION_SCALARS:
            out[k] = v
        else:
            probs.append(_problem(k, "알 수 없는 옵션 키입니다"))
    return out, probs


def validate_options(opts: dict[str, Any]) -> list[dict[str, str]]:
    """병합된 전체 옵션의 값 범위(§4.9). 문제 목록(빈 목록 = 정상)."""
    p: list[dict[str, str]] = []
    add = lambda k, m: p.append(_problem(k, m))  # noqa: E731
    t = opts.get("tag") or {}
    for k in ("tol_abs_mm", "tol_rel", "contact_mm"):
        if not _pos(t.get(k)):
            add(f"tag.{k}", "0보다 큰 유한한 숫자여야 합니다")
    for k in ("min_match_ratio", "contact_min_ratio"):
        if not (_pos(t.get(k)) and t[k] <= 1):
            add(f"tag.{k}", "0 초과 1 이하여야 합니다")
    m = opts.get("morph") or {}
    nu = m.get("poisson")
    if not (isinstance(nu, (int, float)) and not isinstance(nu, bool) and math.isfinite(nu) and 0 <= nu < 0.5):
        add("morph.poisson", "0 이상 0.5 미만이어야 합니다")
    if not (_pos(m.get("solver_rtol")) and m["solver_rtol"] < 1):
        add("morph.solver_rtol", "0 초과 1 미만이어야 합니다")
    if not (_is_int(m.get("solver_maxiter")) and m["solver_maxiter"] >= 1):
        add("morph.solver_maxiter", "1 이상의 정수여야 합니다")
    q = opts.get("quality") or {}
    if not (_pos(q.get("min_stretch")) and q["min_stretch"] <= 1):
        add("quality.min_stretch", "0 초과 1 이하여야 합니다")
    if not (_pos(q.get("max_aspect")) and q["max_aspect"] >= 1):
        add("quality.max_aspect", "1 이상이어야 합니다")
    me = q.get("min_edge_mm")
    if me is not None and not _pos(me):
        add("quality.min_edge_mm", "null(미사용) 또는 0보다 큰 숫자여야 합니다")
    for k in ("min_edge_ratio", "dt_ratio_min"):
        if not (_pos(q.get(k)) and q[k] <= 1):
            add(f"quality.{k}", "0 초과 1 이하여야 합니다")
    if not isinstance(q.get("relative_to_baseline"), bool):
        add("quality.relative_to_baseline", "true 또는 false여야 합니다")
    d = opts.get("deviation") or {}
    for k in ("boundary_max_mm", "param_abs_mm", "param_rel"):
        if not _pos(d.get(k)):
            add(f"deviation.{k}", "0보다 큰 유한한 숫자여야 합니다")
    i = opts.get("interference") or {}
    for k in ("body_mm", "product_mm"):
        if not _pos(i.get(k)):
            add(f"interference.{k}", "0보다 큰 유한한 숫자여야 합니다")
    tie = opts.get("tie") or {}
    ds = tie.get("default_dsearch_mm")
    if ds is not None and not _pos(ds):
        add("tie.default_dsearch_mm", "null 또는 0보다 큰 숫자여야 합니다")
    if not isinstance(tie.get("required"), bool):
        add("tie.required", "true 또는 false여야 합니다")
    e = opts.get("extract") or {}
    if not (_pos(e.get("draft_max_deg")) and e["draft_max_deg"] < 45):
        add("extract.draft_max_deg", "0 초과 45 미만이어야 합니다")
    if not (_pos(e.get("overlap_min")) and e["overlap_min"] <= 1):
        add("extract.overlap_min", "0 초과 1 이하여야 합니다")
    if not (_pos(e.get("range_ratio")) and e["range_ratio"] < 1):
        add("extract.range_ratio", "0 초과 1 미만이어야 합니다")
    if not _pos(e.get("position_range_mm")):
        add("extract.position_range_mm", "0보다 큰 유한한 숫자여야 합니다")
    if not (_is_int(e.get("sample_grid")) and 4 <= e["sample_grid"] <= 64):
        add("extract.sample_grid", "4~64 정수여야 합니다")
    mp = opts.get("map") or {}
    w = mp.get("weights")
    if not isinstance(w, dict) or set(w) != {"pos", "dim", "ori", "nbr"}:
        add("map.weights", "pos·dim·ori·nbr 네 키의 객체여야 합니다")
    elif not all(isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) and x >= 0 for x in w.values()) \
            or sum(w.values()) <= 0:
        add("map.weights", "0 이상 유한한 숫자이고 합이 0보다 커야 합니다")
    if not _pos(mp.get("sigma")):
        add("map.sigma", "0보다 큰 유한한 숫자여야 합니다")
    if not (_pos(mp.get("warn")) and _pos(mp.get("accept")) and mp["warn"] <= mp["accept"] <= 1):
        add("map.accept", "0 < warn ≤ accept ≤ 1 이어야 합니다")
    if not (_pos(mp.get("axis_deg")) and mp["axis_deg"] < 90):
        add("map.axis_deg", "0 초과 90 미만이어야 합니다")
    if opts.get("thickness_ref") not in ("contact_fixed", "larger_area_fixed"):
        add("thickness_ref", "contact_fixed | larger_area_fixed")
    if opts.get("position_ref") not in ("nearest_fixed", "proportional"):
        add("position_ref", "nearest_fixed | proportional")
    ov = opts.get("thickness_ref_overrides")
    if not isinstance(ov, dict) or not all(isinstance(k, str) and isinstance(v, str) and FACE_RE.fullmatch(v) for k, v in ov.items()):
        add("thickness_ref_overrides", "{파라미터 이름: 고정할 면 F<번호>} 객체여야 합니다")
    ss = opts.get("symmetry_split")
    if not isinstance(ss, list) or not all(isinstance(x, str) for x in ss):
        add("symmetry_split", "그룹 id 문자열 목록이어야 합니다")
    return p


def effective_options(defaults: dict[str, Any] | None, geom_options: dict[str, Any] | None = None
                      ) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """(유효 옵션, problems). 코드 기본값 ← 설정 defaults ← 세트 덮어쓰기. problems가 있으면 옵션은 신뢰하지 않는다."""
    base, probs = normalize_override(defaults)
    over, p2 = normalize_override(geom_options)
    probs = probs + p2
    opts = deep_merge(deep_merge(DEFAULT_OPTIONS, base), over)
    return opts, probs + validate_options(opts)


def check_against_features(opts: dict[str, Any], features_doc: dict[str, Any]) -> list[dict[str, str]]:
    """`thickness_ref_overrides` = 그 피처 쌍의 면, `symmetry_split` = 존재하는 그룹 id (extract 결과가 있을 때만 검사 가능)."""
    probs: list[dict[str, str]] = []
    feats = {f.get("name"): f for f in features_doc.get("features", []) if isinstance(f, dict)}
    for name, face in (opts.get("thickness_ref_overrides") or {}).items():
        f = feats.get(name)
        if f is None:
            probs.append(_problem(f"thickness_ref_overrides.{name}", "피처 이름이 없습니다"))
            continue
        fc = f.get("faces") or {}
        pair = list(fc.get("moving") or []) + list(fc.get("fixed") or [])
        if face not in pair:
            probs.append(_problem(f"thickness_ref_overrides.{name}", f"{face}는 이 피처 쌍의 면이 아닙니다({', '.join(pair)})"))
    groups = {g.get("id") for g in features_doc.get("groups", []) if isinstance(g, dict)}
    for gid in opts.get("symmetry_split") or []:
        if gid not in groups:
            probs.append(_problem("symmetry_split", f"존재하지 않는 그룹 id: {gid}"))
    return probs


def usage_document(opts: dict[str, Any], engine_version: str | None) -> dict[str, Any]:
    """`P/geom/options.json`·`R/options.json`·`D/native/options_run.json` 사용값(§4.9): 최상위 engine·engine_version 포함.
    paicad 0.5.0은 최상위 engine·engine_version을 받는다(무시)."""
    return {"schema_version": 1, "engine": "native", "engine_version": engine_version, **copy.deepcopy(opts)}


def paicad_document(opts: dict[str, Any]) -> dict[str, Any]:
    """paicad에 넘기는 options.json(메타 키 없이 schema_version만). 파일 하나로 사용값과 겸용할 때는 usage_document."""
    return {"schema_version": 1, **copy.deepcopy(opts)}


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def tag_options_sha256(opts: dict[str, Any]) -> str:
    """준비본 유효성(§4.2) 비교용: 유효 옵션의 `tag` 절만 정규화 JSON으로 sha256."""
    return hashlib.sha256(canonical_json(opts.get("tag") or {}).encode("utf-8")).hexdigest()


def tag_section_changed(old: dict[str, Any] | None, new: dict[str, Any] | None) -> bool:
    """PATCH geom_options에서 tag 절이 바뀌었는지(§7.4 → prep_status STALE)."""
    return (old or {}).get("tag") != (new or {}).get("tag")
