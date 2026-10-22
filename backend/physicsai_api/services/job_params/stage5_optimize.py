"""⑤ 최적화 작업 params·사전조건(phase2 §6.12): OPTIMIZE. 이슈 #4(phase3 §18.8) mesh_only 템플릿 막기,
SURROGATE_OPT(내장 최적화 반복, §18.4)는 POST /jobs로 만들 수 없고 재시도만 opt를 이어 받는다."""

from __future__ import annotations

import math
import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from physicsai_core.db.repositories import models as models_repo
from physicsai_core.db.repositories import param_sets as ps_repo
from physicsai_core.errors import DomainError
from physicsai_core.stage5_optimize import optimize as opt

from physicsai_core.stage4_predict import input_kind as ik

from ...context import AppContext
from ...schemas.common import InputKind
from ..input_kind_gate import reject_input
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
    # input-kind.md IK-13: HyperStudy 최적화는 입력 종류를 받지 않는다 — 값이 오면 422 INPUT_KIND_UNSUPPORTED(받아서 거부하려고 필드만 둠)
    input: InputKind | None = Field(default=None, description="사용 불가 — 오면 422 INPUT_KIND_UNSUPPORTED")

    @field_validator("responses")
    @classmethod
    def _finite(cls, v: list[dict[str, Any]]) -> list[dict[str, Any]]:
        for r in v:
            x = r.get("value") if isinstance(r, dict) else None
            if isinstance(x, float) and not math.isfinite(x):
                raise ValueError("value는 유한해야 합니다")
        return v


class SurrogateRoundParams(_P):
    """서비스·종료 훅만 만드는 반복 작업 params(POST /jobs의 job_type 열거에 없음 → 422)."""

    surrogate_opt_id: str
    opt_no: int
    round: int


PARAM_MODELS: dict[str, type[BaseModel]] = {
    "OPTIMIZE": OptimizeParams,
    "SURROGATE_OPT": SurrogateRoundParams,
}


def legacy_criteria_missing(responses: list[dict[str, Any]]) -> list[str]:
    """원본(레거시) 최적화: CONSTRAINT 행의 빈 bound·value 경로(ON-C4). 목적 없음은 기존 422 OBJECTIVE_REQUIRED."""
    out: list[str] = []
    for i, r in enumerate(responses):
        if isinstance(r, dict) and r.get("goal") == "CONSTRAINT":
            out += [f"responses.{i}.{k}" for k in ("bound", "value") if r.get(k) in (None, "")]
    return out


def assembly_required() -> DomainError:
    return DomainError("TEMPLATE_ASSEMBLY_REQUIRED", opt.TEMPLATE_ASSEMBLY_REQUIRED_MSG, status=409)


def on_retry(conn: Any, old: dict[str, Any], new_id: str) -> None:
    """OPTIMIZE 재시도: mesh_only 템플릿이면 409(이미 대기 중이던 옛 작업 포함, 이슈 #4).
    SURROGATE_OPT 재시도: 실패한 최신 반복 작업이면 opt를 FITTING·새 작업으로(아니면 409 SURROGATE_OPT_NOT_RESUMABLE)."""
    if old["job_type"] == "OPTIMIZE":
        ps = ps_repo.get(conn, (old.get("params") or {}).get("param_set_id") or "")
        if opt.needs_assembly_block(ps):
            raise assembly_required()
        return
    if old["job_type"] == "SURROGATE_OPT":
        from physicsai_core.db.repositories import surrogate_opts as so_repo

        o = so_repo.get(conn, (old.get("params") or {}).get("surrogate_opt_id") or "", for_update=True)
        if o is None or o["status"] != "FAILED" or o["current_job_id"] != old["id"]:
            raise DomainError("SURROGATE_OPT_NOT_RESUMABLE", "실패한 내장 최적화의 마지막 반복 작업만 다시 실행할 수 있습니다",
                              status=409)
        if so_repo.get_iter(conn, o["id"], int((old.get("params") or {}).get("round") or 0)) is not None:
            raise DomainError("SURROGATE_OPT_NOT_RESUMABLE", "이 반복의 검증 배치가 이미 등록돼 있습니다 — ⑤에서 '이어서 실행'을 쓰세요",
                              status=409)
        if so_repo.active_for_study(conn, o["study_id"]) is not None:
            raise DomainError("SURROGATE_OPT_ACTIVE", "이 Study에 진행 중인 내장 최적화가 있습니다", status=409)
        so_repo.set_opt(conn, o["id"], status="FITTING", current_job_id=new_id, stop_reason=None, finished_at=None)


def prepare(ctx: AppContext, conn: Any, study: dict[str, Any], job_type: str, p: Any
            ) -> tuple[dict[str, Any], dict[str, Any] | None, list[dict[str, str]]]:
    """사전조건 확인(§8.2) → (저장할 params, 초기 result, warnings). 기능 확인(check_feature)은 디스패처가 먼저 한다."""
    cfg = ctx.settings
    sid = study["id"]
    if job_type == "OPTIMIZE":
        reject_input(p.input, ik.REASON_LEGACY)
        ps = ps_repo.get(conn, p.param_set_id) if p.param_set_id else ps_repo.current(conn, sid)
        if ps is None or ps["study_id"] != sid:
            raise prerequisite_missing("PARAM_SET")
        if ps.get("engine") == "native":  # geometry-engine.md §7.7: 원본(HyperStudy) 최적화는 altair 전용 — 내장 최적화를 쓴다
            raise DomainError("ENGINE_NATIVE_UNSUPPORTED", "Native 형상 엔진 세트는 원본 최적화를 지원하지 않습니다 — 내장 최적화를 쓰세요",
                              status=409)
        if opt.needs_assembly_block(ps):  # 이슈 #4: 쿠션 단독 템플릿은 원본 최적화 불가 — 내장 모드 안내
            raise assembly_required()
        if p.model_id:
            m = models_repo.get(conn, p.model_id)
            if m is None or m["study_id"] != sid or m["status"] != "ACTIVE":
                raise prerequisite_missing("ACTIVE_MODEL")
        else:
            m = models_repo.get(conn, study["final_model_id"]) if study["final_model_id"] else None
            if m is None or m["status"] != "ACTIVE":
                raise DomainError("FINAL_MODEL_REQUIRED", "Final 모델을 먼저 지정하세요", status=409)
        crit = legacy_criteria_missing(p.responses)
        if crit:  # opt-native ON-C4: 제약 조건(bound)·임계값(value)은 사용자가 정한다(기본 "<=" 등으로 채우지 않음)
            raise DomainError("OPT_CRITERIA_REQUIRED", "최적화 기준이 비어 있습니다 — 제약의 조건(≤·≥·=)과 임계값을 직접 입력하세요",
                              status=422, missing=crit)
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
