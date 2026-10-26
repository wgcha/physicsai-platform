"""native 추출 조건(찾을 종류·조건) — 그룹↔종류 매핑·정규화·검증·paicad 변환·통계 요약(extract-filter.md §3·§4·§6·§7).

표준 라이브러리만 쓴다. 그룹 키·조건 키는 이 파일이 단일 출처이고 API 스키마·워커·시험이 가져다 쓴다.
정규화본(플랫폼 모양) = `{groups, conditions, draft_max_deg}`. paicad 모양 = `extract.filter` `{types, <조건>…}` + `extract.draft_max_deg`.
"""

from __future__ import annotations

import copy
import math
from typing import Any

# 그룹 키 → paicad 종류(표 §3.1, 순서 고정 — paicad `TYPE_ORDER`와 같은 부분 순서)
GROUP_TYPES: dict[str, tuple[str, ...]] = {
    "thickness": ("THICKNESS", "RIB_THICKNESS", "POCKET_WIDTH"),
    "height": ("RIB_HEIGHT", "POCKET_DEPTH"),
    "position": ("HOLE_POS_U", "HOLE_POS_V", "RIB_POS_U", "RIB_POS_V"),
    "rib_pitch": ("RIB_PITCH_U", "RIB_PITCH_V"),  # rib-gap.md §8: 독립 돌출 리브 열의 이웃 중심 간 거리(조건 없음)
    "hole_radius": ("HOLE_RADIUS",),
    "fillet": ("FILLET_RADIUS",),
}
GROUP_ORDER: tuple[str, ...] = tuple(GROUP_TYPES)
GROUP_LABELS = {"thickness": "두께", "height": "높이·깊이", "position": "위치(구멍·리브)",
                "rib_pitch": "리브 간격(피치)", "hole_radius": "구멍 반경", "fillet": "필렛"}

# 그룹 → 그 그룹에 속한 조건 키(§4.2). 범위형은 {min, max}, 나머지는 양수 하나.
GROUP_CONDITIONS: dict[str, tuple[str, ...]] = {
    "thickness": ("thickness_mm", "face_area_min_mm2"),
    "height": ("height_mm",),
    "position": ("position_min_size_mm",),
    "rib_pitch": (),  # 조건 없음
    "hole_radius": ("hole_radius_min_mm",),
    "fillet": ("fillet_radius_min_mm",),
}
RANGE_KEYS = ("thickness_mm", "height_mm")
SCALAR_KEYS = ("face_area_min_mm2", "position_min_size_mm", "hole_radius_min_mm", "fillet_radius_min_mm")
CONDITION_KEYS = RANGE_KEYS + SCALAR_KEYS
DRAFT_KEY = "draft_max_deg"
NO_GROUP_MESSAGE = "찾을 종류를 하나 이상 고르세요"
CANT_CHANGE_MESSAGE = "등록된 세트의 추출 조건은 바꿀 수 없습니다 — 새 세트로 등록하세요"
UNSUPPORTED_MESSAGE = "찾을 종류 선택은 native 솔리드 추출에서만 쓸 수 있습니다"
DEFAULTS_IGNORED_MESSAGE = "geometry.defaults.extract.filter는 쓰지 않습니다 — 추출 조건은 추출·세트 등록 때 사용자가 정합니다"
GEOM_OPTIONS_MESSAGE = "추출 조건은 geom_options가 아니라 등록 요청의 extract_filter로 정합니다"
EMPTY_MESSAGE = "조건에 맞는 피처가 없습니다 — 찾을 종류·조건을 넓혀 보세요"
STATS_JSON = "extract_stats.json"

