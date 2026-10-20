"""⑤ 플랫폼 내장 최적화 반복 SURROGATE_OPT(phase3 §18.4·§18.5 S13): SO_COLLECT → SO_FIT → SO_PROPOSE → SO_NEXT.

반복 작업 r은 반복 0..r−1 배치(탐색·재사용·검증)의 run 결과로 대리모델을 적합하고 반복 r 후보 k개를 낸 뒤, 같은 트랜잭션에서
검증 PREDICT_BATCH(source table)를 등록한다(또는 정지 판정이면 마무리). 슬롯은 이 작업이 도는 동안만 잡는다 — 검증 배치가
끝나면 종료 훅(job_end → surrogate_opts.on_batch_done)이 다음 반복 작업을 넣는다.

폴더 O = <study>/05_opt/surrogate/SO-001: opt.json, iter_NN/{dataset.csv, surrogate.json, loo.csv, candidates.csv},
convergence.csv, verified_runs.csv, summary.json. 재실행이면 그 iter_NN/을 _backup 후 다시.
numpy·scipy는 SO_FIT·SO_PROPOSE 안에서만(BLAS 스레드 상한을 먼저 건다).
"""

from __future__ import annotations

import csv
import io
import json
import math
import os
import time
from typing import Any

from physicsai_core.db.repositories import jobs as jobs_repo
from physicsai_core.db.repositories import notifications as notif_repo
from physicsai_core.db.repositories import param_sets as ps_repo
from physicsai_core.db.repositories import predict_batches as pb_repo
from physicsai_core.db.repositories import studies as studies_repo
from physicsai_core.db.repositories import surrogate_opts as so_repo
from physicsai_core.errors import StepFailure
from physicsai_core.fileutil import write_json_atomic, write_text
from physicsai_core.stage4_predict import contour_capture as cc
from physicsai_core.stage4_predict import performance, run_metrics
from physicsai_core.stage4_predict.batch_matrix import batch_label, build_matrix_for
from physicsai_core.stage5_optimize.surrogate import algo as so_algo
from physicsai_core.stage5_optimize.surrogate import dataset as ds
from physicsai_core.stage5_optimize.surrogate import limit_threads

from ...signals import StepSkipped
from . import surrogate_mo as mo

STOP_TEXT = {ds.STOP_CONVERGED: "수렴", ds.STOP_MAX_ITER: "최대 반복", ds.STOP_NO_NEW: "새 후보 없음"}


# ---- 공용 ----------------------------------------------------------------------------------------


def _opt(ctx: Any) -> dict[str, Any]:
    oid = ctx.params.get("surrogate_opt_id")
    with ctx.ex.engine.connect() as conn:
        opt = so_repo.get(conn, oid) if isinstance(oid, str) else None
    if opt is None or opt["study_id"] != ctx.study["id"]:
        raise StepFailure("INPUT_INVALID", "내장 최적화를 찾을 수 없습니다")
    if opt["status"] not in so_repo.ACTIVE or opt["current_job_id"] != ctx.ex.job_id:
        raise StepFailure("SURROGATE_OPT_INACTIVE", "이 반복 작업은 진행 중인 내장 최적화의 최신 작업이 아닙니다(취소·종료됨)")
    return opt


def _round(ctx: Any) -> int:
    r = ctx.params.get("round")
    if not isinstance(r, int) or r < 1:
        raise StepFailure("INPUT_INVALID", "반복 번호가 올바르지 않습니다")
    return r


def _O(ctx: Any, opt: dict[str, Any]) -> str:
    return ctx.abs(opt["dir_rel"])


def _iter_dir(O: str, n: int) -> str:
    return os.path.join(O, f"iter_{n:02d}")


def _problem(opt: dict[str, Any]) -> ds.Problem:
    return ds.Problem.from_settings(opt["settings"])


def _metric(m: run_metrics.RunMetrics, metric: str, series: str | None, table: Any) -> float | None:
    try:
        return run_metrics.metric_value(m, metric, series=series, table=table)
    except ValueError:
        return None


