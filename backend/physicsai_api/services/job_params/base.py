"""작업 params 공용(§10.6, phase2 §6.1.1): 기본 모델·HPC 덮어쓰기·오류 생성·기능 확인."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from physicsai_core.errors import DomainError
from physicsai_core.features import JOB_FEATURE, missing_for

from ...context import AppContext


class _P(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class HpcOverrides(_P):
    queue: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_.\-@]{1,64}$")
    ncpus: int | None = Field(default=None, ge=1, le=4096)
    walltime: str | None = Field(default=None, pattern=r"^\d{1,4}:\d{2}:\d{2}$")


def prerequisite_missing(*items: str) -> DomainError:
    return DomainError("PREREQUISITE_MISSING", "사전 조건이 충족되지 않았습니다", status=409, missing=list(items))


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
    if tmpl:
        raise DomainError("TEMPLATE_NOT_CONFIGURED", f"명령 템플릿이 설정되지 않았습니다: {', '.join(tmpl)}", status=409,
                          template=tmpl[0].split(".", 1)[1], missing=tmpl)
    if res:
        raise DomainError("RESOURCE_NOT_CONFIGURED", f"관리자 설정 필요: {', '.join(res[:3])}", status=409, missing=res)
