"""⑥ 내장 최적화 문제 정의(phase3 §18.6 + S17 §22.4): 미리보기·생성 공용 정규화(`normalize`)와 run 지표 계산.

목적 1~3(단수 `objective` 호환), 제약 ≤ 5(≤·≥·range), 관찰 ≤ max_observe, 가중치, 성능(`perf:<NAME>`) 스냅샷.
API는 numpy를 불러오지 않는다(§18.2) — 값은 공용 `run_metrics`·`performance`(표준 라이브러리)로 계산한다.
300줄 분할(R-B): 지표(run_metrics·performance)는 `surrogate_opt_metrics`, 범위·수준·다중 baseline 등은
`surrogate_opt_space`(둘 다 여기서 재노출)."""

from __future__ import annotations

import math
from typing import Any

from physicsai_core.db.repositories import predict_batches as pb_repo
from physicsai_core.errors import DomainError
from physicsai_core.features import optimize_builtin_missing, predict_responses_missing
from physicsai_core.stage4_predict import performance, run_metrics
from physicsai_core.stage5_optimize.surrogate import algo as so_algo
from physicsai_core.stage5_optimize.surrogate import criteria
from physicsai_core.stage5_optimize.surrogate import dataset as ds

from ..context import AppContext
from .geometry_gate import check_engine_match, engine_of, native_set_gate
from .job_params.stage4_batch import resolve_param_set
from .job_params.stage4_predict import model_for, require_template_features, template_kind
from .surrogate_opt_metrics import (  # noqa: F401 - 기존 경로 재노출
    PERF_PREFIX, _p, run_metric_rows, metric_value, value, new_metrics, snapshot_perfs,
)
from .surrogate_opt_space import (  # noqa: F401 - 300줄 분할(R-B): 범위·가중치·다중 baseline·수준·제약 행·성능 미리보기
    _bounds, _constraint_row, _levels, _multi_settings, _perf_info, _weights, multi_baseline,
)

MAX_CONSTRAINTS = 5


def require_feature(ctx: AppContext) -> None:
    tmpl, res = optimize_builtin_missing(ctx.settings)
    if tmpl or res:
        raise DomainError("FEATURE_NOT_AVAILABLE", f"플랫폼 내장 최적화를 쓸 수 없습니다(관리자 설정 필요): {', '.join(tmpl + res)}",
                          status=409, missing=tmpl + res)



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
    multi = None
    if engine_of(ps) == "native":
        native_set_gate(ctx, ps)
        multi = multi_baseline(ctx, ps)  # opt-native §7: 확정 세트만(미확정 409 PARAM_MAP_UNCONFIRMED)
    else:
        require_template_features(cfg, kind)
    problems: list[dict[str, Any]] = []
    names, integer, bounds, fixed = _bounds(ps, body, so, problems)
    cat_levels = _levels(multi, body, so, problems)
    mb_settings = _multi_settings(multi, ps, cat_levels) if multi is not None else None
    if cat_levels is not None:  # 위상 변형: 범주 변수 baseline = 수준 인덱스 0..L−1(정수 표현, 인코딩은 원-핫)
        names = [*names, "baseline"]
        integer = sorted(set(integer) | {"baseline"})
        bounds["baseline"] = [0.0, float(len(cat_levels) - 1)]
        if len(cat_levels) == 1:
            fixed["baseline"] = 0.0
    free = [n for n in names if n in bounds and n not in fixed]
    verification = body.verification if body.verification is not None else "loop"
    iterations = body.iterations if body.iterations is not None else so.default_iterations
    candidates = body.candidates if body.candidates is not None else so.default_candidates
    tol = body.tol_rel if body.tol_rel is not None else so.default_tol_rel
    if verification == "none":  # opt-native §8: 반복·개선 기준은 무시하고 반복 1로 저장
        iterations, tol = 1, so.default_tol_rel
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
        n_lv = len(cat_levels) if cat_levels else 1  # R-3: 범주 수준 수를 곱한 값을 기본(권장)으로
        explore_count = body.explore.count if body.explore.count is not None else \
            min(ds.default_explore_count(len([n for n in free if n != "baseline"]), cfg.predict_batch.max_runs) * n_lv,
                cfg.predict_batch.max_runs)
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
    # ON-C4: 응답·방향·임계값·가중치는 사용자가 정한다 — 비면 OPT_CRITERIA_REQUIRED(자동 지정·기본값 없음)
    crit = criteria.missing(objs, body.constraints, body.weights, max_objectives=so.max_objectives,
                            obj_prefix="objective" if body.objectives is None and body.objective is not None else "objectives")
    if len(objs) > so.max_objectives:
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
            if c.lo is None or c.hi is None:
                continue  # 빈 하한·상한 = OPT_CRITERIA_REQUIRED
            if not (math.isfinite(c.lo) and math.isfinite(c.hi)) or c.lo >= c.hi:
                _p(problems, "CONSTRAINT_INVALID", f"제약 {i + 1}: 범위는 유한한 하한 < 상한이어야 합니다", f"constraints.{i}")
        elif c.value is not None and not math.isfinite(c.value):
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
    problems += criteria.problems_of(crit)
    # 알고리즘·고급 옵션·검증 방식(opt-native §6.1·§6.7·§8)
    algorithm = body.algorithm if body.algorithm is not None else "ego"
    n_g = len(free)
    problems += so_algo.algorithm_problems(algorithm, verification, max(len(objs), 1))
    if algorithm in so_algo.ALGORITHMS:
        problems += so_algo.option_problems(algorithm, body.algo_options, n_g, so, len(objs))
    algo_options = (so_algo.resolve_options(algorithm, body.algo_options, n_g, so, len(objs))
                    if algorithm in ("ga", "nsga2") and not any(p["code"] == "ALGO_OPTIONS_INVALID" for p in problems) else {})
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
        "explore": explore, "algorithm": algorithm, "algo_options": algo_options, "verification": verification,
    }
    if cat_levels is not None:  # opt-native §7: 다중 baseline 위상 세트 범주 변수
        settings["levels"] = {"baseline": list(cat_levels)}
    if mb_settings is not None:
        settings["multi_baseline"] = mb_settings
    kinds = {n: ("integer" if n in integer else "continuous") for n in free}
    if cat_levels is not None and len(cat_levels) > 1:
        kinds["baseline"] = "categorical"
    return {"ps": ps, "model": m, "kind": kind, "settings": settings, "problems": problems, "free": free,
            "integer": integer, "fixed": fixed, "explore_count": explore_count, "reuse": reuse, "valid_points": valid_points,
            "performances": perf_info, "variables_kind": kinds, "multi": multi, "criteria_missing": crit}
