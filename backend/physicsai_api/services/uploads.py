"""브라우저 분할 업로드 세션(upload-report.md §4·§5) — 허용된 유일한 업로드 경로(청크 PUT octet-stream, 폼 본문 없음).

흐름: POST /studies/{id}/uploads(사전 검사·폴더 생성) → PUT /uploads/{id}/files/{i}?offset=(`upload_chunks`) →
POST /uploads/{id}/complete(`upload_complete` — 기존 paths/inspect 서비스 호출) → 필요하면 POST /uploads/{id}/files로 추가 후 다시 complete.
DELETE는 OPEN 세션 취소(폴더를 `_backup`으로 이동). 낡은 OPEN 세션은 `_backup`으로 이동(STALE). 파일 삭제는 하지 않는다.
쓰기(생성·청크·추가·complete)는 본인 세션 + 해당 Study 프로젝트 power 이상, 조회·취소는 본인 또는 전역 관리자(남의 세션은 404).
로그·감사에는 id·수치·폴더 상대경로만 남긴다(쿠키·세션 토큰·파일 이름 목록·내용 없음).
"""

from __future__ import annotations

import logging
import os
from typing import Any

from physicsai_core import uploads as U
from physicsai_core import uploads_retire
from physicsai_core.config.schema_upload import ALWAYS_DENIED
from physicsai_core.db.repositories import studies as studies_repo
from physicsai_core.db.repositories import uploads as repo
from physicsai_core.errors import DomainError
from physicsai_core.paths import display_path

from ..auth import Principal
from ..context import AppContext
from .common import audit, require_config_ok, require_global_admin, require_power
from .upload_checks import check_free, norm_files, part_of, prepare_files, segs_of  # noqa: F401 - segs_of 재노출

log = logging.getLogger("physicsai_api.uploads")
OPEN, COMPLETED = repo.OPEN, repo.COMPLETED


def enabled(ctx: AppContext) -> bool:
    return bool(U.upload_root_path(ctx.settings)) and ctx.config.ok


def require_root(ctx: AppContext) -> str:
    root = U.upload_root_path(ctx.settings)
    if not root:
        raise DomainError("UPLOAD_DISABLED", "업로드 저장 위치(storage.upload_root)가 설정되지 않았습니다", status=503)
    return root


def not_found() -> DomainError:
    return DomainError("UPLOAD_NOT_FOUND", "업로드를 찾을 수 없습니다", status=404)


def get_row(conn: Any, upload_id: str, *, for_update: bool = False) -> dict[str, Any]:
    row = repo.get(conn, upload_id, for_update=for_update)
    if row is None:
        raise not_found()
    return row


def visible(principal: Principal, row: dict[str, Any]) -> dict[str, Any]:
    """조회·취소: 본인 또는 전역 관리자. 남의 세션은 404(존재 여부를 알리지 않음)."""
    if row["user_id"] != principal.user_id and not principal.is_global_admin:
        raise not_found()
    return row


def owned(principal: Principal, row: dict[str, Any]) -> dict[str, Any]:
    """쓰기: 본인 세션만(전역 관리자도 남의 세션에는 쓰지 않는다) + 프로젝트 power 이상."""
    if row["user_id"] != principal.user_id:
        raise not_found()
    require_power(principal, row["project_id"])
    return row


def require_open(row: dict[str, Any]) -> None:
    if row["state"] != OPEN:
        raise DomainError("UPLOAD_CLOSED", f"이미 끝난 업로드입니다({row['state']})", status=409, state=row["state"])


def result_path(ctx: AppContext, row: dict[str, Any]) -> str | None:
    """경로 칸에 채울 값: 폴더(업로드 폴더) 또는 파일 1개(CAD 등). 취소·낡음은 폴더가 옮겨져 None."""
    if row["state"] not in (OPEN, COMPLETED):
        return None
    d = U.abs_dir_of(ctx.settings, row["dir_rel"])
    one = U.result_rel(row["purpose"], [f["rel"] for f in row["files"]])
    return os.path.join(d, *one.split("/")) if one else d


def display_rel(ctx: AppContext, rel: str, extra: str | None = None) -> str | None:
    parts = [x for x in rel.split("/") if x]
    return display_path(ctx.settings.storage.ai_root, parts[0], "/".join([*parts[1:], *([extra] if extra else [])]))


