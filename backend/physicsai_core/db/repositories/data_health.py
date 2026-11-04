"""③-1 데이터 점검 읽기 전용 조회(data-health.md §3.6·§4.2): 3D 컨투어 캐시 행(프레임 수·시각 원천 ①)과 최신 READY T01 큐레이션(hg/접촉 비)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import and_, select
from sqlalchemy.engine import Connection

from ..tables import contour3d_cache, curations
from .jobs import row_dict


def contour_done_rows(conn: Connection, study_id: str) -> list[dict[str, Any]]:
    """Study의 결과 3D 컨투어 캐시 중 DONE·OK·SOLVER_H3D(해석 h3d 출처)인 행(최신순)."""
    q = (select(contour3d_cache)
         .where(and_(contour3d_cache.c.study_id == study_id, contour3d_cache.c.status == "DONE",
                     contour3d_cache.c.result_status == "OK", contour3d_cache.c.source_kind == "SOLVER_H3D"))
         .order_by(contour3d_cache.c.created_at.desc(), contour3d_cache.c.id))
    return [row_dict(r) for r in conn.execute(q)]


def latest_ready_t01(conn: Connection, study_id: str) -> dict[str, Any] | None:
    """같은 Study 최신 READY T01(곡선) 큐레이션."""
    q = (select(curations)
         .where(and_(curations.c.study_id == study_id, curations.c.kind == "T01", curations.c.status == "READY"))
         .order_by(curations.c.created_at.desc(), curations.c.id).limit(1))
    return row_dict(conn.execute(q).first())
