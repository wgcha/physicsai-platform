"""⑥ 내장 최적화 문제 정의의 부분 규칙(R-B 300줄 분할 — `surrogate_opt_problem`에서 분리): 변수 범위·가중치·다중 baseline·
수준·제약 행·성능 미리보기. 동작 불변, `normalize`가 호출한다(위 모듈은 이 모듈을 import, 반대는 없음)."""

from __future__ import annotations

import math
from typing import Any

from physicsai_core.errors import DomainError
from physicsai_core.stage4_predict import nearest, performance

from ..context import AppContext
from .surrogate_opt_metrics import PERF_PREFIX, _p

# ---- 정규화(미리보기·생성 공용) --------------------------------------------------------------------------


def _bounds(ps: dict[str, Any], body: Any, so: Any, problems: list[dict[str, Any]], *, native: bool = False
            ) -> tuple[list[str], list[str], dict, dict]:
    """변수 범위 정규화. native=True(native-vars.md NV-7): 유한·하한 ≤ 상한만 검사하고 `BOUNDS_OUT_OF_RANGE`는 내지 않는다
    (학습·모핑 가능 범위 밖은 호출부가 경고로). Altair는 기존 그대로(세트 min·max 안만)."""
    params = list(ps["parameters"])
    names = [str(p["name"]) for p in params]
    integer = sorted(set(nearest.integer_vars(list(ps.get("tpl_params") or []))) & set(names))
    given = body.bounds or {}
    for k in given:
        if k not in names:
            _p(problems, "BOUNDS_INVALID", f"'{k}'는 템플릿 파라미터가 아닙니다", f"bounds.{k}")
    bounds: dict[str, list[float]] = {}
    for p in params:
        n, tlo, thi = str(p["name"]), float(p["min"]), float(p["max"])
        b = given.get(n)
        if b is None:
            bounds[n] = [tlo, thi]
            continue
        if len(b) != 2 or not all(isinstance(v, (int, float)) and math.isfinite(v) for v in b) or b[0] > b[1]:
            _p(problems, "BOUNDS_INVALID", f"'{n}' 범위는 유한한 [하한, 상한]이고 하한 ≤ 상한이어야 합니다", f"bounds.{n}")
            continue
        lo, hi = float(b[0]), float(b[1])
        if not native and (lo < tlo - 1e-12 * max(1.0, abs(tlo)) or hi > thi + 1e-12 * max(1.0, abs(thi))):
            _p(problems, "BOUNDS_OUT_OF_RANGE", f"'{n}' 범위는 학습 범위 {tlo:g}~{thi:g} 안이어야 합니다", f"bounds.{n}")
            continue
        if n in integer and lo < hi and math.ceil(lo - 1e-9) > math.floor(hi + 1e-9):  # s12_s13.md 기존 규칙: 범위 안에 정수가 아예 없음
            _p(problems, "BOUNDS_INVALID", f"'{n}'(정수) 범위 안에 정수가 없습니다", f"bounds.{n}")
            continue
        if n in integer and not nearest.is_integer_range(lo, hi):  # altair-vars.md §5.1: PUT variables·④ 일괄과 공용 검사
            _p(problems, nearest.INT_RANGE_CODE, f"'{n}' {nearest.INT_RANGE_MESSAGE}", f"bounds.{n}")
            continue
        bounds[n] = [lo, hi]
    fixed = {n: b[0] for n, b in bounds.items() if b[0] == b[1]}
    free = [n for n in names if n in bounds and n not in fixed]
    if not free and len(bounds) == len(names):
        _p(problems, "NO_FREE_VARIABLE", "범위가 있는 자유 변수가 1개 이상 필요합니다", "bounds")
    if len(free) > so.max_variables:
        _p(problems, "TOO_MANY_VARIABLES", f"자유 변수는 최대 {so.max_variables}개입니다(현재 {len(free)}개)", "bounds")
    return names, integer, bounds, fixed


def _weights(body: Any, m: int, problems: list[dict[str, Any]]) -> list[float]:
    if body.weights is None:  # ON-C4: 다목적 가중치는 자동으로 채우지 않는다(빈 항목은 criteria가 422로 막음)
        return [1.0] if m == 1 else []
    w = list(body.weights)
    if len(w) != m or any(not math.isfinite(x) or x < 0 for x in w) or sum(w) <= 0:
        _p(problems, "WEIGHTS_INVALID", "가중치는 목적 수와 같은 개수의 0 이상 유한 수이고 합이 0보다 커야 합니다", "weights")
        return [1.0 / m] * m if m else []
    tot = sum(w)
    return [x / tot for x in w]


