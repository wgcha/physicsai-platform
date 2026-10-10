"""작업 params 스키마·사전조건 디스패치(§10.6, §8.2, phase2 §6.1.1). 알 수 없는 키는 422.

단계 모듈(stageN_*)이 PARAM_MODELS 조각과 prepare(필요하면 after_insert·on_retry)를 가진다.
"""

from __future__ import annotations

from types import ModuleType
from typing import Any

from pydantic import BaseModel, ValidationError

from ...context import AppContext
from . import stage1_train_data, stage2_curation, stage3_model, stage4_predict, stage5_optimize
from .base import check_feature, invalid_errors

_STAGES: tuple[ModuleType, ...] = (stage3_model, stage4_predict, stage1_train_data, stage2_curation, stage5_optimize)

PARAM_MODELS: dict[str, type[BaseModel]] = {jt: m for mod in _STAGES for jt, m in mod.PARAM_MODELS.items()}
_STAGE_OF: dict[str, ModuleType] = {jt: mod for mod in _STAGES for jt in mod.PARAM_MODELS}


def parse_params(job_type: str, params: dict[str, Any]) -> Any:
    try:
        return PARAM_MODELS[job_type].model_validate(params)
    except ValidationError as exc:
        raise invalid_errors([{"loc": ["params", *e["loc"]], "msg": e["msg"]} for e in exc.errors()]) from None


def prepare(ctx: AppContext, conn: Any, study: dict[str, Any], job_type: str, p: Any
            ) -> tuple[dict[str, Any], dict[str, Any] | None, list[dict[str, str]]]:
    """사전조건 확인(§8.2) → (저장할 params, 초기 result, warnings). 템플릿·자원 기능 확인이 먼저(409)."""
    check_feature(ctx, job_type)
    mod = _STAGE_OF.get(job_type)
    if mod is None:
        raise invalid_errors([{"loc": ["job_type"], "msg": "unknown"}])
    return mod.prepare(ctx, conn, study, job_type, p)


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
