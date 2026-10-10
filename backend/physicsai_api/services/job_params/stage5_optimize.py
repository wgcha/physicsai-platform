"""⑤ 최적화 작업 params·사전조건(phase2 §6.12): OPTIMIZE."""

from __future__ import annotations

import math
import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from physicsai_core.db.repositories import models as models_repo
from physicsai_core.db.repositories import param_sets as ps_repo
from physicsai_core.errors import DomainError
from physicsai_core.stage5_optimize import optimize as opt

from ...context import AppContext
from .base import _P, invalid_at, prerequisite_missing


class OptSettings(_P):
    abs_convergence: float = Field(default=0.001, ge=1e-6, le=1000)
    rel_convergence: float = Field(default=1.0, ge=1e-6, le=1000)
    dv_convergence: float = Field(default=0.001, ge=0, le=1000)


class OptimizeParams(_P):
    param_set_id: str | None = None
    model_id: str | None = None
    approach: Literal["OPT", "DOE"] = "OPT"
    opt_method: Literal["ARSM", "GRSM", "SQP"] = "ARSM"
    max_designs: int = Field(default=25, ge=1, le=100000)
    run_nominal: bool = True
    study_folder: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_\-]{1,64}$")
    opt_settings: OptSettings = Field(default_factory=OptSettings)
    on_failed: Literal["IGNORE", "TERMINATE"] = "IGNORE"
    responses: list[dict[str, Any]]

    @field_validator("responses")
    @classmethod
    def _finite(cls, v: list[dict[str, Any]]) -> list[dict[str, Any]]:
        for r in v:
            x = r.get("value") if isinstance(r, dict) else None
            if isinstance(x, float) and not math.isfinite(x):
                raise ValueError("value는 유한해야 합니다")
        return v


PARAM_MODELS: dict[str, type[BaseModel]] = {
    "OPTIMIZE": OptimizeParams,
}


def prepare(ctx: AppContext, conn: Any, study: dict[str, Any], job_type: str, p: Any
            ) -> tuple[dict[str, Any], dict[str, Any] | None, list[dict[str, str]]]:
    """사전조건 확인(§8.2) → (저장할 params, 초기 result, warnings). 기능 확인(check_feature)은 디스패처가 먼저 한다."""
    cfg = ctx.settings
    sid = study["id"]
    if job_type == "OPTIMIZE":
        ps = ps_repo.get(conn, p.param_set_id) if p.param_set_id else ps_repo.current(conn, sid)
        if ps is None or ps["study_id"] != sid:
            raise prerequisite_missing("PARAM_SET")
        if p.model_id:
            m = models_repo.get(conn, p.model_id)
            if m is None or m["study_id"] != sid or m["status"] != "ACTIVE":
                raise prerequisite_missing("ACTIVE_MODEL")
        else:
            m = models_repo.get(conn, study["final_model_id"]) if study["final_model_id"] else None
            if m is None or m["status"] != "ACTIVE":
                raise DomainError("FINAL_MODEL_REQUIRED", "Final 모델을 먼저 지정하세요", status=409)
        rows, probs = opt.validate_responses(p.responses, p.approach)
        if probs == [{"row": "", "message": "OBJECTIVE_REQUIRED"}]:
            raise DomainError("OBJECTIVE_REQUIRED", "최적화에는 목적함수(MINIMIZE / MAXIMIZE)가 1개 이상 필요합니다", status=422)
        if probs:
            raise DomainError("RESPONSES_INVALID", "응답 정의가 올바르지 않습니다", status=422, problems=probs)
        oid = str(uuid.uuid4())
        params = {
            "param_set_id": ps["id"], "model_id": m["id"], "approach": p.approach, "opt_method": p.opt_method,
            "max_designs": p.max_designs, "run_nominal": p.run_nominal,
            "study_folder": p.study_folder or cfg.optimize.default_study_folder,
            "opt_settings": p.opt_settings.model_dump(), "on_failed": p.on_failed, "responses": rows,
            "optimization_id": oid,
        }
        return params, {"optimization_id": oid, "model_id": m["id"], "param_set_id": ps["id"]}, []
    raise invalid_at("job_type", "unknown")
