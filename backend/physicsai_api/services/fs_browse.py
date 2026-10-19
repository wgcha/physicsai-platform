"""서버 경로 탐색(phase3 §12 S7, D3-46): 실행 권한(어느 프로젝트든 power 이상 또는 전역 관리자)만. 로그에는 경로만."""

from __future__ import annotations

import logging
from typing import Any

from physicsai_core import fs_browse
from physicsai_core.errors import DomainError

from ..auth import Principal
from ..context import AppContext

log = logging.getLogger("physicsai_api.fs")


def require_any_power(principal: Principal) -> None:
    if principal.is_global_admin or any(r in ("power", "admin") for r in principal.roles.values()):
        return
    raise DomainError("PERMISSION_DENIED", "실행 권한(power 이상)이 필요합니다", status=403, required="power")


def roots(ctx: AppContext, principal: Principal, include_spdm: bool = False) -> dict[str, Any]:
    require_any_power(principal)
    st = ctx.settings.storage
    return {"roots": fs_browse.roots(ctx.settings, include_spdm=include_spdm), "inbox_share_hint": st.inbox_share_hint or None}


def list_dir(ctx: AppContext, principal: Principal, path: str, exts: str | None) -> dict[str, Any]:
    require_any_power(principal)
    out = fs_browse.list_dir(ctx.settings, path, fs_browse.parse_exts(exts))
    log.info("경로 탐색 path=%s entries=%d", out["path"], len(out["entries"]))
    return out
