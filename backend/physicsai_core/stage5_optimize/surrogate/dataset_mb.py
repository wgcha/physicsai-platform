"""opt-native §7 다중 baseline(위상 변형 범주 · 범위 분할) spec·판정 — 표준 라이브러리만. dataset에서 재노출."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

# ---- opt-native §7: 다중 baseline(위상 변형 범주 · 범위 분할) — 표준 라이브러리 ----------------------------------

CAT = "baseline"


def cat_spec(settings: Mapping[str, Any]) -> dict[str, Any] | None:
    """범주 spec(위상 변형 세트만): {cat, levels, active: {이름: [수준별 활성]}, na: [N/A 가능 이름]}. 없으면 None."""
    mb = settings.get("multi_baseline")
    if not isinstance(mb, Mapping) or mb.get("usage") != "topology":
        return None
    levels = list((settings.get("levels") or {}).get(CAT) or [])
    if not levels:
        return None
    return {"cat": CAT, "levels": levels, "active": {k: [bool(x) for x in v] for k, v in (mb.get("active") or {}).items()},
            "na": list(mb.get("na") or [])}


def cover_spec(settings: Mapping[str, Any]) -> dict[str, Any] | None:
    """범위 분할 spec: {baselines: [id], per: {이름: {id: [feasible 하한, 상한] | None}}}. 없으면 None."""
    mb = settings.get("multi_baseline")
    if not isinstance(mb, Mapping) or mb.get("usage") != "range":
        return None
    return {"baselines": list(mb.get("baselines") or []), "per": dict(mb.get("cover") or {})}


def covered(values: Mapping[str, Any], spec: Mapping[str, Any]) -> bool:
    """범위 분할: 활성 값이 모두 feasible 안인 baseline이 하나라도 있으면 True(`baselines.assign_baseline` ≠ None과 같은 판정)."""
    for b in spec["baselines"]:
        ok = True
        for name, per in spec["per"].items():
            rg = per.get(b)
            x = values.get(name)
            if rg is None or x is None:
                continue
            if not (float(rg[0]) - 1e-12 <= float(x) <= float(rg[1]) + 1e-12):
                ok = False
                break
        if ok:
            return True
    return False


def canonical_values(values: Mapping[str, Any], spec: Mapping[str, Any] | None) -> dict[str, Any]:
    """범주 수준에서 비활성인 공통 변수 = 0.0(배치 values의 N/A 규칙)."""
    out = dict(values)
    if spec is None or out.get(spec["cat"]) is None:
        return out
    li = int(round(float(out[spec["cat"]])))
    for n, act in spec["active"].items():
        if n in out and 0 <= li < len(act) and not act[li]:
            out[n] = 0.0
    return out


def run_values(applied: Mapping[str, Any] | None, source_meta: Mapping[str, Any] | None, doe_no: int,
               spec: Mapping[str, Any] | None) -> dict[str, float]:
    """run 반영값 → 설계 값. 위상 변형 범주 세트면 배치 source_meta.multi_baseline.assign의 baseline을 수준 인덱스로 더한다
    (선택 수준 밖·배정 없음이면 넣지 않음 — 그 run은 실패 설계가 된다)."""
    vals = {k: float(v) for k, v in (applied or {}).items() if isinstance(v, (int, float)) and not isinstance(v, bool)}
    if spec is None:
        return vals
    bid = (((source_meta or {}).get("multi_baseline") or {}).get("assign") or {}).get(str(doe_no))
    if isinstance(bid, str) and bid in spec["levels"]:
        vals[spec["cat"]] = float(spec["levels"].index(bid))
    return canonical_values(vals, spec)


def tag_baseline(rows: list[dict[str, Any]], problem: Any) -> list[dict[str, Any]]:
    """후보·예측 전선 행에 범주 수준 id(`baseline`)를 붙인다(화면 표시용, values에는 수준 인덱스)."""
    spec = problem.cat_spec
    if spec is None:
        return rows
    for r in rows:
        v = (r.get("values") or {}).get(spec["cat"])
        if isinstance(v, (int, float)) and 0 <= int(round(v)) < len(spec["levels"]):
            r["baseline"] = spec["levels"][int(round(v))]
    return rows