TYPE_LABELS = {
    "THICKNESS": "두께", "RIB_THICKNESS": "리브 두께", "POCKET_WIDTH": "포켓 폭", "RIB_HEIGHT": "리브 높이", "POCKET_DEPTH": "포켓 깊이",
    "HOLE_RADIUS": "구멍 반경", "HOLE_POS_U": "구멍 위치 U", "HOLE_POS_V": "구멍 위치 V", "FILLET_RADIUS": "필렛 반경",
    "RIB_POS_U": "리브 위치 U", "RIB_POS_V": "리브 위치 V", "RIB_PITCH_U": "리브 피치 U", "RIB_PITCH_V": "리브 피치 V",
}
# 제외 사유(EF-C1 §5 `excluded` 키) — 모르는 키는 원문 키로 표시
EXCLUDED_LABELS = {
    "face_area": "면적", "thickness_range": "범위", "not_mutual": "비상호", "no_overlap": "겹침 없음",
    "not_thinner_than_height": "높이보다 두꺼움", "height_range": "범위", "hole_radius_min": "반경", "fillet_radius_min": "반경",
    "position_min_size": "최소 크기", "shape": "측면 형상", "base_axis": "축 비정렬",
    "not_slender": "기둥형", "row_branch": "열 분기", "row_single": "이웃 없음", "row_member": "간격 열 소속",  # rib-gap.md §8
}
# 리브 후보 탈락 사유(EF-C1 `rib_rejects` 7키)
RIB_REJECT_LABELS = {
    "cap_inner_wire": "윗면 내부 구멍", "cap_not_convex": "윗면 볼록 아님", "lateral_not_plane": "측면 곡면", "lateral_draft": "측면 구배",
    "lateral_count": "측면 3개 미만", "base_mismatch": "밑면 불일치", "height_not_positive": "높이 0 이하",
}