def _read_points(ctx: Any, O: str, problem: ds.Problem, last_iter: int) -> list[ds.Point]:
    p = os.path.join(_iter_dir(O, last_iter), "dataset.csv")
    if not os.path.isfile(p):
        raise StepFailure("INPUT_CHANGED", f"자료 파일이 없습니다: {ctx.rel(p)}")
    with open(p, encoding="utf-8-sig") as fh:
        return ds.read_dataset_csv(fh.read(), problem)


def _threads(ctx: Any) -> None:
    s = ctx.settings
    limit_threads(min(s.surrogate_opt.blas_threads, s.worker.max_logical_cores or s.surrogate_opt.blas_threads))


class _Clock:
    """SO_FIT+SO_PROPOSE 합계 시간 한도(fit_timeout_s) + 취소 확인."""

    def __init__(self, ctx: Any) -> None:
        self.ctx = ctx
        clk = ctx.result().get("fit_clock") or {}
        same = isinstance(clk, dict) and clk.get("job_id") == ctx.ex.job_id and isinstance(clk.get("t0"), (int, float))
        self.t0 = float(clk["t0"]) if same else time.time()  # 재시도(다른 작업)는 새로 잰다
        self.limit = ctx.settings.surrogate_opt.fit_timeout_s

    def __call__(self) -> None:
        self.ctx.checkpoint()
        if time.time() - self.t0 > self.limit:
            raise StepFailure(ds.FAIL_TIMEOUT, f"대리모델 학습·후보 탐색이 {self.limit}초를 넘었습니다 — 탐색 run·변수를 줄이세요")


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


# ---- SO_FIT ---------------------------------------------------------------------------------------


def so_fit(ctx: Any) -> None:
    opt = _opt(ctx)
    r = _round(ctx)
    s = opt["settings"]
    cfg = ctx.settings.surrogate_opt
    problem = _problem(opt)
    O = _O(ctx, opt)
    ctx.patch_result({"fit_clock": {"job_id": ctx.ex.job_id, "t0": time.time()}})
    _threads(ctx)
    from physicsai_core.stage5_optimize.surrogate import infill

    points = _read_points(ctx, O, problem, r - 1)
    designs, _failed = ds.merge(points, problem)
    d = _iter_dir(O, r)
    if os.path.lexists(d):
        ctx.backup([d])
    os.makedirs(d, exist_ok=True)
    clock = _Clock(ctx)
    seed = int(s["seed"]) * 1000 + r
    if problem.multi:  # S17 §22.5.2 목적별 GP
        mo.fit_multi(ctx, problem, designs, d, kind=s["surrogate"], restarts=cfg.gp_restarts, seed=seed, clock=clock)
        return
    try:
        fit = infill.fit_all(designs, problem, kind=s["surrogate"], restarts=cfg.gp_restarts, seed=seed,
                             progress=lambda lbl: ctx.progress(None, lbl), checkpoint=clock)
    except infill.SurrogateError as exc:
        raise StepFailure(exc.code, exc.message) from None
    for w in fit.warnings:
        ctx.add_warning(w["code"], w["message"])
    import numpy
    import scipy

    sj = fit.to_json()
    sj["versions"] = {"numpy": numpy.__version__, "scipy": scipy.__version__}
    write_json_atomic(os.path.join(d, "surrogate.json"), sj)
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow([*problem.names, "objective", "loo_pred"])
    for dz, lp in zip(designs, fit.quality["loo_pred"]):
        w.writerow([*[repr(float(dz.values[n])) for n in problem.names], repr(dz.objective), repr(float(lp))])
    write_text(os.path.join(d, "loo.csv"), buf.getvalue())
    q = {k: v for k, v in fit.quality.items() if k != "loo_pred"}
    q["pred_vs_verified_mae"] = None
    ctx.log(f"대리모델 {q['kind']} n={q['n_train']} d={q['d_free']} LOO RMSE={q['loo_rmse']:.4g} Q2={q['q2']}")
    ctx.patch_result({"fit": q})


