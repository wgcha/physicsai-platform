"""작업 종류 레지스트리 `JOB_KINDS`(mcp.md §5.1). 새 job_type은 여기 한 줄 등록 또는 `MCP_JOB_EXCLUDED`에 사유.

규칙: `plan_fn`·`create_fn`은 **기존 서비스 함수·미리보기 함수를 호출만** 한다(로직 복제 금지 — V-MCP-7이 가짜 서비스 주입으로 확인).
- plan_fn(ctx, principal, study_id, params_model) → JobPlan 수치 조각 dict(runs·parallel·lane·estimate·targets·warnings·problems)
- create_fn(ctx, principal, study_id, params_model, rid, ip) → (생성 결과 dict, 대표 작업 id | None, 엔티티 id | None)
- 서비스 모듈은 호출 시점에 `_svc(name)`으로 찾는다(시험이 가짜 모듈로 바꿔 끼운다).
"""

from __future__ import annotations

import statistics
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from physicsai_core.errors import DomainError
from physicsai_core.job_types import JOB_TYPES

from ..schemas import equiv_check as _EQ
from ..schemas import fem_verify_req as _FV
from ..schemas import surrogate_opt_req as _SO
from ..services import (
    equiv_check,
    fem_verify,
    geom_view_api,
    job_params,
    jobs,
    predict_batches,
    stage4_predict,
    surrogate_opt_pareto,
    surrogate_opts,
)
from ..services.job_params import stage1_train_data as _TD
from ..services.job_params import stage4_batch as _PB
from ..services.job_params import stage4_predict as _PR
from ..services.job_params import study_manage

SERVICES: dict[str, Any] = {
    "equiv_check": equiv_check, "fem_verify": fem_verify, "geom_view_api": geom_view_api, "job_params": job_params, "jobs": jobs,
    "job_params.study_manage": study_manage, "predict_batches": predict_batches, "stage4_predict": stage4_predict,
    "surrogate_opt_pareto": surrogate_opt_pareto, "surrogate_opts": surrogate_opts,
}


def _svc(name: str) -> Any:
    """기존 서비스 모듈(시험은 이 함수를 가짜로 바꿔 끼운다)."""
    return SERVICES[name]


@dataclass(frozen=True)
class JobKind:
    kind: str
    version: int
    label_ko: str
    stage: str  # 화면 번호(①-3 등)
    job_types: tuple[str, ...]
    cost: str  # heavy | light
    params_model: type[BaseModel]
    plan_fn: Callable[..., dict[str, Any]]
    create_fn: Callable[..., tuple[dict[str, Any], str | None, str | None]]
    summary_entity: str
    example: dict[str, Any]
    cancel_fn: Callable[..., Any] | None = None  # (ctx, principal, entity_id, rid, ip) — 없으면 기존 작업 취소
    limits: Callable[[Any], dict[str, Any]] = field(default=lambda s: {})


def described(base: type[BaseModel], name: str, docs: dict[str, str]) -> type[BaseModel]:
    """기존 params 모델을 그대로 쓰되(검증·서비스 호환) JSON Schema 최상위 필드에 설명·단위·범위 문구를 붙인 하위 클래스."""

    def extra(schema: dict[str, Any], cls: Any = None) -> None:
        props = schema.get("properties") or {}
        for k, d in docs.items():
            if k in props:
                props[k]["description"] = d

    cfg = ConfigDict(**{**base.model_config, "json_schema_extra": extra})  # type: ignore[typeddict-item]
    return type(name, (base,), {"model_config": cfg, "__doc__": base.__doc__, "__module__": __name__})


# ---- 공용 도우미(기존 서비스 호출) ---------------------------------------------------------------------


def problem(code: str, message: str, fld: str | None = None) -> dict[str, Any]:
    return {"code": code, "message": message, **({"field": fld} if fld else {})}


def problems_of(exc: DomainError) -> list[dict[str, Any]]:
    """DomainError → JobPlan.problems(code·message·field). problems·errors 상세가 있으면 펼친다."""
    out: list[dict[str, Any]] = []
    for p in exc.extra.get("problems") or []:
        if isinstance(p, dict):
            out.append(problem(str(p.get("code") or exc.code), str(p.get("message") or exc.message), p.get("field")))
    for e in exc.extra.get("errors") or []:
        if isinstance(e, dict):
            loc = ".".join(str(x) for x in e.get("loc") or [] if x not in ("body", "params"))
            out.append(problem(exc.code, f"{loc}: {e.get('msg')}" if loc else str(e.get("msg")), loc or None))
    if exc.extra.get("missing"):
        out.append(problem(exc.code, f"{exc.message}: {', '.join(map(str, exc.extra['missing']))}"))
    return out or [problem(exc.code, exc.message)]