def multi_baseline(ctx: AppContext, ps: dict[str, Any]) -> dict[str, Any] | None:
    """다중 baseline 세트면 확정 매칭표 {usage, baselines, pm}(opt-native §7 — 409 MULTI_BASELINE_UNSUPPORTED 조건부 해제).
    미확정이면 409 PARAM_MAP_UNCONFIRMED. 단일 세트면 None."""
    from physicsai_core.geometry import baselines as bl

    from .param_set_native_api import set_path

    S = set_path(ctx, ps)
    if not bl.is_multi(S):
        return None
    try:
        pm = bl.load(S, ctx.settings.ui.max_artifact_bytes)
    except bl.MapError as exc:
        raise DomainError(exc.code, exc.message, status=409, param_set_id=ps["id"]) from None
    if not pm or pm.get("status") != "confirmed":
        raise DomainError("PARAM_MAP_UNCONFIRMED", "매칭표가 확정되지 않았습니다 — ③ 매칭표를 확정한 뒤 최적화하세요",
                          status=409, param_set_id=ps["id"])
    return {"usage": pm.get("usage"), "baselines": bl.baseline_ids(pm), "pm": pm}


def _multi_settings(multi: dict[str, Any], ps: dict[str, Any], levels: list[str] | None) -> dict[str, Any]:
    """settings.multi_baseline(opt-native §7): 위상 변형 = 선택 수준별 활성 표·N/A 가능 이름(학습 열 순서), 범위 분할 = baseline별 feasible."""
    rows = [r for r in ps["parameters"] if isinstance(r.get("baselines"), dict)]
    out: dict[str, Any] = {"usage": multi["usage"], "baselines": list(multi["baselines"])}
    if multi["usage"] == "topology":
        lv = list(levels or multi["baselines"])
        act = {str(r["name"]): [r["baselines"].get(b) is not None for b in lv] for r in rows}
        out["active"] = {n: a for n, a in act.items() if not all(a)}
        out["na"] = [n for n in act if not all(act[n])]
    else:
        cover: dict[str, dict[str, list[float] | None]] = {}
        for r in rows:
            per: dict[str, list[float] | None] = {}
            for b in multi["baselines"]:
                info = r["baselines"].get(b)
                fe = (info.get("feasible") or {"min": info["min"], "max": info["max"]}) if isinstance(info, dict) else None
                per[b] = [float(fe["min"]), float(fe["max"])] if fe else None
            cover[str(r["name"])] = per
        out["cover"] = cover
    return out


def _levels(multi: dict[str, Any] | None, body: Any, so: Any, problems: list[dict[str, Any]]) -> list[str] | None:
    """범주 baseline 수준(위상 변형 세트만, 매칭표 baseline 순서). 요청 levels로 줄일 수 있고 1개면 고정."""
    given = body.levels
    if multi is None or multi["usage"] != "topology":
        if given:
            _p(problems, "LEVELS_INVALID", "수준(levels)은 다중 baseline 위상 변형 세트에서만 쓸 수 있습니다", "levels")
        return None
    ids = list(multi["baselines"])
    lv = ids
    if given is not None:
        bad = [k for k in given if k != "baseline"]
        if bad:
            _p(problems, "LEVELS_INVALID", f"수준은 baseline 변수만 줄 수 있습니다: {', '.join(bad)}", "levels")
        sel = given.get("baseline")
        if sel is not None:
            unknown = [x for x in sel if x not in ids]
            if not sel:
                _p(problems, "LEVELS_INVALID", "baseline 수준 목록이 비어 있습니다", "levels.baseline")
            elif unknown:
                _p(problems, "LEVELS_INVALID", f"매칭표에 없는 baseline입니다: {', '.join(unknown)}", "levels.baseline")
            else:
                lv = [b for b in ids if b in sel]
    if len(lv) > so.max_levels and not any(p["code"] == "LEVELS_INVALID" for p in problems):
        _p(problems, "TOO_MANY_LEVELS", f"baseline 수준은 최대 {so.max_levels}개입니다(현재 {len(lv)}개)", "levels.baseline")
    return lv


def _constraint_row(c: Any) -> dict[str, Any]:
    row: dict[str, Any] = {"metric": c.metric, "series": c.series, "op": c.op,
                           "value": None if c.value is None else float(c.value)}
    if c.op == "range":
        row.update(value=None, lo=float(c.lo) if c.lo is not None else None, hi=float(c.hi) if c.hi is not None else None)
    return row


def _perf_info(perfs: dict[str, Any], rows: list[tuple[dict[str, Any], Any]] | None) -> list[dict[str, Any]]:
    """미리보기 `performances`(§22.4.2): 재사용이면 값 있는 run·전체 성공 run·SPEC_CHANGED run 수."""
    out = []
    for name, d in perfs.items():
        x: dict[str, Any] = {"id": f"{PERF_PREFIX}{name}", "name": name, "unit": d.unit, "source": d.source, "stat": d.stat,
                             "label": performance.perf_label(d), "available": None, "total": None, "spec_changed": None}
        if rows is not None:
            ok = [mm for _r, mm in rows if mm is not None]
            vals = [performance.perf_value(d, mm) for mm in ok]
            x.update(available=sum(1 for v, _w in vals if v is not None), total=len(ok),
                     spec_changed=sum(1 for _v, w in vals if w == "SPEC_CHANGED"))
        out.append(x)
    return out
