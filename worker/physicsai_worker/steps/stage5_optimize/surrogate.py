"""⑤ 플랫폼 내장 최적화 반복 SURROGATE_OPT(phase3 §18.4·§18.5 S13): SO_COLLECT → SO_FIT → SO_PROPOSE → SO_NEXT.

반복 작업 r은 반복 0..r−1 배치(탐색·재사용·검증)의 run 결과로 대리모델을 적합하고 반복 r 후보 k개를 낸 뒤, 같은 트랜잭션에서
검증 PREDICT_BATCH(source table)를 등록한다(또는 정지 판정이면 마무리). 슬롯은 이 작업이 도는 동안만 잡는다 — 검증 배치가
끝나면 종료 훅(job_end → surrogate_opts.on_batch_done)이 다음 반복 작업을 넣는다.

폴더 O = <study>/05_opt/surrogate/SO-001: opt.json, iter_NN/{dataset.csv, surrogate.json, loo.csv, candidates.csv},
convergence.csv, verified_runs.csv, summary.json. 재실행이면 그 iter_NN/을 _backup 후 다시.
numpy·scipy는 SO_FIT·SO_PROPOSE 안에서만(BLAS 스레드 상한을 먼저 건다).
300줄 분할(R-B): 공용 도우미 `surrogate_common`, SO_COLLECT `surrogate_collect`, 마무리·같은 범례 `surrogate_final`
(여기서 재노출). SO_FIT·SO_PROPOSE·SO_NEXT와 HANDLERS는 이 파일.
"""

from __future__ import annotations

import csv
import io
import json
import os
import time
from typing import Any

from physicsai_core.db.repositories import param_sets as ps_repo
from physicsai_core.db.repositories import predict_batches as pb_repo
from physicsai_core.db.repositories import studies as studies_repo
from physicsai_core.db.repositories import surrogate_opts as so_repo
from physicsai_core.errors import StepFailure
from physicsai_core.fileutil import write_json_atomic, write_text
from physicsai_core.stage4_predict.batch_matrix import batch_label, build_matrix_for
from physicsai_core.stage5_optimize.surrogate import dataset as ds

from ...signals import StepSkipped
from . import surrogate_mo as mo
from .surrogate_common import (  # noqa: F401 - 기존 경로 재노출
    STOP_TEXT,
    _opt,
    _round,
    _O,
    _iter_dir,
    _problem,
    _read_points,
    _threads,
    _Clock,
    _table_text,
)
from .surrogate_collect import point_values, snapshot_perfs, collect_points, so_collect  # noqa: F401 - 기존 경로 재노출
from .surrogate_final import stop_text, _finalize, LEGEND_HEADROOM, shared_legend  # noqa: F401 - 기존 경로 재노출


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
    if problem.multi:  # S17 §22.5.3·§22.5.4 예측 전선 + HVI·ParEGO
        mo.propose_multi(ctx, opt, problem, fit, designs, failed, _iter_dir(O, r), r, clock)
        return
    try:
        cands, optimum = infill.propose(fit, problem, designs, failed, k=int(s["candidates"]), seed=int(s["seed"]),
                                        round_no=r, de_maxiter=cfg.de_maxiter, de_popsize=cfg.de_popsize,
                                        progress=lambda i, n: ctx.progress(i / n * 100.0, f"후보 {i}/{n}"), checkpoint=clock)
    except infill.SurrogateError as exc:
        raise StepFailure(exc.code, exc.message) from None
    rows = [c.as_dict(i) for i, c in enumerate(cands, 1)]
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    cons = [c.key for c in problem.constraints]
    w.writerow(["doe_no", *problem.names, "predicted", "ei", *[f"pred:{k}" for k in cons]])
    for row in rows:
        w.writerow([row["doe_no"], *[repr(float(row["values"][n])) for n in problem.names], repr(row["predicted"]),
                    "" if row["ei"] is None else repr(row["ei"]), *[repr(v) for v in row["constraints_pred"]]])
    write_text(os.path.join(_iter_dir(O, r), "candidates.csv"), buf.getvalue())
    patch: dict[str, Any] = {"candidates": rows, "surrogate_optimum": optimum.as_dict() if optimum else None}
    if not rows:
        patch["stop"] = ds.STOP_NO_NEW
        ctx.log("새 후보 없음 — 기존 설계와 모두 같습니다")
    ctx.patch_result(patch)


def so_next(ctx: Any) -> None:
    opt = _opt(ctx)
    r = _round(ctx)
    res = ctx.result()
    if res.get("stop"):
        _finalize(ctx, opt, r, res)
        return
    cands = res.get("candidates") or []
    with ctx.ex.engine.connect() as conn:
        ps = ps_repo.get(conn, opt["param_set_id"])
    if ps is None:
        raise StepFailure("INPUT_INVALID", "템플릿(파라미터 세트)을 찾을 수 없습니다")
    names = [str(p["name"]) for p in ps["parameters"]]
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
HANDLERS = {
    ("SURROGATE_OPT", "SO_COLLECT"): so_collect,
    ("SURROGATE_OPT", "SO_FIT"): so_fit,
    ("SURROGATE_OPT", "SO_PROPOSE"): so_propose,
    ("SURROGATE_OPT", "SO_NEXT"): so_next,
}