def lane_info(job_type: str) -> dict[str, Any]:
    jt = JOB_TYPES[job_type]
    return {"lane": jt.lane, "uses_global_slot": jt.lane == "SLOT"}


def dry_prepare(ctx: Any, study_id: str, job_type: str, params: dict[str, Any]
                ) -> tuple[dict[str, Any] | None, list[dict[str, Any]], list[dict[str, Any]], dict[str, Any] | None]:
    """기존 범용 작업 생성의 검증 경로(게이트·params·사전조건)를 저장 없이 실행 → (저장될 params, warnings, problems, study).
    연결은 커밋하지 않고 닫는다(prepare는 읽기만 — 삽입·after_insert는 부르지 않는다)."""
    from physicsai_core.db.repositories import studies as studies_repo

    jp = _svc("job_params")
    sm = _svc("job_params.study_manage")
    with ctx.engine.connect() as conn:
        study = studies_repo.get(conn, study_id)
        if study is None:
            return None, [], [problem("NOT_FOUND", "Study를 찾을 수 없습니다", "study_id")], None
        try:
            sm.study_gate(conn, study, job_type)
            p = jp.parse_params(job_type, params)
            prepared, _result, warnings = jp.prepare(ctx, conn, study, job_type, p)
        except DomainError as exc:
            return None, [], problems_of(exc), study
    return prepared, [problem(w.get("code", "WARN"), w.get("message", "")) for w in warnings or []], [], study


def recent_per_run_min(ctx: Any, study_id: str, job_type: str, n_key: str = "num_runs", limit: int = 5) -> float | None:
    """최근 성공 작업의 run당 소요 중앙값[분](없으면 None)."""
    from physicsai_core.db.repositories import jobs as jobs_repo

    with ctx.engine.connect() as conn:
        rows = jobs_repo.list_with_study_title(conn, study_id=study_id, states=["SUCCEEDED"], created_by=None, job_type=job_type,
                                               limit=limit * 4, offset=0)
    per: list[float] = []
    for j in rows:
        n = (j.get("params") or {}).get(n_key) or (j.get("result") or {}).get("run_count")
        if j.get("started_at") and j.get("finished_at") and isinstance(n, int) and n > 0:
            per.append((j["finished_at"] - j["started_at"]).total_seconds() / n / 60.0)
        if len(per) >= limit:
            break
    return statistics.median(per) if per else None


def predict_estimate(ctx: Any, study_id: str, count: int) -> float | None:
    """④ 미리보기와 같은 계산(최근 성공 PREDICT 중앙값 × N) — predict_batches._estimate_min 재사용."""
    pb = _svc("predict_batches")
    with ctx.engine.connect() as conn:
        return pb._estimate_min(conn, study_id, count)


def _dump(p: BaseModel) -> dict[str, Any]:
    return p.model_dump(exclude_unset=True, mode="json")


def _job_id_of(out: dict[str, Any], *keys: str) -> str | None:
    for k in keys:
        v = out.get(k)
        if isinstance(v, dict):
            v = v.get("id")
        if isinstance(v, str):
            return v
    return None


# ---- ①-3 DOE 생성 ------------------------------------------------------------------------------------

DoeGenParams = described(_TD.TdDoeGenParams, "DoeGenerateParams", {
    "generator": "생성 방식 platform(표본 sampling) | hyperstudy(원본 doe_label) — 생략 = sampling 있으면 platform",
    "doe_label": "HyperStudy DOE 유형 이름(hyperstudy만, ①-3 유형 목록)",
    "num_runs": "run 수[개](2~train_data.max_runs, hyperstudy만)",
    "options": "HyperStudy DOE 옵션(유형별, hyperstudy만)",
    "sampling": "플랫폼 표본 방식 {kind: lhs|sobol|…, count[개], seed} — platform 필수",
    "seed": "native LHS 난수 시드[-](0 이상, native 형상 엔진 전용)",
    "multi_execution": "동시 실행 수[개](1~train_data.max_multi_execution, 생략 = platform_parallel_default)",
    "radioss_assem_path": "Radioss 조립 폴더 경로(허용 루트 안, 세트 기준 native DOE면 생략)",
    "on_run_failure": "run 실패 시 fail(작업 실패) | continue(계속, platform만)",
    "param_set_id": "native 파라미터 세트 기준 DOE면 세트 id",
})