def _num(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def _p(key: str, message: str) -> dict[str, str]:
    return {"key": key, "message": message}


def normalize(raw: Any) -> tuple[dict[str, Any] | None, list[dict[str, str]]]:
    """요청 `extract_filter`(dict) → (정규화본, problems[{key, message}]). raw가 None이면 (None, []).
    정규화: 그룹은 표 순서로 정렬, 선택하지 않은 그룹의 조건·null 조건 제거(범위는 min·max 두 키 유지), 수치는 float."""
    if raw is None:
        return None, []
    probs: list[dict[str, str]] = []
    if not isinstance(raw, dict):
        return None, [_p("(root)", "추출 조건은 객체여야 합니다")]
    groups_in = raw.get("groups")
    groups: list[str] = []
    if not isinstance(groups_in, list) or not groups_in:
        probs.append(_p("groups", NO_GROUP_MESSAGE))
    else:
        for g in groups_in:
            if g not in GROUP_TYPES:
                probs.append(_p("groups", f"알 수 없는 종류 그룹입니다: {g}"))
            elif g in groups:
                probs.append(_p("groups", f"종류 그룹이 중복됩니다: {g}"))
            else:
                groups.append(g)
    cond_in = raw.get("conditions")
    cond_in = {} if cond_in is None else cond_in
    kept: dict[str, Any] = {}
    if not isinstance(cond_in, dict):
        probs.append(_p("conditions", "조건은 객체여야 합니다"))
        cond_in = {}
    for k in cond_in:
        if k not in CONDITION_KEYS:
            probs.append(_p(f"conditions.{k}", "알 수 없는 조건입니다"))
    for k in RANGE_KEYS:
        r = cond_in.get(k)
        if r is None:
            continue
        if not isinstance(r, dict) or any(s not in ("min", "max") for s in r):
            probs.append(_p(f"conditions.{k}", "{min, max} 객체여야 합니다"))
            continue
        lo, hi = r.get("min"), r.get("max")
        ok = True
        if lo is not None and not (_num(lo) and lo >= 0):
            probs.append(_p(f"conditions.{k}.min", "0 이상의 값을 넣으세요"))
            ok = False
        if hi is not None and not (_num(hi) and hi > 0):
            probs.append(_p(f"conditions.{k}.max", "0보다 큰 값을 넣으세요"))
            ok = False
        if ok and lo is not None and hi is not None and lo > hi:
            probs.append(_p(f"conditions.{k}", "최솟값이 최댓값보다 큽니다"))
            ok = False
        if ok and (lo is not None or hi is not None):
            kept[k] = {"min": None if lo is None else float(lo), "max": None if hi is None else float(hi)}
    for k in SCALAR_KEYS:
        v = cond_in.get(k)
        if v is None:
            continue
        if not (_num(v) and v > 0):
            probs.append(_p(f"conditions.{k}", "0보다 큰 값을 넣으세요"))
        else:
            kept[k] = float(v)
    d = raw.get(DRAFT_KEY)
    if d is not None and not (_num(d) and 0 < d < 45):
        probs.append(_p(DRAFT_KEY, "구배 허용각은 0°보다 크고 45°보다 작아야 합니다"))
        d = None
    if probs:
        return None, probs
    ordered = [g for g in GROUP_ORDER if g in groups]
    allowed = {k for g in ordered for k in GROUP_CONDITIONS[g]}
    conds = {k: kept[k] for k in CONDITION_KEYS if k in kept and k in allowed}
    return {"groups": ordered, "conditions": conds, DRAFT_KEY: None if d is None else float(d)}, []


def types_of(norm: dict[str, Any]) -> list[str]:
    return [t for g in GROUP_ORDER if g in norm["groups"] for t in GROUP_TYPES[g]]


def to_paicad(norm: dict[str, Any]) -> tuple[dict[str, Any], float | None]:
    """정규화본 → (`extract.filter`, draft_max_deg|None). 조건 키는 정규화본에서 이미 선택 그룹 것만 남아 있다."""
    flt: dict[str, Any] = {"types": types_of(norm)}
    flt.update(copy.deepcopy(norm["conditions"]))
    return flt, norm.get(DRAFT_KEY)


def from_paicad(flt: Any) -> dict[str, Any] | None:
    """`parameter_features.json` `filter`(paicad 사용값 사본: types·조건·draft_max_deg) → 정규화본. 없거나 모르는 모양이면 None."""
    if not isinstance(flt, dict) or not isinstance(flt.get("types"), list):
        return None
    types = {t for t in flt["types"] if isinstance(t, str)}
    groups = [g for g in GROUP_ORDER if types & set(GROUP_TYPES[g])]
    if not groups:
        return None
    allowed = {k for g in groups for k in GROUP_CONDITIONS[g]}
    conds: dict[str, Any] = {}
    for k in CONDITION_KEYS:
        v = flt.get(k)
        if k not in allowed or v is None:
            continue
        if k in RANGE_KEYS:
            if isinstance(v, dict) and (_num(v.get("min")) or _num(v.get("max"))):
                conds[k] = {"min": float(v["min"]) if _num(v.get("min")) else None, "max": float(v["max"]) if _num(v.get("max")) else None}
        elif _num(v):
            conds[k] = float(v)
    d = flt.get(DRAFT_KEY)
    return {"groups": groups, "conditions": conds, DRAFT_KEY: float(d) if _num(d) else None}


def apply_to_options(opts: dict[str, Any], norm: dict[str, Any] | None) -> dict[str, Any]:
    """유효 옵션 사본에 `extract.filter`·`extract.draft_max_deg`(job > defaults, §6.3)를 더한다. norm이 None이면 사본 그대로."""
    out = copy.deepcopy(opts)
    if norm is None:
        return out
    flt, draft = to_paicad(norm)
    ext = out.setdefault("extract", {})
    ext["filter"] = flt
    if draft is not None:
        ext[DRAFT_KEY] = draft
    return out


def options_inherit_features_filter(opts: dict[str, Any], features_filter: Any) -> dict[str, Any]:
    """기준 baseline의 features `filter`(paicad 사용값 사본)를 그대로 새 baseline 옵션에 승계(§6.7). 없으면 사본 그대로.
    draft_max_deg는 `extract.draft_max_deg`로 옮긴다(filter 절 안에는 두지 않는다 — paicad 입력 스키마에 없음)."""
    out = copy.deepcopy(opts)
    if not isinstance(features_filter, dict) or not isinstance(features_filter.get("types"), list):
        return out
    flt = {k: copy.deepcopy(v) for k, v in features_filter.items() if k != DRAFT_KEY}
    ext = out.setdefault("extract", {})
    ext["filter"] = flt
    d = features_filter.get(DRAFT_KEY)
    if _num(d):
        ext[DRAFT_KEY] = float(d)
    return out


def has_defaults_filter(defaults: Any) -> bool:
    """`geometry.defaults.extract.filter`가 설정에 적혀 있는가(경고 대상, 값은 무시)."""
    return isinstance(defaults, dict) and isinstance(defaults.get("extract"), dict) and "filter" in defaults["extract"]


def strip_defaults_filter(defaults: Any) -> Any:
    """설정 defaults에서 `extract.filter`를 뺀 사본(값은 무시한다, §6.3)."""
    if not has_defaults_filter(defaults):
        return defaults
    out = copy.deepcopy(defaults)
    del out["extract"]["filter"]
    return out


# ------------------------------------------------------------------ extract_stats.json 요약(§7.2)
def _int(x: Any) -> int:
    return int(x) if isinstance(x, (int, float)) and not isinstance(x, bool) else 0


def summarize_stats(doc: Any) -> dict[str, Any] | None:
    """`extract_stats.json` → `extract_summary`(수치만) `{types:{<type>:{selected, kept, excluded, …}}, png_rendered, elapsed_s, rib_rejects, filter_applied}`.
    바디별 값은 종류별로 합산한다. 구조가 아니면 None(경고 없음)."""
    if not isinstance(doc, dict) or not isinstance(doc.get("bodies"), list):
        return None
    types: dict[str, dict[str, Any]] = {}
    rejects: dict[str, int] = {}
    for b in doc["bodies"]:
        if not isinstance(b, dict):
            continue
        for t, v in (b.get("types") or {}).items():
            if not isinstance(v, dict):
                continue
            e = types.setdefault(t, {"selected": False, "kept": 0, "excluded": {}})
            e["selected"] = e["selected"] or bool(v.get("selected"))
            for k in ("initiators", "candidates", "pair_tests"):
                if k in v:
                    e[k] = e.get(k, 0) + _int(v[k])
            e["kept"] += _int(v.get("kept"))
            for why, n in (v.get("excluded") or {}).items():
                e["excluded"][why] = e["excluded"].get(why, 0) + _int(n)
            if isinstance(v.get("elapsed_s"), (int, float)):
                e["elapsed_s"] = round(e.get("elapsed_s", 0.0) + float(v["elapsed_s"]), 2)
        for why, n in (b.get("rib_rejects") or {}).items():
            rejects[why] = rejects.get(why, 0) + _int(n)
    png = doc.get("png") if isinstance(doc.get("png"), dict) else {}
    el = doc.get("elapsed_s") if isinstance(doc.get("elapsed_s"), dict) else {}
    return {"filter_applied": bool(doc.get("filter_applied")), "types": types, "png_rendered": _int(png.get("rendered")),
            "png_elapsed_s": float(png["elapsed_s"]) if isinstance(png.get("elapsed_s"), (int, float)) else None,
            "elapsed_s": float(el["total"]) if isinstance(el.get("total"), (int, float)) else None,
            "rib_rejects": dict(sorted(rejects.items()))}


def _sec(x: Any) -> str:
    return f"{x:.1f}초" if isinstance(x, (int, float)) else "-"


def _ordered(counts: dict[str, int], known: dict[str, str]) -> list[str]:
    """표기표 순서대로, 모르는 키는 뒤에 이름순."""
    return [k for k in known if k in counts] + sorted(k for k in counts if k not in known)


def summary_lines(summary: dict[str, Any]) -> list[str]:
    """작업 로그용 한국어 요약(§7.2) — 종류별 1줄. 선택 안 한 종류는 그룹 단위로 한 줄로 합친다(조건을 쓴 추출일 때만 보여 준다)."""
    lines: list[str] = []
    types = summary.get("types") or {}
    shown_groups: set[str] = set()
    order = [t for g in GROUP_ORDER for t in GROUP_TYPES[g]]
    for t in order + [t for t in types if t not in order]:
        v = types.get(t)
        if v is None:
            continue
        label = TYPE_LABELS.get(t, t)
        if not v.get("selected"):
            g = next((g for g in GROUP_ORDER if t in GROUP_TYPES[g]), None)
            if summary.get("filter_applied") and g is not None and g not in shown_groups \
                    and not any((types.get(x) or {}).get("selected") for x in GROUP_TYPES[g]):
                shown_groups.add(g)
                lines.append(f"{GROUP_LABELS[g]}: 건너뜀(선택 안 함)")
            continue
        excl = v.get("excluded") or {}
        total = sum(excl.values())
        parts = []
        if "pair_tests" in v:
            parts.append(f"판정 {v['pair_tests']}")
        elif "candidates" in v:
            parts.append(f"후보 {v['candidates']}")
        parts.append(f"채택 {v.get('kept', 0)}")
        why = ", ".join(f"{EXCLUDED_LABELS.get(k, k)} {excl[k]}" for k in _ordered(excl, EXCLUDED_LABELS) if excl[k])
        parts.append(f"제외 {total}" + (f"({why})" if why else ""))
        if "elapsed_s" in v:
            parts.append(_sec(v["elapsed_s"]))
        lines.append(f"{label}: " + " · ".join(parts))
    lines.append(f"하이라이트 PNG {summary.get('png_rendered', 0)}장 · {_sec(summary.get('png_elapsed_s'))} · 전체 {_sec(summary.get('elapsed_s'))}")
    rr = summary.get("rib_rejects") or {}
    if sum(rr.values()):
        why = ", ".join(f"{RIB_REJECT_LABELS.get(k, k)} {rr[k]}" for k in _ordered(rr, RIB_REJECT_LABELS) if rr[k])
        lines.append(f"리브 후보 탈락 {sum(rr.values())}({why})")
    return lines
