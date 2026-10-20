"""다중 baseline 파라미터 표·샘플 배정·변환·층화 LHS(R-B 300줄 분할 — `baselines`에서 재노출, §7.3.8)."""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from .baselines_base import NA_SUFFIX, ONEHOT_PREFIX, MapError, baseline_ids
from .baselines_decide import variables


# ------------------------------------------------------------------ 파라미터 표
def _range_of(f: Mapping[str, Any] | None, rows: Mapping[str, Mapping[str, Any]], name: str) -> dict[str, float] | None:
    """원 파라미터의 (nominal, min, max): 그 baseline 파라미터 표 행 우선, 없으면 features range."""
    r = rows.get(name)
    if r is not None:
        return {"nominal": float(r["nominal"]), "min": float(r["min"]), "max": float(r["max"])}
    if f is None:
        return None
    rg = f.get("range") if isinstance(f.get("range"), dict) else {}
    try:
        return {"nominal": float(f["nominal"]), "min": float(rg["min"]), "max": float(rg["max"])}
    except (KeyError, TypeError, ValueError):
        return None


def feasible_of(f: Mapping[str, Any] | None, fallback: Mapping[str, float] | None) -> tuple[float, float] | None:
    """`feasible`(source envelope 우선, 없으면 estimate) → (lo, hi). 없으면 파라미터 범위."""
    fe = (f or {}).get("feasible")
    if isinstance(fe, dict):
        lo, hi = fe.get("min"), fe.get("max")
        if isinstance(lo, (int, float)) and isinstance(hi, (int, float)) and math.isfinite(lo) and math.isfinite(hi) and lo <= hi:
            return float(lo), float(hi)
    if fallback is not None:
        return float(fallback["min"]), float(fallback["max"])
    return None


def parameter_rows(pm: Mapping[str, Any], features: Mapping[str, Mapping[str, Mapping[str, Any]]],
                   param_rows: Mapping[str, Mapping[str, Mapping[str, Any]]]) -> list[dict[str, Any]]:
    """확정 매칭표 → 세트 파라미터 표(공통 이름 행). features = {bid: {원 이름: 피처}}, param_rows = {bid: {원 이름: 표 행}}.
    공통 행 min·max = 활성 baseline 범위의 합집합, nominal = 첫 활성 baseline 공칭, `baselines` = {bid: {param, nominal, min, max, feasible}|null}."""
    out = []
    bids = baseline_ids(pm)
    for v in variables(pm):
        per: dict[str, Any] = {}
        for b in bids:
            orig = v.map.get(b)
            if orig is None:
                per[b] = None
                continue
            f = (features.get(b) or {}).get(orig)
            rg = _range_of(f, param_rows.get(b) or {}, orig)
            if rg is None:
                raise MapError("GEOM_INPUT_INVALID", f"{v.name}: baseline {b}의 {orig} 범위를 알 수 없습니다")
            fe = feasible_of(f, rg)
            per[b] = {"param": orig, **rg, "feasible": {"min": fe[0], "max": fe[1]} if fe else None}
        act = [per[b] for b in bids if per[b] is not None]
        lo, hi = min(x["min"] for x in act), max(x["max"] for x in act)
        nom = act[0]["nominal"]
        out.append({"name": v.name, "nominal": min(max(nom, lo), hi), "min": lo, "max": hi, "unit": v.unit or "mm", "baselines": per})
    return out


