"""⑥ 내장 최적화 SO_PROPOSE의 GA·NSGA-II 분기(opt-native §6) — SURROGATE_OPT 같은 4 step, settings.algorithm으로 분기.

산출: iter_NN/{candidates.csv, algo_history.csv, final_population.csv, (다목적) predicted_front.csv}, surrogate.json `algo`,
결과 패치 candidates·predicted_front(DB ≤ 28점)·fit.algo·surrogate_optimum. numpy는 이 함수 안에서만(호출부가 BLAS 상한).
"""

from __future__ import annotations

import csv
import io
import json
import os
from typing import Any

from physicsai_core.errors import StepFailure
from physicsai_core.fileutil import write_json_atomic, write_text
from physicsai_core.stage5_optimize.surrogate import algo as so_algo
from physicsai_core.stage5_optimize.surrogate import dataset as ds


def _csv(head: list[str], rows: list[list[Any]]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(head)
    for r in rows:
        w.writerow(r)
    return buf.getvalue()


def _num(v: Any) -> str:
    return "" if v is None else (v if isinstance(v, str) else repr(float(v)))


def propose_evo(ctx: Any, opt: dict[str, Any], problem: ds.Problem, fit: Any, designs: list[ds.Design],
                failed: list[dict[str, float]], idir: str, r: int, clock: Any, space_factory: Any = None) -> None:
    from physicsai_core.stage5_optimize.surrogate import evo, evo_infill, infill

    s = opt["settings"]
    cfg = ctx.settings.surrogate_opt
    algorithm = so_algo.settings_algorithm(s)
    n_g_space = None
    try:
        space = space_factory(fit, problem) if space_factory is not None else evo_infill.Space.basic(fit, problem)
        n_g_space = len(space.genes)
        options = so_algo.resolve_options(algorithm, s.get("algo_options"), n_g_space, cfg)
        total = int(options["generations"])

        def prog(gen: int, n: int) -> None:
            ctx.progress(gen / max(n, 1) * 100.0, evo_infill.progress_label(algorithm, gen, n))

        ctx.progress(0.0, evo_infill.progress_label(algorithm, 0, total), force=True)
        if algorithm == "ga":
            prop = evo_infill.propose_ga(space, designs, failed, k=int(s["candidates"]), seed=int(s["seed"]), round_no=r,
                                         options=options, stall=cfg.ga_stall_generations, archive_max=cfg.ga_archive_max,
                                         progress=prog, checkpoint=clock)
        else:
            frame = opt.get("hv_frame") or ds.make_hv_frame(designs, problem, cfg.mo_ref_offset)
            prop = evo_infill.propose_nsga2(space, designs, failed, k=int(s["candidates"]), seed=int(s["seed"]), round_no=r,
                                            options=options, stall=cfg.ga_stall_generations, hv_frame=frame,
                                            ref_offset=cfg.mo_ref_offset, progress=prog, checkpoint=clock)
    except infill.SurrogateError as exc:
        raise StepFailure(exc.code, exc.message) from None
    multi = problem.multi
    rows = [{"doe_no": i, **c} for i, c in enumerate(prop.candidates, 1)]
    m = problem.m
    cons = [c.key for c in problem.constraints]
    extra = ["baseline"] if any("baseline" in (c.get("values") or {}) for c in rows) and "baseline" not in problem.names else []
    names = [*problem.names, *extra]
    head = ["doe_no", *names, "role", "weight", *[f"pred_{i}" for i in range(1, m + 1)],
            *[f"std_{i}" for i in range(1, m + 1)], "acq", *[f"pred:{k}" for k in cons]]
    body = [[row["doe_no"], *[_num(row["values"].get(n)) for n in names], row["role"], "",
             *[repr(v) for v in row["predicted_objectives"]], *[repr(v) for v in row["predicted_std"]],
             "" if row["acq"] is None else repr(row["acq"]), *[repr(v) for v in row["constraints_pred"]]] for row in rows]
    write_text(os.path.join(idir, "candidates.csv"), _csv(head, body))
    h_head, h_rows = evo.history_csv_rows(prop.result.history, multi)
    write_text(os.path.join(idir, "algo_history.csv"), _csv(h_head, h_rows))
    write_text(os.path.join(idir, "final_population.csv"), _csv(prop.population_head, prop.population_rows))
    front_db: list[dict[str, Any]] | None = None
    if multi:
        front = prop.predicted_front
        fh = [*names, *[f"mean_{i}" for i in range(1, m + 1)], *[f"std_{i}" for i in range(1, m + 1)], "pof"]
        fr = [[*[_num(p["values"].get(n)) for n in names], *[repr(v) for v in p["mean"]], *[repr(v) for v in p["std"]],
               repr(p["pof"])] for p in front]
        write_text(os.path.join(idir, "predicted_front.csv"), _csv(fh, fr))
        red = prop.algo.pop("front_reduce", None)
        front_db = [front[i] for i in red] if red is not None else list(front)
    else:
        prop.algo.pop("front_reduce", None)
    algo_rec = dict(prop.algo)
    sp = os.path.join(idir, "surrogate.json")
    try:
        with open(sp, encoding="utf-8") as fh_:
            sj = json.load(fh_)
        sj["algo"] = {**algo_rec, "options": options}
        write_json_atomic(sp, sj)
    except (OSError, ValueError):
        ctx.log("[WARN] surrogate.json에 알고리즘 기록을 남기지 못했습니다")
    for name in ("candidates.csv", "algo_history.csv", "final_population.csv", *(["predicted_front.csv"] if multi else [])):
        ctx.add_output(os.path.join(idir, name))
    res_fit = ctx.result().get("fit") or {}
    patch: dict[str, Any] = {"candidates": rows, "fit": {**res_fit, "algo": algo_rec}, "algo": algo_rec,
                             "surrogate_optimum": prop.optimum if not multi else None}
    if multi:
        patch["predicted_front"] = front_db
    label = so_algo.ALGO_LABEL[algorithm]
    stop_txt = "정체 종료" if algo_rec["stop"] == evo.STOP_STALL else "최대 세대"
    ctx.log(f"{label} 세대 {algo_rec['generations_run']}/{algo_rec['generations']}({stop_txt}) · 평가 {algo_rec['evals']} · "
            f"후보 {len(rows)}개({', '.join(r_['role'] for r_ in rows)})"
            + (f" · 예측 전선 {len(prop.predicted_front)}점" if multi else ""))
    if not rows:
        patch["stop"] = ds.STOP_NO_NEW
        ctx.log("새 후보 없음 — 기존 설계와 모두 같습니다")
    ctx.patch_result(patch)
