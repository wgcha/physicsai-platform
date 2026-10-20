"""⑤ 등가성 판정 레시피 API 서비스(equiv-check.md §3·§6): 목록·조회·생성(복제)·편집(새 버전)·소프트 삭제·되살리기.

시스템 기본 레시피(`sys:default`)는 설정의 제안값 — 읽기 전용(수정·삭제 409 EQ_RECIPE_READONLY), 복제해서 쓴다."""

from __future__ import annotations

from typing import Any

from physicsai_core.config.schema_equiv import SYSTEM_RECIPE_KEY, SYSTEM_RECIPE_NAME
from physicsai_core.db.repositories import equiv_check as eq_repo
from physicsai_core.db.repositories import studies as studies_repo
from physicsai_core.equiv.recipes import normalize_definition, validate_definition
from physicsai_core.errors import DomainError

from ..auth import Principal
from ..context import AppContext
from .common import audit, require_global_admin, require_power


def system_recipe(ctx: AppContext) -> dict[str, Any]:
    s = ctx.settings.equiv_check
    return {"key": SYSTEM_RECIPE_KEY, "version": int(s.system_version), "name": SYSTEM_RECIPE_NAME,
            "description": "시스템 제안값 — 복제해서 허용오차·필수 여부·원천 연결을 사용자가 정합니다", "scope": "system",
            "study_id": None, "metrics_count": len(s.system_recipe.get("metrics") or []), "updated_at": None,
            "updated_by_name": None, "readonly": True, "deleted": False, "can_edit": False,
            "definition": normalize_definition(s.system_recipe), "parent": None, "versions": None}


def _can_edit(principal: Principal, row: dict[str, Any], study: dict[str, Any] | None) -> bool:
    if row["scope"] == "global":
        return principal.is_global_admin or row["created_by"] == principal.user_id
    return bool(study) and principal.can_execute(study["project_id"])


