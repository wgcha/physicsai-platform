"""⑥ 내장 최적화 상세의 S17 부분(phase3 §22.7·§22.10): 역할 정의(라벨·단위), 검증된 파레토 해·가중 추천·예측 전선·HV 추이,
추가 검증(EXTRA) `POST /surrogate-opts/{oid}/verify`.

검증된 해 = 최적화의 모든 검증 run(EXPLORE·REUSE·VERIFY·EXTRA, FINAL 제외) 중 만족 유효 설계(같은 설계 평균, key = 그 설계의 첫 run
`"<iter_no>:<doe_no>"`)의 비지배 집합 — 상세 요청마다 표준 라이브러리 `pareto.py`로 다시 계산한다(EXTRA run이 늘면 바로 반영).
"""

from __future__ import annotations

import math
from typing import Any

from physicsai_core.db.repositories import param_sets as ps_repo
from physicsai_core.db.repositories import predict_batches as pb_repo
from physicsai_core.db.repositories import studies as studies_repo
from physicsai_core.db.repositories import surrogate_opts as so_repo
from physicsai_core.errors import DomainError
from physicsai_core.stage4_predict import performance
from physicsai_core.stage4_predict.batch_matrix import batch_label, build_matrix_for
from physicsai_core.stage5_optimize.surrogate import dataset as ds

from ..auth import Principal
from ..context import AppContext
from .common import audit, require_config_ok, require_power
from .surrogate_opt_problem import snapshot_perfs

ACTIVE_BATCH = ("GENERATING", "PREDICTING")


def _label_unit(metric: str, series: str | None, perfs: dict[str, Any]) -> tuple[str, str]:
    if metric.startswith("perf:") and metric[5:] in perfs:
        d = perfs[metric[5:]]
        return performance.perf_label(d), d.unit
    return ds.metric_label(metric, series), ""


def role_defs(settings: dict[str, Any]) -> dict[str, Any]:
    """objectives·constraints_def·observe(라벨·단위)·weights·mode."""
    perfs = snapshot_perfs(settings)
    objs = []
    for o in ds.settings_objectives(settings):
        label, unit = _label_unit(o["metric"], o.get("series"), perfs)
        objs.append({"metric": o["metric"], "series": o.get("series"), "sense": o.get("sense"), "label": label,
                     "unit": unit})
    cons = []
    for c in settings.get("constraints") or []:
        label, unit = _label_unit(c["metric"], c.get("series"), perfs)
        cons.append({"metric": c["metric"], "series": c.get("series"), "op": c["op"], "value": c.get("value"),
                     "lo": c.get("lo"), "hi": c.get("hi"), "label": label, "unit": unit})
    obs = []
    for o in settings.get("observe") or []:
        label, unit = _label_unit(o["metric"], o.get("series"), perfs)
        obs.append({"metric": o["metric"], "series": o.get("series"), "label": label, "unit": unit})
    m = len(objs)
    w = [float(x) for x in settings.get("weights") or []] or ([1.0] if m == 1 else [])  # ON-C4: 저장된 사용자 값만
    return {"mode": "multi" if m >= 2 else "single", "objectives": objs, "constraints_def": cons, "observe": obs, "weights": w}


def _points(runs: list[dict[str, Any]]) -> list[ds.Point]:
    return [ds.Point(r["iter_no"], r["batch_label"], r["doe_no"], r["run_key"], dict(r["values"] or {}), r["objective"],
                     list(r["constraints"]), r["state"], r["job_id"], r["batch_id"], objectives=list(r["objectives"]),
                     observed=dict(r["observed"]), kind=r.get("kind")) for r in runs]


def front_of(runs: list[dict[str, Any]], problem: ds.Problem) -> tuple[list[ds.Design], list[ds.Design]]:
    """(설계 전부, 검증된 전선 — (iter_no, doe_no) 순)."""
    designs, _failed = ds.merge(_points(runs), problem)
    front = sorted(ds.front_designs(designs, problem), key=lambda d: (d.sources[0].iter_no, d.sources[0].doe_no))
    return designs, front


def _front_row(d: ds.Design, problem: ds.Problem) -> dict[str, Any]:
    p = d.sources[0]
    return {"key": p.key, "iter_no": p.iter_no, "doe_no": p.doe_no, "run_key": p.run_key, "job_id": p.job_id,
            "batch_label": p.batch_label, "values": dict(p.values), "objectives": list(d.objectives),
            "constraints": {c.key: v for c, v in zip(problem.constraints, d.constraints)}, "observed": dict(p.observed)}


