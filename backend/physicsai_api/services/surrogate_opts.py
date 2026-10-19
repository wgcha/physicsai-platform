"""⑤ 플랫폼 내장 최적화 API(phase3 §18.6 S13): 미리보기·생성·목록·상세·runs.csv·일괄 취소·이어서 실행.

권한: 조회·미리보기 = 로그인(member), 생성·이어서 실행 = power, 취소 = power + (등록자 또는 전역 관리자).
생성은 한 트랜잭션(Study 행 FOR UPDATE, D3-25): opt 행 + 탐색 PREDICT_BATCH(새 DOE) 또는 반복 작업 1(재사용).
목적·제약 값은 공용 `run_metrics`(§17.3)로 계산한다 — API는 numpy를 불러오지 않는다(§18.2).
"""

from __future__ import annotations

from typing import Any

from physicsai_core.db.repositories import jobs as jobs_repo
from physicsai_core.db.repositories import param_sets as ps_repo
from physicsai_core.db.repositories import predict_batches as pb_repo
from physicsai_core.db.repositories import studies as studies_repo
from physicsai_core.db.repositories import surrogate_opts as so_repo
from physicsai_core.errors import DomainError
from physicsai_core.paths import display_path
from physicsai_core.stage4_predict.batch_matrix import batch_label, build_matrix_for, lhs_values
from physicsai_core.stage5_optimize.surrogate import dataset as ds

from ..auth import Principal
from ..context import AppContext
from . import surrogate_opt_pareto as so_pareto
from .common import audit, require_config_ok, require_power
from .job_params.study_manage import study_gate
from .jobs import retry_locked
from .predict_batches import _estimate_min, retry_failed_locked
from .surrogate_opt_problem import MAX_CONSTRAINTS, require_feature  # noqa: F401 - 재노출(기존 import 경로)
from .surrogate_opt_problem import metric_value as _metric_value
from .surrogate_opt_problem import normalize as _normalize
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


def _invalid(problems: list[dict[str, Any]]) -> DomainError:
    return DomainError("SURROGATE_OPT_INVALID", "내장 최적화 설정이 올바르지 않습니다", status=422, problems=problems)


def preview(ctx: AppContext, study_id: str, body: Any) -> dict[str, Any]:
    with ctx.engine.connect() as conn:
        s = studies_repo.require(conn, study_id)
        n = _normalize(ctx, conn, s, body)
        st = n["settings"]
        total = n["explore_count"] + st["iterations"] * st["candidates"]
        est = _estimate_min(conn, study_id, total) if total else None
    return {"free_variables": n["free"], "integer_variables": [x for x in n["integer"] if x in n["free"]],
            "fixed": n["fixed"], "explore_count": n["explore_count"], "max_total_runs": total, "estimate_min": est,
            "objective_available": n["valid_points"] is None or n["valid_points"] > 0, "problems": n["problems"],
            "mode": st["mode"], "performances": n["performances"]}


def create(ctx: AppContext, principal: Principal, study_id: str, body: Any, rid: str, ip: str | None) -> dict[str, Any]:
    cfg = ctx.settings
    with ctx.engine.begin() as conn:
        study = studies_repo.require(conn, study_id, for_update=True)
        require_power(principal, study["project_id"])
        require_config_ok(ctx)
        study_gate(conn, study, "SURROGATE_OPT")
        n = _normalize(ctx, conn, study, body)
        if n["problems"]:
            raise _invalid(n["problems"])
        if so_repo.active_for_study(conn, study_id) is not None:
            raise DomainError("SURROGATE_OPT_ACTIVE", "이 Study에 진행 중인 내장 최적화가 있습니다 — 끝나거나 취소한 뒤 시작하세요",
                              status=409)
        st = n["settings"]
        no = so_repo.next_opt_no(conn, study_id)
        oid = so_repo.new_opt_id()
        opt = so_repo.create_opt(
            conn, id=oid, study_id=study_id, opt_no=no, param_set_id=n["ps"]["id"], model_id=n["model"]["id"],
            input_kind=n["kind"], settings=st, status="EXPLORING" if n["reuse"] is None else "FITTING", iter_no=0,
            dir_rel=so_repo.opt_dir_rel(cfg.surrogate_opt.dir_name, no), created_by=principal.user_id,
            created_by_name=principal.display_name)
        if n["reuse"] is not None:
            so_repo.add_iter(conn, oid, 0, "REUSE", n["reuse"]["id"])
            job = so_repo.enqueue_round(conn, opt, 1)
        else:
            job, _b = _explore_batch(ctx, conn, opt, n)
        audit(conn, principal, "SURROGATE_OPT_CREATE", "surrogate_opt", oid, {"study_id": study_id, "job_id": job["id"]}, rid, ip)
        return _detail(ctx, conn, so_repo.get(conn, oid), principal)  # type: ignore[arg-type]


