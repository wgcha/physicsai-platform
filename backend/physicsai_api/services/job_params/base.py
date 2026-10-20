"""작업 params 공용(§10.6, phase2 §6.1.1): 기본 모델·HPC 덮어쓰기·오류 생성·기능 확인."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from physicsai_core.commands import PSCFG_REQUIRED_MESSAGE, model_lacks_required_pscfg
from physicsai_core.errors import DomainError
from physicsai_core.features import JOB_FEATURE, missing_for

from ...context import AppContext
from ...schemas.common import HpcVersion


class _P(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class HpcOverrides(_P):
    queue: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_.\-@]{1,64}$")
    ncpus: int | None = Field(default=None, ge=1, le=4096)
    walltime: str | None = Field(default=None, pattern=r"^\d{1,4}:\d{2}:\d{2}$")
    version: HpcVersion = None  # D3-68: SCX Radioss 버전(null = hpc.scx.version, command 모드는 무시)


def prerequisite_missing(*items: str) -> DomainError:
    return DomainError("PREREQUISITE_MISSING", "사전 조건이 충족되지 않았습니다", status=409, missing=list(items))


def require_model_pscfg(cfg: Any, template_key: str, m: dict[str, Any]) -> None:
    """D3-43: .pscfg 없이 등록한 모델 + {model_pscfg}를 쓰는 명령 템플릿 → 409 PSCFG_REQUIRED(작업 생성 거부)."""
    if model_lacks_required_pscfg(getattr(cfg.commands, template_key, None), m):
        raise DomainError("PSCFG_REQUIRED", PSCFG_REQUIRED_MESSAGE, status=409, template=template_key, model_id=m["id"])


def invalid_errors(errors: list[dict[str, Any]], message: str = "요청 값이 올바르지 않습니다") -> DomainError:
    """errors 목록을 그대로 담는 422(1차 형식)."""
    return DomainError("INVALID_PARAMS", message, status=422, errors=errors)


def invalid_at(loc: str, msg: str, code: str = "INVALID_PARAMS", **extra: Any) -> DomainError:
    """한 위치(params.<loc>) 오류 422(2차 형식). invalid_errors와 출력 모양이 달라 합치지 않는다."""
    return DomainError(code, msg, status=422, errors=[{"loc": ["params", *loc.split(".")], "msg": msg}], **extra)


def check_feature(ctx: AppContext, job_type: str) -> None:
    req = JOB_FEATURE.get(job_type)
    if req is None:
        return
    tmpl, res = missing_for(ctx.settings, req, None)
    raise_feature_missing(tmpl, res)


def raise_feature_missing(tmpl: list[str], res: list[str]) -> None:
    """기능 판정 결과 → 409 TEMPLATE_NOT_CONFIGURED(템플릿 우선) / RESOURCE_NOT_CONFIGURED. 빠진 것이 없으면 그대로."""
    if tmpl:
        raise DomainError("TEMPLATE_NOT_CONFIGURED", f"명령 템플릿이 설정되지 않았습니다: {', '.join(tmpl)}", status=409,
                          template=tmpl[0].split(".", 1)[1], missing=tmpl)
    if res:
        raise DomainError("RESOURCE_NOT_CONFIGURED", f"관리자 설정 필요: {', '.join(res[:3])}", status=409, missing=res)
