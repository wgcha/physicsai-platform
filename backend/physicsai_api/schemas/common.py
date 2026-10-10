"""API 스키마 — 공통 기반·오류·헬스·사용자·프로젝트(§10)."""

from __future__ import annotations


from pydantic import BaseModel, ConfigDict

__all__ = ["Req", "Resp", "ErrorBody", "ErrorResponse", "Health", "Me", "Project"]


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
