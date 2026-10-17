"""⑤ 플랫폼 내장 최적화 API(phase3 §18.6 S13): 미리보기·생성·목록·상세·runs.csv·일괄 취소·이어서 실행.

권한: 조회·미리보기 = 로그인(member), 생성·이어서 실행 = power, 취소 = power + (등록자 또는 전역 관리자).
생성은 한 트랜잭션(Study 행 FOR UPDATE, D3-25): opt 행 + 탐색 PREDICT_BATCH(새 DOE) 또는 반복 작업 1(재사용).
목적·제약 값은 공용 `run_metrics`(§17.3)로 계산한다 — API는 numpy를 불러오지 않는다(§18.2).
"""

from __future__ import annotations

import math
from typing import Any

from physicsai_core.db.repositories import jobs as jobs_repo
from physicsai_core.db.repositories import param_sets as ps_repo
from physicsai_core.db.repositories import predict_batches as pb_repo
from physicsai_core.db.repositories import studies as studies_repo
from physicsai_core.db.repositories import surrogate_opts as so_repo
from physicsai_core.errors import DomainError
from physicsai_core.features import optimize_builtin_missing
from physicsai_core.paths import display_path
from physicsai_core.stage4_predict import nearest, run_metrics
from physicsai_core.stage4_predict.batch_matrix import batch_label, build_matrix_for, lhs_values
from physicsai_core.stage5_optimize.surrogate import dataset as ds

from ..auth import Principal
from ..context import AppContext
from .common import audit, require_config_ok, require_power, study_root
from .job_params.stage4_batch import resolve_param_set
from .job_params.stage4_predict import model_for, require_template_features, template_kind
from .job_params.study_manage import study_gate
from .jobs import retry_locked
from .predict_batches import _estimate_min, retry_failed_locked

MAX_CONSTRAINTS = 5
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


def _p(out: list[dict[str, Any]], code: str, message: str, field: str | None = None) -> None:
    out.append({"code": code, "field": field, "message": message})


def require_feature(ctx: AppContext) -> None:
    tmpl, res = optimize_builtin_missing(ctx.settings)
    if tmpl or res:
        raise DomainError("FEATURE_NOT_AVAILABLE", f"플랫폼 내장 최적화를 쓸 수 없습니다(관리자 설정 필요): {', '.join(tmpl + res)}",
                          status=409, missing=tmpl + res)


# ---- 지표(run_metrics) ------------------------------------------------------------------------------


def _run_metric_rows(ctx: AppContext, conn: Any, study: dict[str, Any], batch_id: str) -> list[tuple[dict[str, Any], Any]]:
    """배치 run 행 + (성공이면) RunMetrics."""
    root = study_root(ctx, study)
    out = []
    for r in pb_repo.runs_with_jobs(conn, batch_id):
        m = None
        if pb_repo.row_state(r, r["job_state"]) == "SUCCEEDED":
            m = run_metrics.load_run_metrics(run_metrics.locate_run_files(conn, root, jobs_repo.get_job(conn, r["predict_job_id"])),
                                             max_bytes=ctx.settings.ui.max_artifact_bytes)
        out.append((r, m))
    return out


def _value(m: Any, metric: str, series: str | None, table: Any) -> float | None:
    if m is None:
        return None
    try:
        return run_metrics.metric_value(m, metric, series=series, table=table)
    except ValueError:
        return None


def _new_metrics(ps: dict[str, Any]) -> set[str]:
    """새 DOE에서 고를 수 있는 지표: 템플릿 응답 이름 → resp:<NAME>_MIN|_MAX, curve:*."""
    out = {f"curve:{k}" for k in run_metrics.CURVE_KINDS}
    for r in ps.get("responses") or []:
        name = r.get("name") if isinstance(r, dict) else None
        if isinstance(name, str):
            for suf in ("MIN", "MAX"):
                mid = f"resp:{name}_{suf}"
                if run_metrics.METRIC_RE.fullmatch(mid):
                    out.add(mid)
    return out


# ---- 정규화(미리보기·생성 공용) --------------------------------------------------------------------------