# ---- SO_PROPOSE -----------------------------------------------------------------------------------


def so_propose(ctx: Any) -> None:
    opt = _opt(ctx)
    r = _round(ctx)
    res = ctx.result()
    if res.get("stop"):
        raise StepSkipped(f"정지: {STOP_TEXT.get(res['stop'], res['stop'])}")
    s = opt["settings"]
    cfg = ctx.settings.surrogate_opt
    problem = _problem(opt)
    O = _O(ctx, opt)
    _threads(ctx)
    from physicsai_core.stage5_optimize.surrogate import infill

    with open(os.path.join(_iter_dir(O, r), "surrogate.json"), encoding="utf-8") as fh:
        fit = infill.FitResult.from_json(json.load(fh))
    designs, failed = ds.merge(_read_points(ctx, O, problem, r - 1), problem)
    clock = _Clock(ctx)
    if so_algo.settings_algorithm(s) != "ego":  # opt-native §6: GA·NSGA-II 내부 탐색기
        from .surrogate_evo import propose_evo

        propose_evo(ctx, opt, problem, fit, designs, failed, _iter_dir(O, r), r, clock)
        return
    if problem.multi:  # S17 §22.5.3·§22.5.4 예측 전선 + HVI·ParEGO
        mo.propose_multi(ctx, opt, problem, fit, designs, failed, _iter_dir(O, r), r, clock)
        return
    try:
        cands, optimum = infill.propose(fit, problem, designs, failed, k=int(s["candidates"]), seed=int(s["seed"]),
                                        round_no=r, de_maxiter=cfg.de_maxiter, de_popsize=cfg.de_popsize,
                                        progress=lambda i, n: ctx.progress(i / n * 100.0, f"후보 {i}/{n}"), checkpoint=clock)
    except infill.SurrogateError as exc:
        raise StepFailure(exc.code, exc.message) from None
    rows = ds.tag_baseline([c.as_dict(i) for i, c in enumerate(cands, 1)], problem)
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    cons = [c.key for c in problem.constraints]
    w.writerow(["doe_no", *problem.names, "predicted", "ei", *[f"pred:{k}" for k in cons]])
    for row in rows:
        w.writerow([row["doe_no"], *[repr(float(row["values"][n])) for n in problem.names], repr(row["predicted"]),
                    "" if row["ei"] is None else repr(row["ei"]), *[repr(v) for v in row["constraints_pred"]]])
    write_text(os.path.join(_iter_dir(O, r), "candidates.csv"), buf.getvalue())
    patch: dict[str, Any] = {"candidates": rows, "surrogate_optimum": optimum.as_dict() if optimum else None,
                             "fit": {**(ctx.result().get("fit") or {}), "algo": {"name": "ego"}}}  # opt-native §6.6
    if not rows:
        patch["stop"] = ds.STOP_NO_NEW
        ctx.log("새 후보 없음 — 기존 설계와 모두 같습니다")
    ctx.patch_result(patch)


# ---- SO_NEXT --------------------------------------------------------------------------------------


def _multi_matrix(ctx: Any, ps: dict[str, Any], st: dict[str, Any], rows: list[dict[str, Any]]) -> Any:
    from physicsai_core.geometry import baselines as bl
    from physicsai_core.stage4_predict.batch_multi import build_multi_table

    try:
        pm = bl.load(ctx.abs(ps["stored_rel"]), ctx.settings.geometry.max_report_bytes)
    except bl.MapError as exc:
        raise StepFailure(exc.code, exc.message) from None
    if pm is None or pm.get("status") != "confirmed":
        raise StepFailure("INPUT_CHANGED", "최적화를 시작한 뒤 다중 baseline 매칭표가 바뀌었습니다(미확정) — 확정 후 다시 실행하세요")
    levels = (st.get("levels") or {}).get("baseline") or []
    pts = []
    for v in rows:
        p = dict(v)
        if levels and isinstance(v.get("baseline"), (int, float)):
            p["baseline"] = levels[int(round(v["baseline"]))]
        pts.append(p)
    return build_multi_table(pts, ps, pm)


