"""④ 일괄 예측(DOE) 작업 params·사전조건(phase3 §14.5·§14.7 S9): PREDICT_BATCH.

조합 계산은 공용 `batch_matrix.build_matrix_for` — 미리보기(`services/predict_batches.preview`)와 같은 함수(`build_matrix`)를 쓴다.
저장 params에는 표 본문을 넣지 않는다(출처 요약만) — run 값은 predict_batch_runs에, 워커는 배치 행을 읽는다.
"""

from __future__ import annotations

import os
from contextvars import ContextVar
from typing import Any

from pydantic import BaseModel, Field

from physicsai_core.db.repositories import param_sets as ps_repo
from physicsai_core.db.repositories import predict_batches as pb_repo
from physicsai_core.db.repositories import train as train_repo
from physicsai_core.errors import DomainError
from physicsai_core.geometry import native_vars as nv
from physicsai_core.paths import resolve_in_study
from physicsai_core.stage1_train_data import doe_samples
from physicsai_core.stage4_predict.batch_matrix import (
    BatchMatrix,
    BatchShapeError,
    batch_dir_rel,
    batch_label,
    build_matrix_for,
)
from physicsai_core.stage4_predict.batch_multi import build_multi_matrix

from ...context import AppContext
from ...schemas.common import InputKind
from ...schemas.contour_capture import BatchCaptureOptions, CaptureDisplay
from ...schemas.native_vars import VarsEdit
from ...schemas.predict_batch import BatchSource
from ..common import study_root
from ..input_kind_gate import resolve_internal
from .base import _P, invalid_at, prerequisite_missing, require_model_pscfg
from ..geometry_gate import check_engine_match, engine_of, native_set_gate, require_map_confirmed
from .stage4_predict import model_for, require_template_features


class PredictBatchParams(_P):
    """§14.7 생성 body params. multi_execution = 사용자 입력 동시 실행 수(1~train_data.max_multi_execution)."""

    param_set_id: str | None = None
    model_id: str | None = None
    multi_execution: int = Field(ge=1, le=64)
    source: BatchSource
    display: CaptureDisplay | None = None  # phase3 §15 S10: 배치 단위 컨투어 표시(범례 fixed로 run끼리 비교)
    capture: BatchCaptureOptions | None = None  # D3-53: 하위 예측 컨투어 캡처 켜기·방향·동영상(null = 기본)
    vars: VarsEdit | None = None  # native-vars.md §6.3: Native 변수 그 자리 편집(이 실행에만 적용). train_doe·Altair는 불가
    input: InputKind | None = Field(default=None, description="예측 입력 종류 assembly(조립, m_3) | cushion(쿠션 rad만, m_3 없음). 생략 = 템플릿이 조립 가능하면 assembly, 쿠션만 가능하면 cushion. 능력 밖이면 422 INPUT_KIND_UNSUPPORTED")


PARAM_MODELS: dict[str, type[BaseModel]] = {
    "PREDICT_BATCH": PredictBatchParams,
}

# prepare → after_insert(같은 요청·같은 스레드)로 조합 행을 넘긴다(params에는 표 본문을 넣지 않으므로)
_PENDING: ContextVar[dict[str, Any] | None] = ContextVar("predict_batch_pending", default=None)


def resolve_param_set(conn: Any, study: dict[str, Any], param_set_id: str | None) -> dict[str, Any]:
    ps = ps_repo.get(conn, param_set_id) if param_set_id else ps_repo.current(conn, study["id"])
    if ps is None or ps["study_id"] != study["id"]:
        raise prerequisite_missing("PARAM_SET")
    return ps


def build_matrix(ctx: AppContext, conn: Any, study: dict[str, Any], ps: dict[str, Any], source: dict[str, Any]) -> BatchMatrix:
    """source(모양 검사 끝난 dict) → 조합(세트 정의 그대로). `vars`·모델이 필요한 Native 경로는 `build_matrix_vars`."""
    return build_matrix_vars(ctx, conn, study, ps, source, None, None)[0]


