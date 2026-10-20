"""형상 미리보기·결과 3D 컨투어 캐시 인덱스(geometry-view.md §6.7·§13.5, migration 0017_geom_view).

캐시 파일은 서버측 AI 루트 `<study>/_cache/{geom_preview,contour3d}/<key[0:2]>/<key>/`(플랫폼 임시 산출물). DB에는 키·상태·수치 요약·
산출물 id만 둔다(파일 본문 없음). 산출물 id 열은 FK가 아니다 — housekeeping이 artifacts 행을 지운 뒤에도 410 ARTIFACT_EXPIRED 판정에 쓴다.
"""

from __future__ import annotations

from sqlalchemy import BigInteger, CheckConstraint, Column, ForeignKey, Index, Integer, String, Table, func, text
from sqlalchemy.dialects.postgresql import JSONB

from ._base import ID, TS, metadata

CACHE_STATUSES = ("QUEUED", "RUNNING", "DONE", "FAILED", "CANCELED", "EXPIRED")
CACHE_LIVE = ("QUEUED", "RUNNING", "DONE")
CONTOUR_SOURCES = ("SOLVER_H3D", "PREDICT_H3D")


def _in(col: str, vals: tuple[str, ...]) -> str:
    return f"{col} IN (" + ",".join(f"'{v}'" for v in vals) + ")"


LIVE_WHERE = "status IN ('QUEUED','RUNNING','DONE')"

geom_previews = Table(
    "geom_previews",
    metadata,
    Column("id", ID, primary_key=True),
    Column("study_id", ID, ForeignKey("studies.id"), nullable=False),
    Column("param_set_id", ID, ForeignKey("param_sets.id"), nullable=False),
    Column("cache_key", String(64), nullable=False),
    Column("job_id", ID, ForeignKey("jobs.id"), nullable=True),
    Column("created_by", String, nullable=False),
    Column("status", String(12), nullable=False),
    Column("fe", String(8), nullable=False),
    Column("values", JSONB, nullable=False),
    Column("engine_version", String(32), nullable=True),
    Column("result_status", String(8), nullable=True),
    Column("code", String(64), nullable=True),
    Column("category", String(16), nullable=True),
    Column("fe_status", String(8), nullable=True),
    Column("fe_code", String(64), nullable=True),
    Column("glb_artifact_id", ID, nullable=True),
    Column("fe_glb_artifact_id", ID, nullable=True),
    Column("manifest_artifact_id", ID, nullable=True),
    Column("bytes", BigInteger, nullable=True),
    Column("timing", JSONB, nullable=True),
    Column("created_at", TS, nullable=False, server_default=func.now()),
    Column("finished_at", TS, nullable=True),
    Column("last_access_at", TS, nullable=False, server_default=func.now()),
    CheckConstraint(_in("status", CACHE_STATUSES), name="ck_geom_previews_status"),
    CheckConstraint("fe IN ('off','check','morph')", name="ck_geom_previews_fe"),
)
Index("ux_geom_previews_key_live", geom_previews.c.cache_key, unique=True, postgresql_where=text(LIVE_WHERE))
Index("ix_geom_previews_creator_status", geom_previews.c.created_by, geom_previews.c.status)
Index("ix_geom_previews_last_access", geom_previews.c.last_access_at)

contour3d_cache = Table(
    "contour3d_cache",
    metadata,
    Column("id", ID, primary_key=True),
    Column("study_id", ID, ForeignKey("studies.id"), nullable=False),
    Column("cache_key", String(64), nullable=False),
    Column("job_id", ID, ForeignKey("jobs.id"), nullable=True),
    Column("created_by", String, nullable=False),
    Column("status", String(12), nullable=False),
    Column("source_kind", String(12), nullable=False),
    Column("source_ref", JSONB, nullable=False),
    Column("display", JSONB, nullable=True),
    Column("frames", Integer, nullable=True),
    Column("nodes", Integer, nullable=True),
    Column("bytes", BigInteger, nullable=True),
    Column("result_status", String(8), nullable=True),
    Column("code", String(64), nullable=True),
    Column("glb_artifact_id", ID, nullable=True),
    Column("frames_artifact_id", ID, nullable=True),
    Column("manifest_artifact_id", ID, nullable=True),
    Column("timing", JSONB, nullable=True),
    Column("created_at", TS, nullable=False, server_default=func.now()),
    Column("finished_at", TS, nullable=True),
    Column("last_access_at", TS, nullable=False, server_default=func.now()),
    CheckConstraint(_in("status", CACHE_STATUSES), name="ck_contour3d_cache_status"),
    CheckConstraint(_in("source_kind", CONTOUR_SOURCES), name="ck_contour3d_cache_source_kind"),
)
Index("ux_contour3d_cache_key_live", contour3d_cache.c.cache_key, unique=True, postgresql_where=text(LIVE_WHERE))
Index("ix_contour3d_cache_creator_status", contour3d_cache.c.created_by, contour3d_cache.c.status)
Index("ix_contour3d_cache_last_access", contour3d_cache.c.last_access_at)
