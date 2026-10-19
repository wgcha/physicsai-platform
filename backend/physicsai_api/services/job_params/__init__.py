"""작업 params 스키마·사전조건 디스패치(§10.6, §8.2, phase2 §6.1.1). 알 수 없는 키는 422.

단계 모듈(stageN_*)이 PARAM_MODELS 조각과 prepare(필요하면 after_insert·on_retry)를 가진다.
"""

from __future__ import annotations

from types import ModuleType
from typing import Any

from pydantic import BaseModel, ValidationError

from ...context import AppContext
from . import (
    stage1_train_data,
    stage2_curation,
    stage3_model,
    stage4_batch,
    stage4_capture,
    stage4_native,
    stage4_predict,
    stage5_optimize,
    study_manage,
)
from .base import check_feature, invalid_errors

_STAGES: tuple[ModuleType, ...] = (stage3_model, stage4_predict, stage4_batch, stage1_train_data, stage2_curation,
                                  stage5_optimize, study_manage, stage4_capture, stage4_native)

PARAM_MODELS: dict[str, type[BaseModel]] = {jt: m for mod in _STAGES for jt, m in mod.PARAM_MODELS.items()}
_STAGE_OF: dict[str, ModuleType] = {jt: mod for mod in _STAGES for jt in mod.PARAM_MODELS}


def parse_params(job_type: str, params: dict[str, Any]) -> Any:
    try:
        return PARAM_MODELS[job_type].model_validate(params)
    except ValidationError as exc:
        raise invalid_errors([{"loc": ["params", *e["loc"]], "msg": e["msg"]} for e in exc.errors()]) from None


def _feature_type(ctx: AppContext, conn: Any, study: dict[str, Any], job_type: str, p: Any) -> str | None:
    """native 세트의 일괄 예측은 geom_update 대신 paicad가 형상을 만들므로 단건 예측과 같은 기능 조건(geometry-engine.md §7.7)."""
    if job_type in ("TD_EXTRACT_PARAMS", "TD_DOE_GEN"):  # native는 prepare가 자체 게이트(paicad 사용 가능)를 한다
        from physicsai_core.db.repositories import train as train_repo

        if job_type == "TD_EXTRACT_PARAMS":
            return None if (getattr(p, "engine", None) or ctx.settings.geometry.engine) == "native" else job_type
        setup = train_repo.get_setup(conn, study["id"])
        return None if setup is not None and setup.get("engine") == "native" else job_type
    if job_type != "PREDICT_BATCH":
        return job_type
    from physicsai_core.db.repositories import param_sets as ps_repo

    ps = ps_repo.get(conn, p.param_set_id) if p.param_set_id else ps_repo.current(conn, study["id"])
    return "PREDICT" if ps is not None and ps.get("engine") == "native" else job_type


def prepare(ctx: AppContext, conn: Any, study: dict[str, Any], job_type: str, p: Any
            ) -> tuple[dict[str, Any], dict[str, Any] | None, list[dict[str, str]]]:
    """사전조건 확인(§8.2) → (저장할 params, 초기 result, warnings). 템플릿·자원 기능 확인이 먼저(409)."""
    ft = _feature_type(ctx, conn, study, job_type, p)
    if ft is not None:
        check_feature(ctx, ft)
    mod = _STAGE_OF.get(job_type)
    if mod is None:
        raise invalid_errors([{"loc": ["job_type"], "msg": "unknown"}])
    params, result, warnings = mod.prepare(ctx, conn, study, job_type, p)
    if job_type in ("PREDICT", "PREDICT_BATCH"):  # phase3 §15: 컨투어 표시 설정(선택) — 준비된 입력·배치 단위 범례
        params.update(stage4_capture.display_param(p))
    if job_type == "PREDICT_BATCH":  # D3-53: 하위 예측 캡처 옵션
        params.update(stage4_capture.capture_param(p))
    return params, result, warnings


def after_insert(conn: Any, principal: Any, study: dict[str, Any], job_type: str, job_id: str, params: dict[str, Any],
                 result: dict[str, Any] | None) -> None:
    """작업 생성과 같은 트랜잭션에서 엔터티 행(BUILDING) 생성."""
    hook = getattr(_STAGE_OF.get(job_type), "after_insert", None)
    if hook is not None:
        hook(conn, principal, study, job_type, job_id, params, result)


def on_retry(conn: Any, old: dict[str, Any], new_id: str) -> None:
    """재시도: 엔터티 행을 새 작업으로 다시 BUILDING."""
    hook = getattr(_STAGE_OF.get(old["job_type"]), "on_retry", None)
    if hook is not None:
        hook(conn, old, new_id)
