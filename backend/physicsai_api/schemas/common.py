"""API 스키마 — 공통 기반·오류·헬스·사용자·프로젝트(§10)."""

from __future__ import annotations
from typing import Annotated, Any

from pydantic import BaseModel, BeforeValidator, ConfigDict, StringConstraints

__all__ = ["Req", "Resp", "ErrorBody", "ErrorResponse", "Health", "Me", "Project", "HpcVersion", "HPC_VERSION_PATTERN"]

# D3-68(S20): 작업별 SCX Radioss 버전. 앞뒤 공백은 잘라 저장, 빈 문자열은 null(= 설정 hpc.scx.version)
HPC_VERSION_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9 ._\-]{0,63}$"


def _blank_to_none(v: Any) -> Any:
    if isinstance(v, str):
        v = v.strip()
        return v or None
    return v


HpcVersion = Annotated[Annotated[str, StringConstraints(pattern=HPC_VERSION_PATTERN)] | None, BeforeValidator(_blank_to_none)]


class Req(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Resp(BaseModel):
    model_config = ConfigDict(extra="ignore")


class ErrorBody(Resp):
    code: str
    message: str


class ErrorResponse(Resp):
    detail: ErrorBody


class Health(Resp):
    status: str
    version: str


class Me(Resp):
    user_id: str
    username: str
    display_name: str
    is_global_admin: bool
    roles: dict[str, str]


class Project(Resp):
    id: str
    name: str
    product_name: str | None = None
