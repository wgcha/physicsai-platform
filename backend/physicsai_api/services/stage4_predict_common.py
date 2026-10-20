"""④ 파라미터 세트 등록 공용 도우미(라벨·권한 확인·폴더 세트 행 삽입) — stage4_predict에서 재노출."""

from __future__ import annotations

import contextlib
import os
from typing import Any

from physicsai_core.db.repositories import param_sets as ps_repo
from physicsai_core.db.repositories import studies as studies_repo
from physicsai_core.errors import DomainError
from physicsai_core.naming import LABEL_MAX, label_problem
from physicsai_core.paths import resolve_in_study
from physicsai_core.stage4_predict import param_sets as ps_mod

from ..auth import Principal
from ..context import AppContext
from .common import (
    audit,
    param_set_out,
    require_config_ok,
    require_power,
)


def _label(raw: str | None) -> str | None:
    """표시 이름 공통 검증(D3-50, 스키마 `Label`과 같은 함수). 제어·양방향 제어 문자 → 422. 등록은 사본을 만들기 전에 부른다."""
    why = label_problem(raw or "")
    if why:
        raise DomainError("LABEL_INVALID", why, status=422)
    v = (raw or "").strip()
    return v[:LABEL_MAX] or None


def _require_active_power(ctx: AppContext, principal: Principal, study_id: str) -> dict[str, Any]:
    with ctx.engine.connect() as conn:
        s = studies_repo.require(conn, study_id)
    require_power(principal, s["project_id"])
    require_config_ok(ctx)
    if s["status"] != "ACTIVE":
        raise DomainError("STUDY_ARCHIVED", "보관된 Study입니다", status=409)
    return s


def _insert_folder_set(ctx: AppContext, principal: Principal, study_id: str, f: Any, psid: str, root: str, out_tmp: str,
                       source_path: str, label: str | None, action: str, detail: dict[str, Any], rid: str,
                       ip: str | None, **extra: Any) -> dict[str, Any]:
    """정규화본(`logs/_paramset_tmp/<tmp>.out`)을 `04_params/<id>`로 옮기고 DB 행을 넣는다(D3-50).

    이동은 DB 트랜잭션 안에서 하고, insert·commit이 실패하면 방금 옮긴 미등록 사본을 `logs/_paramset_tmp`로 되돌린다
    (삭제 호출 없음 — 이번 요청이 만든 사본이라 사용자 산출물이 아니며, 04_params에 DB 행 없는 고아 폴더를 남기지 않는다).
    mesh_only(phase3 §14.4): 조립 폴더 없음 → assem_rel·starter_name NULL. 경고 SIMLAB_EXPORT_NAME은 응답 `warnings`.
    """
    stored_rel = f"04_params/{psid}"
    dst = resolve_in_study(root, stored_rel)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    mesh_only = f.input_kind == "mesh_only"
    warnings = ps_mod.export_name_notes(out_tmp, ctx.settings.param_set.tpl_export_regex, ctx.settings.predict.simlab_mesh_name)
    moved = False
    try:
        with ctx.engine.begin() as conn:
            ps_repo.insert_current(conn, {
                "id": psid, "study_id": study_id, "source_path": source_path, "stored_rel": stored_rel + "/",
                "unit_system": f.unit_system, "parameters": f.parameters, "responses": f.responses,
                "sample_count": len(f.samples), "sample_has_measured": f.sample_has_measured,
                "cad_file_name": f.cad_file, "tpl_rel": f"{stored_rel}/{ps_mod.TPL_NAME}",
                "assem_rel": None if mesh_only else f"{stored_rel}/radioss_assem/",
                "starter_name": None if mesh_only else f.starter_name, "input_kind": f.input_kind, "tpl_params": f.tpl_params,
                "registered_by": principal.user_id, "registered_by_name": principal.display_name, "label": label, **extra,
            })
            audit(conn, principal, action, "param_set", psid,
                  {**detail, "label": label, "input_kind": f.input_kind, "warnings": [w["code"] for w in warnings]}, rid, ip)
            os.replace(out_tmp, dst)  # 원래 위치에서 이동(삭제 호출 없음)
            moved = True
            p = ps_repo.get(conn, psid)
    except BaseException:
        if moved and os.path.isdir(dst) and not os.path.lexists(out_tmp):
            with contextlib.suppress(OSError):
                os.replace(dst, out_tmp)  # 미등록 사본을 되돌림(04_params 고아 방지)
        raise
    return {**param_set_out(p), "warnings": warnings}  # type: ignore[arg-type]