def _samples(ctx: AppContext, conn: Any, study: dict[str, Any], source: dict[str, Any]) -> tuple[list[str], list[dict[str, Any]]]:
    """train_doe: DOE 상태 확인(409) 후 samples.csv를 읽는다."""
    d = train_repo.get_doe(conn, source.get("doe_id") or "")
    if d is None or d["study_id"] != study["id"] or d["status"] != "READY":
        raise DomainError("DOE_NOT_READY", "READY 상태의 DOE가 필요합니다", status=409)
    if d["sample_status"] not in ("PARSED", "PARTIAL") or not d["samples_rel"]:
        raise DomainError("SAMPLES_MISSING", "DOE 샘플 표가 없습니다(샘플 추출기 설정 확인)", status=409)
    path = resolve_in_study(study_root(ctx, study), d["samples_rel"])
    if not os.path.isfile(path):
        raise DomainError("SAMPLES_MISSING", "DOE 샘플 표 파일이 없습니다(Study 정리로 옮겨졌을 수 있습니다)", status=409)
    return doe_samples.read_samples_csv(path)


def build_matrix_vars(ctx: AppContext, conn: Any, study: dict[str, Any], ps: dict[str, Any], source: dict[str, Any],
                      vars_req: Any, model: dict[str, Any] | None) -> tuple[BatchMatrix, Any]:
    """조합 + 변수 확정(native-vars.md §6.3). 유효 변수(세트 − exclude + add)로 조합을 만들고, 오류·경고는 `matrix.problems`·`notes`에 합친다.
    Altair: `vars`가 오면 problem NATIVE_VARS_UNSUPPORTED(그 밖 무변경). train_doe: `vars` 거부, 유효 변수 = DOE 헤더."""
    from .. import native_vars_run  # 지연 import(순환: native_vars_api → param_set_native_api → jobs → job_params)

    pm = multi_map(ctx, ps)
    cont = _continue_batch(conn, study, source)
    header = rows = None
    train_doe = source.get("kind") == "train_doe"
    if train_doe and pm is None:
        header, rows = _samples(ctx, conn, study, source)
    doe_names = [h for h in (header or [])[1:] if not h.startswith("resp:")] if train_doe and engine_of(ps) == "native" and pm is None else None
    res = native_vars_run.resolve(ctx, conn, study, ps, model, vars_req, doe_names=doe_names)
    extra: list[dict[str, Any]] = []
    for x in res.problems:
        code = x.get("code") or "RANGE_INVALID"
        if code == "NATIVE_VARS_MULTI_UNSUPPORTED":
            code = "RANGE_INVALID"
        extra.append({"code": code, "message": x["message"]})
    if train_doe and doe_names is not None and (res.vars is not None) and edit_of_nonempty(vars_req):
        extra.append({"code": "RANGE_INVALID", "message": "① 학습 DOE 재사용에는 변수 추가·제외를 쓸 수 없습니다"})
    if pm is not None:  # geometry-engine.md §7.3.8: 확정 다중 baseline 세트 = baseline별 층화 LHS(lhs만)
        try:
            mx = build_multi_matrix(source, ps, pm, ctx.settings)
        except BatchShapeError as exc:
            raise invalid_at("source", str(exc)) from None
        mx.problems = [*extra, *mx.problems]
        mx.notes = [*mx.notes, *res.notes]
        return mx, res
    oor = nv.out_of_range_parameters(res.vars) if res.vars is not None else None  # Native 일괄 out_of_range = 학습 범위(§5.3)
    try:
        mx = build_matrix_for(source, res.ps, ctx.settings, samples_header=header, samples=rows, continue_batch=cont, oor_parameters=oor)
    except BatchShapeError as exc:
        raise invalid_at("source", str(exc)) from None
    mx.problems = [*extra, *mx.problems]
    if res.vars is not None:
        mx.notes = [*mx.notes, *_var_notes(res, mx), *res.notes]
    return mx, res


def edit_of_nonempty(vars_req: Any) -> bool:
    from .. import native_vars_run

    add, exclude = native_vars_run.edit_of(vars_req)
    return bool(add or exclude)


