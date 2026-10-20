"""레시피 정의(equiv-check.md §3.1) 검증·정규화 — 순수 함수.

problems 코드(422 EQ_RECIPE_INVALID): METRIC_ID_INVALID · METRIC_DUPLICATE · METRICS_RANGE · TOL_INVALID · SOURCE_INVALID ·
KIND_SOURCE_MISMATCH · LABEL_INVALID · RULE_INVALID. 실행 시 지표(필수·참고 모두, mesh_volume 제외)의 source null은
METRIC_UNBOUND(EQ_CHECK_INVALID) — 응답 연결은 사용자가 고른다(EQ-C1)."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from typing import Any

ID_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
KINDS = ("scalar", "curve_corr", "curve_nrmse", "mesh_volume")
SOURCE_TYPES = ("perf", "h3d", "curve", "mesh_volume")
# kind별 허용 source.type(null은 "연결 필요" — 모든 kind에서 허용, 실행 전 연결)
KIND_SOURCES: dict[str, tuple[str, ...]] = {
    "scalar": ("perf", "h3d", "curve"),
    "curve_corr": ("curve", "perf"),
    "curve_nrmse": ("curve", "perf"),
    "mesh_volume": ("mesh_volume",),
}
STATS = ("MAX", "MIN", "ABSMAX")
VOLUME_ORIGINS = ("mesh", "starter_mass", "paicad")  # Q3: 기본 mesh(include 적분), 레시피에서 선택 가능
PAIR_MODES = ("all", "min_ratio")
VERDICT_RULES = ("required_all",)
MAX_LABEL = 40
SCHEMA_VERSION = 1


def _problem(code: str, message: str, metric_id: str | None = None) -> dict[str, Any]:
    p: dict[str, Any] = {"code": code, "message": message}
    if metric_id is not None:
        p["metric_id"] = metric_id
    return p


def _finite(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _tol_problems(mid: str, kind: str, tol: Any) -> list[dict[str, Any]]:
    if not isinstance(tol, Mapping):
        return [_problem("TOL_INVALID", "허용오차(tol)는 객체여야 합니다", mid)]
    out: list[dict[str, Any]] = []
    if kind in ("scalar", "mesh_volume"):
        rel, ab = tol.get("rel_pct"), tol.get("abs")
        if rel is None and ab is None:
            out.append(_problem("TOL_INVALID", "상대 %(rel_pct) 또는 절대값(abs) 중 하나 이상이 필요합니다", mid))
        for k, v in (("rel_pct", rel), ("abs", ab)):
            if v is not None and (not _finite(v) or v < 0):
                out.append(_problem("TOL_INVALID", f"{k}는 0 이상 유한한 수여야 합니다", mid))
    elif kind == "curve_corr":
        c = tol.get("corr_min")
        if not _finite(c) or not 0 <= c <= 1:
            out.append(_problem("TOL_INVALID", "상관 하한(corr_min)은 0~1이어야 합니다", mid))
    elif kind == "curve_nrmse":
        n = tol.get("nrmse_max_pct")
        if not _finite(n) or n < 0:
            out.append(_problem("TOL_INVALID", "NRMSE 상한(nrmse_max_pct)은 0 이상이어야 합니다", mid))
    return out


def _source_problems(mid: str, kind: str, src: Any) -> list[dict[str, Any]]:
    if src is None:
        return []
    if not isinstance(src, Mapping) or src.get("type") not in SOURCE_TYPES:
        return [_problem("SOURCE_INVALID", "원천(source)은 perf | h3d | curve | mesh_volume 중 하나여야 합니다", mid)]
    t = str(src["type"])
    if t not in KIND_SOURCES[kind]:
        return [_problem("KIND_SOURCE_MISMATCH", f"지표 종류 {kind}에는 원천 {t}를 쓸 수 없습니다", mid)]
    out: list[dict[str, Any]] = []
    if t == "perf":
        n = src.get("perf")
        if not isinstance(n, str) or not n.strip() or len(n) > 64:
            out.append(_problem("SOURCE_INVALID", "perf 원천에는 성능 정의 이름(perf)이 필요합니다", mid))
    elif t == "h3d":
        for k in ("datatype",):
            if not isinstance(src.get(k), str) or not str(src.get(k)).strip():
                out.append(_problem("SOURCE_INVALID", f"h3d 원천에는 {k}가 필요합니다", mid))
        sc = src.get("subcase", 1)
        if not isinstance(sc, int) or isinstance(sc, bool) or sc < 1:
            out.append(_problem("SOURCE_INVALID", "h3d 원천의 subcase는 1 이상 정수여야 합니다", mid))
        if str(src.get("stat") or "MAX").upper() not in STATS:
            out.append(_problem("SOURCE_INVALID", "stat은 MAX | MIN | ABSMAX 중 하나여야 합니다", mid))
    elif t == "curve":
        s = src.get("series")
        if s is not None and (not isinstance(s, str) or not s.strip() or len(s) > 200):
            out.append(_problem("SOURCE_INVALID", "curve 원천의 series는 문자열(또는 null = 첫 계열)이어야 합니다", mid))
        if kind == "scalar" and str(src.get("stat") or "MAX").upper() not in STATS:
            out.append(_problem("SOURCE_INVALID", "stat은 MAX | MIN | ABSMAX 중 하나여야 합니다", mid))
        t01 = src.get("t01")
        if t01 is not None and (not isinstance(t01, Mapping) or not all(isinstance(t01.get(k), str) for k in ("type", "request", "component"))):
            out.append(_problem("SOURCE_INVALID", "t01 추출 요청은 {type, request, component} 문자열이어야 합니다", mid))
    elif t == "mesh_volume":
        parts = src.get("parts", "cushion")
        if parts != "cushion" and not (isinstance(parts, list) and parts and all(isinstance(p, (str, int)) and str(p).strip() for p in parts)):
            out.append(_problem("SOURCE_INVALID", 'mesh_volume의 parts는 "cushion" 또는 part id 목록이어야 합니다', mid))
        if src.get("origin", "mesh") not in VOLUME_ORIGINS:
            out.append(_problem("SOURCE_INVALID", "부피 원천(origin)은 mesh | starter_mass | paicad 중 하나여야 합니다", mid))
    return out


def validate_definition(defn: Any, *, max_metrics: int, allow_unbound: bool = True) -> list[dict[str, Any]]:
    """레시피 정의 → problems(빈 목록 = 정상). allow_unbound=False면 source null인 **필수** 지표를 METRIC_UNBOUND로 보고한다."""
    if not isinstance(defn, Mapping):
        return [_problem("RULE_INVALID", "레시피 정의는 객체여야 합니다")]
    out: list[dict[str, Any]] = []
    metrics = defn.get("metrics")
    if not isinstance(metrics, list):
        return [_problem("METRICS_RANGE", "지표 목록(metrics)이 필요합니다")]
    if not 1 <= len(metrics) <= max_metrics:
        out.append(_problem("METRICS_RANGE", f"지표는 1~{max_metrics}개여야 합니다(현재 {len(metrics)}개)"))
    seen: set[str] = set()
    for i, m in enumerate(metrics):
        if not isinstance(m, Mapping):
            out.append(_problem("METRIC_ID_INVALID", f"{i + 1}번째 지표가 객체가 아닙니다"))
            continue
        mid = m.get("id")
        if not isinstance(mid, str) or not ID_RE.match(mid):
            out.append(_problem("METRIC_ID_INVALID", f"지표 id는 소문자 영숫자·_ 32자 이내(영문자로 시작)여야 합니다: {mid!r}"))
            mid = str(mid)
        elif mid in seen:
            out.append(_problem("METRIC_DUPLICATE", f"지표 id가 중복됩니다: {mid}", mid))
        seen.add(mid)
        label = m.get("label")
        if not isinstance(label, str) or not label.strip() or len(label) > MAX_LABEL:
            out.append(_problem("LABEL_INVALID", f"지표 이름(label)은 1~{MAX_LABEL}자여야 합니다", mid))
        kind = m.get("kind")
        if kind not in KINDS:
            out.append(_problem("KIND_SOURCE_MISMATCH", "지표 종류(kind)는 scalar | curve_corr | curve_nrmse | mesh_volume 중 하나여야 합니다", mid))
            continue
        if not isinstance(m.get("required", True), bool):
            out.append(_problem("RULE_INVALID", "required는 true/false여야 합니다", mid))
        out += _source_problems(mid, kind, m.get("source"))
        out += _tol_problems(mid, kind, m.get("tol"))
        if not allow_unbound and m.get("source") is None and kind != "mesh_volume":
            out.append(_problem("METRIC_UNBOUND", unbound_message(label if isinstance(label, str) else mid), mid))
    pr = defn.get("pair_rule", {"mode": "all"})
    if not isinstance(pr, Mapping) or pr.get("mode", "all") not in PAIR_MODES:
        out.append(_problem("RULE_INVALID", "쌍 집계 규칙(pair_rule.mode)은 all | min_ratio 중 하나여야 합니다"))
    elif pr.get("mode") == "min_ratio":
        r = pr.get("ratio")
        if not _finite(r) or not 0 < r <= 1:
            out.append(_problem("RULE_INVALID", "min_ratio의 ratio는 0 초과 1 이하여야 합니다"))
    if defn.get("verdict_rule", "required_all") not in VERDICT_RULES:
        out.append(_problem("RULE_INVALID", "종합 규칙(verdict_rule)은 required_all만 지원합니다"))
    return out


def normalize_definition(defn: Mapping[str, Any]) -> dict[str, Any]:
    """검증을 통과한 정의를 저장 모양으로(키 순서·기본값 채움). 정의·수치만(결과 데이터 없음)."""
    metrics = []
    for m in defn["metrics"]:
        src = m.get("source")
        if isinstance(src, Mapping):
            src = dict(src)
            if src["type"] == "h3d":
                src = {"type": "h3d", "name": src.get("name"), "subcase": int(src.get("subcase", 1)), "datatype": src["datatype"],
                       "component": str(src.get("component") or ""), "layer": str(src.get("layer") or ""),
                       "stat": str(src.get("stat") or "MAX").upper()}
            elif src["type"] == "curve":
                src = {"type": "curve", "series": src.get("series"), **({"stat": str(src.get("stat") or "MAX").upper()} if m["kind"] == "scalar" else {}),
                       "t01": dict(src["t01"]) if isinstance(src.get("t01"), Mapping) else None}
            elif src["type"] == "mesh_volume":
                parts = src.get("parts", "cushion")
                src = {"type": "mesh_volume", "parts": parts if parts == "cushion" else [str(p) for p in parts],
                       "origin": src.get("origin", "mesh")}
            else:
                src = {"type": "perf", "perf": str(src["perf"]).strip()}
        tol = dict(m["tol"])
        if m["kind"] in ("scalar", "mesh_volume"):
            tol = {"rel_pct": tol.get("rel_pct"), "abs": tol.get("abs")}
        elif m["kind"] == "curve_corr":
            tol = {"corr_min": float(tol["corr_min"])}
        else:
            tol = {"nrmse_max_pct": float(tol["nrmse_max_pct"])}
        metrics.append({"id": m["id"], "label": str(m["label"]).strip(), "kind": m["kind"], "source": src, "tol": tol,
                        "required": bool(m.get("required", True))})
    pr = dict(defn.get("pair_rule") or {"mode": "all"})
    pair_rule = {"mode": pr.get("mode", "all")}
    if pair_rule["mode"] == "min_ratio":
        pair_rule["ratio"] = float(pr["ratio"])
    return {"schema_version": SCHEMA_VERSION, "metrics": metrics, "pair_rule": pair_rule,
            "verdict_rule": defn.get("verdict_rule", "required_all")}


def unbound_metrics(defn: Mapping[str, Any]) -> list[str]:
    """source가 null인 지표 id — 필수·참고 모두(실행 전 사용자가 응답 연결 필요 — 422 METRIC_UNBOUND, EQ-C1).
    mesh_volume은 원천 기본값(include 적분)이 있어 제외."""
    return [m["id"] for m in defn.get("metrics", []) if m.get("source") is None and m.get("kind") != "mesh_volume"]


def unbound_message(label: str) -> str:
    return f"지표 '{label}'의 응답이 연결되지 않았습니다 — 성능 정의(응답)를 선택하거나 레시피에서 지표를 빼세요"


def tol_text(m: Mapping[str, Any]) -> str:
    """허용오차 표시(한국어, 결과 표·알림용)."""
    t = m.get("tol") or {}
    k = m.get("kind")
    if k in ("scalar", "mesh_volume"):
        parts = []
        if t.get("rel_pct") is not None:
            parts.append(f"상대 {t['rel_pct']:g}%")
        if t.get("abs") is not None:
            parts.append(f"절대 {t['abs']:g}")
        return " 또는 ".join(parts)
    if k == "curve_corr":
        return f"r ≥ {t.get('corr_min', 0):g}"
    return f"NRMSE ≤ {t.get('nrmse_max_pct', 0):g}%"