def _table_text(names: list[str], cands: list[dict[str, Any]]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(names)
    for c in cands:
        w.writerow([repr(float(c["values"][n])) for n in names])
    return buf.getvalue()


def so_next(ctx: Any) -> None:
    opt = _opt(ctx)
    r = _round(ctx)
    res = ctx.result()
    if so_algo.settings_verification(opt["settings"]) == "none" and (not res.get("stop") or res.get("stop") == ds.STOP_NO_NEW):
        _finalize_surrogate_only(ctx, opt, r, res)  # opt-native §5 ON-4: 검증 배치 없이 마무리
        return
    if res.get("stop"):
        _finalize(ctx, opt, r, res)
        return
    cands = res.get("candidates") or []
    with ctx.ex.engine.connect() as conn:
        ps = ps_repo.get(conn, opt["param_set_id"])
    if ps is None:
        raise StepFailure("INPUT_INVALID", "템플릿(파라미터 세트)을 찾을 수 없습니다")
    names = [str(p["name"]) for p in ps["parameters"]]
    if opt["settings"].get("multi_baseline"):  # opt-native §7: baseline 열 표 + 배정 메타(batch_native가 배정 준비본으로 생성)
        matrix = _multi_matrix(ctx, ps, opt["settings"], [c["values"] for c in cands])
    else:
        matrix = build_matrix_for({"kind": "table", "text": _table_text(names, cands)}, ps, ctx.settings)
    if matrix.problems or not matrix.rows:
        raise StepFailure("INPUT_INVALID", f"검증 조합을 만들 수 없습니다: {matrix.problems[:3]}")
    cfg = ctx.settings
    fit = res.get("fit")

    def tx(c: Any) -> dict[str, Any] | None:
        studies_repo.require(c, opt["study_id"], for_update=True)  # D3-25: batch_no 경합 차단
        o = so_repo.get(c, opt["id"], for_update=True)
        if o is None or o["status"] not in so_repo.ACTIVE or o["current_job_id"] != ctx.ex.job_id:
            return None
        prev = so_repo.get_iter(c, o["id"], r)
        if prev is not None:  # 멱등: 이미 등록된 검증 배치(이전 시도의 커밋)를 그대로 쓴다
            so_repo.set_opt(c, o["id"], status="VERIFYING", iter_no=r)
            pb = pb_repo.get(c, prev["batch_id"]) or {}
            return {"job_id": pb.get("job_id"), "batch_id": prev["batch_id"], "batch_label": batch_label(pb.get("batch_no") or 0),
                    "reused": True}
        job, batch = so_repo.create_opt_batch(
            c, opt=o, iter_no=r, kind="VERIFY", matrix=matrix, source_meta=matrix.source_meta,
            batch_dir_name=cfg.predict_batch.dir_name, simlab_mesh_name=cfg.predict.simlab_mesh_name,
            round_job_id=ctx.ex.job_id, candidates=cands)
        so_repo.set_iter(c, o["id"], r, fit=fit, predicted_front=res.get("predicted_front"))
        so_repo.set_opt(c, o["id"], status="VERIFYING", iter_no=r)
        return {"job_id": job["id"], "batch_id": batch["id"], "batch_label": batch_label(batch["batch_no"])}

    made = ctx.ex.db(tx)
    if made is None:
        ctx.log("내장 최적화가 이미 종료되어 검증 배치를 만들지 않았습니다")
        return
    ctx.log(f"검증 배치 {made['batch_label']} 등록: 후보 {len(cands)}개")
    ctx.patch_result({"verify_batch": made})


def _fmt(v: Any) -> str:
    return "—" if not isinstance(v, (int, float)) else f"{v:.4g}"


def stop_text(reason: str, improvement: float | None, tol_rel: float) -> str:
    if reason == ds.STOP_CONVERGED and improvement is not None:
        return f"수렴(개선 {improvement * 100:.1f}% < 기준 {tol_rel * 100:g}%)"
    return STOP_TEXT.get(reason, reason)


def _finalize(ctx: Any, opt: dict[str, Any], r: int, res: dict[str, Any]) -> None:
    problem = _problem(opt)
    s = opt["settings"]
    O = _O(ctx, opt)
    t = r - 1
    points = _read_points(ctx, O, problem, t)
    with ctx.ex.engine.connect() as conn:
        its = so_repo.iters(conn, opt["id"])
    preds = {(it["iter_no"], c.get("doe_no")): c.get("predicted") for it in its for c in (it.get("candidates") or [])}
    files = {"convergence.csv": "", "verified_runs.csv": ds.dataset_csv(points, problem, predicted=preds, with_feasible=True),
             "summary.json": None}
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["iter", "kind", "batch", "runs", "valid", "best_value", "best_feasible", "improvement_rel",
                *(["hv", "front_size"] if problem.multi else [])])
    for it in its:
        if it["kind"] in ("FINAL", "EXTRA"):
            continue
        mine = [p for p in points if p.iter_no == it["iter_no"]]
        w.writerow([it["iter_no"], it["kind"], mine[0].batch_label if mine else "", len(mine), sum(p.valid for p in mine),
                    "" if it["best_value"] is None else repr(it["best_value"]),
                    "" if it["best_feasible"] is None else str(it["best_feasible"]).lower(),
                    "" if it["improvement_rel"] is None else repr(it["improvement_rel"]),
                    *([("" if it.get("hv") is None else repr(it["hv"])),
                       ("" if it.get("front_size") is None else it["front_size"])] if problem.multi else [])])
    files["convergence.csv"] = buf.getvalue()
    best = ds.best_point(points, problem)
    # SO_COLLECT가 저장한 최선(작업·배치 id 포함)을 우선 — CSV에서 다시 읽은 점에는 id가 없다
    best_d = opt.get("best") or (_best_dict(best[0], best[1], problem) if best else None)
    reason = res["stop"]
    last_opt = None
    for it in reversed(its):
        if it.get("candidates"):
            last_opt = it["candidates"][0]
            break
    summary = {"label": so_repo.opt_label(opt["opt_no"]), "stop_reason": reason,
               "stop_text": stop_text(reason, res.get("improvement_rel"), float(s["tol_rel"])),
               "best": best_d, "iterations": t, "final_fit": res.get("fit"),
               "surrogate_optimum": res.get("surrogate_optimum") or last_opt, **_algo_meta(s),
               "note": "best는 실제 예측 체인으로 검증된 설계만, surrogate_optimum은 대리모델 예측(참고)"}
    for name in files:
        p = os.path.join(O, name)
        if os.path.lexists(p):
            ctx.backup([p])
    write_text(os.path.join(O, "convergence.csv"), files["convergence.csv"])
    write_text(os.path.join(O, "verified_runs.csv"), files["verified_runs.csv"])
    write_json_atomic(os.path.join(O, "summary.json"), summary)
    for name in files:
        ctx.add_output(os.path.join(O, name))
    n_verify = sum(1 for p in points if p.iter_no >= 1)
    obj = s["objective"]
    title = (f"내장 최적화 {so_repo.opt_label(opt['opt_no'])} 완료 — 최적 {ds.metric_label(obj['metric'], obj.get('series'))} "
             f"{_fmt(best_d['objective'] if best_d else None)} (반복 {t} · 검증 {n_verify} run)")
    if problem.multi:  # §22.7 다목적 알림 문구
        title = mo.notice_title(so_repo.opt_label(opt["opt_no"]), problem, its, best_d, t, n_verify)
    body = summary["stop_text"] + ("" if not best_d or best_d["feasible"] else " · 제약을 만족하는 설계 없음(위반 최소 설계)")

    final_plan = _final_plan(ctx, opt, r, best_d, problem)
    final_plan.update({"stop_reason": reason, "notice": {"title": title, "body": body}})

    def tx(c: Any) -> str | None:
        studies_repo.require(c, opt["study_id"], for_update=True)  # D3-25: batch_no 경합 차단
        o = so_repo.get(c, opt["id"], for_update=True)
        if o is None or o["status"] not in so_repo.ACTIVE or o["current_job_id"] != ctx.ex.job_id:
            return None
        prev = so_repo.get_iter(c, o["id"], r)
        if prev is not None and prev["kind"] == "FINAL":  # 멱등: 이미 마무리 캡처 배치를 등록함
            return "reused"
        if final_plan["status"] == "SKIPPED" or final_plan.get("matrix") is None:
            so_repo.set_opt(c, o["id"], status="DONE", best=best_d, stop_reason=reason, finished_at=_now(),
                            final=_final_json(final_plan))
            notif_repo.notify_opt_done(c, o, ctx.ex.job_id, title, body)
            return "done"
        job, batch = so_repo.create_opt_batch(
            c, opt=o, iter_no=r, kind="FINAL", matrix=final_plan["matrix"], source_meta=final_plan["matrix"].source_meta,
            batch_dir_name=ctx.settings.predict_batch.dir_name, simlab_mesh_name=ctx.settings.predict.simlab_mesh_name,
            round_job_id=ctx.ex.job_id, capture=True, display=final_plan.get("display"))
        final_plan["batch_id"] = batch["id"]
        so_repo.set_opt(c, o["id"], status="FINALIZING", best=best_d, stop_reason=reason, final=_final_json(final_plan))
        return "finalizing"

    outcome = ctx.ex.db(tx)
    ctx.log(f"마무리: {outcome} — 캡처 {final_plan['status']}{(' · ' + final_plan['reason']) if final_plan.get('reason') else ''}")
    ctx.patch_result({"finished": True, "stop_text": summary["stop_text"], "final": outcome})