def _normalize(ctx: AppContext, conn: Any, study: dict[str, Any], body: Any) -> dict[str, Any]:
    """사전조건(409)과 설정 정규화. 반환: {ps, model, kind, settings, problems, free, integer, fixed, explore_count,
    reuse_batch, valid_points}."""
    cfg = ctx.settings
    so = cfg.surrogate_opt
    require_feature(ctx)
    ps = resolve_param_set(conn, study, body.param_set_id)
    kind = template_kind(ps)
    require_template_features(cfg, kind)
    m = model_for(conn, study, body.model_id)
    problems: list[dict[str, Any]] = []
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
        if lo < tlo - 1e-12 * max(1.0, abs(tlo)) or hi > thi + 1e-12 * max(1.0, abs(thi)):
            _p(problems, "BOUNDS_OUT_OF_RANGE", f"'{n}' 범위는 학습 범위 {tlo:g}~{thi:g} 안이어야 합니다", f"bounds.{n}")
            continue
        if n in integer and lo < hi and math.ceil(lo - 1e-9) > math.floor(hi + 1e-9):
            _p(problems, "BOUNDS_INVALID", f"'{n}'(정수) 범위 안에 정수가 없습니다", f"bounds.{n}")
            continue
        bounds[n] = [lo, hi]
    fixed = {n: b[0] for n, b in bounds.items() if b[0] == b[1]}
    free = [n for n in names if n in bounds and n not in fixed]
    if not free and len(bounds) == len(names):
        _p(problems, "NO_FREE_VARIABLE", "범위가 있는 자유 변수가 1개 이상 필요합니다", "bounds")
    if len(free) > so.max_variables:
        _p(problems, "TOO_MANY_VARIABLES", f"자유 변수는 최대 {so.max_variables}개입니다(현재 {len(free)}개)", "bounds")
    iterations = body.iterations if body.iterations is not None else so.default_iterations
    candidates = body.candidates if body.candidates is not None else so.default_candidates
    tol = body.tol_rel if body.tol_rel is not None else so.default_tol_rel
    if not 1 <= iterations <= so.max_iterations:
        _p(problems, "ITERATIONS_RANGE", f"반복은 1~{so.max_iterations}회입니다", "iterations")
    if not 1 <= candidates <= so.max_candidates:
        _p(problems, "CANDIDATES_RANGE", f"후보는 1~{so.max_candidates}개입니다", "candidates")
    if not 0.0 < tol < 1.0:
        _p(problems, "TOL_RANGE", "개선 기준은 0 초과 1 미만입니다(예 0.01 = 1%)", "tol_rel")
    if body.multi_execution > cfg.train_data.max_multi_execution:
        _p(problems, "MULTI_EXECUTION_RANGE", f"동시 실행 수는 1~{cfg.train_data.max_multi_execution}", "multi_execution")
    # 탐색
    need = ds.min_points(len(free))
    reuse = None
    reuse_rows: list[tuple[dict[str, Any], Any]] = []
    if body.explore.kind == "reuse":
        reuse = pb_repo.get(conn, body.explore.batch_id)
        if reuse is None or reuse["study_id"] != study["id"]:
            raise DomainError("BATCH_NOT_FOUND", "일괄 예측을 찾을 수 없습니다", status=404)
        reason = ("NOT_DONE" if reuse["status"] != "DONE" else "TEMPLATE_MISMATCH" if reuse["param_set_id"] != ps["id"]
                  else "MODEL_MISMATCH" if reuse["model_id"] != m["id"] else None)
        if reason:
            msg = {"NOT_DONE": "완료(DONE)된 배치만 재사용할 수 있습니다", "TEMPLATE_MISMATCH": "같은 템플릿의 배치가 아닙니다",
                   "MODEL_MISMATCH": "같은 모델로 예측한 배치가 아닙니다"}[reason]
            raise DomainError("BATCH_NOT_REUSABLE", msg, status=409, reason=reason)
        reuse_rows = _run_metric_rows(ctx, conn, study, reuse["id"])
        explore_count = 0
    else:
        explore_count = body.explore.count if body.explore.count is not None else \
            ds.default_explore_count(len(free), cfg.predict_batch.max_runs)
        if explore_count < need:
            _p(problems, "EXPLORE_TOO_FEW", f"탐색 run은 최소 {need}개입니다(자유 변수 {len(free)}개)", "explore.count")
        elif explore_count > cfg.predict_batch.max_runs:
            _p(problems, "EXPLORE_TOO_MANY", f"탐색 run은 최대 {cfg.predict_batch.max_runs}개입니다", "explore.count")
    # 지표
    if reuse is not None:
        allowed = {f"curve:{k}" for k in run_metrics.CURVE_KINDS if any(mm and mm.curve for _r, mm in reuse_rows)}
        allowed |= {f"resp:{k}" for _r, mm in reuse_rows if mm and mm.resp for k in mm.resp}
        allowed |= {f"tbl:{k}" for r, mm in reuse_rows if mm is not None for k in (r["responses"] or {})}
    else:
        allowed = _new_metrics(ps)
    obj = body.objective
    if not run_metrics.METRIC_RE.fullmatch(obj.metric) or obj.metric not in allowed:
        _p(problems, "METRIC_UNKNOWN", f"목적 지표 '{obj.metric}'를 쓸 수 없습니다", "objective.metric")
    if len(body.constraints) > MAX_CONSTRAINTS:
        _p(problems, "CONSTRAINT_INVALID", f"제약은 최대 {MAX_CONSTRAINTS}개입니다", "constraints")
    for i, c in enumerate(body.constraints):
        if not run_metrics.METRIC_RE.fullmatch(c.metric) or c.metric not in allowed or not math.isfinite(c.value):
            _p(problems, "CONSTRAINT_INVALID", f"제약 {i + 1}의 지표 '{c.metric}'를 쓸 수 없습니다", f"constraints.{i}")
    valid_points = None
    if reuse is not None:
        valid_points = sum(1 for r, mm in reuse_rows if _value(mm, obj.metric, obj.series, r["responses"]) is not None)
        if valid_points < need:
            _p(problems, "EXPLORE_TOO_FEW", f"재사용 배치에 목적 값이 있는 성공 run이 {valid_points}개뿐입니다(최소 {need}개)",
               "explore.batch_id")
    explore = ({"kind": "reuse", "batch_id": reuse["id"]} if reuse is not None
               else {"kind": "new", "count": explore_count, "seed": body.explore.seed})
    settings = {
        "names": names, "integer": integer, "bounds": bounds,
        "objective": {"metric": obj.metric, "series": obj.series, "sense": obj.sense},
        "constraints": [{"metric": c.metric, "series": c.series, "op": c.op, "value": float(c.value)} for c in body.constraints],
        "surrogate": body.surrogate or so.default_surrogate, "iterations": iterations, "candidates": candidates,
        "tol_rel": tol, "seed": body.seed, "multi_execution": body.multi_execution, "capture": bool(body.capture),
        "explore": explore,
    }
    return {"ps": ps, "model": m, "kind": kind, "settings": settings, "problems": problems, "free": free,
            "integer": integer, "fixed": fixed, "explore_count": explore_count, "reuse": reuse, "valid_points": valid_points}