def _item(row: dict[str, Any], principal: Principal, study: dict[str, Any] | None, *, full: bool = False,
          versions: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    out = {"key": row["recipe_key"], "version": int(row["version"]), "name": row["name"], "description": row.get("description") or "",
           "scope": row["scope"], "study_id": row.get("study_id"), "metrics_count": len((row.get("definition") or {}).get("metrics") or []),
           "updated_at": row["created_at"], "updated_by_name": row.get("created_by_name"), "readonly": False,
           "deleted": row.get("deleted_at") is not None, "can_edit": _can_edit(principal, row, study) and row.get("deleted_at") is None}
    if full:
        out["definition"] = row["definition"]
        out["parent"] = {"key": row["parent_key"], "version": row["parent_version"]} if row.get("parent_key") else None
        out["versions"] = [{"version": int(v["version"]), "created_at": v["created_at"], "created_by_name": v["created_by_name"],
                            "name": v["name"]} for v in (versions or [])]
    return out


def list_(ctx: AppContext, principal: Principal, study_id: str | None) -> list[dict[str, Any]]:
    with ctx.engine.connect() as conn:
        study = studies_repo.require(conn, study_id) if study_id else None
        rows = eq_repo.latest_versions(conn, study_id=study_id)
    return [system_recipe(ctx)] + [_item(r, principal, study) for r in rows]


def _require_row(conn: Any, key: str, version: int | None, *, for_update: bool = False) -> dict[str, Any]:
    row = eq_repo.get_version(conn, key, version, for_update=for_update)
    if row is None:
        raise DomainError("EQ_RECIPE_NOT_FOUND", "레시피를 찾을 수 없습니다", status=404)
    return row


def get(ctx: AppContext, principal: Principal, key: str, version: int | None, *, with_versions: bool = False) -> dict[str, Any]:
    if key == SYSTEM_RECIPE_KEY:
        return system_recipe(ctx)
    with ctx.engine.connect() as conn:
        row = _require_row(conn, key, version)
        study = studies_repo.get(conn, row["study_id"]) if row.get("study_id") else None
        vs = eq_repo.versions(conn, key) if with_versions else None
    return _item(row, principal, study, full=True, versions=vs)


def _validated(ctx: AppContext, definition: Any) -> dict[str, Any]:
    probs = validate_definition(definition, max_metrics=ctx.settings.equiv_check.max_metrics, allow_unbound=True)
    if probs:
        raise DomainError("EQ_RECIPE_INVALID", "레시피 정의가 올바르지 않습니다", status=422, problems=probs)
    return normalize_definition(definition)


def _source_definition(ctx: AppContext, conn: Any, body: Any) -> tuple[dict[str, Any], tuple[str, int] | None]:
    """생성 입력 → (정의, parent). definition | clone_from | from_check 중 정확히 하나."""
    given = [k for k in ("definition", "clone_from", "from_check") if getattr(body, k) is not None]
    if len(given) != 1:
        raise DomainError("EQ_RECIPE_INVALID", "definition, clone_from, from_check 중 하나만 지정하세요", status=422,
                          problems=[{"code": "SOURCE_INVALID", "message": "생성 원천은 하나여야 합니다"}])
    if body.definition is not None:
        return _validated(ctx, body.definition), None
    if body.clone_from is not None:
        if body.clone_from.key == SYSTEM_RECIPE_KEY:
            sysr = system_recipe(ctx)
            return sysr["definition"], (SYSTEM_RECIPE_KEY, sysr["version"])
        row = _require_row(conn, body.clone_from.key, body.clone_from.version)
        return _validated(ctx, row["definition"]), (row["recipe_key"], int(row["version"]))
    chk = eq_repo.get_check(conn, body.from_check)
    if chk is None:
        raise DomainError("EQ_CHECK_NOT_FOUND", "판정 이력을 찾을 수 없습니다", status=404)
    snap = dict(chk["recipe_snapshot"])
    defn = {k: snap[k] for k in ("schema_version", "metrics", "pair_rule", "verdict_rule") if k in snap}
    parent = (chk["recipe_key"], int(chk["recipe_version"])) if chk.get("recipe_key") and chk.get("recipe_version") else None
    return _validated(ctx, defn), parent


def create(ctx: AppContext, principal: Principal, body: Any, rid: str, ip: str | None) -> dict[str, Any]:
    with ctx.engine.begin() as conn:
        study = None
        if body.scope == "study":
            if not body.study_id:
                raise DomainError("EQ_RECIPE_INVALID", "Study 범위 레시피에는 study_id가 필요합니다", status=422,
                                  problems=[{"code": "SOURCE_INVALID", "message": "study_id 필요"}])
            study = studies_repo.require(conn, body.study_id)
            require_power(principal, study["project_id"])
        else:
            if not principal.is_global_admin and not any(principal.can_execute(p) for p in principal.roles):
                raise DomainError("PERMISSION_DENIED", "실행 권한(power 이상)이 필요합니다", status=403, required="power")
        defn, parent = _source_definition(ctx, conn, body)
        if eq_repo.name_taken(conn, body.scope, body.study_id if body.scope == "study" else None, body.name):
            raise DomainError("EQ_RECIPE_NAME_TAKEN", f"같은 범위에 같은 이름의 레시피가 있습니다: {body.name}", status=409)
        row = eq_repo.insert_version(conn, key=None, version=1, scope=body.scope, study_id=body.study_id if body.scope == "study" else None,
                                     name=body.name.strip(), description=body.description, definition=defn, parent=parent,
                                     user_id=principal.user_id, user_name=principal.display_name)
        audit(conn, principal, "EQ_RECIPE_CREATE", "eq_recipe", row["recipe_key"],
              {"name": row["name"], "scope": row["scope"], "parent": list(parent) if parent else None}, rid, ip)
        return _item(row, principal, study, full=True, versions=eq_repo.versions(conn, row["recipe_key"]))


def _require_editable(ctx: AppContext, conn: Any, principal: Principal, key: str) -> tuple[dict[str, Any], dict[str, Any] | None]:
    if key == SYSTEM_RECIPE_KEY:
        raise DomainError("EQ_RECIPE_READONLY", "시스템 기본 레시피는 수정·삭제할 수 없습니다 — 복제해서 사용하세요", status=409)
    row = _require_row(conn, key, None, for_update=True)
    study = studies_repo.require(conn, row["study_id"]) if row.get("study_id") else None
    if row["scope"] == "global":
        if not (principal.is_global_admin or (row["created_by"] == principal.user_id and any(principal.can_execute(p) for p in principal.roles))):
            raise DomainError("PERMISSION_DENIED", "전역 레시피는 작성자 또는 관리자만 고칠 수 있습니다", status=403, required="owner")
    else:
        require_power(principal, study["project_id"])  # type: ignore[index]
    return row, study


def update(ctx: AppContext, principal: Principal, key: str, body: Any, rid: str, ip: str | None) -> dict[str, Any]:
    with ctx.engine.begin() as conn:
        row, study = _require_editable(ctx, conn, principal, key)
        if row.get("deleted_at") is not None:
            raise DomainError("EQ_RECIPE_NOT_FOUND", "삭제된 레시피입니다(관리자 되살리기 후 편집)", status=404)
        if int(row["version"]) != int(body.base_version):
            raise DomainError("EQ_RECIPE_VERSION_CONFLICT", f"레시피가 다른 곳에서 바뀌었습니다(현재 v{row['version']}, 요청 v{body.base_version})",
                              status=409, current_version=int(row["version"]))
        defn = _validated(ctx, body.definition)
        name = (body.name or row["name"]).strip()
        if name.casefold() != row["name"].casefold() and eq_repo.name_taken(conn, row["scope"], row.get("study_id"), name, exclude_key=key):
            raise DomainError("EQ_RECIPE_NAME_TAKEN", f"같은 범위에 같은 이름의 레시피가 있습니다: {name}", status=409)
        new = eq_repo.insert_version(conn, key=key, version=int(row["version"]) + 1, scope=row["scope"], study_id=row.get("study_id"),
                                     name=name, description=row["description"] if body.description is None else body.description,
                                     definition=defn, parent=(row["parent_key"], row["parent_version"]) if row.get("parent_key") else None,
                                     user_id=principal.user_id, user_name=principal.display_name)
        audit(conn, principal, "EQ_RECIPE_UPDATE", "eq_recipe", key, {"version": int(new["version"])}, rid, ip)
        return _item(new, principal, study, full=True, versions=eq_repo.versions(conn, key))


def delete(ctx: AppContext, principal: Principal, key: str, rid: str, ip: str | None) -> None:
    with ctx.engine.begin() as conn:
        row, _study = _require_editable(ctx, conn, principal, key)
        if row.get("deleted_at") is None:
            eq_repo.soft_delete(conn, key, principal.user_id)
            audit(conn, principal, "EQ_RECIPE_DELETE", "eq_recipe", key, {"name": row["name"]}, rid, ip)


def restore(ctx: AppContext, principal: Principal, key: str, rid: str, ip: str | None) -> dict[str, Any]:
    require_global_admin(principal)
    with ctx.engine.begin() as conn:
        if key == SYSTEM_RECIPE_KEY:
            raise DomainError("EQ_RECIPE_READONLY", "시스템 기본 레시피는 되살릴 대상이 아닙니다", status=409)
        row = _require_row(conn, key, None, for_update=True)
        if row.get("deleted_at") is not None:
            if eq_repo.name_taken(conn, row["scope"], row.get("study_id"), row["name"], exclude_key=key):
                raise DomainError("EQ_RECIPE_NAME_TAKEN", f"같은 이름의 활성 레시피가 있어 되살릴 수 없습니다: {row['name']}", status=409)
            eq_repo.restore(conn, key)
            audit(conn, principal, "EQ_RECIPE_RESTORE", "eq_recipe", key, {"name": row["name"]}, rid, ip)
        row = _require_row(conn, key, None)
        study = studies_repo.get(conn, row["study_id"]) if row.get("study_id") else None
        return _item(row, principal, study, full=True, versions=eq_repo.versions(conn, key))


def load_for_check(ctx: AppContext, conn: Any, ref: Any) -> tuple[dict[str, Any], str, str | None, int | None]:
    """판정 요청의 recipe 참조 → (정의, source system|user, key, version). 삭제된 레시피는 404."""
    if ref.key == SYSTEM_RECIPE_KEY:
        sysr = system_recipe(ctx)
        return sysr["definition"], "system", SYSTEM_RECIPE_KEY, sysr["version"]
    row = _require_row(conn, ref.key, ref.version)
    if row.get("deleted_at") is not None:
        raise DomainError("EQ_RECIPE_NOT_FOUND", "삭제된 레시피입니다 — 다른 레시피를 선택하세요", status=404)
    return dict(row["definition"]), "user", row["recipe_key"], int(row["version"])
