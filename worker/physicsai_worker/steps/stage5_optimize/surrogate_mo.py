"""⑥ 내장 최적화 다목적 분기(phase3 §22.5 S17) — SURROGATE_OPT 같은 4 step에서 목적 2·3개일 때 쓰는 부분.

- SO_COLLECT: r = 1에서 HV 정규화 틀 확정(`surrogate_opts.hv_frame`, 이미 있으면 재사용), 반복 t의 HV·전선 크기·HV 개선율,
  best = 검증된 전선 중 가중 추천점(settings.weights, 만족 해가 없으면 위반 최소).
- SO_FIT: 목적별 GP(`mo_infill.fit_mo`), loo.csv 열 `model,i,y,loo_mean,loo_std`.
- SO_PROPOSE: 예측 전선 + HVI·ParEGO 후보(`mo_infill.propose_mo`), candidates.csv·predicted_front.csv.
numpy·scipy는 SO_FIT·SO_PROPOSE 안에서만 불러온다(호출부가 BLAS 스레드 상한을 먼저 건다).
"""

from __future__ import annotations

import csv
import io
import json
import os
from collections.abc import Sequence
from typing import Any

from physicsai_core.db.repositories import surrogate_opts as so_repo
from physicsai_core.errors import StepFailure
from physicsai_core.fileutil import write_json_atomic, write_text
from physicsai_core.stage5_optimize.surrogate import dataset as ds

MAX_PREDICTED_FRONT = 28


def _best_from(d: ds.Design, feasible: bool, problem: ds.Problem, score: float | None) -> dict[str, Any]:
    p = d.sources[0]
    return {"iter_no": p.iter_no, "batch_id": p.batch_id, "batch_label": p.batch_label, "doe_no": p.doe_no,
            "run_key": p.run_key, "job_id": p.job_id, "values": dict(p.values), "objective": d.objectives[0],
            "objectives": {o.key: v for o, v in zip(problem.objectives, d.objectives)},
            "constraints": {c.key: v for c, v in zip(problem.constraints, d.constraints)}, "feasible": feasible,
            "weights": list(problem.weights), "score": score}


def best_multi(designs: Sequence[ds.Design], problem: ds.Problem) -> dict[str, Any] | None:
    """검증된 전선의 가중 추천점(§22.6, settings.weights). 만족 해가 없으면 위반량 최소 설계(feasible false)."""
    front = sorted(ds.front_designs(designs, problem), key=lambda d: (d.sources[0].iter_no, d.sources[0].doe_no))
    if front:
        idx, scores = ds.recommend_design(front, problem, problem.weights)
        return _best_from(front[idx], True, problem, scores[idx])
    if not designs:
        return None
    d = min(designs, key=lambda x: (ds.violation(x.constraints, problem.constraints), ds.signed_objectives(x, problem)[0]))
    return _best_from(d, False, problem, None)


def collect_multi(ctx: Any, opt: dict[str, Any], problem: ds.Problem, points: list[ds.Point], t: int
                  ) -> tuple[dict[str, Any], dict[str, Any] | None, float | None]:
    """(iters 갱신, best, HV 개선율)."""
    frame = opt.get("hv_frame")
    if frame is None:
        d0, _ = ds.merge([p for p in points if p.iter_no == 0], problem)
        frame = ds.make_hv_frame(d0, problem, ctx.settings.surrogate_opt.mo_ref_offset)
        if frame is not None:
            ctx.ex.db(lambda c: so_repo.set_opt(c, opt["id"], hv_frame=frame))
            opt["hv_frame"] = frame
            ctx.log(f"HV 정규화 틀 확정: ideal={frame['ideal']} nadir={frame['nadir']} 기준점 {1 + frame['ref_offset']:g}")

    def hv_upto(k: int) -> tuple[float | None, int]:
        if frame is None:
            return None, 0
        d, _ = ds.merge([p for p in points if p.iter_no <= k], problem)
        return ds.hv_value(d, problem, frame)

    hv_t, size = hv_upto(t)
    imp = ds.hv_improvement_rel(hv_upto(t - 1)[0], hv_t) if t >= 1 else None
    designs, _ = ds.merge(points, problem)
    upd = {"best_value": None, "best_feasible": size > 0, "improvement_rel": imp, "hv": hv_t, "front_size": size}
    return upd, best_multi(designs, problem), imp


def last_used_weights(its: Sequence[dict[str, Any]]) -> list[int]:
    """직전 반복까지 ParEGO에 쓴 가중치(격자 인덱스) — 최신 반복 fit.used_weights(§22.5.4 ②)."""
    for it in sorted(its, key=lambda x: -int(x["iter_no"])):
        uw = (it.get("fit") or {}).get("used_weights")
        if isinstance(uw, list):
            return [int(x) for x in uw if isinstance(x, int)]
    return []


def fit_multi(ctx: Any, problem: ds.Problem, designs: list[ds.Design], d: str, *, kind: str, restarts: int, seed: int,
              clock: Any) -> None:
    from physicsai_core.stage5_optimize.surrogate import infill, mo_infill

    try:
        fit = mo_infill.fit_mo(designs, problem, kind=kind, restarts=restarts, seed=seed,
                               progress=lambda lbl: ctx.progress(None, lbl), checkpoint=clock)
    except infill.SurrogateError as exc:
        raise StepFailure(exc.code, exc.message) from None
    for w in fit.warnings:
        ctx.add_warning(w["code"], w["message"][:480])
    import numpy
    import scipy

    loo_rows = fit.quality.pop("loo_rows", [])
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["model", "i", "y", "loo_mean", "loo_std"])
    for row in loo_rows:
        w.writerow([row[0], row[1], *[repr(float(v)) for v in row[2:]]])
    write_text(os.path.join(d, "loo.csv"), buf.getvalue())
    sj = fit.to_json()
    sj["versions"] = {"numpy": numpy.__version__, "scipy": scipy.__version__}
    write_json_atomic(os.path.join(d, "surrogate.json"), sj)
    q = dict(fit.quality)
    q["pred_vs_verified_mae"] = None
    ctx.log("대리모델 " + " · ".join(f"목적 {i + 1} {po['kind']} LOO RMSE={po['loo_rmse']:.4g} Q2={po['q2']}"
                                    for i, po in enumerate(q["per_objective"])))
    ctx.patch_result({"fit": q})