def preview(ctx: AppContext, study_id: str, body: Any) -> dict[str, Any]:
    with ctx.engine.connect() as conn:
        s = studies_repo.require(conn, study_id)
        n = _normalize(ctx, conn, s, body)
        st = n["settings"]
        total = n["explore_count"] + st["iterations"] * st["candidates"]
        est = _estimate_min(conn, study_id, total) if total else None
    return {"free_variables": n["free"], "integer_variables": [x for x in n["integer"] if x in n["free"]],
            "fixed": n["fixed"], "explore_count": n["explore_count"], "max_total_runs": total, "estimate_min": est,
            "objective_available": n["valid_points"] is None or n["valid_points"] > 0, "problems": n["problems"]}


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
    """반복마다 배치 run 전부의 목적·제약·예측·만족 여부(run_metrics, 성공 run만 값)."""
    problem = ds.Problem.from_settings(o["settings"])
    obj = o["settings"]["objective"]
    out = []
    for it in its:
        b = pb_repo.get(conn, it["batch_id"])
        if b is None:
            continue
        preds = {c.get("doe_no"): c.get("predicted") for c in it.get("candidates") or []}
        for r, mm in _run_metric_rows(ctx, conn, study, b["id"]):
            state = pb_repo.row_state(r, r["job_state"])
            objective = _value(mm, obj["metric"], obj.get("series"), r["responses"])
            cons = [_value(mm, c.metric, c.series, r["responses"]) for c in problem.constraints]
            valid = state == "SUCCEEDED" and objective is not None and all(v is not None for v in cons)
            out.append({"iter_no": it["iter_no"], "batch_id": b["id"], "batch_label": batch_label(b["batch_no"]),
                        "doe_no": r["doe_no"], "run_key": r["run_key"], "job_id": r["predict_job_id"],
                        "values": r["applied_values"], "objective": objective, "constraints": cons,
                        "predicted": preds.get(r["doe_no"]),
                        "feasible": ds.is_feasible(cons, problem.constraints) if valid else None, "state": state})
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
    its = so_repo.iters(conn, o["id"])
    batches: dict[str, dict[str, Any]] = {}
    for it in its:
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
                           "improvement_rel": it["improvement_rel"]})
    job = jobs_repo.get_job(conn, o["current_job_id"]) if o["current_job_id"] else None
    fail_msg = job["failure_message"] if job and o["status"] == "FAILED" and job["state"] in ("FAILED", "INTERRUPTED") else None
    can_exec = principal.can_execute(s["project_id"])
    return {
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


def get_opt(ctx: AppContext, principal: Principal, opt_id: str) -> dict[str, Any]:
    with ctx.engine.connect() as conn:
        return _detail(ctx, conn, _require_opt(conn, opt_id), principal)


def runs_csv(ctx: AppContext, principal: Principal, opt_id: str) -> tuple[bytes, str]:
    """iter,batch,doe_no,run_key,<변수>,objective,<제약>,predicted,feasible,state (UTF-8 BOM·CRLF)."""
    with ctx.engine.connect() as conn:
        o = _require_opt(conn, opt_id)
        s = studies_repo.require(conn, o["study_id"])
        runs = collect_runs(ctx, conn, s, o, so_repo.iters(conn, o["id"]))
    problem = ds.Problem.from_settings(o["settings"])
    pts = [ds.Point(r["iter_no"], r["batch_label"], r["doe_no"], r["run_key"], dict(r["values"] or {}), r["objective"],
                    list(r["constraints"]), r["state"]) for r in runs]
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
