"""업로드 세션 접기(upload-report.md §4·§5): 취소·낡음 → 폴더를 `_backup`으로 옮기고 상태만 바꾼다(파일 삭제 0).

API(취소·세션 생성 때 낡음 정리·관리자 즉시 실행)와 워커 하우스키핑이 같은 함수를 쓴다.
"""

from __future__ import annotations

import datetime as _dt
import logging
import os
from typing import Any

from sqlalchemy.engine import Connection, Engine

from . import uploads as U
from .db.repositories import audit as audit_repo
from .db.repositories import uploads as repo
from .path_links import is_link_or_reparse, is_under

log = logging.getLogger("physicsai_core.uploads")


def retire(settings: Any, conn: Connection, row: dict[str, Any], state: str) -> dict[str, Any]:
    """OPEN 세션 폴더를 `<upload_root>/_backup/<사용자>/<폴더명>`으로 옮기고 state(CANCELED|STALE)로 바꾼다."""
    root = U.upload_root_path(settings)
    moved = None
    d = U.abs_dir_of(settings, row["dir_rel"])
    if root and os.path.lexists(d) and is_under(os.path.normpath(d), os.path.normpath(root)) and not is_link_or_reparse(d):
        moved = U.move_to_backup(root, U.user_segment(row["username"], row["user_id"]), d)
    return repo.update_row(conn, row["id"], state=state, backup_rel=U.dir_rel_of(settings, moved) if moved else None)


def cleanup_stale(settings: Any, engine: Engine, now: _dt.datetime | None = None) -> list[str]:
    """updated_at이 upload.stale_hours보다 오래된 OPEN 세션 → `_backup`으로 옮기고 STALE. 옮긴 id 목록."""
    if not U.upload_root_path(settings):
        return []
    with engine.connect() as conn:
        ref = now if now is not None else repo.db_now(conn)
        cutoff = ref - _dt.timedelta(hours=settings.upload.stale_hours)
        ids = repo.stale_ids(conn, cutoff)
    out: list[str] = []
    for uid in ids:
        try:
            with engine.begin() as conn:
                row = repo.get(conn, uid, for_update=True)
                if row is None or row["state"] != repo.OPEN or row["updated_at"] >= cutoff:
                    continue
                row = retire(settings, conn, row, repo.STALE)
                audit_repo.record(conn, user_id="system", username=None, action="UPLOAD_STALE", target_type="upload",
                                  target_id=uid, detail={"purpose": row["purpose"], "files": len(row["files"]),
                                                         "bytes": int(row["total_bytes"]), "dir_rel": row["dir_rel"]})
            out.append(uid)
            log.info("낡은 업로드 세션을 _backup으로 옮김 upload_id=%s", uid)
        except Exception:  # noqa: BLE001 - 한 세션 실패가 나머지 정리를 막지 않는다(다음 주기에 다시)
            log.warning("낡은 업로드 세션 정리 실패 upload_id=%s", uid, exc_info=True)
    return out