def _var_notes(res: Any, mx: BatchMatrix) -> list[dict[str, str]]:
    """범위 경고(§6.3): 요청 범위(없으면 표본 값의 범위) 기준 VAR_OUT_OF_TRAIN·VAR_OUT_OF_FEASIBLE·… + 모핑 가능 범위 밖 run 요약."""
    ranges = mx.source_meta.get("ranges") if isinstance(mx.source_meta.get("ranges"), dict) else None
    if ranges is None and mx.rows:
        ranges = {n: [min(r.values[n] for r in mx.rows), max(r.values[n] for r in mx.rows)] for n in mx.rows[0].values}
    notes = [{"code": w["code"], "message": w["message"]} for w in nv.warn_rows(res.vars or {}, ranges)]  # ④ notes = {code, message}
    feas = {str(v["name"]): v.get("feasible") for v in (res.vars or {}).get("variables") or [] if v.get("feasible")}
    bad = sum(1 for r in mx.rows if any(
        (f.get("min") is not None and r.values.get(n, f["min"]) < f["min"] - 1e-9) or (f.get("max") is not None and r.values.get(n, f["max"]) > f["max"] + 1e-9)
        for n, f in feas.items()))
    if bad:
        notes.append({"code": "RUNS_OUT_OF_FEASIBLE", "message": f"모핑 가능 범위 밖 값이 있는 run {bad}개 — 형상 생성 실패(스킵) 가능"})
    return notes


def multi_map(ctx: AppContext, ps: dict[str, Any]) -> dict[str, Any] | None:
    """확정된 다중 baseline 매칭표(native 세트만, 없거나 draft면 None — draft는 작업 생성 때 409로 막힌다)."""
    if engine_of(ps) != "native":
        return None
    from physicsai_core.geometry import baselines as bl

    from ..param_set_native_api import set_path

    try:
        pm = bl.load(set_path(ctx, ps), ctx.settings.geometry.max_report_bytes)
    except bl.MapError as exc:
        raise DomainError(exc.code, exc.message, status=422, problems=exc.problems) from None
    return pm if pm is not None and pm.get("status") == "confirmed" else None


def _continue_batch(conn: Any, study: dict[str, Any], source: dict[str, Any]) -> dict[str, Any] | None:
    """Sobol 이어서 추가(S15 §20.5.3): 같은 Study의 이전 배치 행(id·표시·종류·템플릿·meta·run 값). 없거나 다른 Study면 {"missing": True}."""
    cid = source.get("continue_from") if source.get("kind") == "sobol" else None
    if not isinstance(cid, str) or not cid:
        return None
    b = pb_repo.get(conn, cid)
    if b is None or b["study_id"] != study["id"]:
        return {"missing": True}
    runs = ([{"doe_no": r["doe_no"], "values": r["values"]} for r in pb_repo.runs(conn, b["id"])]
            if b["source_kind"] == "SOBOL" else [])
    return {"id": b["id"], "label": batch_label(b["batch_no"]), "source_kind": b["source_kind"],
            "param_set_id": b["param_set_id"], "source_meta": b["source_meta"] or {}, "runs": runs}


def source_invalid(problems: list[dict[str, Any]]) -> DomainError:
    return DomainError("BATCH_SOURCE_INVALID", "조합을 만들 수 없습니다", status=422, problems=problems)


