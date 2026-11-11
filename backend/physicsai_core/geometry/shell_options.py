"""쉘 판금 모핑 옵션 `options.json`(kind:"shell", shell-morph.md §4.10): 기본값 병합·범위 검사·준비본 해시.

유효 옵션 = 코드 기본값(§4.10 예시) ← 설정 `geometry.shell_defaults` ← `param_sets.geom_options`(쉘 세트 덮어쓰기) 깊은 병합.
솔리드 options(`options.py`)와 스키마가 다르다 — 솔리드 명령에 쉘 절을 주지 않는다(GE-C10). 범위 위반은 422 GEOM_OPTIONS_INVALID.
준비본 유효성(§4.2)은 `tag` 절 + `fixed` 절(transition_mm 제외)의 sha256로 본다(전이 폭은 고급 옵션 — 준비본 재생성 불필요).

SM-C3~C8(§14, paicad 0.15.0) 새 키는 `NEW_KEY_DEFAULTS`에 둔다. **기본값과 같은 새 키는 유효 옵션에서 뺀다**(options.json에 쓰지 않음 — 기존
결과 바이트·옵션 sha 유지, 옛 paicad의 모르는 키 거부 회피, §14.4). 기본값에서 벗어난 키만 사용값 문서에 실린다.
"""

from __future__ import annotations

import copy
import hashlib
import math
from typing import Any

from .options import canonical_json, deep_merge

SHELL_KIND = "shell"
FIXED_KINDS = ("INTER_TYPE2", "RBE2", "RBE3", "RBODY", "BCS", "SHARED")
FIXED_REQUIRED = ("INTER_TYPE2", "RBE2")
DEFAULT_SHELL_OPTIONS: dict[str, Any] = {
    "tag": {"tol_abs_mm": 0.05, "tol_rel": 1.0e-4, "min_match_ratio": 0.98},
    "fixed": {"kinds": list(FIXED_KINDS), "required": True, "transition_mm": 6.0, "tol_mm": 0.001},
    "morph": {"smoother": "elastic", "poisson": 0.3, "relax_iters": 3, "solver_rtol": 1.0e-8, "solver_maxiter": 5000},
    "quality": {"max_warpage_deg": 15.0, "max_skew_deg": 60.0, "max_aspect": 5.0, "min_jacobian": 0.6,
                "min_edge_ratio": 0.8, "dt_ratio_min": 0.8, "min_edge_mm": None, "relative_to_baseline": True},
    "deviation": {"boundary_max_mm": 0.05, "param_abs_mm": 0.05, "param_rel": 0.01},
    "interference": {"product_mm": 0.05},
    "tie": {"default_dsearch_mm": None, "required": True},
    "extract": {"range_ratio": 0.05, "position_range_mm": 5.0, "draft_max_deg": 3.0, "min_flank_deg": 10.0, "min_depth_mm": 0.5,
                "land_min_mm": 2.0, "linear_aspect": 1.2},
    "bead": {"depth_mode": "keep_angle", "position_ref": "nearest_fixed_edge"},
    "symmetry_split": [],
}
# SM-C3~C8 새 키 기본값(§14.1·14.2·14.3·14.4·14.5). 기본값과 같으면 유효 옵션에서 생략한다.
HOLD_DEFAULT: dict[str, Any] = {"beads": [], "ring_mm": 3.0, "blend_mm": 8.0}
NEW_KEY_DEFAULTS: dict[str, dict[str, Any]] = {
    "tag": {"label_angle_deg": 15.0},
    "fixed": {"policy": "skip"},
    "quality": {"fail_policy": "skip", "distort_min_mm": 0.1, "distort_rel": 0.25},
    "extract": {"islands": True, "island_max_mm": 40.0, "island_ring_frac": 0.9},
    "bead": {"hold": HOLD_DEFAULT},
}
POLICIES = ("skip", "warn")
# 정책 키(PREDICT(A)·⑤ 최적화는 skip 고정, SM-10). (절, 키)
POLICY_KEYS = (("fixed", "policy"), ("quality", "fail_policy"))
# 준비본(STALE 판정)에 쓰이지 않는 새 키(§14.3: label_angle_deg, 정책은 실행 시점 옵션)
PREP_EXEMPT = {"tag": ("label_angle_deg",), "fixed": ("transition_mm", "policy")}
SECTIONS = ("tag", "fixed", "morph", "quality", "deviation", "interference", "tie", "extract", "bead")
SCALARS = ("symmetry_split",)
META_KEYS = ("schema_version", "engine", "engine_version", "kind")


def _allowed(section: str) -> set[str]:
    return set(DEFAULT_SHELL_OPTIONS[section]) | set(NEW_KEY_DEFAULTS.get(section, {}))


