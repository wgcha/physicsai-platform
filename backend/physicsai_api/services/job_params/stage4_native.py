"""④ native 세트 등록 작업 params·사전조건(geometry-engine.md §7.3.4): PARAM_SET_NATIVE (등록 API가 만든다, 사용자 선택 job_type 아님)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel

from physicsai_core.db.repositories import param_sets as ps_repo
from physicsai_core.errors import DomainError

from ...context import AppContext
from ..geometry_gate import require_native_available, validate_geom_options
from .base import _P, invalid_at


class NativeSetParams(_P):
    mode: Literal["new", "reprep"]
    path: str | None = None
    choice: dict[str, Any] | None = None
    label: str | None = None
    geom_options: dict[str, Any] | None = None
    param_set_id: str | None = None


PARAM_MODELS: dict[str, type[BaseModel]] = {"PARAM_SET_NATIVE": NativeSetParams}


def prepare(ctx: AppContext, conn: Any, study: dict[str, Any], job_type: str, p: Any
            ) -> tuple[dict[str, Any], dict[str, Any] | None, list[dict[str, str]]]:
    require_native_available(ctx.settings)
    if p.mode == "new":
        if not p.path:
            raise invalid_at("path", "path가 필요합니다")
        over = validate_geom_options(ctx.settings, p.geom_options)
        return {"engine": "native", "mode": "new", "path": p.path, "choice": p.choice or {}, "label": p.label,
                "geom_options": over or None}, None, []
    ps = ps_repo.get(conn, p.param_set_id) if p.param_set_id else None
    if ps is None or ps["study_id"] != study["id"]:
        raise DomainError("NOT_FOUND", "파라미터 세트를 찾을 수 없습니다", status=404)
    if ps.get("engine") != "native":
        raise DomainError("ENGINE_MISMATCH", "native 형상 엔진 세트가 아닙니다", status=409)
    return {"engine": "native", "mode": "reprep", "param_set_id": ps["id"]}, None, []