def prepare(ctx: AppContext, conn: Any, study: dict[str, Any], job_type: str, p: Any
            ) -> tuple[dict[str, Any], dict[str, Any] | None, list[dict[str, str]]]:
    """사전조건(§14.7 순서): 세트(409) → 템플릿 종류별 기능(409) → 모델(409) → 동시 실행 수(422) → 조합(422·409)."""
    cfg = ctx.settings
    if job_type != "PREDICT_BATCH":
        raise invalid_at("job_type", "unknown")
    ps = resolve_param_set(conn, study, p.param_set_id)
    native = engine_of(ps) == "native"
    kind = resolve_internal(ctx, ps, p.input)  # input-kind.md IK-1·IK-3(능력 밖 422, Native 쿠션 명령 없으면 409)
    m = model_for(conn, study, p.model_id)
    require_model_pscfg(cfg, "edspy_predict", m)
    warnings = check_engine_match(ps, m)
    if native:  # geometry-engine.md §7.7
        native_set_gate(ctx, ps)
        require_map_confirmed(ctx, ps)  # §7.3.8 확정 게이트(일괄 생성)
    else:
        require_template_features(cfg, kind)
    cap = cfg.train_data.max_multi_execution
    if p.multi_execution > cap:
        raise invalid_at("multi_execution", f"동시 실행 수는 1~{cap}")
    source = p.source.model_dump()
    matrix, res = build_matrix_vars(ctx, conn, study, ps, source, p.vars, m)
    if any(x["code"] == "NATIVE_VARS_UNSUPPORTED" for x in matrix.problems):  # native-vars.md §6.3: Altair에 vars → 422
        raise DomainError("NATIVE_VARS_UNSUPPORTED", "변수 추가·제외는 Native 템플릿에서만 쓸 수 있습니다", status=422)
    if matrix.problems or not matrix.rows:
        raise source_invalid(matrix.problems or [{"code": "TOO_FEW_ROWS", "message": "조합이 없습니다"}])
    batch_no = pb_repo.next_batch_no(conn, study["id"])  # create_job이 Study 행을 잠근 트랜잭션(D3-25)
    batch_id = pb_repo.new_batch_id()
    dir_rel = batch_dir_rel(cfg.predict_batch.dir_name, batch_no)
    params = {
        "batch_id": batch_id, "batch_no": batch_no, "param_set_id": ps["id"], "model_id": m["id"],
        "multi_execution": p.multi_execution, "template_kind": kind,
        "source": {"kind": source["kind"], **matrix.source_meta},  # 표 본문 저장 안 함(§14.3)
    }
    if res.vars is not None:  # native-vars.md §4.2: 사용한 변수 정의 전체를 job params + source_meta에 기록(워커·조회는 스냅숏 우선)
        params["vars"] = res.vars
        matrix.source_meta = {**matrix.source_meta, "vars": res.vars}
    _PENDING.set({"batch_id": batch_id, "matrix": matrix, "dir_rel": dir_rel,
                  "simlab_mesh_name": cfg.predict.simlab_mesh_name})
    if native:
        params["engine"] = "native"
    result = {"batch_id": batch_id, "batch_no": batch_no, "run_count": len(matrix.rows), "dir_rel": dir_rel}
    return params, result, warnings


def after_insert(conn: Any, principal: Any, study: dict[str, Any], job_type: str, job_id: str, params: dict[str, Any],
                 result: dict[str, Any] | None) -> None:
    """같은 트랜잭션에서 배치 행 + run 행(GENERATING, gen_state PENDING)."""
    pend = _PENDING.get()
    _PENDING.set(None)
    if pend is None or pend["batch_id"] != params.get("batch_id"):
        raise RuntimeError("PREDICT_BATCH 조합이 준비되지 않았습니다")
    pb_repo.create_batch(
        conn, batch_id=params["batch_id"], batch_no=params["batch_no"], study_id=study["id"], job_id=job_id,
        param_set_id=params["param_set_id"], model_id=params["model_id"], input_kind=params["template_kind"],
        matrix=pend["matrix"], multi_execution=params["multi_execution"], dir_rel=pend["dir_rel"],
        simlab_mesh_name=pend["simlab_mesh_name"], user_id=principal.user_id, user_name=principal.display_name,
    )


def on_retry(conn: Any, old: dict[str, Any], new_id: str) -> None:
    """부모 재시도(기존 /jobs/{id}/retry): 최신 부모를 새 작업으로, 배치 GENERATING, 생성 실패·중단 run은 생성 대기로."""
    bid = (old.get("params") or {}).get("batch_id")
    b = pb_repo.get(conn, bid, for_update=True) if isinstance(bid, str) else None
    if b is None or b["job_id"] != old["id"]:
        return
    pb_repo.reset_failed_gen(conn, b["id"])
    pb_repo.set_parent_job(conn, b["id"], new_id)
