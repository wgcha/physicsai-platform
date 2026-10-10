"""Study 저장소(§6.2)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import and_, func, select, update
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError

from ...errors import DomainError
from ..tables import studies
from .jobs import row_dict


def get(conn: Connection, study_id: str, *, for_update: bool = False) -> dict[str, Any] | None:
    q = select(studies).where(studies.c.id == study_id)
    if for_update:
        q = q.with_for_update()
    return row_dict(conn.execute(q).first())


def require(conn: Connection, study_id: str, *, for_update: bool = False) -> dict[str, Any]:
    s = get(conn, study_id, for_update=for_update)
    if s is None:
        raise DomainError("NOT_FOUND", "Study를 찾을 수 없습니다", status=404)
    return s


def list_(conn: Connection, *, project_id: str | None, status: str | None, limit: int, offset: int) -> list[dict[str, Any]]:
    q = select(studies)
    if project_id:
        q = q.where(studies.c.project_id == project_id)
    if status:
        q = q.where(studies.c.status == status)
    q = q.order_by(studies.c.created_at.desc(), studies.c.id).limit(limit).offset(offset)
    return [row_dict(r) for r in conn.execute(q)]


def insert(conn: Connection, values: dict[str, Any]) -> dict[str, Any]:
    sp = conn.begin_nested()
    try:
        conn.execute(studies.insert().values(**values))
        sp.commit()
    except IntegrityError:
        sp.rollback()
        raise DomainError("STUDY_NAME_EXISTS", "같은 폴더 이름의 Study가 이미 있습니다", status=409) from None
    return require(conn, values["id"])


def update_cas(conn: Connection, study_id: str, version: int | None, **values: Any) -> dict[str, Any]:
    cond = [studies.c.id == study_id]
    if version is not None:
        cond.append(studies.c.version == version)
    r = conn.execute(
        update(studies).where(and_(*cond)).values(updated_at=func.now(), version=studies.c.version + 1, **values)
    )
    if r.rowcount != 1:
        raise DomainError("VERSION_CONFLICT", "다른 사용자가 먼저 수정했습니다. 새로 고친 뒤 다시 시도하세요", status=409)
    return require(conn, study_id)


def set_final_model(conn: Connection, study_id: str, model_id: str | None, user_id: str) -> dict[str, Any]:
    """Final 모델 지정·해제(§10.4). 해제(None)면 지정자·시각도 비운다."""
    return update_cas(
        conn, study_id, None, final_model_id=model_id,
        final_set_by=user_id if model_id else None,
        final_set_at=func.now() if model_id else None,
    )
