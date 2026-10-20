"""⑤ 플랫폼 내장 최적화 조회(목록·상세·진행 문구·최종 결과·run CSV) — surrogate_opts에서 재노출."""

from __future__ import annotations

from typing import Any

from physicsai_core.db.repositories import jobs as jobs_repo
from physicsai_core.db.repositories import param_sets as ps_repo
from physicsai_core.db.repositories import predict_batches as pb_repo
from physicsai_core.db.repositories import studies as studies_repo
from physicsai_core.db.repositories import surrogate_opts as so_repo
from physicsai_core.errors import DomainError
from physicsai_core.paths import display_path
from physicsai_core.stage4_predict.batch_matrix import batch_label
from physicsai_core.stage5_optimize.surrogate import dataset as ds

from ..auth import Principal
from ..context import AppContext
from . import surrogate_opt_pareto as so_pareto
from .surrogate_opt_problem import metric_value as _metric_value
from .surrogate_opt_problem import run_metric_rows as _run_metric_rows
from .surrogate_opt_problem import snapshot_perfs
from .surrogate_opt_problem import value as _value

FAIL_TEXT = {
    "BATCH_FAILED": "검증·탐색 배치 입력 생성이 실패했습니다", "ROUND_FAILED": "반복 작업이 실패했습니다",
    ds.FAIL_VERIFY_ALL: "검증 run이 모두 실패했습니다", ds.FAIL_TOO_FEW: "유효 run이 부족합니다 — 탐색 run 수를 늘리세요",
    ds.FAIL_TIMEOUT: "대리모델 학습 시간을 넘었습니다", "SURROGATE_FIT_FAILED": "대리모델을 적합할 수 없습니다",
    "NO_FREE_VARIABLE": "자료에서 바뀌는 자유 변수가 없습니다",
}
STOP_TEXT = {ds.STOP_CONVERGED: "수렴", ds.STOP_MAX_ITER: "최대 반복", ds.STOP_NO_NEW: "새 후보 없음"}


def _require_opt(conn: Any, opt_id: str, *, for_update: bool = False) -> dict[str, Any]:
    o = so_repo.get(conn, opt_id, for_update=for_update)
    if o is None:
        raise DomainError("SURROGATE_OPT_NOT_FOUND", "내장 최적화를 찾을 수 없습니다", status=404)
    return o


# ---- 조회 -----------------------------------------------------------------------------------------


def list_opts(ctx: AppContext, study_id: str) -> list[dict[str, Any]]:
    with ctx.engine.connect() as conn:
        studies_repo.require(conn, study_id)
        rows = so_repo.list_for_study(conn, study_id)
    return [{"id": o["id"], "label": so_repo.opt_label(o["opt_no"]), "status": o["status"],
             "objective": o["settings"]["objective"], "best_value": (o["best"] or {}).get("objective"),
             "iter_no": o["iter_no"], "iterations": o["settings"]["iterations"], "created_at": o["created_at"],
             "created_by_name": o["created_by_name"]} for o in rows]


def collect_runs(ctx: AppContext, conn: Any, study: dict[str, Any], o: dict[str, Any], its: list[dict[str, Any]]
                 ) -> list[dict[str, Any]]:
    """반복마다 배치 run 전부의 목적들·제약·관찰·예측·만족 여부(run_metrics·성능 스냅샷, 성공 run만 값)."""
    problem = ds.Problem.from_settings(o["settings"])
    perfs = snapshot_perfs(o["settings"])
    out = []
    for it in its:
        b = pb_repo.get(conn, it["batch_id"])
        if b is None:
            continue
        preds = {c.get("doe_no"): c.get("predicted") for c in it.get("candidates") or []}
        for r, mm in _run_metric_rows(ctx, conn, study, b["id"]):
            state = pb_repo.row_state(r, r["job_state"])
            reasons: dict[str, str] = {}

            def val(metric: str, series: str | None, key: str, r: dict[str, Any] = r, mm: Any = mm,
                    reasons: dict[str, str] = reasons) -> float | None:
                v, why = _metric_value(mm, metric, series, r["responses"], perfs)
                if v is None and why and mm is not None:
                    reasons.setdefault(key, why)
                return v

            objs = [val(x.metric, x.series, x.key) for x in problem.objectives]
            cons = [val(c.metric, c.series, c.key) for c in problem.constraints]
            obs = {x.key: val(x.metric, x.series, x.key) for x in problem.observe}
            valid = state == "SUCCEEDED" and all(v is not None for v in objs) and all(v is not None for v in cons)
            out.append({"iter_no": it["iter_no"], "batch_id": b["id"], "batch_label": batch_label(b["batch_no"]),
                        "doe_no": r["doe_no"], "run_key": r["run_key"], "job_id": r["predict_job_id"],
                        "values": r["applied_values"], "objective": objs[0], "constraints": cons,
                        "predicted": preds.get(r["doe_no"]),
                        "feasible": ds.is_feasible(cons, problem.constraints) if valid else None, "state": state,
                        "objectives": objs, "observed": obs, "reason": next(iter(reasons.values()), None),
                        "on_front": False, "kind": it["kind"]})
    return out