def plan_doe(ctx: Any, principal: Any, study_id: str, p: Any) -> dict[str, Any]:
    prepared, warnings, problems, study = dry_prepare(ctx, study_id, "TD_DOE_GEN", _dump(p))
    out: dict[str, Any] = {**lane_info("TD_DOE_GEN"), "warnings": warnings, "problems": problems}
    if prepared is None:
        return out
    n = prepared.get("num_runs") if isinstance(prepared.get("num_runs"), int) else None
    cap = ctx.settings.train_data.max_multi_execution
    per = recent_per_run_min(ctx, study_id, "TD_DOE_GEN")
    out.update(runs=n, parallel=min(int(prepared.get("multi_execution") or 1), cap),
               estimate_min=round(per * n, 1) if per is not None and n else None,
               estimate_basis="recent_median" if per is not None and n else "none",
               targets={"study": f"{study['title']} ({study_id})" if study else study_id,
                        "engine": str(prepared.get("engine") or ("native" if prepared.get("param_set_id") else "altair")),
                        "doe": str(prepared.get("doe_label") or "")})
    return out


def create_generic(job_type: str, entity_key: str | None) -> Callable[..., tuple[dict[str, Any], str | None, str | None]]:
    def create(ctx: Any, principal: Any, study_id: str, p: Any, rid: str, ip: str | None) -> tuple[dict[str, Any], str | None, str | None]:
        out = _svc("jobs").create_job(ctx, principal, study_id, job_type, _dump(p), rid, ip)
        res = out.get("result") or {}
        ent = (res.get(entity_key) or (out.get("params") or {}).get(entity_key)) if entity_key else out["id"]
        return out, out["id"], ent
    return create


# ---- ①-4 PBS 제출 -----------------------------------------------------------------------------------

SolveParams = described(_TD.TdSolveParams, "SolvePbsParams", {
    "doe_id": "READY 상태 DOE id(①-3 결과)",
    "run_keys": "제출할 run 키 목록(생략 = 제출 가능한 run 전부, 최대 train_data.max_runs_per_submit)",
    "hpc": "PBS 덮어쓰기 {queue, ncpus[코어](1~4096), walltime(HH:MM:SS), version}",
    "on_run_failure": "run 실패 시 collect_partial(성공분 회수) | fail",
})


def plan_solve(ctx: Any, principal: Any, study_id: str, p: Any) -> dict[str, Any]:
    prepared, warnings, problems, study = dry_prepare(ctx, study_id, "TD_SOLVE", _dump(p))
    out: dict[str, Any] = {**lane_info("TD_SOLVE"), "warnings": warnings, "problems": problems}
    if prepared is None:
        return out
    from physicsai_core.db.repositories import train as train_repo

    with ctx.engine.connect() as conn:
        runs = train_repo.runs_for_doe(conn, prepared["doe_id"])
        d = train_repo.get_doe(conn, prepared["doe_id"]) or {}
    n = len(prepared["run_keys"]) if prepared.get("run_keys") else sum(1 for r in runs if r["state"] in train_repo.RESUBMIT_STATES)
    hpc = prepared.get("hpc") or {}
    av = ctx.hpc.availability()
    out.update(runs=n, parallel=None, hpc_jobs=n, estimate_basis="none",
               targets={"doe": f"{d.get('doe_label') or ''} ({prepared['doe_id']})", "hpc_mode": str(av.mode),
                        "queue": str(hpc.get("queue") or "기본"), "ncpus": str(hpc.get("ncpus") or "기본"),
                        "walltime": str(hpc.get("walltime") or "기본")})
    return out


# ---- ④ 단일 예측 ------------------------------------------------------------------------------------

PredictParams = described(_PR.PredictParams, "PredictKindParams", {
    "input_mode": "parametric(파라미터 값으로 형상 갱신) | prepared(준비된 입력 폴더)",
    "param_set_id": "파라미터 세트 id(생략 = 현재 세트)",
    "model_id": "모델 id(생략 = Final 모델)",
    "values": "파라미터 이름 → 값[세트 단위](범위는 세트 min~max, check_prediction_input으로 확인)",
    "value_source": "값 출처 nominal | run | manual",
    "source_run_key": "value_source=run일 때 학습 run 키",
    "input_path": "prepared일 때 준비된 입력 폴더 경로(허용 루트 안)",
    "display": "컨투어 표시 설정(선택)",
})