# ------------------------------------------------------------------ 샘플 배정·변환
def _per(rows: Sequence[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    return {str(r["name"]): r for r in rows if isinstance(r.get("baselines"), dict)}


def assign_baseline(pm: Mapping[str, Any], rows: Sequence[Mapping[str, Any]], values: Mapping[str, Any]) -> str | None:
    """샘플 배정(§7.3.8): topology = values["baseline"], range = 활성 값이 모두 그 baseline feasible 이내인 후보 중
    분할 변수 공칭이 가장 가까운 baseline(동률 = baselines 순서). 후보 없음 → None(BASELINE_NO_COVER)."""
    bids = baseline_ids(pm)
    if pm.get("usage") == "topology":
        b = values.get("baseline")
        return b if isinstance(b, str) and b in bids else None
    per = _per(rows)
    split = (pm.get("range_split") or {}).get("param")
    cands = []
    for b in bids:
        ok = True
        for name, r in per.items():
            info = r["baselines"].get(b)
            x = values.get(name)
            if info is None or x is None:
                continue
            fe = info.get("feasible") or {"min": info["min"], "max": info["max"]}
            if not (fe["min"] - 1e-12 <= float(x) <= fe["max"] + 1e-12):
                ok = False
                break
        if ok:
            cands.append(b)
    if not cands:
        return None
    if not split or split not in per or values.get(split) is None:
        return cands[0]
    x = float(values[split])
    return min(cands, key=lambda b: (abs(x - per[split]["baselines"][b]["nominal"]) if per[split]["baselines"].get(b) else math.inf,
                                     bids.index(b)))


def original_values(rows: Sequence[Mapping[str, Any]], bid: str, common: Mapping[str, Any]) -> dict[str, float]:
    """공통 이름 값 → 그 baseline 원 파라미터 이름 값(values.json 키, §4.10). N/A 변수·값 없음은 넣지 않는다."""
    out: dict[str, float] = {}
    for name, r in _per(rows).items():
        info = r["baselines"].get(bid)
        x = common.get(name)
        if info is not None and x is not None:
            out[str(info["param"])] = float(x)
    return out


def na_names(pm: Mapping[str, Any], rows: Sequence[Mapping[str, Any]]) -> list[str]:
    """어느 baseline에서든 N/A인 공통 변수(결측 지시 열 대상)."""
    bids = baseline_ids(pm)
    return [n for n, r in _per(rows).items() if any(r["baselines"].get(b) is None for b in bids)]


def training_columns(pm: Mapping[str, Any], rows: Sequence[Mapping[str, Any]], extra: Sequence[str] = ()) -> list[str]:
    """학습 입력 열(§7.3.8): 공통 변수 + 쉘 두께 등 extra + `<이름>__na`(N/A 가능 변수) + topology면 `baseline__<id>` 원-핫."""
    cols = list(_per(rows)) + list(extra)
    cols += [n + NA_SUFFIX for n in na_names(pm, rows)]
    if pm.get("usage") == "topology":
        cols += [ONEHOT_PREFIX + b for b in baseline_ids(pm)]
    return cols


def training_values(pm: Mapping[str, Any], rows: Sequence[Mapping[str, Any]], bid: str, common: Mapping[str, Any],
                    extra: Mapping[str, float] | None = None) -> dict[str, float]:
    """학습 입력 값: N/A 변수는 0 대체 + 지시 열 1(아니면 0), topology 원-핫. run 메타(null)와 달리 여기서만 0 대체."""
    per = _per(rows)
    out: dict[str, float] = {}
    for name, r in per.items():
        na = r["baselines"].get(bid) is None or common.get(name) is None
        out[name] = 0.0 if na else float(common[name])
    for k, v in (extra or {}).items():
        out[k] = float(v)
    for name in na_names(pm, rows):
        out[name + NA_SUFFIX] = 1.0 if (per[name]["baselines"].get(bid) is None or common.get(name) is None) else 0.0
    if pm.get("usage") == "topology":
        for b in baseline_ids(pm):
            out[ONEHOT_PREFIX + b] = 1.0 if b == bid else 0.0
    return out


def training_snapshot(pm: Mapping[str, Any], rows: Sequence[Mapping[str, Any]], extra_rows: Sequence[Mapping[str, Any]] = ()
                      ) -> list[dict[str, Any]]:
    """DOE parameters_snapshot(학습 입력 열과 같은 순서): 공통 행 + extra 행 + 지시·원-핫 열(0~1)."""
    snap = [{"name": r["name"], "nominal": r["nominal"], "min": r["min"], "max": r["max"], "unit": r.get("unit", "")}
            for r in _per(rows).values()]
    snap += [{"name": r["name"], "nominal": r["nominal"], "min": r["min"], "max": r["max"], "unit": r.get("unit", "")} for r in extra_rows]
    for n in na_names(pm, rows):
        snap.append({"name": n + NA_SUFFIX, "nominal": 0.0, "min": 0.0, "max": 1.0, "unit": ""})
    if pm.get("usage") == "topology":
        snap += [{"name": ONEHOT_PREFIX + b, "nominal": 0.0, "min": 0.0, "max": 1.0, "unit": ""} for b in baseline_ids(pm)]
    return snap


# ------------------------------------------------------------------ 층화 LHS(§7.3.8 DOE)
def stratum_counts(n: int, b: int) -> list[int]:
    """n_b = ⌊N/B⌋ + (앞쪽 baseline부터 나머지 1씩) — 수준별 샘플 수 차 ≤ 1."""
    q, r = divmod(int(n), int(b))
    return [q + (1 if k < r else 0) for k in range(b)]


def _split_intervals(pm: Mapping[str, Any], per_split: Mapping[str, Any]) -> dict[str, tuple[float, float]]:
    """range: 분할 변수 구간 = 인접 공칭의 중점 경계, 양 끝은 그 baseline 범위 끝."""
    ivs = [iv for iv in (pm.get("range_split") or {}).get("intervals") or [] if isinstance(iv, dict)]
    order = sorted(((float(iv["nominal"]), str(iv["baseline"])) for iv in ivs if iv.get("baseline") in per_split
                    and per_split[iv["baseline"]] is not None), key=lambda t: t)
    out: dict[str, tuple[float, float]] = {}
    for k, (nom, b) in enumerate(order):
        lo = (order[k - 1][0] + nom) / 2 if k > 0 else -math.inf
        hi = (nom + order[k + 1][0]) / 2 if k + 1 < len(order) else math.inf
        out[b] = (lo, hi)
    return out


def range_gaps(pm: Mapping[str, Any], rows: Sequence[Mapping[str, Any]]) -> list[str]:
    """range: 분할 변수 구간이 그 baseline feasible과 겹치지 않거나 인접 feasible 사이에 틈이 있으면 경고 대상(BASELINE_RANGE_GAP)."""
    per = _per(rows)
    split = (pm.get("range_split") or {}).get("param")
    if pm.get("usage") != "range" or split not in per:
        return []
    bl = per[split]["baselines"]
    fe = sorted(((info["feasible"] or info)["min"], (info["feasible"] or info)["max"], b) for b, info in bl.items() if info)
    return [f"{fe[k][2]}–{fe[k + 1][2]}" for k in range(len(fe) - 1) if fe[k][1] < fe[k + 1][0]]


def stratified_lhs(pm: Mapping[str, Any], rows: Sequence[Mapping[str, Any]], n: int, seed: int,
                   lhs: Callable[[Sequence[str], Mapping[str, tuple[float, float]], int, int], list[dict[str, float]]],
                   run_key: Callable[[int], str], extra: Mapping[str, tuple[float, float]] | None = None
                   ) -> list[tuple[int, str, str, dict[str, float | None]]]:
    """baseline별 층화 LHS → [(doe_no, run_key, baseline_id, {공통 이름: 값|None})]. 층 k(0부터)의 seed = seed + k(결정적).
    (a) topology: 층 변수 = 그 baseline 활성 변수의 그 baseline 범위. (b) range: 분할 변수 = 담당 구간(인접 공칭 중점 경계)을
    그 baseline feasible로 자른 구간, 나머지 활성 변수 = 그 baseline 범위. N/A 변수 = None.
    extra = baseline과 무관한 변수(쉘 두께 등) {이름: (min, max)} — 모든 층에서 같은 범위로 함께 뽑는다."""
    per = _per(rows)
    bids = baseline_ids(pm)
    counts = stratum_counts(n, len(bids))
    split = (pm.get("range_split") or {}).get("param") if pm.get("usage") == "range" else None
    ivs = _split_intervals(pm, per[split]["baselines"]) if split in per else {}
    out: list[tuple[int, str, str, dict[str, float | None]]] = []
    doe_no = 0
    for k, (b, nb) in enumerate(zip(bids, counts)):
        if nb <= 0:
            continue
        names = [name for name, r in per.items() if r["baselines"].get(b) is not None]
        bounds: dict[str, tuple[float, float]] = {}
        for name in names:
            info = per[name]["baselines"][b]
            lo, hi = float(info["min"]), float(info["max"])
            if name == split and b in ivs:
                fe = info.get("feasible") or {"min": lo, "max": hi}
                lo, hi = max(ivs[b][0], float(fe["min"])), min(ivs[b][1], float(fe["max"]))
                if lo > hi:  # 담당 구간이 feasible 밖 = 미커버 구간 → 그 baseline 범위로(배정이 NO_COVER로 걸러냄)
                    lo, hi = float(info["min"]), float(info["max"])
            bounds[name] = (lo, hi)
        for name, bd in (extra or {}).items():
            names.append(name)
            bounds[name] = (float(bd[0]), float(bd[1]))
        samples = lhs(names, bounds, nb, seed + k) if names else [{} for _ in range(nb)]
        for vals in samples:
            doe_no += 1
            row: dict[str, float | None] = {name: (vals.get(name) if name in vals else None) for name in per}
            row.update({name: vals[name] for name in (extra or {})})
            out.append((doe_no, run_key(doe_no), b, row))
    return out