def propose_multi(ctx: Any, opt: dict[str, Any], problem: ds.Problem, fit: Any, designs: list[ds.Design],
                  failed: list[dict[str, float]], idir: str, r: int, clock: Any) -> None:
    from physicsai_core.stage5_optimize.surrogate import infill, mo_infill

    cfg = ctx.settings.surrogate_opt
    s = opt["settings"]
    frame = opt.get("hv_frame") or ds.make_hv_frame(designs, problem, cfg.mo_ref_offset)
    with ctx.ex.engine.connect() as conn:
        used = last_used_weights(so_repo.iters(conn, opt["id"]))
    try:
        prop = mo_infill.propose_mo(fit, problem, designs, failed, k=int(s["candidates"]), seed=int(s["seed"]), round_no=r,
                                    cfg=mo_infill.MoCfg.from_settings(cfg), hv_frame=frame, used_weights=used,
                                    progress=lambda i, n, lbl: ctx.progress(i / n * 100.0, lbl), checkpoint=clock)
    except infill.SurrogateError as exc:
        raise StepFailure(exc.code, exc.message) from None
    for w in prop.warnings:
        ctx.add_warning(w["code"], w["message"][:480])
    rows = ds.tag_baseline([c.as_dict(i) for i, c in enumerate(prop.candidates, 1)], problem)
    m = problem.m
    cons = [c.key for c in problem.constraints]
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["doe_no", *problem.names, "role", "weight", *[f"pred_{i}" for i in range(1, m + 1)],
                *[f"std_{i}" for i in range(1, m + 1)], "acq", *[f"pred:{k}" for k in cons]])
    for row in rows:
        w.writerow([row["doe_no"], *[repr(float(row["values"][n])) for n in problem.names], row["role"],
                    "" if row["weight"] is None else " ".join(f"{x:g}" for x in row["weight"]),
                    *[repr(v) for v in row["predicted_objectives"]], *[repr(v) for v in row["predicted_std"]],
                    "" if row["acq"] is None else repr(row["acq"]), *[repr(v) for v in row["constraints_pred"]]])
    write_text(os.path.join(idir, "candidates.csv"), buf.getvalue())
    front = ds.tag_baseline(prop.predicted_front[:MAX_PREDICTED_FRONT], problem)
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow([*problem.names, *[f"mean_{i}" for i in range(1, m + 1)], *[f"std_{i}" for i in range(1, m + 1)], "pof"])
    for p in front:
        w.writerow([*[repr(float(p["values"][n])) for n in problem.names], *[repr(v) for v in p["mean"]],
                    *[repr(v) for v in p["std"]], repr(p["pof"])])
    write_text(os.path.join(idir, "predicted_front.csv"), buf.getvalue())
    sp = os.path.join(idir, "surrogate.json")
    try:
        with open(sp, encoding="utf-8") as fh:
            sj = json.load(fh)
        sj["mo"] = {"used_weights": prop.used_weights, "seeds": prop.seeds, "hv_frame": frame}
        write_json_atomic(sp, sj)
    except (OSError, ValueError):
        ctx.log("[WARN] surrogate.json에 ParEGO 가중치·시드를 기록하지 못했습니다")
    res_fit = ctx.result().get("fit") or {}
    patch: dict[str, Any] = {"candidates": rows, "predicted_front": front, "used_weights": prop.used_weights,
                             "mo_seeds": prop.seeds,
                             "fit": {**res_fit, "used_weights": prop.used_weights, "algo": {"name": "ego"}},  # opt-native §6.6
                             "surrogate_optimum": None}
    ctx.log(f"예측 전선 {len(front)}점 · 후보 {len(rows)}개({', '.join(r_['role'] for r_ in rows)})")
    if not rows:
        patch["stop"] = ds.STOP_NO_NEW
        ctx.log("새 후보 없음 — 기존 설계와 모두 같습니다")
    ctx.patch_result(patch)


def _fmt(v: Any) -> str:
    return "—" if not isinstance(v, (int, float)) else f"{v:.4g}"


def notice_title(label: str, problem: ds.Problem, its: Sequence[dict[str, Any]], best_d: dict[str, Any] | None, t: int,
                 n_verify: int) -> str:
    """"내장 최적화 SO-002 완료 — 파레토 해 6개 · HV 0.712 · 추천 CornerStress 132.4 / AccelPeak 41.0 (반복 3 · 검증 12 run)"."""
    last = next((it for it in sorted(its, key=lambda x: -int(x["iter_no"]))
                 if it["kind"] not in ("FINAL", "EXTRA") and it.get("hv") is not None), None)
    size = (last or {}).get("front_size") or 0
    hv = (last or {}).get("hv")
    rec = ""
    if best_d and best_d.get("feasible"):
        objs = best_d.get("objectives") or {}
        rec = " · 추천 " + " / ".join(f"{ds.metric_label(o.metric, o.series)} {_fmt(objs.get(o.key))}" for o in problem.objectives)
    return f"내장 최적화 {label} 완료 — 파레토 해 {size}개 · HV {_fmt(hv)}{rec} (반복 {t} · 검증 {n_verify} run)"