def _extra_active(conn: Any, its: list[dict[str, Any]]) -> bool:
    for it in its:
        if it["kind"] == "EXTRA":
            b = pb_repo.get(conn, it["batch_id"])
            if b is not None and b["status"] in ACTIVE_BATCH:
                return True
    return False


def detail_extra(ctx: AppContext, conn: Any, o: dict[str, Any], ps: dict[str, Any], its: list[dict[str, Any]],
                 runs: list[dict[str, Any]], can_exec: bool) -> dict[str, Any]:
    """§22.10 상세 추가 키. runs의 on_front를 채운다(제자리)."""
    out = role_defs(o["settings"])
    out["can_verify_more"] = o["status"] == "DONE" and can_exec and not _extra_active(conn, its)
    out["pareto"] = None
    out["hv_history"] = None
    if out["mode"] != "multi":
        return out
    problem = ds.Problem.from_settings(o["settings"])
    designs, front = front_of(runs, problem)
    on = {p.key for d in front for p in d.sources}
    for r in runs:
        r["on_front"] = f"{r['iter_no']}:{r['doe_no']}" in on
    frame = o.get("hv_frame")
    hv = ds.hv_value(designs, problem, frame)[0] if frame and designs else None
    rec = None
    if front:
        idx, _scores = ds.recommend_design(front, problem, problem.weights)
        rec = front[idx].sources[0].key
    last = next((it for it in sorted(its, key=lambda x: -int(x["iter_no"])) if it.get("predicted_front")), None)
    out["pareto"] = {"hv": hv, "frame": frame, "front": [_front_row(d, problem) for d in front], "recommended_key": rec,
                     "predicted_iter": last["iter_no"] if last else None,
                     "predicted": list((last or {}).get("predicted_front") or [])}
    out["hv_history"] = [{"iter_no": it["iter_no"], "hv": it.get("hv"), "front_size": it.get("front_size"),
                          "improvement_rel": it.get("improvement_rel")}
                         for it in its if it["kind"] not in ("FINAL", "EXTRA") and it.get("hv") is not None]
    return out


# ---- 추가 검증(EXTRA) -------------------------------------------------------------------------------


def _multi_matrix(ctx: AppContext, ps: dict[str, Any], st: dict[str, Any], rows: list[dict[str, float]]) -> Any:
    from physicsai_core.geometry import baselines as bl
    from physicsai_core.stage4_predict.batch_multi import build_multi_table

    from .param_set_native_api import set_path

    pm = bl.load(set_path(ctx, ps), ctx.settings.ui.max_artifact_bytes)
    if pm is None or pm.get("status") != "confirmed":
        raise DomainError("PARAM_MAP_UNCONFIRMED", "매칭표가 확정되지 않았습니다 — 확정한 뒤 다시 검증하세요", status=409)
    levels = (st.get("levels") or {}).get("baseline") or []
    pts = []
    for v in rows:
        p: dict[str, Any] = dict(v)
        if levels and "baseline" in v:
            p["baseline"] = levels[int(round(v["baseline"]))]
        pts.append(p)
    return build_multi_table(pts, ps, pm)


def _table_text(names: list[str], rows: list[dict[str, float]]) -> str:
    return "\n".join([",".join(names), *[",".join(repr(float(v[n])) for n in names) for v in rows]]) + "\n"


