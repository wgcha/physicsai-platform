"""산출물 저장소(§6.8). 화면 표시용 작은 파일만 등록한다."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.engine import Connection

from ..tables import artifacts
from .jobs import row_dict

CONTENT_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".json": "application/json",
    ".txt": "text/plain",
    ".log": "text/plain",
    ".csv": "text/csv",
}
ALLOWED_CONTENT_TYPES = frozenset(CONTENT_TYPES.values())


def insert(conn: Connection, *, study_id: str, job_id: str | None, kind: str, rel_path: str, size: int,
           sha256: str | None, content_type: str, meta: dict[str, Any] | None = None) -> str:
    aid = str(uuid.uuid4())
    conn.execute(
        artifacts.insert().values(
            id=aid, study_id=study_id, job_id=job_id, kind=kind, rel_path=rel_path, size=size, sha256=sha256,
            content_type=content_type, meta=meta,
        )
    )
    return aid


def get(conn: Connection, artifact_id: str) -> dict[str, Any] | None:
    return row_dict(conn.execute(select(artifacts).where(artifacts.c.id == artifact_id)).first())


def list_for_job(conn: Connection, job_id: str) -> list[dict[str, Any]]:
    q = select(artifacts).where(artifacts.c.job_id == job_id).order_by(artifacts.c.created_at, artifacts.c.id)
    return [row_dict(r) for r in conn.execute(q)]


def list_by_prefix(conn: Connection, study_id: str, kind: str, rel_prefix: str) -> list[dict[str, Any]]:
    """Study의 kind 산출물 중 rel_path가 prefix로 시작하는 것(최신 순) — 세트 폴더 아래 FEATURE_PNG 찾기."""
    q = select(artifacts).where(artifacts.c.study_id == study_id, artifacts.c.kind == kind,
                                artifacts.c.rel_path.like(rel_prefix.replace("%", "").replace("_", "\\_") + "%", escape="\\")
                                ).order_by(artifacts.c.created_at.desc())
    return [row_dict(r) for r in conn.execute(q)]
