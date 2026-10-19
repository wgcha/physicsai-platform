"""④ PREDICT PR_PREP의 prepared(준비된 입력) 분기와 일괄 예측 하위 run 행 조회(phase3 §11.5·§14.5)."""

from __future__ import annotations

import os
from typing import Any

from physicsai_core.errors import StepFailure
from physicsai_core.fileutil import write_json

from .predict_inputs import check_prepared, param_set
from .predict_inputs import predict_dir as _P


def pr_prep_prepared(ctx: Any, m: dict[str, Any]) -> None:
    """PR_PREP(prepared, phase3 §11.5): 입력 재검사·params.json. 형상 값 없음."""
    plan = check_prepared(ctx)
    ps, _S = param_set(ctx)
    P = _P(ctx)
    os.makedirs(P, exist_ok=True)
    pj = os.path.join(P, "params.json")
    ctx.backup([pj])
    write_json(pj, {
        "input_mode": "prepared", "input_path": ctx.params["input_path"], "input_kind": plan.kind,
        "starter_name": plan.starter, "files": [os.path.basename(f) for f in plan.files], "values": {},
        "model_id": m["id"], "param_set_id": ps["id"] if ps else None, "nearest": None,
    })
    res = {
        "model_id": m["id"], "param_set_id": ps["id"] if ps else None, "input_mode": "prepared",
        "input_path": ctx.params["input_path"], "values": {}, "applied_values": {}, "out_of_range": [], "nearest": None,
    }
    run = batch_run_row(ctx)
    if run is not None:  # 일괄 예측 하위(phase3 §14.5): 입력값은 run 행에서
        res.update(values=run["values"], applied_values=run["applied_values"], out_of_range=list(run["out_of_range"] or []),
                   batch={"batch_id": run["batch_id"], "doe_no": run["doe_no"], "run_key": run["run_key"]})
    ctx.patch_result(res)


def batch_run_row(ctx: Any) -> dict[str, Any] | None:
    from physicsai_core.db.repositories import predict_batches as pb_repo

    ref = pb_repo.batch_run_ref(ctx.job)
    if ref is None:
        return None
    with ctx.ex.engine.connect() as conn:
        rows = [r for r in pb_repo.runs(conn, ref[0]) if r["doe_no"] == ref[1]]
    if not rows:
        raise StepFailure("INPUT_INVALID", "일괄 예측 run 행을 찾을 수 없습니다")
    return rows[0]