SURROGATE_ONLY_TEXT = "대리모델만(검증 없음)"


def _algo_meta(s: dict[str, Any]) -> dict[str, Any]:
    """summary.json·opt.json 기록(§6.6): algorithm·algo_options(기본 채운 사용값)·verification."""
    return {"algorithm": so_algo.settings_algorithm(s), "algo_options": s.get("algo_options") or {},
            "verification": so_algo.settings_verification(s)}


def _finalize_surrogate_only(ctx: Any, opt: dict[str, Any], r: int, res: dict[str, Any]) -> None:
    """verification none(ON-4): 검증 배치 없이 DONE·SURROGATE_ONLY. 후보는 반복 0 행 candidates에 UNVERIFIED로, 다목적이면
    predicted_front도 반복 0 행에. best = 탐색·재사용 run의 검증된 최선(SO_COLLECT가 저장). FINAL 캡처는 건너뛴다."""
    problem = _problem(opt)
    s = opt["settings"]
    O = _O(ctx, opt)
    points = _read_points(ctx, O, problem, r - 1)
    cands = [{**c, "state": "UNVERIFIED", "verified": None} for c in (res.get("candidates") or [])]
    reason = so_algo.STOP_SURROGATE_ONLY
    best_d = opt.get("best")
    if best_d is None:
        bp = ds.best_point(points, problem)
        best_d = _best_dict(bp[0], bp[1], problem) if bp else None
    fit = res.get("fit")
    summary = {"label": so_repo.opt_label(opt["opt_no"]), "stop_reason": reason, "stop_text": SURROGATE_ONLY_TEXT,
               "best": best_d, "iterations": 0, "final_fit": fit,
               "surrogate_optimum": res.get("surrogate_optimum"), "candidates": cands,
               "predicted_front_size": len(res.get("predicted_front") or []), **_algo_meta(s),
               "note": "best는 탐색(재사용) run 중 검증된 최선, 후보·surrogate_optimum은 대리모델 예측(미검증)"}
    files = {"verified_runs.csv": ds.dataset_csv(points, problem, with_feasible=True)}
    for name in (*files, "summary.json"):
        p = os.path.join(O, name)
        if os.path.lexists(p):
            ctx.backup([p])
    for name, text in files.items():
        write_text(os.path.join(O, name), text)
    write_json_atomic(os.path.join(O, "summary.json"), summary)
    for name in (*files, "summary.json"):
        ctx.add_output(os.path.join(O, name))
    title = (f"내장 최적화 {so_repo.opt_label(opt['opt_no'])} 완료(대리모델만) — 미검증 후보 {len(cands)}개, "
             "결과 화면에서 예측 검증하세요")
    body = SURROGATE_ONLY_TEXT
    final = {"status": "SKIPPED", "reason": "대리모델만(검증 없음) 모드는 마무리 캡처를 하지 않습니다", "stop_reason": reason,
             "notice": {"title": title, "body": body}}

    def tx(c: Any) -> str | None:
        o = so_repo.get(c, opt["id"], for_update=True)
        if o is None or o["status"] not in so_repo.ACTIVE or o["current_job_id"] != ctx.ex.job_id:
            return None
        so_repo.set_iter(c, o["id"], 0, fit=fit, candidates=cands, predicted_front=res.get("predicted_front"))
        so_repo.set_opt(c, o["id"], status="DONE", best=best_d, stop_reason=reason, finished_at=_now(), final=final)
        notif_repo.notify_opt_done(c, o, ctx.ex.job_id, title, body)
        return "done"

    outcome = ctx.ex.db(tx)
    ctx.log(f"마무리(대리모델만): {outcome} — 미검증 후보 {len(cands)}개")
    ctx.patch_result({"finished": True, "stop_text": SURROGATE_ONLY_TEXT, "final": outcome})


