"""④ 단일 예측 작업 params·사전조건(§10.6, §8.2): PREDICT, PREDICT_VERIFY."""

from __future__ import annotations

import math
import os
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from physicsai_core.db.repositories import jobs as jobs_repo
from physicsai_core.db.repositories import models as models_repo
from physicsai_core.db.repositories import param_sets as ps_repo
from physicsai_core.db.repositories import predict_batches as pb_repo
from physicsai_core.errors import DomainError
from physicsai_core.features import predict_mesh_only_missing, predict_parametric_missing
from physicsai_core.naming import RUN_KEY_RE
from physicsai_core.stage4_predict import prepared_input

from ...context import AppContext
from ..common import study_root
from .base import HpcOverrides, _P, invalid_errors, prerequisite_missing, require_model_pscfg


class PredictParams(_P):
    """§10.6 PREDICT + phase3 §11.5 `input_mode`(생략 = parametric, 기존 호환)."""

    input_mode: Literal["parametric", "prepared"] = "parametric"
    param_set_id: str | None = None
    model_id: str | None = None
    values: dict[str, float] | None = None
    value_source: Literal["nominal", "run", "manual"] | None = None
    source_run_key: str | None = Field(default=None, pattern=RUN_KEY_RE)
    input_path: str | None = Field(default=None, max_length=400)

    @field_validator("values")
    @classmethod
    def _finite(cls, v: dict[str, float] | None) -> dict[str, float] | None:
        for k, x in (v or {}).items():
            if not math.isfinite(x):
                raise ValueError(f"{k} 값은 유한해야 합니다")
        return v


class PredictVerifyParams(_P):
    predict_job_id: str
    hpc: HpcOverrides | None = None


PARAM_MODELS: dict[str, type[BaseModel]] = {
    "PREDICT": PredictParams,
    "PREDICT_VERIFY": PredictVerifyParams,
}


def prepare(ctx: AppContext, conn: Any, study: dict[str, Any], job_type: str, p: Any
            ) -> tuple[dict[str, Any], dict[str, Any] | None, list[dict[str, str]]]:
    """사전조건 확인(§8.2) → (저장할 params, 초기 result, warnings). 기능 확인(check_feature)은 디스패처가 먼저 한다."""
    cfg = ctx.settings
    sid = study["id"]
    warnings: list[dict[str, str]] = []
    if job_type == "PREDICT" and p.input_mode == "prepared":
        return _prepare_prepared(ctx, conn, study, p)
    if job_type == "PREDICT":
        _check_mode_fields(p)
        ps = ps_repo.get(conn, p.param_set_id) if p.param_set_id else ps_repo.current(conn, sid)
        if ps is None or ps["study_id"] != sid:
            raise prerequisite_missing("PARAM_SET")
        m = model_for(conn, study, p.model_id)
        require_model_pscfg(cfg, "edspy_predict", m)
        kind = template_kind(ps)
        require_template_features(cfg, kind)
        values = p.values or {}
        names = [x["name"] for x in ps["parameters"]]
        unknown = [k for k in values if k not in names]
        missing = [n for n in names if n not in values]
        if unknown or missing:
            raise invalid_errors([{"loc": ["params", "values", k], "msg": "unknown" if k in unknown else "required"}
                            for k in unknown + missing])
        if p.value_source == "run" and not p.source_run_key:
            raise invalid_errors([{"loc": ["params", "source_run_key"], "msg": "required"}])
        params = {
            "input_mode": "parametric", "param_set_id": ps["id"], "model_id": m["id"], "values": dict(values),
            "value_source": p.value_source, "source_run_key": p.source_run_key,
            "template_kind": kind,  # phase3 §14.4(B8): 서버가 확정 기록 — mesh_only면 MESH SKIPPED·RAD_ASSEMBLE 복사만
        }
        return params, {"model_id": m["id"], "param_set_id": ps["id"]}, warnings
    if job_type == "PREDICT_VERIFY":
        av = ctx.hpc.availability()
        if not av.configured:
            raise DomainError("HPC_NOT_CONFIGURED", "PBS 연결 안 됨 — 2차에서 제공(관리자 설정 필요)", status=409,
                              mode=av.mode)
        pj = jobs_repo.get_job(conn, p.predict_job_id)
        if pj is None or pj["study_id"] != sid or pj["job_type"] != "PREDICT" or pj["state"] != "SUCCEEDED":
            raise prerequisite_missing("SUCCEEDED_PREDICT")
        inp = os.path.join(study_root(ctx, study), "04_predict", jobs_repo.root_job_id(conn, pj), "INPUT")
        if not os.path.isdir(inp):  # phase3 §5.5: Study 정리로 INPUT을 옮겼으면 검증 불가
            raise prerequisite_missing("PREDICT_INPUT")
        return p.model_dump(), None, warnings
    raise invalid_errors([{"loc": ["job_type"], "msg": "unknown"}])