def verify(ctx: AppContext, principal: Principal, opt_id: str, body: Any, rid: str, ip: str | None) -> dict[str, Any]:
    """§22.7: DONE opt의 고른 해를 최적화 소유 PREDICT_BATCH(source table) + iters EXTRA로 한 트랜잭션에서 등록."""
    cfg = ctx.settings
    with ctx.engine.begin() as conn:
        o0 = so_repo.get(conn, opt_id)
        if o0 is None:
            raise DomainError("SURROGATE_OPT_NOT_FOUND", "내장 최적화를 찾을 수 없습니다", status=404)
        study = studies_repo.require(conn, o0["study_id"], for_update=True)  # D3-25: batch_no 경합 차단
        o = so_repo.get(conn, opt_id, for_update=True)
        require_power(principal, study["project_id"])
        if not principal.is_global_admin and o["created_by"] != principal.user_id:
            raise DomainError("PERMISSION_DENIED", "내장 최적화 등록자 또는 관리자만 추가 검증할 수 있습니다", status=403,
                              required="owner_or_global_admin")
        require_config_ok(ctx)
        if o["status"] != "DONE":
            raise DomainError("SURROGATE_OPT_NOT_DONE", "완료(DONE)된 내장 최적화만 추가 검증할 수 있습니다", status=409)
        its = so_repo.iters(conn, o["id"])
        if _extra_active(conn, its):
            raise DomainError("SURROGATE_OPT_EXTRA_ACTIVE", "진행 중인 추가 검증 배치가 있습니다 — 끝난 뒤 다시 보내세요", status=409)
        problems: list[dict[str, Any]] = []
        n_max = cfg.surrogate_opt.max_extra_points
        if not 1 <= len(body.points) <= n_max:
            problems.append({"code": "EXTRA_POINTS_RANGE", "field": "points", "message": f"추가 검증 점은 1~{n_max}개입니다"})
        st = o["settings"]
        names = list(st["names"])
        bounds = {k: (float(v[0]), float(v[1])) for k, v in st["bounds"].items()}
        rows: list[dict[str, float]] = []
        for i, p in enumerate(body.points):
            vals: dict[str, float] = {}
            for n in names:
                lo, hi = bounds[n]
                if lo == hi:  # 고정 변수는 고정값
                    vals[n] = lo
                    continue
                v = p.values.get(n)
                if v is None or not math.isfinite(v):
                    problems.append({"code": "BOUNDS_OUT_OF_RANGE", "field": f"points.{i}.{n}", "message": f"'{n}' 값이 필요합니다"})
                    continue
                if v < lo - 1e-9 * max(1.0, abs(lo)) or v > hi + 1e-9 * max(1.0, abs(hi)):
                    problems.append({"code": "BOUNDS_OUT_OF_RANGE", "field": f"points.{i}.{n}",
                                     "message": f"'{n}' 값 {v:g}이 최적화 범위 {lo:g}~{hi:g} 밖입니다"})
                    continue
                vals[n] = float(v)
            unknown = sorted(set(p.values) - set(names))
            if unknown:
                problems.append({"code": "BOUNDS_OUT_OF_RANGE", "field": f"points.{i}", "message": f"알 수 없는 변수: {unknown}"})
            rows.append(vals)
        if problems:
            raise DomainError("SURROGATE_OPT_INVALID", "추가 검증 요청이 올바르지 않습니다", status=422, problems=problems)
        ps = ps_repo.get(conn, o["param_set_id"])
        if ps is None:
            raise DomainError("PARAM_SET_NOT_FOUND", "템플릿(파라미터 세트)을 찾을 수 없습니다", status=409)
        if st.get("multi_baseline"):  # opt-native §7: 다중 baseline 세트 = baseline 열 표(배정 메타 포함)
            matrix = _multi_matrix(ctx, ps, st, rows)
        else:
            matrix = build_matrix_for({"kind": "table", "text": _table_text(names, rows)}, ps, cfg)  # 정수는 batch_matrix 반영 규칙
        if matrix.problems or len(matrix.rows) != len(rows):
            raise DomainError("SURROGATE_OPT_INVALID", "추가 검증 조합을 만들 수 없습니다", status=422,
                              problems=[{"code": "BOUNDS_OUT_OF_RANGE", "field": "points", "message": str(matrix.problems[:3])}])
        iter_no = max([int(it["iter_no"]) for it in its] + [0]) + 1
        job, batch = so_repo.create_opt_batch(
            conn, opt=o, iter_no=iter_no, kind="EXTRA", matrix=matrix, source_meta=matrix.source_meta,
            batch_dir_name=cfg.predict_batch.dir_name, simlab_mesh_name=cfg.predict.simlab_mesh_name,
            capture=bool(body.capture), extra=True)
        audit(conn, principal, "SURROGATE_OPT_VERIFY", "surrogate_opt", o["id"],
              {"batch_id": batch["id"], "job_id": job["id"], "points": len(rows)}, rid, ip)
        return {"batch_id": batch["id"], "batch_label": batch_label(batch["batch_no"]), "job_id": job["id"], "iter_no": iter_no}
