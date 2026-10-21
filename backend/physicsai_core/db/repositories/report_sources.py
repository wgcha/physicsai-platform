"""HTML 보고서의 입력 출처 조회(읽기 전용): 완료된 브라우저 업로드 세션 행.

`uploads` 표는 업로드 브랜치(migration 0021) 소유다 — 표가 없거나 열이 다르면 빈 목록을 돌려준다(보고서는 계속).
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import Connection, inspect, text

log = logging.getLogger(__name__)


def completed_uploads(conn: Connection, study_id: str) -> list[dict[str, Any]]:
    try:
        if not inspect(conn).has_table("uploads"):
            return []
        rows = conn.execute(text("select dir_rel, username, created_at from uploads where study_id = :s and state = 'COMPLETED'"), {"s": study_id}).all()
        return [{"dir_rel": r[0], "username": r[1], "at": r[2]} for r in rows]
    except Exception:  # noqa: BLE001 - 표·열 불일치도 보고서를 막지 않는다
        log.debug("업로드 출처 조회 실패(무시)", exc_info=True)
        return []
