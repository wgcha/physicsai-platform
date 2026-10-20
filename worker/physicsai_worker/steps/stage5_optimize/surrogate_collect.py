"""⑤ SO_COLLECT: 반복 0..r−1 배치 run 결과 수집·opt.json 기록 — surrogate에서 재노출."""

from __future__ import annotations

import os
from typing import Any

from physicsai_core.db.repositories import jobs as jobs_repo
from physicsai_core.db.repositories import param_sets as ps_repo
from physicsai_core.db.repositories import predict_batches as pb_repo
from physicsai_core.db.repositories import surrogate_opts as so_repo
from physicsai_core.errors import StepFailure
from physicsai_core.fileutil import write_json_atomic, write_text
from physicsai_core.stage4_predict import performance, run_metrics
from physicsai_core.stage4_predict.batch_matrix import batch_label
from physicsai_core.stage5_optimize.surrogate import dataset as ds

from . import surrogate_mo as mo
from .surrogate_common import _O, _algo_meta, _iter_dir, _metric, _opt, _problem, _round

# ---- SO_COLLECT -----------------------------------------------------------------------------------


def point_values(m: run_metrics.RunMetrics, problem: ds.Problem, table: Any, perfs: dict[str, Any]
                 ) -> tuple[list[float | None], list[float | None], dict[str, float | None], dict[str, str]]:
    """성공 run 1개 → (목적들, 제약들, 관찰 {key: 값}, 사유 {key: 사유}) — `perf:`는 performance.perf_value(사유 포함)."""
    reasons: dict[str, str] = {}

    def val(metric: str, series: str | None, key: str) -> float | None:
        if metric.startswith("perf:") and metric[5:] in perfs:
            v, why = performance.perf_value(perfs[metric[5:]], m)
            if v is None:
                reasons[key] = why or "NO_VALUE"
            return v
        v = _metric(m, metric, series, table)
        if v is None:
            reasons[key] = "NO_VALUE"
        return v

    objs = [val(o.metric, o.series, o.key) for o in problem.objectives]
    cons = [val(c.metric, c.series, c.key) for c in problem.constraints]
    obs = {o.key: val(o.metric, o.series, o.key) for o in problem.observe}
    return objs, cons, obs, reasons


def snapshot_perfs(problem: ds.Problem) -> dict[str, Any]:
    """settings.performances 스냅샷 → PerfDef(진행 중 정의 변경과 무관하게 같은 정의, §22.4.2)."""
    return performance.perf_defs([{"name": k, "unit": (v or {}).get("unit", ""), "spec": (v or {}).get("spec")}
                                  for k, v in problem.performances.items()])


def collect_points(ctx: Any, opt: dict[str, Any], problem: ds.Problem, upto: int) -> list[ds.Point]:
    """반복 0..upto 배치(탐색·재사용·검증 — 마무리 FINAL·추가 검증 EXTRA 제외)의 run 전부 → Point(성공 run만 지표 계산)."""
    out: list[ds.Point] = []
    max_bytes = ctx.settings.ui.max_artifact_bytes
    perfs = snapshot_perfs(problem)
    with ctx.ex.engine.connect() as conn:
        for it in so_repo.iters(conn, opt["id"]):
            if it["iter_no"] > upto or it["kind"] in ("FINAL", "EXTRA"):
                continue
            b = pb_repo.get(conn, it["batch_id"])
            if b is None:
                continue
            label = batch_label(b["batch_no"])
            for r in pb_repo.runs_with_jobs(conn, b["id"]):
                ctx.checkpoint()
                state = pb_repo.row_state(r, r["job_state"])
                vals = ds.run_values(r["applied_values"], b.get("source_meta"), r["doe_no"], problem.cat_spec)  # opt-native §7
                objs: list[float | None] = [None] * problem.m
                cons: list[float | None] = [None] * len(problem.constraints)
                obs: dict[str, float | None] = {o.key: None for o in problem.observe}
                reasons: dict[str, str] = {}
                if state == "SUCCEEDED":
                    job = jobs_repo.get_job(conn, r["predict_job_id"])
                    m = run_metrics.load_run_metrics(run_metrics.locate_run_files(conn, ctx.root, job), max_bytes=max_bytes)
                    objs, cons, obs, reasons = point_values(m, problem, r["responses"], perfs)
                out.append(ds.Point(it["iter_no"], label, r["doe_no"], r["run_key"], vals, objs[0], cons, state,
                                    r["predict_job_id"], b["id"], objectives=objs, observed=obs, reasons=reasons,
                                    kind=it["kind"]))
    return out


def _best_dict(p: ds.Point, feasible: bool, problem: ds.Problem) -> dict[str, Any]:
    return {"iter_no": p.iter_no, "batch_id": p.batch_id, "batch_label": p.batch_label, "doe_no": p.doe_no,
            "run_key": p.run_key, "job_id": p.job_id, "values": p.values, "objective": p.objective,
            "constraints": {c.key: v for c, v in zip(problem.constraints, p.constraints)}, "feasible": feasible}