def _explore_batch(ctx: AppContext, conn: Any, opt: dict[str, Any], n: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """탐색 배치(새 DOE LHS): 범위(고정 변수는 lo = hi)로 batch_matrix와 같은 층화 LHS 값을 만들어 표 조합으로 검증·반영."""
    st = n["settings"]
    ex = st["explore"]
    names = st["names"]
    vals = lhs_values(names, {k: (v[0], v[1]) for k, v in st["bounds"].items()}, ex["count"], ex["seed"])
    text = "\n".join([",".join(names), *[",".join(repr(float(v[k])) for k in names) for v in vals]]) + "\n"
    matrix = build_matrix_for({"kind": "table", "text": text}, n["ps"], ctx.settings)
    if matrix.problems or not matrix.rows:
        raise _invalid([{"code": "EXPLORE_TOO_FEW", "field": "explore", "message": str(matrix.problems[:3])}])
    matrix.source_kind = "LHS"
    meta = {"count": ex["count"], "seed": ex["seed"], "ranges": st["bounds"]}
    matrix.source_meta = meta
    return so_repo.create_opt_batch(conn, opt=opt, iter_no=0, kind="EXPLORE", matrix=matrix, source_meta=meta,
                                    batch_dir_name=ctx.settings.predict_batch.dir_name,
                                    simlab_mesh_name=ctx.settings.predict.simlab_mesh_name)


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


# ---- 취소·이어서 실행 ----------------------------------------------------------------------------------


def cancel(ctx: AppContext, principal: Principal, opt_id: str, rid: str, ip: str | None) -> dict[str, Any]:
    with ctx.engine.begin() as conn:
        o = _require_opt(conn, opt_id, for_update=True)
        s = studies_repo.require(conn, o["study_id"])
        require_power(principal, s["project_id"])
        if not principal.is_global_admin and o["created_by"] != principal.user_id:
            raise DomainError("PERMISSION_DENIED", "내장 최적화 등록자 또는 관리자만 취소할 수 있습니다", status=403,
                              required="owner_or_global_admin")
        done = so_repo.cancel(conn, o, principal.user_id)
        audit(conn, principal, "SURROGATE_OPT_CANCEL", "surrogate_opt", o["id"], {"job_ids": done}, rid, ip)
        return _detail(ctx, conn, so_repo.get(conn, o["id"]), principal)  # type: ignore[arg-type]


def resume(ctx: AppContext, principal: Principal, opt_id: str, rid: str, ip: str | None) -> dict[str, Any]:
    """FAILED만: 반복 작업 실패면 그 작업 재시도(on_retry가 opt FITTING), 배치 실패면 배치 실패만 다시(가드 우회)."""
    with ctx.engine.begin() as conn:
        o = _require_opt(conn, opt_id, for_update=True)
        study = studies_repo.require(conn, o["study_id"], for_update=True)
        require_power(principal, study["project_id"])
        require_config_ok(ctx)
        if o["status"] != "FAILED":
            raise DomainError("SURROGATE_OPT_NOT_RESUMABLE", "실패한 내장 최적화만 이어서 실행할 수 있습니다", status=409)
        if so_repo.active_for_study(conn, o["study_id"]) is not None:
            raise DomainError("SURROGATE_OPT_ACTIVE", "이 Study에 진행 중인 내장 최적화가 있습니다", status=409)
        out: dict[str, Any] = {"job_id": None, "batch_retry": None}
        if o["stop_reason"] == "BATCH_FAILED":
            it = so_repo.get_iter(conn, o["id"], o["iter_no"])
            b = pb_repo.get(conn, it["batch_id"], for_update=True) if it else None
            if b is None:
                raise DomainError("SURROGATE_OPT_NOT_RESUMABLE", "이어서 실행할 배치가 없습니다", status=409)
            out["batch_retry"] = retry_failed_locked(conn, principal, b, study, rid, ip)
            so_repo.set_opt(conn, o["id"], status="EXPLORING" if o["iter_no"] == 0 else "VERIFYING", stop_reason=None,
                            finished_at=None)
            # 하위만 다시 실행하면 배치는 PREDICTING으로 돌아가고, 끝나면 종료 훅이 다음 반복 작업을 넣는다
        else:
            old = jobs_repo.get_job(conn, o["current_job_id"]) if o["current_job_id"] else None
            if old is None:
                raise DomainError("SURROGATE_OPT_NOT_RESUMABLE", "이어서 실행할 반복 작업이 없습니다", status=409)
            # 반복 작업이 검증 배치를 등록한 뒤 실패했으면 다시 돌리지 않고 VERIFYING으로(배치 완료 훅이 이어 감)
            restored = so_repo.restore_verifying(conn, o, int((old.get("params") or {}).get("round") or 0))
            if restored is not None:
                out["job_id"] = restored["round_job_id"]
                out["batch_retry"] = {"restored_batch_id": restored["batch_id"]}
            else:
                out["job_id"] = retry_locked(conn, principal, old, 1, rid, ip)["id"]
        audit(conn, principal, "SURROGATE_OPT_RESUME", "surrogate_opt", o["id"], out, rid, ip)
        return out
