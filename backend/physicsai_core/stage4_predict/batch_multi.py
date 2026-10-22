"""④ 일괄 생성의 다중 baseline 조합(geometry-engine.md §7.3.8): 확정 세트 + source(lhs) → baseline별 층화 LHS 행.

- 지원 source = `registry.SITE_KINDS["batch_multi"]`(lhs·lhs_opt·halton·random, doe-methods.md DM-C4: count·seed(+criterion), ranges는 쓰지 않음 —
  층 범위는 baseline별 대응 범위, 층 seed = seed + 층 번호). 다른 kind는 문제(MULTI_BASELINE_SOURCE → BATCH_SOURCE_INVALID).
- 행 값(predict_batch_runs.values) = 공통 이름 + 쉘 두께, N/A 변수는 0(학습 입력 규칙과 같음 — run 메타 values.json에서는 null).
- 배정: topology = 층 baseline, range = 배정 규칙(`assign_baseline`), 없으면 None → 생성 때 BASELINE_NO_COVER로 스킵.
  배정·층은 배치 source_meta `multi_baseline`({usage, stratum:{doe_no: id}, assign:{doe_no: id|null}})에 둔다(DB 열 없음, §7.5).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..geometry import baselines as bl
from ..geometry import shell as sh
from ..sampling.layer_gen import layer_generator
from ..sampling.qmc import GeneratorUnavailable, generator_label
from ..sampling.registry import METHODS, MULTI_UNSUPPORTED_MESSAGE, SITE_KINDS
from . import nearest
from .batch_matrix import BatchMatrix, BatchRow, BatchShapeError, run_key_for


def build_multi_matrix(source: Mapping[str, Any], param_set: Mapping[str, Any], pm: Mapping[str, Any], settings: Any) -> BatchMatrix:
    problems: list[dict[str, Any]] = []
    kind = source.get("kind")
    if kind not in SITE_KINDS["batch_multi"]:  # doe-methods.md DM-C4: 층 안 생성기 lhs·lhs_opt·halton·random만
        problems.append({"code": "MULTI_BASELINE_SOURCE", "message": MULTI_UNSUPPORTED_MESSAGE})
        return BatchMatrix("LHS", [], problems, {}, [])
    source_kind = METHODS[kind][0]
    criterion = source.get("criterion") or "maximin"
    if criterion not in ("maximin", "corr"):
        raise BatchShapeError("source.criterion은 maximin | corr 중 하나입니다")
    if source.get("criterion") is not None and kind != "lhs_opt":
        raise BatchShapeError("source.criterion은 최적화 LHS(lhs_opt)에서만 쓸 수 있습니다")
    count, seed = source.get("count"), source.get("seed", 1)
    if isinstance(count, bool) or not isinstance(count, int):
        raise BatchShapeError("source.count는 정수여야 합니다")
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise BatchShapeError("source.seed는 정수여야 합니다")
    if source.get("ranges"):
        problems.append({"code": "RANGE_INVALID", "message": "다중 baseline 세트는 ranges를 쓸 수 없습니다(층 범위 = baseline별 대응 범위)"})
    if count < 2:
        problems.append({"code": "TOO_FEW_ROWS", "message": "조합 수는 2개 이상이어야 합니다"})
    elif count > settings.predict_batch.max_runs:
        problems.append({"code": "TOO_MANY_ROWS", "message": f"조합 수는 최대 {settings.predict_batch.max_runs}개입니다"})
    params = list(param_set["parameters"])
    meta: dict[str, Any] = {"count": count, "seed": seed}
    if problems:
        return BatchMatrix(source_kind, [], problems, meta, [])
    if kind == "lhs_opt":
        meta["criterion"] = criterion
    extra = {str(r["name"]): (float(r["min"]), float(r["max"])) for r in sh.prop_rows(params)}
    try:
        raw = bl.stratified_lhs(pm, params, count, seed, layer_generator(kind, criterion), run_key_for, extra)
    except GeneratorUnavailable as exc:
        return BatchMatrix(source_kind, [], [{"code": "GENERATOR_UNAVAILABLE", "message": str(exc)}], meta, [])
    if kind == "halton":
        meta.update({"scramble": True, "generator": generator_label()})
    rows, stratum, assign = [], {}, {}
    for doe_no, rk, bid, vals in raw:
        target = bid if pm.get("usage") == "topology" else bl.assign_baseline(pm, params, vals)
        stratum[str(doe_no)], assign[str(doe_no)] = bid, target
        values = {k: (0.0 if v is None else float(v)) for k, v in vals.items()}
        present = {k: float(v) for k, v in vals.items() if v is not None}
        oor = [o["name"] for o in nearest.out_of_range(params, present)]  # type: ignore[arg-type]
        rows.append(BatchRow(doe_no, rk, values, dict(values), oor))
    meta["multi_baseline"] = {"usage": pm.get("usage"), "baselines": bl.baseline_ids(pm), "stratum": stratum, "assign": assign}
    notes = []
    n_nc = sum(1 for v in assign.values() if v is None)
    if n_nc:
        notes.append({"code": bl.NO_COVER, "message": f"{n_nc}개 조합은 덮는 baseline이 없어 생성 때 스킵됩니다"})
    return BatchMatrix(source_kind, rows, [], meta, notes)


# ---- opt-native §7: 내장 최적화 소유 배치(탐색 LHS·검증·추가 검증 표) ---------------------------------------------


def restrict(pm: Mapping[str, Any], params: list[dict[str, Any]], levels: list[str] | None,
             bounds: Mapping[str, Any] | None) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """매칭표·파라미터 행 사본: baseline을 levels로 줄이고(위상 변형), baseline별 범위를 최적화 범위와 겹치게 자른다(겹침이 없으면 원래 범위)."""
    import copy

    pm2 = copy.deepcopy(dict(pm))
    if levels is not None:
        pm2["baselines"] = [b for b in pm2.get("baselines") or [] if isinstance(b, dict) and b.get("id") in levels]
    rows = copy.deepcopy(list(params))
    for r in rows:
        bd = (bounds or {}).get(str(r.get("name")))
        if not bd:
            continue
        lo, hi = float(bd[0]), float(bd[1])
        if isinstance(r.get("baselines"), dict):
            for info in r["baselines"].values():
                if isinstance(info, dict) and max(lo, float(info["min"])) <= min(hi, float(info["max"])):
                    info["min"], info["max"] = max(lo, float(info["min"])), min(hi, float(info["max"]))
        elif max(lo, float(r["min"])) <= min(hi, float(r["max"])):
            r["min"], r["max"] = max(lo, float(r["min"])), min(hi, float(r["max"]))
    return pm2, rows


def build_multi_table(points: list[Mapping[str, Any]], param_set: Mapping[str, Any], pm: Mapping[str, Any]) -> BatchMatrix:
    """표 조합(내장 최적화 검증·추가 검증 — opt-native §7): 점 = {공통 이름: 값, (위상 변형) "baseline": id}.
    배정: topology = 점의 baseline, range = `assign_baseline`(없으면 None → 생성 때 BASELINE_NO_COVER). 행 값 N/A = 0."""
    params = list(param_set["parameters"])
    per = {str(r["name"]): r for r in params if isinstance(r.get("baselines"), dict)}
    names = [str(r["name"]) for r in params]
    bids = bl.baseline_ids(pm)
    topo = pm.get("usage") == "topology"
    rows, stratum, assign, problems = [], {}, {}, []
    for k, p in enumerate(points, 1):
        b = p.get("baseline") if topo else None
        if topo and b not in bids:
            problems.append({"code": "BASELINE_INVALID", "message": f"{k}행: baseline '{b}'이 매칭표에 없습니다"})
            continue
        vals: dict[str, float | None] = {}
        for n in names:
            v = p.get(n)
            act = n not in per or (per[n]["baselines"].get(b) is not None if topo else True)
            vals[n] = float(v) if (act and isinstance(v, (int, float))) else None
        target = b if topo else bl.assign_baseline(pm, params, {n: v for n, v in vals.items() if v is not None})
        if not topo and target is not None:  # 범위 분할: 배정 baseline에서 비활성인 변수는 N/A
            vals = {n: (None if n in per and per[n]["baselines"].get(target) is None else v) for n, v in vals.items()}
        stratum[str(k)], assign[str(k)] = target, target
        values = {n: (0.0 if v is None else float(v)) for n, v in vals.items()}
        present = {n: float(v) for n, v in vals.items() if v is not None}
        oor = [o["name"] for o in nearest.out_of_range(params, present)]  # type: ignore[arg-type]
        rows.append(BatchRow(k, run_key_for(k), values, dict(values), oor))
    meta = {"multi_baseline": {"usage": pm.get("usage"), "baselines": bids, "stratum": stratum, "assign": assign}}
    notes = []
    n_nc = sum(1 for v in assign.values() if v is None)
    if n_nc:
        notes.append({"code": bl.NO_COVER, "message": f"{n_nc}개 조합은 덮는 baseline이 없어 생성 때 스킵됩니다"})
    return BatchMatrix("TABLE", rows, problems, meta, notes)