def so_collect(ctx: Any) -> None:
    opt = _opt(ctx)
    r = _round(ctx)
    t = r - 1
    s = opt["settings"]
    problem = _problem(opt)
    O = _O(ctx, opt)
    os.makedirs(O, exist_ok=True)
    points = collect_points(ctx, opt, problem, t)
    d = _iter_dir(O, t)
    if os.path.lexists(os.path.join(d, "dataset.csv")):
        ctx.backup([os.path.join(d, "dataset.csv")])
    os.makedirs(d, exist_ok=True)
    write_text(os.path.join(d, "dataset.csv"), ds.dataset_csv(points, problem))
    ctx.add_output(os.path.join(d, "dataset.csv"))
    # 반복 t 기록: 지금까지 최선·개선율, 검증 후보의 실제 값·상태, 직전 적합의 예측-검증 MAE
    with ctx.ex.engine.connect() as conn:
        it = so_repo.get_iter(conn, opt["id"], t)
    mine = [p for p in points if p.iter_no == t]
    if problem.multi:  # S17 §22.5.6: HV(고정 틀)·전선 크기·HV 개선율, best = 가중 추천점
        upd, best, imp = mo.collect_multi(ctx, opt, problem, points, t)
    else:
        cur = ds.best_point(points, problem)
        prev = ds.best_point([p for p in points if p.iter_no < t], problem) if t >= 1 else None
        imp = ds.improvement_rel((prev[0].objective, prev[1]) if prev else None,  # type: ignore[arg-type]
                                 (cur[0].objective, cur[1]) if cur else None, problem.sense) if t >= 1 else None
        upd = {"best_value": cur[0].objective if cur else None, "best_feasible": cur[1] if cur else None,
               "improvement_rel": imp}
        best = _best_dict(cur[0], cur[1], problem) if cur is not None else None
    if it is not None and it.get("candidates"):
        by_no = {p.doe_no: p for p in mine}
        cands, errs = [], []
        errs_i: list[list[float]] = [[] for _ in range(problem.m)]
        for c in it["candidates"]:
            p = by_no.get(c.get("doe_no"))
            c = {**c, "verified": p.objective if p else None, "state": p.state if p else None}
            if problem.multi:
                c["verified_objectives"] = list(p.objectives or []) if p else None
                for i, pv in enumerate(c.get("predicted_objectives") or []):
                    vv = (p.objectives or [])[i] if p else None
                    if vv is not None and isinstance(pv, (int, float)):
                        errs_i[i].append(abs(float(pv) - vv))
            if p is not None and p.objective is not None and isinstance(c.get("predicted"), (int, float)):
                errs.append(abs(float(c["predicted"]) - p.objective))
            cands.append(c)
        upd["candidates"] = cands
        if it.get("fit"):
            fit_q = {**it["fit"], "pred_vs_verified_mae": (sum(errs) / len(errs)) if errs else None}
            if problem.multi and isinstance(fit_q.get("per_objective"), list):
                fit_q["per_objective"] = [{**po, "pred_vs_verified_mae": (sum(e) / len(e)) if e else None}
                                          for po, e in zip(fit_q["per_objective"], errs_i)]
            upd["fit"] = fit_q
    ctx.ex.db(lambda c: so_repo.set_iter(c, opt["id"], t, **upd))
    if best is not None:
        ctx.ex.db(lambda c: so_repo.set_opt(c, opt["id"], best=best))
    ctx.log(f"반복 {t} 자료: run {len(points)}개, 유효 {sum(p.valid for p in points)}개, "
            + (f"HV {upd.get('hv')} · 전선 {upd.get('front_size')}" if problem.multi else f"최선 {upd['best_value']}"))
    # 판정
    if t >= 1 and it is not None and it["kind"] == "VERIFY" and mine and not any(p.valid for p in mine):
        raise StepFailure(ds.FAIL_VERIFY_ALL, f"반복 {t}의 검증 run {len(mine)}개가 모두 실패했습니다(값 없음 포함)")
    designs, _failed = ds.merge(points, problem)
    d_free = len(ds.free_variables(problem, designs))
    need = ds.min_points(d_free)
    if len(designs) < need:
        raise StepFailure(ds.FAIL_TOO_FEW, f"유효 run이 {len(designs)}개뿐입니다(최소 {need}개) — 탐색 run 수를 늘리세요")
    stop = ds.stop_reason(round_no=r, iterations=int(s["iterations"]), improvement=imp, tol_rel=float(s["tol_rel"]))
    _write_opt_json(ctx, opt, O)
    ctx.patch_result({"surrogate_opt_id": opt["id"], "round": r, "n_points": len(points), "n_designs": len(designs),
                      "stop": stop, "improvement_rel": imp, "best_value": upd["best_value"]})


def _write_opt_json(ctx: Any, opt: dict[str, Any], O: str) -> None:
    with ctx.ex.engine.connect() as conn:
        ps = ps_repo.get(conn, opt["param_set_id"]) or {}
        its = so_repo.iters(conn, opt["id"])
        labels = {it["iter_no"]: (pb_repo.get(conn, it["batch_id"]) or {}).get("batch_no") for it in its}
    m = None
    try:
        from ..common import load_model

        m = load_model(ctx, opt["model_id"])
    except Exception:  # noqa: BLE001 - 기록용(모델 행이 없으면 id만)
        m = None
    oj = os.path.join(O, "opt.json")
    if os.path.lexists(oj):
        ctx.backup([oj])  # 기존 산출물은 _backup으로(반복마다 갱신)
    write_json_atomic(oj, {
        "id": opt["id"], "label": so_repo.opt_label(opt["opt_no"]), "settings": opt["settings"],
        "param_set": {"id": opt["param_set_id"], "label": ps.get("label"), "input_kind": opt["input_kind"]},
        "model": {"id": opt["model_id"], "name": (m or {}).get("name"), "version": (m or {}).get("version"),
                  "psmdl_sha256": (m or {}).get("psmdl_sha256")},
        "seed": opt["settings"].get("seed"), **_algo_meta(opt["settings"]),
        "hv_frame": opt.get("hv_frame"), "used_weights": mo.last_used_weights(its),
        "batches": [{"iter_no": it["iter_no"], "kind": it["kind"], "batch_id": it["batch_id"],
                     "label": batch_label(labels[it["iter_no"]]) if labels.get(it["iter_no"]) else None} for it in its],
    })