def plan_predict(ctx: Any, principal: Any, study_id: str, p: Any) -> dict[str, Any]:
    warnings: list[dict[str, Any]] = []
    if p.values:
        try:
            chk = _svc("stage4_predict").predict_check(ctx, study_id, p.param_set_id, dict(p.values))
            warnings += [problem("OUT_OF_RANGE", f"{o['name']}={o['value']}가 범위 {o['min']}~{o['max']} 밖", "values")
                         for o in chk.get("out_of_range") or []]
        except DomainError as exc:
            return {**lane_info("PREDICT"), "problems": problems_of(exc), "warnings": []}
    prepared, w2, problems, study = dry_prepare(ctx, study_id, "PREDICT", _dump(p))
    est = predict_estimate(ctx, study_id, 1) if not problems else None
    return {**lane_info("PREDICT"), "runs": 1, "parallel": 1, "warnings": warnings + w2, "problems": problems,
            "estimate_min": est, "estimate_basis": "recent_median" if est is not None else "none",
            "targets": {"param_set": str((prepared or {}).get("param_set_id") or p.param_set_id or "현재 세트"),
                        "model": str((prepared or {}).get("model_id") or p.model_id or "Final")}}


# ---- ④ 일괄 예측 ------------------------------------------------------------------------------------

BatchParams = described(_PB.PredictBatchParams, "PredictBatchKindParams", {
    "param_set_id": "파라미터 세트 id(생략 = 현재 세트)",
    "model_id": "모델 id(생략 = Final 모델)",
    "multi_execution": "입력 생성 동시 실행 수[개](1~64, 상한 train_data.max_multi_execution)",
    "source": "조합 원천 {kind: lhs|sobol|fullfact|table|train_doe…, count[개], seed, …}",
    "vars": "Native 템플릿 변수 그 자리 편집 {add, exclude}(이 실행에만 적용, 세트 정의는 안 바뀜) — get_native_vars로 변수 풀 확인",
    "display": "배치 단위 컨투어 표시(선택)",
    "capture": "하위 예측 컨투어 캡처 옵션(선택)",
})


def plan_batch(ctx: Any, principal: Any, study_id: str, p: Any) -> dict[str, Any]:
    from ..schemas.predict_batch_source import PredictBatchPreviewRequest

    try:
        pv = _svc("predict_batches").preview(ctx, study_id, PredictBatchPreviewRequest(param_set_id=p.param_set_id, source=p.source, model_id=p.model_id, vars=p.vars, input=p.input))
    except DomainError as exc:
        return {**lane_info("PREDICT_BATCH"), "problems": problems_of(exc), "warnings": []}
    cap = ctx.settings.train_data.max_multi_execution
    probs = [problem(str(x.get("code")), str(x.get("message")), x.get("field")) for x in pv.get("problems") or []]
    if p.multi_execution > cap:
        probs.append(problem("INVALID_PARAMS", f"동시 실행 수는 1~{cap}", "multi_execution"))
    return {**lane_info("PREDICT_BATCH"), "runs": pv.get("count"), "parallel": min(p.multi_execution, cap),
            "estimate_min": pv.get("estimate_min"), "estimate_basis": "recent_median" if pv.get("estimate_min") is not None else "none",
            "warnings": [problem(str(x.get("code")), str(x.get("message"))) for x in pv.get("notes") or []], "problems": probs,
            "targets": {"param_set": str(p.param_set_id or "현재 세트"), "model": str(p.model_id or "Final"),
                        "input_kind": str(pv.get("input_kind")), "input": str(pv.get("input"))}}


# ---- ⑥ 내장 최적화 ----------------------------------------------------------------------------------

OptParams = described(_SO.SurrogateOptCreate, "SurrogateOptKindParams", {
    "param_set_id": "파라미터 세트 id(생략 = 현재 세트)",
    "model_id": "모델 id(생략 = Final 모델)",
    "explore": "탐색 DOE {kind: new, count[개], seed} | {kind: reuse, batch_id}",
    "objective": "단일 목적 {metric, series?, sense: min|max}(objectives와 택1)",
    "objectives": "목적 1~3개 [{metric, series?, sense}]",
    "constraints": "제약 [{metric, op: <=|>=|range, value | lo·hi}]",
    "observe": "관찰만 할 응답 목록",
    "weights": "목적 2개 이상이면 가중치 목록[-](사용자 입력 필수)",
    "bounds": "변수 범위 {이름: [lo, hi]}[세트 단위](생략 = 템플릿 min~max, lo=hi는 고정)",
    "surrogate": "대리모델 gp | rbf(생략 = 설정 기본)",
    "iterations": "반복 수[회](1~surrogate_opt.max_iterations, 생략 = 기본)",
    "candidates": "반복당 검증 후보 수[개](1~surrogate_opt.max_candidates)",
    "tol_rel": "수렴 상대 허용[-](0~1)",
    "seed": "난수 시드[-](0~2^31)",
    "multi_execution": "입력 생성 동시 실행 수[개](1~64)",
    "capture": "검증 예측 컨투어 캡처 여부",
    "algorithm": "ego(기본) | ga(단일 목적) | nsga2(다목적)",
    "algo_options": "GA·NSGA-II 고급 옵션(선택)",
    "verification": "loop(반복 검증, 기본) | none(대리모델만)",
    "levels": "범주 수준 제한(다중 baseline 세트만)",
})


