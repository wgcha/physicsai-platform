from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from .. import schemas as S
from ..auth import Principal
from ..deps import get_ctx, get_principal
from ..services import system
from ..services.common import require_global_admin

router = APIRouter(tags=["admin"])


@router.get("/admin/config", response_model=S.AdminConfig, responses={403: {"model": S.ErrorResponse}})
def admin_config(request: Request, principal: Principal = Depends(get_principal)) -> dict:
    require_global_admin(principal)
    return system.admin_config(get_ctx(request))
