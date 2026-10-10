"""④ 단일 예측 작업 params·사전조건(§10.6, §8.2): PREDICT, PREDICT_VERIFY."""

from __future__ import annotations

import math
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from physicsai_core.db.repositories import jobs as jobs_repo
from physicsai_core.db.repositories import models as models_repo
from physicsai_core.db.repositories import param_sets as ps_repo
from physicsai_core.errors import DomainError
from physicsai_core.naming import RUN_KEY_RE

from ...context import AppContext
from .base import HpcOverrides, _P, invalid_errors, prerequisite_missing


class PredictParams(_P):
    param_set_id: str | None = None
    model_id: str | None = None
    values: dict[str, float]
    value_source: Literal["nominal", "run", "manual"]
    source_run_key: str | None = Field(default=None, pattern=RUN_KEY_RE)

    @field_validator("values")
    @classmethod
    def _finite(cls, v: dict[str, float]) -> dict[str, float]:
        for k, x in v.items():
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
    if job_type == "PREDICT":
        ps = ps_repo.get(conn, p.param_set_id) if p.param_set_id else ps_repo.current(conn, sid)
        if ps is None or ps["study_id"] != sid:
            raise prerequisite_missing("PARAM_SET")
        if p.model_id:
            m = models_repo.get(conn, p.model_id)
            if m is None or m["study_id"] != sid or m["status"] != "ACTIVE":
                raise prerequisite_missing("ACTIVE_MODEL")
        else:
            if not study["final_model_id"]:
                raise DomainError("FINAL_MODEL_REQUIRED", "Final 모델을 먼저 지정하세요", status=409)
            m = models_repo.get(conn, study["final_model_id"])
            if m is None or m["status"] != "ACTIVE":
                raise DomainError("FINAL_MODEL_REQUIRED", "Final 모델이 ACTIVE가 아닙니다", status=409)
        if cfg.commands.geom_update is None:
            raise DomainError("TEMPLATE_NOT_CONFIGURED", "형상 갱신 명령 템플릿(geom_update)이 설정되지 않았습니다", status=409,
                              template="geom_update")
        names = [x["name"] for x in ps["parameters"]]
        unknown = [k for k in p.values if k not in names]
        missing = [n for n in names if n not in p.values]
        if unknown or missing:
            raise invalid_errors([{"loc": ["params", "values", k], "msg": "unknown" if k in unknown else "required"}
                            for k in unknown + missing])
        if p.value_source == "run" and not p.source_run_key:
            raise invalid_errors([{"loc": ["params", "source_run_key"], "msg": "required"}])
        params = {
            "param_set_id": ps["id"], "model_id": m["id"], "values": dict(p.values), "value_source": p.value_source,
            "source_run_key": p.source_run_key,
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
        return p.model_dump(), None, warnings
    raise invalid_errors([{"loc": ["job_type"], "msg": "unknown"}])
