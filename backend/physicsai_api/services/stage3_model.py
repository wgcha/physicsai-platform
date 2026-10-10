"""③ 데이터셋·모델 조회·수정·Final 지정(§10.3, §10.4)."""

from __future__ import annotations

from typing import Any


from physicsai_core.db.repositories import curations as cur_repo
from physicsai_core.db.repositories import datasets as datasets_repo
from physicsai_core.db.repositories import jobs as jobs_repo
from physicsai_core.db.repositories import models as models_repo
from physicsai_core.db.repositories import studies as studies_repo
from physicsai_core.errors import DomainError

from ..auth import Principal
from ..context import AppContext
from .common import (
    audit,
    clamp_limit,
    dataset_out,
    decode_cursor,
    encode_cursor,
    model_out,
    require_power,
    study_out,
)


def list_datasets(ctx: AppContext, study_id: str, limit: int | None, cursor: str | None) -> tuple[list[dict[str, Any]], str | None]:
    lim, off = clamp_limit(limit), decode_cursor(cursor)
    with ctx.engine.connect() as conn:
        st = studies_repo.require(conn, study_id)
        rows = datasets_repo.list_for_study(conn, study_id, lim + 1, off)
        rows = [{**d, "curation_id": cur_repo.curation_id_for_dataset(conn, d["job_id"])} for d in rows[:lim + 1]]
    return [dataset_out(d, st, ctx.settings.storage.ai_root) for d in rows[:lim]], (encode_cursor(off + lim) if len(rows) > lim else None)


def get_dataset(ctx: AppContext, dataset_id: str) -> dict[str, Any]:
    with ctx.engine.connect() as conn:
        d = datasets_repo.get(conn, dataset_id)
        st = studies_repo.get(conn, d["study_id"]) if d else None
        if d is not None:
            d = {**d, "curation_id": cur_repo.curation_id_for_dataset(conn, d["job_id"])}
    if d is None:
        raise DomainError("NOT_FOUND", "데이터셋을 찾을 수 없습니다", status=404)
    return dataset_out(d, st, ctx.settings.storage.ai_root)


def list_models(ctx: AppContext, study_id: str, status: str | None, limit: int | None, cursor: str | None) -> tuple[list[dict[str, Any]], str | None]:
    lim, off = clamp_limit(limit), decode_cursor(cursor)
    with ctx.engine.connect() as conn:
        s = studies_repo.require(conn, study_id)
        rows = models_repo.list_for_study(conn, study_id, status, lim + 1, off)
    return [model_out(m, s["final_model_id"], with_curve=False, study=s, ai_root=ctx.settings.storage.ai_root) for m in rows[:lim]], (
        encode_cursor(off + lim) if len(rows) > lim else None
    )


def get_model(ctx: AppContext, model_id: str) -> dict[str, Any]:
    with ctx.engine.connect() as conn:
        m = models_repo.require(conn, model_id)
        s = studies_repo.require(conn, m["study_id"])
    return model_out(m, s["final_model_id"], with_curve=True, study=s, ai_root=ctx.settings.storage.ai_root)


def patch_model(ctx: AppContext, principal: Principal, model_id: str, body: Any, rid: str, ip: str | None) -> dict[str, Any]:
    with ctx.engine.begin() as conn:
        m = models_repo.require(conn, model_id, for_update=True)
        s = studies_repo.require(conn, m["study_id"], for_update=True)
        require_power(principal, s["project_id"])
        values: dict[str, Any] = {}
        if "label" in body.model_fields_set:
            values["label"] = body.label
        if body.status is not None and body.status != m["status"]:
            if body.status == "ARCHIVED":
                if s["final_model_id"] == model_id:
                    raise DomainError("MODEL_IS_FINAL", "Final 모델은 보관할 수 없습니다. Final을 먼저 해제하세요", status=409)
                if jobs_repo.model_in_use(conn, model_id):
                    raise DomainError("MODEL_IN_USE", "진행 중인 작업이 이 모델을 사용하고 있습니다", status=409)
            if body.status == "ACTIVE" and m["status"] == "INVALID":
                raise DomainError("MODEL_NOT_ACTIVE", "무결성 오류(INVALID) 모델은 다시 활성화할 수 없습니다", status=409)
            values["status"] = body.status
        if values:
            m = models_repo.update_cas(conn, model_id, body.row_version, **values)
            audit(conn, principal, "MODEL_UPDATE", "model", model_id, dict(values), rid, ip)
        elif m["row_version"] != body.row_version:
            raise DomainError("VERSION_CONFLICT", "다른 사용자가 먼저 수정했습니다", status=409)
    return model_out(m, s["final_model_id"], with_curve=True, study=s, ai_root=ctx.settings.storage.ai_root)


def set_final(ctx: AppContext, principal: Principal, study_id: str, model_id: str | None, rid: str, ip: str | None) -> dict[str, Any]:
    with ctx.engine.begin() as conn:
        s = studies_repo.require(conn, study_id, for_update=True)
        if model_id is not None:
            m = models_repo.get(conn, model_id)
            if m is None or m["study_id"] != study_id:
                raise DomainError("NOT_FOUND", "모델을 찾을 수 없습니다", status=404)
        require_power(principal, s["project_id"])
        if model_id is not None and m["status"] != "ACTIVE":  # type: ignore[index]
            raise DomainError("MODEL_NOT_ACTIVE", "ACTIVE 모델만 Final로 지정할 수 있습니다", status=409)
        from sqlalchemy import func

        s = studies_repo.update_cas(
            conn, study_id, None, final_model_id=model_id,
            final_set_by=principal.user_id if model_id else None,
            final_set_at=func.now() if model_id else None,
        )
        audit(conn, principal, "FINAL_MODEL_SET", "study", study_id, {"model_id": model_id}, rid, ip)
    return study_out(s, principal, ctx.settings.storage.ai_root)