def _problem(key: str, message: str) -> dict[str, str]:
    return {"code": "GEOM_OPTIONS_INVALID", "key": key, "message": message}


def _num(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def _pos(x: Any) -> bool:
    return _num(x) and x > 0


def _int(x: Any) -> bool:
    return isinstance(x, int) and not isinstance(x, bool)


def normalize_override(over: Any) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """부분 객체 모양 검사(모르는 키 거부, GE-C10 준용). 메타 키는 입력에 올 수 없다."""
    probs: list[dict[str, str]] = []
    if over is None:
        return {}, probs
    if not isinstance(over, dict):
        return {}, [_problem("(root)", "옵션은 객체여야 합니다")]
    out: dict[str, Any] = {}
    for k, v in over.items():
        if k in META_KEYS:
            probs.append(_problem(k, f"'{k}'는 옵션으로 보낼 수 없습니다(사용값 기록 전용)"))
        elif k in SECTIONS:
            if not isinstance(v, dict):
                probs.append(_problem(k, f"'{k}'는 객체여야 합니다"))
                continue
            probs += [_problem(f"{k}.{s}", "알 수 없는 옵션 키입니다") for s in v if s not in _allowed(k)]
            out[k] = {**out.get(k, {}), **{s: x for s, x in v.items() if s in _allowed(k)}}
        elif k in SCALARS:
            out[k] = v
        else:
            probs.append(_problem(k, "알 수 없는 옵션 키입니다(쉘 옵션)"))
    return out, probs


def _ratio(x: Any) -> bool:
    return _pos(x) and x <= 1


def _hold_problems(h: Any) -> list[dict[str, str]]:
    if not isinstance(h, dict):
        return [_problem("bead.hold", "객체여야 합니다")]
    p = [_problem(f"bead.hold.{k}", "알 수 없는 옵션 키입니다") for k in h if k not in HOLD_DEFAULT]
    beads = h.get("beads", [])
    if not (isinstance(beads, list) and all(isinstance(x, str) and x for x in beads)) or len(set(beads)) != len(beads):
        p.append(_problem("bead.hold.beads", "비드 id 문자열 목록(중복 없음)이어야 합니다"))
    for k in ("ring_mm", "blend_mm"):
        if not _pos(h.get(k, HOLD_DEFAULT[k])):
            p.append(_problem(f"bead.hold.{k}", "0보다 큰 유한한 숫자여야 합니다"))
    return p


def hold_option_problems(h: dict[str, Any]) -> list[dict[str, str]]:
    """①-2 hold_options(ring_mm·blend_mm) 양수 검사 — `bead.hold`와 같은 `_pos` 규칙."""
    return [_problem(f"hold_options.{k}", "0보다 큰 유한한 숫자여야 합니다") for k in ("ring_mm", "blend_mm") if k in h and not _pos(h[k])]


def validate_options(o: dict[str, Any]) -> list[dict[str, str]]:  # noqa: C901 - 표 기반 범위 나열(§4.10)
    p: list[dict[str, str]] = []
    add = lambda k, m: p.append(_problem(k, m))  # noqa: E731
    t = o.get("tag") or {}
    for k in ("tol_abs_mm", "tol_rel"):
        if not _pos(t.get(k)):
            add(f"tag.{k}", "0보다 큰 유한한 숫자여야 합니다")
    if not _ratio(t.get("min_match_ratio")):
        add("tag.min_match_ratio", "0 초과 1 이하여야 합니다")
    la = t.get("label_angle_deg", NEW_KEY_DEFAULTS["tag"]["label_angle_deg"])
    if not (_pos(la) and la <= 90):
        add("tag.label_angle_deg", "0 초과 90 이하여야 합니다")
    f = o.get("fixed") or {}
    if f.get("policy", "skip") not in POLICIES:
        add("fixed.policy", "skip | warn")
    kinds = f.get("kinds")
    if not isinstance(kinds, list) or not all(isinstance(x, str) and x in FIXED_KINDS for x in kinds):
        add("fixed.kinds", "INTER_TYPE2·RBE2·RBE3·RBODY·BCS·SHARED 중에서 고르세요")
    elif not all(x in kinds for x in FIXED_REQUIRED):
        add("fixed.kinds", "INTER_TYPE2와 RBE2는 빼면 안 됩니다(체결부 고정)")
    if not isinstance(f.get("required"), bool):
        add("fixed.required", "true 또는 false여야 합니다")
    if not (_num(f.get("transition_mm")) and f["transition_mm"] >= 0):
        add("fixed.transition_mm", "0 이상이어야 합니다(0 = 전이 없음)")
    if not _pos(f.get("tol_mm")):
        add("fixed.tol_mm", "0보다 큰 유한한 숫자여야 합니다")
    m = o.get("morph") or {}
    if m.get("smoother") not in ("elastic", "laplacian"):
        add("morph.smoother", "elastic | laplacian")
    nu = m.get("poisson")
    if not (_num(nu) and 0 <= nu < 0.5):
        add("morph.poisson", "0 이상 0.5 미만이어야 합니다")
    if not (_int(m.get("relax_iters")) and 0 <= m["relax_iters"] <= 50):
        add("morph.relax_iters", "0~50 정수여야 합니다")
    if not (_pos(m.get("solver_rtol")) and m["solver_rtol"] < 1):
        add("morph.solver_rtol", "0 초과 1 미만이어야 합니다")
    if not (_int(m.get("solver_maxiter")) and m["solver_maxiter"] >= 1):
        add("morph.solver_maxiter", "1 이상의 정수여야 합니다")
    q = o.get("quality") or {}
    if not (_num(q.get("max_warpage_deg")) and 0 <= q["max_warpage_deg"] <= 45):
        add("quality.max_warpage_deg", "0~45도여야 합니다")
    if not (_num(q.get("max_skew_deg")) and 0 <= q["max_skew_deg"] <= 90):
        add("quality.max_skew_deg", "0~90도여야 합니다")
    if not (_num(q.get("max_aspect")) and q["max_aspect"] >= 1):
        add("quality.max_aspect", "1 이상이어야 합니다")
    if not _ratio(q.get("min_jacobian")):
        add("quality.min_jacobian", "0 초과 1 이하여야 합니다")
    for k in ("min_edge_ratio", "dt_ratio_min"):
        if not _ratio(q.get(k)):
            add(f"quality.{k}", "0 초과 1 이하여야 합니다")
    if q.get("min_edge_mm") is not None and not _pos(q.get("min_edge_mm")):
        add("quality.min_edge_mm", "null(미사용) 또는 0보다 큰 숫자여야 합니다")
    if not isinstance(q.get("relative_to_baseline"), bool):
        add("quality.relative_to_baseline", "true 또는 false여야 합니다")
    if q.get("fail_policy", "skip") not in POLICIES:
        add("quality.fail_policy", "skip | warn")
    for k in ("distort_min_mm", "distort_rel"):
        if not _pos(q.get(k, NEW_KEY_DEFAULTS["quality"][k])):
            add(f"quality.{k}", "0보다 큰 유한한 숫자여야 합니다")
    d = o.get("deviation") or {}
    for k in ("boundary_max_mm", "param_abs_mm", "param_rel"):
        if not _pos(d.get(k)):
            add(f"deviation.{k}", "0보다 큰 유한한 숫자여야 합니다")
    if not _pos((o.get("interference") or {}).get("product_mm")):
        add("interference.product_mm", "0보다 큰 유한한 숫자여야 합니다")
    tie = o.get("tie") or {}
    if tie.get("default_dsearch_mm") is not None and not _pos(tie.get("default_dsearch_mm")):
        add("tie.default_dsearch_mm", "null 또는 0보다 큰 숫자여야 합니다")
    if not isinstance(tie.get("required"), bool):
        add("tie.required", "true 또는 false여야 합니다")
    e = o.get("extract") or {}
    if not (_pos(e.get("range_ratio")) and e["range_ratio"] < 1):
        add("extract.range_ratio", "0 초과 1 미만이어야 합니다")
    for k in ("position_range_mm", "min_depth_mm", "land_min_mm"):
        if not _pos(e.get(k)):
            add(f"extract.{k}", "0보다 큰 유한한 숫자여야 합니다")
    for k in ("draft_max_deg", "min_flank_deg"):
        if not (_pos(e.get(k)) and e[k] <= 90):
            add(f"extract.{k}", "0 초과 90 이하여야 합니다")
    if not (_num(e.get("linear_aspect")) and e["linear_aspect"] >= 1):
        add("extract.linear_aspect", "1 이상이어야 합니다")
    if not isinstance(e.get("islands", True), bool):
        add("extract.islands", "true 또는 false여야 합니다")
    if not _pos(e.get("island_max_mm", 40.0)):
        add("extract.island_max_mm", "0보다 큰 유한한 숫자여야 합니다")
    if not _ratio(e.get("island_ring_frac", 0.9)):
        add("extract.island_ring_frac", "0 초과 1 이하여야 합니다")
    b = o.get("bead") or {}
    if "hold" in b:
        p += _hold_problems(b["hold"])
    if b.get("depth_mode") not in ("keep_angle", "keep_bottom"):
        add("bead.depth_mode", "keep_angle | keep_bottom")
    if b.get("position_ref") not in ("nearest_fixed_edge", "proportional"):
        add("bead.position_ref", "nearest_fixed_edge | proportional")
    ss = o.get("symmetry_split")
    if not isinstance(ss, list) or not all(isinstance(x, str) for x in ss):
        add("symmetry_split", "그룹 id 문자열 목록이어야 합니다")
    return p


def effective_shell_options(defaults: dict[str, Any] | None, geom_options: dict[str, Any] | None = None
                            ) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """(유효 쉘 옵션, problems). 코드 기본값 ← 설정 shell_defaults ← 세트 덮어쓰기."""
    base, probs = normalize_override(defaults)
    over, p2 = normalize_override(geom_options)
    opts = deep_merge(deep_merge(DEFAULT_SHELL_OPTIONS, base), over)
    hold = (opts.get("bead") or {}).get("hold")
    if isinstance(hold, dict):  # 부분 hold(beads만 등)는 기본 ρ·b로 채운다
        opts["bead"]["hold"] = {**HOLD_DEFAULT, **hold}
    problems = probs + p2 + validate_options(opts)
    return strip_default_new_keys(opts), problems


def strip_default_new_keys(opts: dict[str, Any]) -> dict[str, Any]:
    """기본값과 같은 새 키(SM-C3~C8)를 뺀다(§14.4: 옵션 sha·기존 결과 불변, 옛 paicad 호환)."""
    out = copy.deepcopy(opts)
    for sec, keys in NEW_KEY_DEFAULTS.items():
        d = out.get(sec)
        if not isinstance(d, dict):
            continue
        for k, dv in keys.items():
            if k in d and d[k] == dv and isinstance(d[k], bool) == isinstance(dv, bool):
                del d[k]
    return out


def force_skip(opts: dict[str, Any]) -> dict[str, Any]:
    """PREDICT(A)·⑤ 최적화용: 고정 침범·품질 미달 정책을 `skip`으로 고정(SM-10). 정책 키는 기본값이라 생략된다."""
    out = copy.deepcopy(opts)
    for sec, k in POLICY_KEYS:
        if isinstance(out.get(sec), dict):
            out[sec].pop(k, None)
    return out


def doe_policy_opts(opts: dict[str, Any], request: dict[str, Any] | None) -> dict[str, Any]:
    """DOE 정책 원천 = DOE 요청 geom_options만(SM-10). 세트·설정 기본값에서 온 정책은 버리고 요청의 정책 키만 되살린다."""
    out = force_skip(opts)
    for sec, k in POLICY_KEYS:
        v = ((request or {}).get(sec) or {}).get(k)
        if v in POLICIES and v != NEW_KEY_DEFAULTS[sec][k]:
            out.setdefault(sec, {})[k] = v
    return out


def stored_policy_warn(geom_options: dict[str, Any] | None) -> bool:
    """세트에 저장된 geom_options에 warn 정책이 남아 있는지(이전 버전·직접 저장)."""
    return any(((geom_options or {}).get(sec) or {}).get(k) == "warn" for sec, k in POLICY_KEYS)


def policy_of(opts: dict[str, Any]) -> dict[str, str]:
    return {"fixed": (opts.get("fixed") or {}).get("policy", "skip"), "quality": (opts.get("quality") or {}).get("fail_policy", "skip")}


def hold_beads(opts: dict[str, Any]) -> list[str]:
    return list(((opts.get("bead") or {}).get("hold") or {}).get("beads") or [])


def hold_problems(opts: dict[str, Any], features: dict[str, Any] | None) -> list[dict[str, str]]:
    """`bead.hold.beads` ⊆ `shell_features.json`의 `hold_eligible` 비드(§14.5). features가 없으면 확인할 수 없어 목록이 비어 있어야 한다."""
    want = hold_beads(opts)
    if not want:
        return []
    beads = {b.get("id"): b for b in (features or {}).get("beads", []) if isinstance(b, dict)}
    bad = [b for b in want if not (b in beads and beads[b].get("hold_eligible") is True)]
    if not bad:
        return []
    return [_problem("bead.hold.beads", "체결 보스 고정(hold)은 hold 가능으로 표시된 비드에만 쓸 수 있습니다: " + ", ".join(bad[:5]))]


def paicad_document(opts: dict[str, Any]) -> dict[str, Any]:
    """paicad에 넘기는 쉘 options.json(`kind:"shell"` + schema_version, 메타 키 없음)."""
    return {"schema_version": 1, "kind": SHELL_KIND, **copy.deepcopy(opts)}


def prep_sections(opts: dict[str, Any]) -> dict[str, Any]:
    """준비본에 영향을 주는 절: tag 전체 + fixed(transition_mm 제외)."""
    def keep(sec: str) -> dict[str, Any]:
        return {k: v for k, v in (opts.get(sec) or {}).items() if k not in PREP_EXEMPT.get(sec, ())}

    return {"tag": keep("tag"), "fixed": keep("fixed")}


def prep_options_sha256(opts: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(prep_sections(opts)).encode("utf-8")).hexdigest()
