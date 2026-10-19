"""⑥ 내장 최적화 문제 정의(phase3 §18.6 + S17 §22.4): 미리보기·생성 공용 정규화(`normalize`)와 run 지표 계산.

목적 1~3(단수 `objective` 호환), 제약 ≤ 5(≤·≥·range), 관찰 ≤ max_observe, 가중치, 성능(`perf:<NAME>`) 스냅샷.
API는 numpy를 불러오지 않는다(§18.2) — 값은 공용 `run_metrics`·`performance`(표준 라이브러리)로 계산한다.
"""

from __future__ import annotations

import math
from typing import Any

from physicsai_core.db.repositories import jobs as jobs_repo
from physicsai_core.db.repositories import predict_batches as pb_repo
from physicsai_core.errors import DomainError
from physicsai_core.features import optimize_builtin_missing, predict_responses_missing
from physicsai_core.stage4_predict import nearest, performance, run_metrics
from physicsai_core.stage5_optimize.surrogate import dataset as ds

from ..context import AppContext
from .common import study_root
from .geometry_gate import check_engine_match, engine_of, native_set_gate
from .job_params.stage4_batch import resolve_param_set
from .job_params.stage4_predict import model_for, require_template_features, template_kind

MAX_CONSTRAINTS = 5
PERF_PREFIX = "perf:"


def _p(out: list[dict[str, Any]], code: str, message: str, field: str | None = None, **extra: Any) -> None:
    out.append({"code": code, "field": field, "message": message, **extra})


def require_feature(ctx: AppContext) -> None:
    tmpl, res = optimize_builtin_missing(ctx.settings)
    if tmpl or res:
        raise DomainError("FEATURE_NOT_AVAILABLE", f"플랫폼 내장 최적화를 쓸 수 없습니다(관리자 설정 필요): {', '.join(tmpl + res)}",
                          status=409, missing=tmpl + res)


# ---- 지표(run_metrics·performance) ------------------------------------------------------------------


def run_metric_rows(ctx: AppContext, conn: Any, study: dict[str, Any], batch_id: str) -> list[tuple[dict[str, Any], Any]]:
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


def metric_value(m: Any, metric: str, series: str | None, table: Any, perfs: dict[str, Any] | None = None
                 ) -> tuple[float | None, str | None]:
    """(값, 사유) — `perf:`는 performance.perf_value(사유 포함), 그 밖은 run_metrics.metric_value(사유 NO_VALUE)."""
    if m is None:
        return None, None
    if metric.startswith(PERF_PREFIX):
        d = (perfs or {}).get(metric[len(PERF_PREFIX):])
        if d is None:
            return None, "NOT_DEFINED"
        return performance.perf_value(d, m)
    try:
        v = run_metrics.metric_value(m, metric, series=series, table=table)
    except ValueError:
        return None, "NO_VALUE"
    return v, None if v is not None else "NO_VALUE"


def value(m: Any, metric: str, series: str | None, table: Any, perfs: dict[str, Any] | None = None) -> float | None:
    return metric_value(m, metric, series, table, perfs)[0]


def new_metrics(ps: dict[str, Any]) -> set[str]:
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


def snapshot_perfs(settings: dict[str, Any]) -> dict[str, Any]:
    """settings.performances 스냅샷 → PerfDef."""
    return performance.perf_defs([{"name": k, "unit": (v or {}).get("unit", ""), "spec": (v or {}).get("spec")}
                                  for k, v in (settings.get("performances") or {}).items()])


# ---- 정규화(미리보기·생성 공용) --------------------------------------------------------------------------


def _bounds(ps: dict[str, Any], body: Any, so: Any, problems: list[dict[str, Any]]) -> tuple[list[str], list[str], dict, dict]:
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
    return names, integer, bounds, fixed


def _weights(body: Any, m: int, problems: list[dict[str, Any]]) -> list[float]:
    if body.weights is None:
        return [1.0 / m] * m if m else []
    w = list(body.weights)
    if len(w) != m or any(not math.isfinite(x) or x < 0 for x in w) or sum(w) <= 0:
        _p(problems, "WEIGHTS_INVALID", "가중치는 목적 수와 같은 개수의 0 이상 유한 수이고 합이 0보다 커야 합니다", "weights")
        return [1.0 / m] * m if m else []
    tot = sum(w)
    return [x / tot for x in w]