def _final_json(plan: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in plan.items() if k not in ("matrix", "display")}


def _final_plan(ctx: Any, opt: dict[str, Any], r: int, best_d: dict[str, Any] | None, problem: ds.Problem) -> dict[str, Any]:
    """D3-61 마무리 캡처 계획: 기준안(템플릿 nominal) + 최적안 2행 표 조합, 같은 범례(0 ~ max(기준안 예측, 최적값)).
    캡처가 구성되지 않았거나 최적안이 없으면 SKIPPED(사유)."""
    from physicsai_core.features import contour_capture_missing

    with ctx.ex.engine.connect() as conn:
        ps = ps_repo.get(conn, opt["param_set_id"])
    if ps is None or not best_d:
        return {"status": "SKIPPED", "reason": "최적안이 없어 캡처하지 않았습니다"}
    if opt["settings"].get("multi_baseline"):  # opt-native §7: 기준안·최적안의 baseline이 다를 수 있어 같은 범례 비교를 하지 않는다
        return {"status": "SKIPPED", "reason": "다중 baseline 세트는 마무리 캡처를 하지 않습니다(최적안은 ④에서 캡처하세요)"}
    names = [str(p["name"]) for p in ps["parameters"]]
    base = {str(p["name"]): float(p.get("nominal", p["min"])) for p in ps["parameters"]}
    plan: dict[str, Any] = {"status": "PENDING", "reason": None, "baseline_values": base, "legend": None,
                            "baseline_predicted": None, "baseline_doe": 1, "best_doe": 2}
    try:
        _threads(ctx)
        from physicsai_core.stage5_optimize.surrogate import infill

        with open(os.path.join(_iter_dir(_O(ctx, opt), r), "surrogate.json"), encoding="utf-8") as fh:
            fit = infill.FitResult.from_json(json.load(fh))
        import numpy as np

        x = np.array([base[n] for n in fit.free])
        pred = float(fit.sign * fit.objective.raw(fit.normalize(x))[0][0])
        plan["baseline_predicted"] = pred if math.isfinite(pred) else None
    except (OSError, ValueError, KeyError, ImportError):
        ctx.log("[WARN] 기준안 예측(범례)을 계산하지 못했습니다 — 범례 개별")
    legend, why = shared_legend(ctx.settings.capture, ps, opt["settings"]["objective"]["metric"],
                                [plan["baseline_predicted"], best_d.get("objective")])
    plan["legend"] = legend
    plan["legend_note"] = why
    tmpl, res = contour_capture_missing(ctx.settings)
    if tmpl or res:
        plan.update(status="SKIPPED", reason=f"컨투어 캡처가 구성되지 않았습니다({', '.join((tmpl + res)[:3])})")
        return plan
    vals = [base, {n: float((best_d.get("values") or {}).get(n, base[n])) for n in names}]
    matrix = build_matrix_for({"kind": "table", "text": _table_text(names, [{"values": v} for v in vals])}, ps, ctx.settings)
    if matrix.problems or len(matrix.rows) != 2:
        plan.update(status="SKIPPED", reason=f"캡처 조합을 만들 수 없습니다: {matrix.problems[:2]}")
        return plan
    plan["matrix"] = matrix
    if plan["legend"]:
        display = {"legend": {"mode": "fixed", **plan["legend"]}}
        if cc.validate_display(display):
            plan.update(legend=None, legend_note="범례 설정이 올바르지 않아 이미지마다 자동 범례")
        else:
            plan["display"] = display
    return plan