def result_display(ctx: AppContext, row: dict[str, Any]) -> str | None:
    if row["state"] not in (OPEN, COMPLETED):
        return None
    one = U.result_rel(row["purpose"], [f["rel"] for f in row["files"]])
    return display_rel(ctx, row["dir_rel"], one)


def inspect_out(row: dict[str, Any], path: str | None) -> dict[str, Any] | None:
    ins = row.get("inspect")
    if not ins:
        return None
    return {"normalized_path": path or "", "ok": bool(ins.get("ok")), "problems": ins.get("problems") or [],
            "summary": ins.get("summary") or {}}


def upload_out(ctx: AppContext, row: dict[str, Any]) -> dict[str, Any]:
    up_dir = U.abs_dir_of(ctx.settings, row["dir_rel"])
    live = row["state"] == OPEN
    files = []
    for i, f in enumerate(row["files"]):
        rec = int(f["size"]) if f.get("done") else (U.part_size(part_of(up_dir, f)) if live else 0)
        files.append({"index": i, "rel": f["rel"], "size": int(f["size"]), "received": rec, "done": bool(f.get("done")),
                      "sha256": f.get("sha256"), "sha256_expected": f.get("sha256_expected")})
    path = result_path(ctx, row)
    return {"upload_id": row["id"], "study_id": row["study_id"], "purpose": row["purpose"], "engine": row["engine"],
            "name": row["name"], "state": row["state"], "path": path, "display_path": result_display(ctx, row),
            "chunk_size": ctx.settings.upload.chunk_bytes, "total_bytes": int(row["total_bytes"]),
            "received_bytes": sum(f["received"] for f in files), "files": files, "inspect": inspect_out(row, path),
            "backup_display_path": display_rel(ctx, row["backup_rel"]) if row.get("backup_rel") else None,
            "created_by": row["username"], "created_at": row["created_at"], "updated_at": row["updated_at"],
            "completed_at": row.get("completed_at")}


# ---------------------------------------------------------------- 설정·상태
def config_out(ctx: AppContext) -> dict[str, Any]:
    cfg = ctx.settings.upload
    root = U.upload_root_path(ctx.settings)
    return {"enabled": enabled(ctx), "chunk_size": cfg.chunk_bytes, "max_file_bytes": cfg.max_file_bytes,
            "max_upload_bytes": cfg.max_upload_bytes, "max_files": cfg.max_files,
            "max_concurrent_per_user": cfg.max_concurrent_per_user, "purposes": U.config_purposes(ctx.settings),
            "always_denied": list(ALWAYS_DENIED), "free_bytes": U.free_bytes(root) if root else None}


def status_block(ctx: AppContext) -> dict[str, Any]:
    root = U.upload_root_path(ctx.settings)
    return {"enabled": enabled(ctx), "free_bytes": U.free_bytes(root) if root else None}


# ---------------------------------------------------------------- 세션
def create_upload(ctx: AppContext, principal: Principal, study_id: str, body: Any, rid: str | None, ip: str | None) -> dict[str, Any]:
    root = require_root(ctx)
    require_config_ok(ctx)
    with ctx.engine.connect() as conn:
        study = studies_repo.require(conn, study_id)
    require_power(principal, study["project_id"])
    if body.purpose not in U.UPLOAD_PURPOSES:
        raise DomainError("UPLOAD_PURPOSE_INVALID", f"업로드할 수 없는 용도입니다: {body.purpose}", status=422, purpose=body.purpose)
    uploads_retire.cleanup_stale(ctx.settings, ctx.engine)
    name_seg = U.safe_name(body.name)
    user_seg = U.user_segment(principal.username, principal.user_id)
    projected = U.projected_dir(root, user_seg, name_seg, U.utc_stamp())
    files = norm_files(ctx, None, body.purpose, body.engine, body.files, [], projected)
    cfg = ctx.settings.upload
    need = sum(f["size"] for f in files)
    with ctx.engine.begin() as conn:
        repo.lock_user(conn, principal.user_id)
        n_open = repo.count_open(conn, principal.user_id)
        if n_open >= cfg.max_concurrent_per_user:
            raise DomainError("UPLOAD_LIMIT", f"진행 중인 업로드가 {n_open}개입니다(사용자당 최대 {cfg.max_concurrent_per_user}개) — "
                              "끝내거나 취소한 뒤 다시 시도하세요", status=429, limit=cfg.max_concurrent_per_user)
        check_free(ctx, conn, root, need)
        up_dir = U.make_upload_dir(ctx.settings.storage.ai_root, root, user_seg, name_seg, U.utc_stamp())
        try:
            prepare_files(up_dir, files)
            row = repo.insert_row(conn, study_id=study_id, project_id=study["project_id"], user_id=principal.user_id,
                                  username=principal.username, purpose=body.purpose, engine=body.engine,
                                  name=body.name.strip(), dir_rel=U.dir_rel_of(ctx.settings, up_dir), state=OPEN, files=files,
                                  total_bytes=need)
            audit(conn, principal, "UPLOAD_CREATE", "upload", row["id"],
                  {"purpose": body.purpose, "files": len(files), "bytes": need, "dir_rel": row["dir_rel"]}, rid, ip)
        except BaseException:
            U.move_to_backup(root, user_seg, up_dir)  # 만든 폴더는 지우지 않고 _backup으로
            raise
    log.info("업로드 세션 생성 upload_id=%s purpose=%s files=%d bytes=%d", row["id"], body.purpose, len(files), need)
    return upload_out(ctx, row)


