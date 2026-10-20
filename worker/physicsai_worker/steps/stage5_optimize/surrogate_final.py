"""⑤ SURROGATE_OPT 마무리(정지 문구·summary·최종 검증 계획)와 같은 범례 — surrogate에서 재노출."""

from __future__ import annotations

import csv
import io
import json
import math
import os
from typing import Any

from physicsai_core.db.repositories import notifications as notif_repo
from physicsai_core.db.repositories import param_sets as ps_repo
from physicsai_core.db.repositories import studies as studies_repo
from physicsai_core.db.repositories import surrogate_opts as so_repo
from physicsai_core.fileutil import write_json_atomic, write_text
from physicsai_core.stage4_predict import contour_capture as cc
from physicsai_core.stage4_predict.batch_matrix import build_matrix_for
from physicsai_core.stage5_optimize.surrogate import dataset as ds

from . import surrogate_mo as mo
from .surrogate_collect import _best_dict
from .surrogate_common import _O, STOP_TEXT, _iter_dir, _now, _problem, _read_points, _table_text, _threads


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
               "surrogate_optimum": res.get("surrogate_optimum") or last_opt,
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
