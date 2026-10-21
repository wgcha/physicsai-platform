"""업로드 complete(upload-report.md §4): 모든 파일 done 확인 → 해당 purpose의 기존 `paths/inspect` 서비스 호출(HTTP 재호출 아님).

inspect `ok=true`면 COMPLETED(이후 쓰기 409), `ok=false`면 OPEN 유지(파일 추가 후 재시도). DISCOVER는 inspect 없이 모양만 보고 통과.
`RESULT_FOLDER`처럼 doe_id가 필요한 확인은 doe_id 없이 형식만 본다(프런트가 기존대로 paths/inspect를 한 번 더 호출).
"""

from __future__ import annotations

import logging
from typing import Any

from physicsai_core.db.repositories import uploads as repo
from physicsai_core.errors import DomainError

from .. import schemas as S
from ..auth import Principal
from ..context import AppContext
from . import path_inspect
from . import uploads as base
from .common import audit, require_config_ok

log = logging.getLogger("physicsai_api.uploads")


def _inspect(ctx: AppContext, principal: Principal, row: dict[str, Any], path: str) -> dict[str, Any] | None:
    """purpose별 기존 inspect 서비스 호출. 경로 규칙 위반(DomainError)은 ok=false 한 줄로 바꿔 OPEN 유지."""
    if row["purpose"] == "DISCOVER":
        return None
    req = S.PathInspectRequest(purpose=row["purpose"], path=path, engine=row["engine"])
    try:
        return path_inspect.inspect_path(ctx, principal, row["study_id"], req)
    except DomainError as exc:
        return {"normalized_path": path, "ok": False, "summary": {},
                "problems": [{"code": exc.code, "message": exc.message}]}


def _stored(ins: dict[str, Any] | None) -> dict[str, Any] | None:
    """DB에는 절대경로(normalized_path)를 빼고 ok·problems·summary 요약만 둔다(§6.2)."""
    if ins is None:
        return None
    return {"ok": bool(ins["ok"]), "problems": ins.get("problems") or [], "summary": ins.get("summary") or {}}


def _out(ctx: AppContext, row: dict[str, Any]) -> dict[str, Any]:
    path = base.result_path(ctx, row)
    ins = base.inspect_out(row, path)
    return {"upload_id": row["id"], "state": row["state"], "path": path, "display_path": base.result_display(ctx, row),
            "purpose": row["purpose"], "inspect": ins, "problems": list((ins or {}).get("problems") or [])}


def complete(ctx: AppContext, principal: Principal, upload_id: str, rid: str | None, ip: str | None) -> dict[str, Any]:
    base.require_root(ctx)
    require_config_ok(ctx)
    with ctx.engine.begin() as conn:
        row = base.owned(principal, base.get_row(conn, upload_id, for_update=True))
        if row["state"] == repo.COMPLETED:
            return _out(ctx, row)
        base.require_open(row)
        pending = [f["rel"] for f in row["files"] if not f.get("done")]
        if pending:
            raise DomainError("UPLOAD_INCOMPLETE", f"아직 다 받지 못한 파일이 {len(pending)}개 있습니다", status=409,
                              pending=pending[:100], pending_count=len(pending))
        path = base.result_path(ctx, row)
        assert path is not None
        ins = _inspect(ctx, principal, row, path)
        ok = ins is None or bool(ins["ok"])
        vals: dict[str, Any] = {"inspect": _stored(ins)}
        if ok:
            vals.update(state=repo.COMPLETED, completed_at=repo.db_now(conn))
        row = repo.update_row(conn, upload_id, **vals)
        if ok:
            audit(conn, principal, "UPLOAD_COMPLETE", "upload", upload_id,
                  {"purpose": row["purpose"], "files": len(row["files"]), "bytes": int(row["total_bytes"]),
                   "dir_rel": row["dir_rel"]}, rid, ip)
    log.info("업로드 complete upload_id=%s state=%s", upload_id, row["state"])
    return _out(ctx, row)
