"""DOE 표본 형상 그리드 미리보기 `doe_previews`·셀 캐시 인덱스 `doe_preview_cells`(doe-preview.md §6.7, migration 0025_doe_preview).

셀 파일은 서버측 AI 루트 `<study>/_cache/doe_preview/cells/<key[0:2]>/<key>/`(플랫폼 임시 산출물). DB에는 키·상태·수치 요약·산출물 id만 둔다
(파일 본문 없음). 산출물 id 열은 FK가 아니다 — housekeeping이 artifacts 행을 지운 뒤에도 410 ARTIFACT_EXPIRED 판정에 쓴다.
`doe_previews.cell_keys`(JSONB) = `{cells: [{key, doe_no, nominal}], order: [doe_no…], params: [{name, nominal, min, max, unit}], tag_state,
disp_range_mm}`(페이지 셀 키 순서 + doe_no와 응답 조립용 요약 — 값·본문 아님).
"""

from __future__ import annotations

from sqlalchemy import CHAR, REAL, BigInteger, Boolean, CheckConstraint, Column, ForeignKey, Index, Integer, String, Table, func
from sqlalchemy.dialects.postgresql import JSONB

from ._base import ID, TS, metadata

PREVIEW_STATUSES = ("QUEUED", "RUNNING", "DONE", "FAILED", "CANCELED")
CELL_STATUSES = ("DONE", "EXPIRED")
SOURCE_KINDS = ("train", "param_set", "train_doe")


def _in(col: str, vals: tuple[str, ...]) -> str:
    return f"{col} IN (" + ",".join(f"'{v}'" for v in vals) + ")"


doe_previews = Table(
    "doe_previews",
    metadata,
    Column("id", ID, primary_key=True),
    Column("study_id", ID, ForeignKey("studies.id"), nullable=False),
    Column("created_by", String, nullable=False),
    Column("job_id", ID, ForeignKey("jobs.id"), nullable=True),
    Column("grid_key", CHAR(64), nullable=False),
    Column("source_kind", String(12), nullable=False),
    Column("source_ref", JSONB, nullable=False),
    Column("matrix_key", CHAR(64), nullable=True),
    Column("select", JSONB, nullable=False),
    Column("status", String(12), nullable=False),
    Column("cell_keys", JSONB, nullable=True),
    Column("n_total", Integer, nullable=True),
    Column("n_ok", Integer, nullable=True),
    Column("n_fail", Integer, nullable=True),
    Column("n_error", Integer, nullable=True),
    Column("timing", JSONB, nullable=True),
    Column("created_at", TS, nullable=False, server_default=func.now()),
    Column("finished_at", TS, nullable=True),
    CheckConstraint(_in("status", PREVIEW_STATUSES), name="ck_doe_previews_status"),
    CheckConstraint(_in("source_kind", SOURCE_KINDS), name="ck_doe_previews_source_kind"),
)
Index("ix_doe_previews_creator_status", doe_previews.c.created_by, doe_previews.c.status)
Index("ix_doe_previews_grid_key", doe_previews.c.grid_key)

doe_preview_cells = Table(
    "doe_preview_cells",
    metadata,
    Column("cache_key", CHAR(64), primary_key=True),
    Column("study_id", ID, ForeignKey("studies.id"), nullable=False),
    Column("status", String(12), nullable=False),
    Column("result_status", String(8), nullable=True),
    Column("code", String(64), nullable=True),
    Column("category", String(16), nullable=True),
    Column("max_disp_mm", REAL, nullable=True),
    Column("clipped", Boolean, nullable=True),
    Column("values", JSONB, nullable=False),
    Column("png_artifact_id", ID, nullable=True),
    Column("glb_artifact_id", ID, nullable=True),
    Column("manifest_artifact_id", ID, nullable=True),
    Column("bytes", BigInteger, nullable=True),
    Column("engine_version", String(32), nullable=True),
    Column("created_at", TS, nullable=False, server_default=func.now()),
    Column("last_access_at", TS, nullable=False, server_default=func.now()),
    CheckConstraint(_in("status", CELL_STATUSES), name="ck_doe_preview_cells_status"),
)
Index("ix_doe_preview_cells_last_access", doe_preview_cells.c.last_access_at)