def normalize(ctx: AppContext, conn: Any, study: dict[str, Any], body: Any) -> dict[str, Any]:
    """사전조건(409)과 설정 정규화. 반환: {ps, model, kind, settings, problems, free, integer, fixed, explore_count,
    reuse, valid_points, performances}."""
    cfg = ctx.settings
    so = cfg.surrogate_opt
    require_feature(ctx)
    ps = resolve_param_set(conn, study, body.param_set_id)
    kind = template_kind(ps)
    m = model_for(conn, study, body.model_id)
    check_engine_match(ps, m)  # geometry-engine.md §7.7: 세트·모델 엔진 일치(409 ENGINE_MISMATCH)
    if engine_of(ps) == "native":
        native_set_gate(ctx, ps)
    else:
        require_template_features(cfg, kind)
    problems: list[dict[str, Any]] = []
    names, integer, bounds, fixed = _bounds(ps, body, so, problems)
    free = [n for n in names if n in bounds and n not in fixed]
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
    rows: list[tuple[dict[str, Any], Any]] = []
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
        rows = run_metric_rows(ctx, conn, study, reuse["id"])
        explore_count = 0
    else:
        explore_count = body.explore.count if body.explore.count is not None else \
            ds.default_explore_count(len(free), cfg.predict_batch.max_runs)
        if explore_count < need:
            _p(problems, "EXPLORE_TOO_FEW", f"탐색 run은 최소 {need}개입니다(자유 변수 {len(free)}개)", "explore.count")
        elif explore_count > cfg.predict_batch.max_runs:
            _p(problems, "EXPLORE_TOO_MANY", f"탐색 run은 최대 {cfg.predict_batch.max_runs}개입니다", "explore.count")
    # 성능(템플릿 spec 있는 응답)
    perfs = performance.perf_defs(ps.get("responses"))
    perf_info = _perf_info(perfs, rows if reuse is not None else None)
    # 허용 지표
    if reuse is not None:
        allowed = {f"curve:{k}" for k in run_metrics.CURVE_KINDS if any(mm and mm.curve for _r, mm in rows)}
        allowed |= {f"resp:{k}" for _r, mm in rows if mm and mm.resp for k in mm.resp}
        allowed |= {f"tbl:{k}" for r, mm in rows if mm is not None for k in (r["responses"] or {})}
        allowed |= {x["id"] for x in perf_info if x["available"]}
    else:
        allowed = new_metrics(ps) | {x["id"] for x in perf_info}

    def metric_ok(metric: str, code: str, label: str, field: str) -> bool:
        if metric.startswith(PERF_PREFIX) and run_metrics.METRIC_RE.fullmatch(metric) and metric[5:] not in perfs:
            _p(problems, "PERF_UNDEFINED", f"성능 '{metric[5:]}'이 템플릿에 정의되어 있지 않습니다(추출 정의 필요)", field)
            return False
        if not run_metrics.METRIC_RE.fullmatch(metric) or metric not in allowed:
            _p(problems, code, f"{label} 지표 '{metric}'를 쓸 수 없습니다", field)
            return False
        return True

    # 목적
    if body.objective is not None and body.objectives is not None:
        _p(problems, "OBJECTIVES_CONFLICT", "objective와 objectives를 함께 보낼 수 없습니다", "objectives")
    objs = list(body.objectives) if body.objectives is not None else ([body.objective] if body.objective is not None else [])
    if not 1 <= len(objs) <= so.max_objectives:
        _p(problems, "OBJECTIVES_RANGE", f"목적은 1~{so.max_objectives}개입니다", "objectives")
    for i, o in enumerate(objs):
        metric_ok(o.metric, "METRIC_UNKNOWN", "목적" if len(objs) == 1 else f"목적 {i + 1}",
                  "objective.metric" if body.objectives is None else f"objectives.{i}.metric")
    # 제약
    if len(body.constraints) > MAX_CONSTRAINTS:
        _p(problems, "CONSTRAINT_INVALID", f"제약은 최대 {MAX_CONSTRAINTS}개입니다", "constraints")
    for i, c in enumerate(body.constraints):
        ok = metric_ok(c.metric, "CONSTRAINT_INVALID", f"제약 {i + 1}의", f"constraints.{i}")
        if not ok:
            continue
        if c.op == "range":
            if c.lo is None or c.hi is None or not (math.isfinite(c.lo) and math.isfinite(c.hi)) or c.lo >= c.hi:
                _p(problems, "CONSTRAINT_INVALID", f"제약 {i + 1}: 범위는 유한한 하한 < 상한이어야 합니다", f"constraints.{i}")
        elif c.value is None or not math.isfinite(c.value):
            _p(problems, "CONSTRAINT_INVALID", f"제약 {i + 1}: 값(유한 수)이 필요합니다", f"constraints.{i}")
    # 관찰
    if len(body.observe) > so.max_observe:
        _p(problems, "OBSERVE_INVALID", f"관찰 지표는 최대 {so.max_observe}개입니다", "observe")
    for i, o in enumerate(body.observe):
        metric_ok(o.metric, "OBSERVE_INVALID", f"관찰 {i + 1}의", f"observe.{i}")
    # 중복(목적끼리·목적·제약·관찰 사이)
    keys = [("objectives", (o.metric, o.series)) for o in objs] + [("constraints", (c.metric, c.series)) for c in body.constraints]
    keys += [("observe", (o.metric, o.series)) for o in body.observe]
    seen: dict[tuple[str, str | None], str] = {}
    for grp, k in keys:
        prev = seen.get(k)
        if prev is not None and (prev != grp or grp == "objectives"):
            _p(problems, "OBJECTIVE_DUPLICATE", f"지표 '{k[0]}'가 목적·제약·관찰에 겹칩니다", grp)
        seen.setdefault(k, grp)
    weights = _weights(body, len(objs), problems) if objs else []
    # 성능 사용 조건
    used_perf = [x for x in dict.fromkeys(mm for mm, _s in [k for _g, k in keys]) if x.startswith(PERF_PREFIX) and x[5:] in perfs]
    if reuse is None and any(perfs[x[5:]].source == "H3D" for x in used_perf):
        tmpl, res = predict_responses_missing(cfg)
        if tmpl or res:
            _p(problems, "PERF_EXTRACT_UNAVAILABLE", f"H3D 성능 추출을 쓸 수 없습니다(관리자 설정 필요): {', '.join((tmpl + res)[:3])}",
               "objectives")
    valid_points = None
    if reuse is not None:
        info = {x["id"]: x for x in perf_info}
        for x in [k for k in used_perf if k in {o.metric for o in objs} | {c.metric for c in body.constraints}]:
            if (info.get(x) or {}).get("available", 0) < need:
                _p(problems, "PERF_MISSING_IN_BATCH",
                   f"재사용 배치에 성능 '{x[5:]}' 값이 있는 성공 run이 {(info.get(x) or {}).get('available', 0)}개뿐입니다"
                   f"(최소 {need}개) — 성능을 다시 추출하세요", "explore.batch_id", action="extract", batch_id=reuse["id"],
                   performance=x[5:])
        need_metrics = [(o.metric, o.series) for o in objs] + [(c.metric, c.series) for c in body.constraints]
        valid_points = sum(1 for r, mm in rows if mm is not None and all(
            value(mm, mt, se, r["responses"], perfs) is not None for mt, se in need_metrics))
        if valid_points < need:
            _p(problems, "EXPLORE_TOO_FEW", f"재사용 배치에 목적 값이 있는 성공 run이 {valid_points}개뿐입니다(최소 {need}개)",
               "explore.batch_id")
    explore = ({"kind": "reuse", "batch_id": reuse["id"]} if reuse is not None
               else {"kind": "new", "count": explore_count, "seed": body.explore.seed})
    obj_rows = [{"metric": o.metric, "series": o.series, "sense": o.sense} for o in objs]
    settings = {
        "names": names, "integer": integer, "bounds": bounds,
        "objective": obj_rows[0] if obj_rows else None, "objectives": obj_rows,
        "constraints": [_constraint_row(c) for c in body.constraints],
        "observe": [{"metric": o.metric, "series": o.series} for o in body.observe], "weights": weights,
        "mode": "multi" if len(objs) >= 2 else "single",
        "performances": {x[5:]: {"unit": perfs[x[5:]].unit, "spec": dict(perfs[x[5:]].spec)} for x in used_perf},
        "surrogate": body.surrogate or so.default_surrogate, "iterations": iterations, "candidates": candidates,
        "tol_rel": tol, "seed": body.seed, "multi_execution": body.multi_execution, "capture": bool(body.capture),
        "explore": explore,
    }
    return {"ps": ps, "model": m, "kind": kind, "settings": settings, "problems": problems, "free": free,
            "integer": integer, "fixed": fixed, "explore_count": explore_count, "reuse": reuse, "valid_points": valid_points,
            "performances": perf_info}