def template_kind(ps: dict[str, Any]) -> str:
    """파라미터 세트(템플릿) 입력 종류: assembly | mesh_only(phase3 §14.3)."""
    return "mesh_only" if ps.get("input_kind") == "mesh_only" else "assembly"


def require_template_features(cfg: Any, kind: str) -> None:
    """템플릿 종류별 형상 생성 조건(409 TEMPLATE_NOT_CONFIGURED): assembly = predict_parametric(phase3 §11.4),
    mesh_only = predict_mesh_only(geom_update만 — MESH SKIPPED라 commands.mesh·include TCL 불필요, §14.4)."""
    if cfg.commands.geom_update is None:
        raise DomainError("TEMPLATE_NOT_CONFIGURED", "형상 갱신 명령 템플릿(geom_update)이 설정되지 않았습니다", status=409,
                          template="geom_update")
    tmpl, res = predict_mesh_only_missing(cfg) if kind == "mesh_only" else predict_parametric_missing(cfg)
    if tmpl or res:
        raise DomainError("TEMPLATE_NOT_CONFIGURED", f"형상 갱신 설정 필요(관리자): {', '.join(tmpl + res)}", status=409,
                          template="mesh" if res else tmpl[0].split(".", 1)[1], missing=tmpl + res)


def on_retry(conn: Any, old: dict[str, Any], new_id: str) -> None:
    """phase3 §14.5: 일괄 예측 하위 PREDICT 재시도 → run의 predict_job_id를 새 작업으로, 배치 PREDICTING."""
    if old["job_type"] == "PREDICT" and pb_repo.batch_run_ref(old) is not None:
        pb_repo.replace_child_job(conn, old["id"], new_id)


def _check_mode_fields(p: PredictParams) -> None:
    """phase3 §11.5 params 조합(422 INVALID_PARAMS): parametric → values·value_source 필수, input_path 금지.
    prepared → input_path 필수, values 비어 있음, value_source·source_run_key null."""
    errs: list[dict[str, Any]] = []
    if p.input_mode == "parametric":
        if p.values is None:
            errs.append({"loc": ["params", "values"], "msg": "required"})
        if p.value_source is None:
            errs.append({"loc": ["params", "value_source"], "msg": "required"})
        if p.input_path is not None:
            errs.append({"loc": ["params", "input_path"], "msg": "parametric 모드에서는 쓸 수 없습니다"})
    else:
        if not p.input_path:
            errs.append({"loc": ["params", "input_path"], "msg": "required"})
        if p.values:
            errs.append({"loc": ["params", "values"], "msg": "prepared 모드에서는 비어 있어야 합니다"})
        for k in ("value_source", "source_run_key"):
            if getattr(p, k) is not None:
                errs.append({"loc": ["params", k], "msg": "prepared 모드에서는 null이어야 합니다"})
    if errs:
        raise invalid_errors(errs)


def model_for(conn: Any, study: dict[str, Any], model_id: str | None) -> dict[str, Any]:
    """지정 모델(ACTIVE) 또는 Final(§8.2)."""
    sid = study["id"]
    if model_id:
        m = models_repo.get(conn, model_id)
        if m is None or m["study_id"] != sid or m["status"] != "ACTIVE":
            raise prerequisite_missing("ACTIVE_MODEL")
        return m
    if not study["final_model_id"]:
        raise DomainError("FINAL_MODEL_REQUIRED", "Final 모델을 먼저 지정하세요", status=409)
    m = models_repo.get(conn, study["final_model_id"])
    if m is None or m["status"] != "ACTIVE":
        raise DomainError("FINAL_MODEL_REQUIRED", "Final 모델이 ACTIVE가 아닙니다", status=409)
    return m


def _prepare_prepared(ctx: AppContext, conn: Any, study: dict[str, Any], p: PredictParams
                      ) -> tuple[dict[str, Any], dict[str, Any] | None, list[dict[str, str]]]:
    """phase3 §11.5 준비된 입력 예측: 경로·복사 계획 검사(422) → 모델·파라미터 세트(409). 세트는 응답 목록용(선택)."""
    _check_mode_fields(p)
    cp = prepared_input.check_path(p.input_path, ctx.settings)
    plan = prepared_input.plan_copy(cp.path, ctx.settings)
    if plan.problems:
        raise DomainError("PREDICT_INPUT_INVALID", "준비된 입력을 쓸 수 없습니다", status=422, problems=plan.problems)
    m = model_for(conn, study, p.model_id)
    require_model_pscfg(ctx.settings, "edspy_predict", m)
    if p.param_set_id:
        ps = ps_repo.get(conn, p.param_set_id)
        if ps is None or ps["study_id"] != study["id"]:
            raise prerequisite_missing("PARAM_SET")
    else:
        ps = ps_repo.current(conn, study["id"])
    params = {
        "input_mode": "prepared", "input_path": cp.path, "input_kind": plan.kind, "starter_name": plan.starter,
        "model_id": m["id"], "param_set_id": ps["id"] if ps else None,
    }
    return params, {"model_id": m["id"], "param_set_id": params["param_set_id"], "input_mode": "prepared"}, []
