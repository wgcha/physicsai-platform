"""브라우저 분할 업로드 세션(upload-report.md §6.2, migration 0021_uploads).

DB에는 경로(AI 루트 기준 상대)·상태·수치·파일별 진행 요약만 둔다(파일 본문·쿠키·토큰 없음).
`files` = [{rel, size, sha256_expected, sha256, done}], `inspect` = 마지막 complete 요약(절대경로 제외).
"""

from __future__ import annotations

from sqlalchemy import BigInteger, CheckConstraint, Column, ForeignKey, Index, String, Table, func, text
from sqlalchemy.dialects.postgresql import JSONB

from ._base import ID, TS, metadata

UPLOAD_STATES = ("OPEN", "COMPLETED", "CANCELED", "STALE")

uploads = Table(
    "uploads",
    metadata,
    Column("id", ID, primary_key=True),
    Column("study_id", ID, ForeignKey("studies.id"), nullable=False),
    Column("project_id", String, nullable=False),
    Column("user_id", String, nullable=False),
    Column("username", String, nullable=False),
    Column("purpose", String, nullable=False),
    Column("engine", String, nullable=True),
    Column("name", String(200), nullable=False),
    Column("dir_rel", String, nullable=False),
    Column("state", String, nullable=False, server_default="OPEN"),
    Column("files", JSONB, nullable=False, server_default=text("'[]'::jsonb")),
    Column("total_bytes", BigInteger, nullable=False, server_default="0"),
    Column("inspect", JSONB, nullable=True),
    Column("backup_rel", String, nullable=True),
    Column("created_at", TS, nullable=False, server_default=func.now()),
    Column("updated_at", TS, nullable=False, server_default=func.now()),
    Column("completed_at", TS, nullable=True),
    CheckConstraint("state IN ('OPEN','COMPLETED','CANCELED','STALE')", name="ck_uploads_state"),
    CheckConstraint("total_bytes >= 0", name="ck_uploads_total_bytes"),
    CheckConstraint("jsonb_typeof(files) = 'array'", name="ck_uploads_files_array"),
)
Index("ix_uploads_user_state", uploads.c.user_id, uploads.c.state)
Index("ix_uploads_state_updated", uploads.c.state, uploads.c.updated_at)
Index("ix_uploads_study_created", uploads.c.study_id, uploads.c.created_at.desc())