def plan_opt(ctx: Any, principal: Any, study_id: str, p: Any) -> dict[str, Any]:
    try:
        pv = _svc("surrogate_opts").preview(ctx, study_id, p)
    except DomainError as exc:
        return {**lane_info("SURROGATE_OPT"), "problems": problems_of(exc), "warnings": []}
    return {**lane_info("PREDICT_BATCH"), "runs": pv.get("max_total_runs"), "parallel": p.multi_execution,
            "estimate_min": pv.get("estimate_min"), "estimate_basis": "recent_median" if pv.get("estimate_min") is not None else "none",
            "problems": [problem(str(x.get("code")), str(x.get("message")), x.get("field")) for x in pv.get("problems") or []],
            "warnings": [], "targets": {"algorithm": str(pv.get("algorithm")), "verification": str(pv.get("verification")),
                                        "explore_runs": str(pv.get("explore_count"))}}


def create_opt(ctx: Any, principal: Any, study_id: str, p: Any, rid: str, ip: str | None) -> tuple[dict[str, Any], str | None, str | None]:
    out = _svc("surrogate_opts").create(ctx, principal, study_id, p, rid, ip)
    return out, out.get("current_job_id"), out.get("id")


def cancel_opt(ctx: Any, principal: Any, opt_id: str, rid: str, ip: str | None) -> Any:
    return _svc("surrogate_opts").cancel(ctx, principal, opt_id, rid, ip)


# ---- ⑥ 최적화 추가 검증 -------------------------------------------------------------------------------


class OptVerifyParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    opt_id: str = Field(min_length=1, max_length=64, description="완료(DONE)된 내장 최적화 id")
    points: list[_SO.SoVerifyPoint] = Field(min_length=1, max_length=50,
                                            description="검증할 해 [{values: {이름: 값[세트 단위]}}](1~surrogate_opt.max_extra_points개)")
    capture: bool = Field(default=False, description="검증 예측 컨투어 캡처 여부")


def plan_opt_verify(ctx: Any, principal: Any, study_id: str, p: Any) -> dict[str, Any]:
    from physicsai_core.db.repositories import surrogate_opts as so_repo

    try:
        o = _svc("surrogate_opts").get_opt(ctx, principal, p.opt_id)
    except DomainError as exc:
        return {**lane_info("PREDICT_BATCH"), "problems": problems_of(exc), "warnings": []}
    with ctx.engine.connect() as conn:
        raw = so_repo.get(conn, p.opt_id) or {}
    probs = []
    if raw.get("study_id") != study_id or o.get("status") != "DONE":
        probs.append(problem("SURROGATE_OPT_NOT_DONE", "같은 Study의 완료(DONE)된 내장 최적화만 추가 검증할 수 있습니다", "opt_id"))
    n_max = ctx.settings.surrogate_opt.max_extra_points
    if len(p.points) > n_max:
        probs.append(problem("EXTRA_POINTS_RANGE", f"추가 검증 점은 1~{n_max}개입니다", "points"))
    est = predict_estimate(ctx, study_id, len(p.points))
    return {**lane_info("PREDICT_BATCH"), "runs": len(p.points), "parallel": None, "problems": probs, "warnings": [],
            "estimate_min": est, "estimate_basis": "recent_median" if est is not None else "none",
            "targets": {"surrogate_opt": f"{o.get('label')} ({p.opt_id})",
                        "verification": str((o.get("param_set") or {}).get("engine") or "altair")}}


def create_opt_verify(ctx: Any, principal: Any, study_id: str, p: Any, rid: str, ip: str | None) -> tuple[dict[str, Any], str | None, str | None]:
    from physicsai_core.db.repositories import surrogate_opts as so_repo

    from ..schemas.surrogate_opt_req import SurrogateOptVerify

    with ctx.engine.connect() as conn:
        o = so_repo.get(conn, p.opt_id)
    if o is None or o["study_id"] != study_id:
        raise DomainError("SURROGATE_OPT_NOT_FOUND", "이 Study의 내장 최적화를 찾을 수 없습니다", status=404)
    body = SurrogateOptVerify(points=p.points, capture=p.capture)
    out = _svc("surrogate_opt_pareto").verify(ctx, principal, p.opt_id, body, rid, ip)
    return out, out.get("job_id"), p.opt_id