def _stop_text(o: dict[str, Any], its: list[dict[str, Any]]) -> str:
    reason = o["stop_reason"] or ""
    if reason == ds.STOP_CONVERGED:
        imp = next((it["improvement_rel"] for it in reversed(its) if it["improvement_rel"] is not None), None)
        if imp is not None:
            return f"수렴(개선 {imp * 100:.1f}% < {o['settings']['tol_rel'] * 100:g}%)"
    return STOP_TEXT.get(reason, reason)


def progress_text(o: dict[str, Any], its: list[dict[str, Any]], batches: dict[str, dict[str, Any]], fail_msg: str | None) -> str:
    st = o["status"]
    T = o["settings"]["iterations"]
    cur = next((it for it in its if it["iter_no"] == o["iter_no"]), None)
    b = batches.get(cur["batch_id"]) if cur else None
    if st == "EXPLORING" and b:
        if b["gen"]["done"] + b["gen"]["failed"] < b["gen"]["total"]:
            return f"탐색 {b['label']} · 입력 생성 {b['gen']['done']}/{b['gen']['total']}"
        return f"탐색 {b['label']} · 예측 완료 {b['predict']['succeeded']}/{b['gen']['total']}"
    if st == "FITTING":
        return f"반복 {o['iter_no'] + 1}/{T} · 대리모델 학습"
    if st == "VERIFYING" and b:
        return f"반복 {o['iter_no']}/{T} · 검증 {b['label']} 예측 {b['predict']['succeeded']}/{b['gen']['total']}"
    if st == "FINALIZING":
        fb = batches.get(((o.get("final") or {}).get("batch_id")) or "")
        cnt = f" {fb['label']} 예측 {fb['predict']['succeeded']}/{fb['gen']['total']}" if fb else ""
        return f"마무리 — 기준안·최적안 컨투어 캡처{cnt}"
    if st == "DONE":
        return f"완료 — {_stop_text(o, its)}"
    if st == "FAILED":
        return f"실패 — {FAIL_TEXT.get(o['stop_reason'] or '', o['stop_reason'] or '')}" + (f": {fail_msg}" if fail_msg else "")
    if st == "CANCELED":
        return "취소됨"
    return st


def _detail(ctx: AppContext, conn: Any, o: dict[str, Any], principal: Principal) -> dict[str, Any]:
    s = studies_repo.require(conn, o["study_id"])
    ps = ps_repo.get(conn, o["param_set_id"]) or {}
    from physicsai_core.db.repositories import models as models_repo

    m = models_repo.get(conn, o["model_id"]) or {}
    its_all = so_repo.iters(conn, o["id"])
    its = [it for it in its_all if it["kind"] != "FINAL"]  # D3-61 마무리 캡처 배치는 반복이 아니다
    batches: dict[str, dict[str, Any]] = {}
    for it in its_all:
        b = pb_repo.get(conn, it["batch_id"])
        if b is not None:
            batches[b["id"]] = {"id": b["id"], "label": batch_label(b["batch_no"]), "status": b["status"],
                                **pb_repo.counts(conn, b["id"])}
    runs = collect_runs(ctx, conn, s, o, its)
    by = {(r["iter_no"], r["doe_no"]): r for r in runs}
    iterations = []
    for it in its:
        cands = None
        if it.get("candidates"):
            cands = [{**c, "verified": (by.get((it["iter_no"], c.get("doe_no"))) or {}).get("objective"),
                      "state": (by.get((it["iter_no"], c.get("doe_no"))) or {}).get("state")} for c in it["candidates"]]
        iterations.append({"iter_no": it["iter_no"], "kind": it["kind"], "batch": batches.get(it["batch_id"]), "fit": it["fit"],
                           "candidates": cands, "best_value": it["best_value"], "best_feasible": it["best_feasible"],
                           "improvement_rel": it["improvement_rel"], "hv": it.get("hv"), "front_size": it.get("front_size")})
    job = jobs_repo.get_job(conn, o["current_job_id"]) if o["current_job_id"] else None
    fail_msg = job["failure_message"] if job and o["status"] == "FAILED" and job["state"] in ("FAILED", "INTERRUPTED") else None
    can_exec = principal.can_execute(s["project_id"])
    final_it = next((it for it in its_all if it["kind"] == "FINAL"), None)
    s17 = so_pareto.detail_extra(ctx, conn, o, ps, its, runs, can_exec)  # S17 §22.10: 역할 정의·파레토·HV 추이
    return {
        **s17,
        "final": _final_out(ctx, conn, s, o, final_it, batches),
        "parameters": [{"name": p["name"], "nominal": p.get("nominal"), "min": p["min"], "max": p["max"], "unit": p.get("unit") or ""}
                       for p in ps.get("parameters") or []],
        "id": o["id"], "label": so_repo.opt_label(o["opt_no"]), "status": o["status"],
        "dir": display_path(ctx.settings.storage.ai_root, s["folder_name"], o["dir_rel"]),
        "param_set": {"id": o["param_set_id"], "label": ps.get("label"), "input_kind": o["input_kind"]},
        "model": {"id": o["model_id"], "name": f"{m['name']} v{m['version']}" if m else o["model_id"]},
        "settings": o["settings"], "iter_no": o["iter_no"], "progress_text": progress_text(o, its, batches, fail_msg),
        "iterations": iterations, "runs": runs, "best": o["best"], "stop_reason": o["stop_reason"],
        "can_cancel": o["status"] in so_repo.ACTIVE and can_exec and (principal.is_global_admin or o["created_by"] == principal.user_id),
        "can_resume": o["status"] == "FAILED" and can_exec,
        "warnings": list((job or {}).get("warnings") or []), "current_job_id": o["current_job_id"],
        "created_at": o["created_at"], "created_by_name": o["created_by_name"], "finished_at": o["finished_at"],
    }


