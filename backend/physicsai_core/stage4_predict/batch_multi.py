"""④ 일괄 생성의 다중 baseline 조합(geometry-engine.md §7.3.8): 확정 세트 + source(lhs) → baseline별 층화 LHS 행.

- 지원 source = lhs(count·seed, ranges는 쓰지 않음 — 층 범위는 baseline별 대응 범위). 다른 kind는 문제(BATCH_SOURCE_INVALID).
- 행 값(predict_batch_runs.values) = 공통 이름 + 쉘 두께, N/A 변수는 0(학습 입력 규칙과 같음 — run 메타 values.json에서는 null).
- 배정: topology = 층 baseline, range = 배정 규칙(`assign_baseline`), 없으면 None → 생성 때 BASELINE_NO_COVER로 스킵.
  배정·층은 배치 source_meta `multi_baseline`({usage, stratum:{doe_no: id}, assign:{doe_no: id|null}})에 둔다(DB 열 없음, §7.5).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..geometry import baselines as bl
from ..geometry import shell as sh
from . import nearest
from .batch_matrix import BatchMatrix, BatchRow, BatchShapeError, lhs_values, run_key_for


def build_multi_matrix(source: Mapping[str, Any], param_set: Mapping[str, Any], pm: Mapping[str, Any], settings: Any) -> BatchMatrix:
    problems: list[dict[str, Any]] = []
    if source.get("kind") != "lhs":
        problems.append({"code": "MULTI_BASELINE_SOURCE", "message": "다중 baseline 세트의 일괄 생성은 LHS(lhs)만 지원합니다(baseline별 층화)"})
        return BatchMatrix("LHS", [], problems, {}, [])
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
        return BatchMatrix("LHS", [], problems, meta, [])
    extra = {str(r["name"]): (float(r["min"]), float(r["max"])) for r in sh.prop_rows(params)}
    raw = bl.stratified_lhs(pm, params, count, seed, lhs_values, run_key_for, extra)
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
    return BatchMatrix("LHS", rows, [], meta, notes)