# ---- ⑤ 등가성 판정 ----------------------------------------------------------------------------------

EqParams = described(_EQ.EqCheckCreate, "EquivCheckKindParams", {
    "side_a": "기준 쪽 {kind: train_doe|predict_batch|fem_verify|folder, ref…}",
    "side_b": "비교 쪽(side_a와 같은 모양)",
    "pairing": "쌍 규칙 {mode: by_name|by_params|manual|all, pairs?}",
    "recipe": "저장된 레시피 {key, version?}(recipe_inline과 택1)",
    "recipe_inline": "1회용 레시피 정의",
    "bindings": "지표 id → 원천(레시피의 빈 원천 채우기)",
    "note": "메모(500자 이내)",
})


def plan_eq(ctx: Any, principal: Any, study_id: str, p: Any) -> dict[str, Any]:
    try:
        pv = _svc("equiv_check").preview(ctx, principal, study_id, p)
    except DomainError as exc:
        return {**lane_info("EQ_CHECK"), "problems": problems_of(exc), "warnings": []}
    ex = pv.get("extract") or {}
    return {**lane_info("EQ_CHECK"), "runs": (pv.get("pairing") or {}).get("n_pairs"), "parallel": 1,
            "disk_bytes_est": int(ex.get("copy_bytes") or 0),
            "problems": [problem(str(x.get("code")), str(x.get("message"))) for x in pv.get("problems") or []],
            "warnings": [problem(str(x.get("code")), str(x.get("message"))) for x in pv.get("warnings") or []],
            "targets": {"extract_h3d_runs": str(ex.get("h3d_runs", 0)), "extract_t01_runs": str(ex.get("t01_runs", 0))}}


def create_eq(ctx: Any, principal: Any, study_id: str, p: Any, rid: str, ip: str | None) -> tuple[dict[str, Any], str | None, str | None]:
    out = _svc("equiv_check").create(ctx, principal, study_id, p, rid, ip)
    return out, out.get("job_id"), out.get("eq_id")


# ---- ④ 조립 FEM 검증 --------------------------------------------------------------------------------

FvParams = described(_FV.FemVerifyCreate, "FemVerifyKindParams", {
    "source": "검증 대상 {kind: predict_job, job_id} | {kind: batch_run, batch_id, doe_no} | {kind: values, param_set_id, values} | {kind: opt_design, opt_id, pick}",
    "assembly": "조립 입력(생략 = 예측 입력이 조립 상태면 그것, 아니면 최신 READY DOE)",
    "fem": "FEM 비교 옵션(선택)",
    "display": "컨투어 표시 설정(선택)",
    "hpc": "HPC 덮어쓰기(선택)",
})


def plan_fv(ctx: Any, principal: Any, study_id: str, p: Any) -> dict[str, Any]:
    try:
        pv = _svc("fem_verify").preview(ctx, principal, study_id, p)
    except DomainError as exc:
        return {**lane_info("FEM_VERIFY"), "problems": problems_of(exc), "warnings": []}
    return {**lane_info("FEM_VERIFY"), "runs": 1, "parallel": 1, "hpc_jobs": 1,
            "problems": [problem(str(x.get("code")), str(x.get("message"))) for x in pv.get("problems") or []],
            "warnings": [problem(str(x.get("code")), str(x.get("message"))) for x in pv.get("warnings") or []],
            "targets": {"source": str(pv.get("source_label")), "hpc_mode": str(pv.get("hpc_mode"))}}


def create_fv(ctx: Any, principal: Any, study_id: str, p: Any, rid: str, ip: str | None) -> tuple[dict[str, Any], str | None, str | None]:
    out = _svc("fem_verify").create(ctx, principal, study_id, p, rid, ip)
    return out, _job_id_of(out, "job"), out.get("id")


def cancel_fv(ctx: Any, principal: Any, fid: str, rid: str, ip: str | None) -> Any:
    return _svc("fem_verify").cancel(ctx, principal, fid, rid, ip)


def cancel_batch(ctx: Any, principal: Any, batch_id: str, rid: str, ip: str | None) -> Any:
    return _svc("predict_batches").cancel_batch(ctx, principal, batch_id, rid, ip)


# ---- 형상 미리보기 ----------------------------------------------------------------------------------


class GeomPreviewParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    param_set_id: str = Field(min_length=1, max_length=64, description="native 파라미터 세트 id(이 Study)")
    values: dict[str, float] = Field(default_factory=dict, description="대표 파라미터 이름 → 값[세트 단위](빠진 이름은 공칭)")
    fe: str = Field(default="off", pattern="^(off|check)$", description="FE 품질 검사 off | check")