def _final_out(ctx: AppContext, conn: Any, study: dict[str, Any], o: dict[str, Any], it: dict[str, Any] | None,
               batches: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    """D3-61 마무리: 상태·사유·범례·기준안 예측(대리모델) + 캡처 배치의 기준안(doe 1)·최적안(doe 2) run(값·응답 확인·작업 id)."""
    f = o.get("final")
    if not f:
        return None
    obj = o["settings"]["objective"]
    problem = ds.Problem.from_settings(o["settings"])
    perfs = snapshot_perfs(o["settings"])
    rows: dict[int, dict[str, Any]] = {}
    if it is not None:
        for r, mm in _run_metric_rows(ctx, conn, study, it["batch_id"]):
            rows[r["doe_no"]] = {"doe_no": r["doe_no"], "job_id": r["predict_job_id"], "values": r["applied_values"],
                                 "objective": _value(mm, obj["metric"], obj.get("series"), r["responses"], perfs),
                                 "constraints": [_value(mm, c.metric, c.series, r["responses"], perfs)
                                                 for c in problem.constraints],
                                 "state": pb_repo.row_state(r, r["job_state"])}
    return {"status": f.get("status"), "reason": f.get("reason"), "legend": f.get("legend"), "legend_note": f.get("legend_note"),
            "baseline_values": f.get("baseline_values"), "baseline_predicted": f.get("baseline_predicted"),
            "batch": batches.get(f.get("batch_id") or ""), "baseline": rows.get(1), "best": rows.get(2)}


def get_opt(ctx: AppContext, principal: Principal, opt_id: str) -> dict[str, Any]:
    with ctx.engine.connect() as conn:
        return _detail(ctx, conn, _require_opt(conn, opt_id), principal)


def runs_csv(ctx: AppContext, principal: Principal, opt_id: str) -> tuple[bytes, str]:
    """iter,batch,doe_no,run_key,<변수>,objective(다목적 objective_1..m),<제약>,(obs:·reason),predicted,feasible,state
    (UTF-8 BOM·CRLF, §22.4.3). FINAL 제외, EXTRA 포함."""
    with ctx.engine.connect() as conn:
        o = _require_opt(conn, opt_id)
        s = studies_repo.require(conn, o["study_id"])
        runs = collect_runs(ctx, conn, s, o, [it for it in so_repo.iters(conn, o["id"]) if it["kind"] != "FINAL"])
    problem = ds.Problem.from_settings(o["settings"])
    pts = [ds.Point(r["iter_no"], r["batch_label"], r["doe_no"], r["run_key"], dict(r["values"] or {}), r["objective"],
                    list(r["constraints"]), r["state"], objectives=list(r["objectives"]), observed=dict(r["observed"]),
                    reasons={"": r["reason"]} if r["reason"] else {}) for r in runs]
    preds = {(r["iter_no"], r["doe_no"]): r["predicted"] for r in runs if r["predicted"] is not None}
    text = ds.dataset_csv(pts, problem, predicted=preds, with_feasible=True, bom=True, crlf=True)
    return text.encode("utf-8"), f"{so_repo.opt_label(o['opt_no'])}_runs.csv"