def add_files(ctx: AppContext, principal: Principal, upload_id: str, body: Any) -> dict[str, Any]:
    root = require_root(ctx)
    require_config_ok(ctx)
    with ctx.engine.begin() as conn:
        row = owned(principal, get_row(conn, upload_id, for_update=True))
        require_open(row)
        up_dir = U.abs_dir_of(ctx.settings, row["dir_rel"])
        new = norm_files(ctx, row, row["purpose"], row["engine"], body.files, row["files"], up_dir)
        own_left = sum(max(0, int(f["size"]) - U.part_size(part_of(up_dir, f))) for f in row["files"] if not f.get("done"))
        check_free(ctx, conn, root, sum(f["size"] for f in new) + own_left, exclude_id=upload_id)
        prepare_files(up_dir, new)
        files = list(row["files"]) + new
        row = repo.update_row(conn, upload_id, files=files, total_bytes=sum(int(f["size"]) for f in files), inspect=None)
    return upload_out(ctx, row)


def get_upload(ctx: AppContext, principal: Principal, upload_id: str) -> dict[str, Any]:
    with ctx.engine.connect() as conn:
        row = visible(principal, get_row(conn, upload_id))
    return upload_out(ctx, row)


def list_uploads(ctx: AppContext, principal: Principal, study_id: str, state: str | None, mine: bool) -> list[dict[str, Any]]:
    """최근 50개. mine=false(남의 세션 포함)는 전역 관리자만 — 그 밖에는 본인 세션만."""
    with ctx.engine.connect() as conn:
        studies_repo.require(conn, study_id)
        rows = repo.list_for_study(conn, study_id, user_id=None if (not mine and principal.is_global_admin) else principal.user_id,
                                   state=state)
    return [upload_out(ctx, r) for r in rows]


def cancel(ctx: AppContext, principal: Principal, upload_id: str, rid: str | None, ip: str | None) -> dict[str, Any]:
    require_root(ctx)
    require_config_ok(ctx)
    with ctx.engine.begin() as conn:
        row = visible(principal, get_row(conn, upload_id, for_update=True))
        if row["user_id"] == principal.user_id:
            require_power(principal, row["project_id"])
        if row["state"] == COMPLETED:
            raise DomainError("UPLOAD_CLOSED", "완료된 업로드는 취소할 수 없습니다(작업 입력 원본으로 쓰일 수 있음)", status=409,
                              state=row["state"])
        require_open(row)
        row = uploads_retire.retire(ctx.settings, conn, row, repo.CANCELED)
        audit(conn, principal, "UPLOAD_CANCEL", "upload", upload_id,
              {"purpose": row["purpose"], "files": len(row["files"]), "bytes": int(row["total_bytes"]),
               "dir_rel": row["dir_rel"]}, rid, ip)
    log.info("업로드 세션 취소 upload_id=%s", upload_id)
    return upload_out(ctx, row)


def cleanup_stale(ctx: AppContext, principal: Principal) -> dict[str, Any]:
    """관리자: 낡은 OPEN 세션 정리 즉시 실행(`_backup` 이동, 삭제 없음)."""
    require_global_admin(principal)
    return {"moved": uploads_retire.cleanup_stale(ctx.settings, ctx.engine)}