def plan_geom(ctx: Any, principal: Any, study_id: str, p: Any) -> dict[str, Any]:
    try:
        ps = _svc("stage4_predict").get_param_set(ctx, p.param_set_id)
    except DomainError as exc:
        return {**lane_info("GEOM_PREVIEW"), "problems": problems_of(exc), "warnings": []}
    probs = [] if ps.get("study_id") == study_id else [problem("NOT_FOUND", "이 Study의 파라미터 세트가 아닙니다", "param_set_id")]
    if ps.get("engine") != "native":
        probs.append(problem("NOT_NATIVE", "형상 미리보기는 native 세트만 가능합니다", "param_set_id"))
    return {**lane_info("GEOM_PREVIEW"), "runs": 1, "parallel": 1, "problems": probs,
            "warnings": [problem("CACHE_UNKNOWN", "같은 값의 캐시가 있으면 실행 없이 바로 결과를 돌려줍니다")],
            "targets": {"param_set": f"{ps.get('label') or ''} ({p.param_set_id})"}}


def create_geom(ctx: Any, principal: Any, study_id: str, p: Any, rid: str, ip: str | None) -> tuple[dict[str, Any], str | None, str | None]:
    from ..schemas.geometry_view import GeomPreviewCreate

    ps = _svc("stage4_predict").get_param_set(ctx, p.param_set_id)
    if ps.get("study_id") != study_id:
        raise DomainError("NOT_FOUND", "이 Study의 파라미터 세트가 아닙니다", status=404)
    out, _status = _svc("geom_view_api").create_preview(ctx, principal, p.param_set_id,
                                                         GeomPreviewCreate(values=p.values, fe=p.fe), rid, ip)  # type: ignore[arg-type]
    return out, out.get("job_id"), out.get("id")


# ---- 레지스트리 --------------------------------------------------------------------------------------

JOB_KINDS: dict[str, JobKind] = {k.kind: k for k in (
    JobKind("doe_generate", 1, "학습 데이터 DOE 생성", "①-3", ("TD_DOE_GEN",), "heavy", DoeGenParams, plan_doe,
            create_generic("TD_DOE_GEN", "doe_id"), "train_doe",
            {"generator": "platform", "sampling": {"kind": "lhs", "count": 20, "seed": 1}, "radioss_assem_path": "D:/AI/assem"},
            limits=lambda s: {"max_runs": s.train_data.max_runs, "max_multi_execution": s.train_data.max_multi_execution}),
    JobKind("solve_pbs", 1, "학습 데이터 PBS 해석 제출", "①-4", ("TD_SOLVE",), "heavy", SolveParams, plan_solve,
            create_generic("TD_SOLVE", "doe_id"), "train_doe", {"doe_id": "doe-1", "hpc": {"ncpus": 8}},
            limits=lambda s: {"max_runs_per_submit": s.train_data.max_runs_per_submit}),
    JobKind("predict", 1, "단일 예측", "④", ("PREDICT",), "light", PredictParams, plan_predict,
            create_generic("PREDICT", None), "predict_run", {"values": {"THK_1": 3.2}, "value_source": "manual"}),
    JobKind("predict_batch", 1, "일괄 예측", "④", ("PREDICT_BATCH",), "heavy", BatchParams, plan_batch,
            create_generic("PREDICT_BATCH", "batch_id"), "predict_batch",
            {"multi_execution": 4, "source": {"kind": "lhs", "count": 20, "seed": 1}}, cancel_fn=cancel_batch,
            limits=lambda s: {"max_runs": s.predict_batch.max_runs, "max_multi_execution": s.train_data.max_multi_execution}),
    JobKind("surrogate_opt", 1, "내장 최적화", "⑥", ("SURROGATE_OPT",), "heavy", OptParams, plan_opt, create_opt, "surrogate_opt",
            {"explore": {"kind": "new", "count": 20, "seed": 1}, "objective": {"metric": "MASS", "sense": "min"}},
            cancel_fn=cancel_opt,
            limits=lambda s: {"max_iterations": s.surrogate_opt.max_iterations, "max_candidates": s.surrogate_opt.max_candidates}),
    JobKind("surrogate_opt_verify", 1, "최적화 추가 검증", "⑥", ("PREDICT_BATCH",), "heavy", OptVerifyParams, plan_opt_verify,
            create_opt_verify, "surrogate_opt", {"opt_id": "opt-1", "points": [{"values": {"THK_1": 3.1}}]},
            limits=lambda s: {"max_extra_points": s.surrogate_opt.max_extra_points}),
    JobKind("equiv_check", 1, "해석 등가성 판정", "⑤", ("EQ_CHECK",), "heavy", EqParams, plan_eq, create_eq, "equiv_check",
            {"side_a": {"kind": "train_doe", "doe_id": "doe-1"}, "side_b": {"kind": "predict_batch", "batch_id": "b-1"},
             "recipe": {"key": "rcp-1"}},
            limits=lambda s: {"max_pairs": s.equiv_check.max_pairs, "max_active": s.equiv_check.max_active}),
    JobKind("fem_verify", 1, "조립 FEM 검증", "④", ("FEM_VERIFY",), "heavy", FvParams, plan_fv, create_fv, "fem_verify",
            {"source": {"kind": "predict_job", "job_id": "job-1"}}, cancel_fn=cancel_fv,
            limits=lambda s: {"max_active": s.fem_verify.max_active}),
    JobKind("geom_preview", 1, "형상 미리보기", "④", ("GEOM_PREVIEW",), "light", GeomPreviewParams, plan_geom, create_geom,
            "geom_preview", {"param_set_id": "ps-1", "values": {"THK_1": 3.2}}),
)}