def _constraint_row(c: Any) -> dict[str, Any]:
    row: dict[str, Any] = {"metric": c.metric, "series": c.series, "op": c.op,
                           "value": None if c.value is None else float(c.value)}
    if c.op == "range":
        row.update(value=None, lo=float(c.lo) if c.lo is not None else None, hi=float(c.hi) if c.hi is not None else None)
    return row


def _perf_info(perfs: dict[str, Any], rows: list[tuple[dict[str, Any], Any]] | None) -> list[dict[str, Any]]:
    """미리보기 `performances`(§22.4.2): 재사용이면 값 있는 run·전체 성공 run·SPEC_CHANGED run 수."""
    out = []
    for name, d in perfs.items():
        x: dict[str, Any] = {"id": f"{PERF_PREFIX}{name}", "name": name, "unit": d.unit, "source": d.source, "stat": d.stat,
                             "label": performance.perf_label(d), "available": None, "total": None, "spec_changed": None}
        if rows is not None:
            ok = [mm for _r, mm in rows if mm is not None]
            vals = [performance.perf_value(d, mm) for mm in ok]
            x.update(available=sum(1 for v, _w in vals if v is not None), total=len(ok),
                     spec_changed=sum(1 for _v, w in vals if w == "SPEC_CHANGED"))
        out.append(x)
    return out