LEGEND_HEADROOM = 1.05


def shared_legend(capture_cfg: Any, ps: dict[str, Any], metric: str, values: list[Any]) -> tuple[dict[str, float] | None, str]:
    """기준안·최적안 같은 범례(D3-61): 목적이 컨투어 결과 종류의 RESP 값(`resp:<필드>_MAX|_MIN`, 또는 그 결과 종류를
    추출하는 템플릿 응답 이름)일 때만 0 ~ max(기준안 예측, 최적값) × 1.05. 아니면 None(이미지마다 자동) + 사유."""
    disp, _src = cc.resolve_display(capture_cfg, ps)
    field = str(disp.get("field") or "")
    names = {field} | {str(r.get("name")) for r in ps.get("responses") or []
                       if isinstance(r, dict) and isinstance(r.get("spec"), dict) and r["spec"].get("datatype") == field}
    # S17 §22.7: perf:<NAME>도 H3D·datatype = 컨투어 field·stat MAX·ABSMAX면 같은 범례 대상
    perf_ok = {f"perf:{r.get('name')}" for r in ps.get("responses") or []
               if isinstance(r, dict) and isinstance(r.get("spec"), dict)
               and str(r["spec"].get("source") or "H3D").upper() == "H3D" and r["spec"].get("datatype") == field
               and str(r["spec"].get("stat") or "").upper() in ("MAX", "ABSMAX")}
    if not any(metric in (f"resp:{n}_MAX", f"resp:{n}_MIN") for n in names if n) and metric not in perf_ok:
        return None, f"목적 지표가 컨투어 결과 종류({field})의 값이 아니라 이미지마다 자동 범례"
    nums = [float(v) for v in values if isinstance(v, (int, float)) and math.isfinite(v)]
    top = max(nums) * LEGEND_HEADROOM if nums else 0.0
    if not math.isfinite(top) or top <= 0:
        return None, "목적 값이 0 이하라 이미지마다 자동 범례"
    return {"min": 0.0, "max": top}, f"같은 범례 0 ~ {top:.4g}({field}, 여유 5%)"


def _now() -> Any:
    from sqlalchemy import func

    return func.now()


HANDLERS = {
    ("SURROGATE_OPT", "SO_COLLECT"): so_collect,
    ("SURROGATE_OPT", "SO_FIT"): so_fit,
    ("SURROGATE_OPT", "SO_PROPOSE"): so_propose,
    ("SURROGATE_OPT", "SO_NEXT"): so_next,
}