# 등록하지 않는 job_type과 사유(§5.1). 나중에 등록하면 여기서 빼기만 한다(V-MCP-7).
MCP_JOB_EXCLUDED: dict[str, str] = {
    "DATASET_CREATE": "③ 모델 관리 — 사람 판단 단계",
    "PACKAGE_EXPORT": "③ 모델 관리 — 사람 판단 단계",
    "MODEL_REGISTER": "③ 모델 관리 — 사람 판단 단계",
    "EVALUATE": "③ 모델 관리 — 사람 판단 단계",
    "TD_EXTRACT_PARAMS": "데이터 준비",
    "TD_RESULT_IMPORT": "데이터 준비",
    "TD_RESP_EXTRACT": "데이터 준비",
    "CU_H3D_PREVIEW": "데이터 준비",
    "CU_H3D_CURATE": "데이터 준비",
    "CU_T01_PREVIEW": "데이터 준비",
    "CU_T01_CURVES": "데이터 준비",
    "SPDM_IMPORT": "데이터 준비",
    "OPTIMIZE": "레거시 HyperStudy 최적화",
    "PARAM_SET_NATIVE": "내부·후속 단계",
    "PB_RESP_EXTRACT": "내부·후속 단계",
    "CONTOUR_3D": "내부·후속 단계",
    "CONTOUR_RECAPTURE": "내부·후속 단계",
    "PREDICT_VERIFY": "내부·후속 단계",
    "STUDY_STORAGE_SCAN": "관리",
    "STUDY_CLEANUP": "관리",
}

# job_type → 대표 종류(작업 조회·취소에서 종류를 찾는다, 첫 등록 우선)
KIND_OF_JOB_TYPE: dict[str, str] = {}
for _k in JOB_KINDS.values():
    for _jt in _k.job_types:
        KIND_OF_JOB_TYPE.setdefault(_jt, _k.kind)

# 작업 행에서 엔티티 id를 찾는 키(params·result) — summary_entity와 짝
ENTITY_KEYS: dict[str, tuple[str, ...]] = {
    "train_doe": ("doe_id",), "predict_batch": ("batch_id",), "surrogate_opt": ("surrogate_opt_id", "surrogate_opt"),
    "equiv_check": ("eq_id",), "fem_verify": ("fem_verify_id",), "geom_preview": ("preview_id",),
}


def kind_of_job(job: dict[str, Any]) -> str | None:
    params = job.get("params") or {}
    if job["job_type"] == "PREDICT_BATCH" and params.get("surrogate_opt"):
        return "surrogate_opt"
    return KIND_OF_JOB_TYPE.get(job["job_type"])


def entity_of_job(job: dict[str, Any]) -> tuple[str, str | None] | None:
    kind = kind_of_job(job)
    if kind is None:
        return None
    ent = JOB_KINDS[kind].summary_entity
    if ent == "predict_run":
        return ent, job["id"]
    for src in (job.get("result") or {}, job.get("params") or {}):
        for key in ENTITY_KEYS.get(ent, ()):
            v = src.get(key)
            if isinstance(v, dict):
                v = v.get("id") or v.get("opt_id")
            if isinstance(v, str):
                return ent, v
    return ent, None


def confirm_required(kind: JobKind, settings: Any) -> bool:
    return kind.cost == "heavy" and bool(settings.mcp.require_confirm_for_token)


def kind_allowed(kind: str, settings: Any) -> bool:
    m = settings.mcp
    if m.allowed_job_kinds is not None and kind not in m.allowed_job_kinds:
        return False
    return kind not in (m.denied_job_kinds or [])
