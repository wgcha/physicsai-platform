"""업로드 세션 사전 검사(upload-report.md §4·§5): 파일 목록(이름·패턴·크기·개수·중복·모양), 디스크 여유·예약, 대상 경로 준비."""

from __future__ import annotations

import os
from typing import Any

from physicsai_core import uploads as U
from physicsai_core.db.repositories import uploads as repo
from physicsai_core.errors import DomainError

from ..context import AppContext

INSUFFICIENT = "INSUFFICIENT_STORAGE"


def segs_of(f: dict[str, Any]) -> list[str]:
    return f["rel"].split("/")


def part_of(up_dir: str, f: dict[str, Any]) -> str:
    return os.path.join(up_dir, *segs_of(f)) + U.PART_SUFFIX


def norm_files(ctx: AppContext, row_or_none: dict[str, Any] | None, purpose: str, engine: str | None, files: list[Any],
               existing: list[dict[str, Any]], up_dir_for_len: str) -> list[dict[str, Any]]:
    """새 파일 목록 검사(이름·패턴·크기·개수·중복·모양) → 저장용 dict 목록. 오류는 DomainError."""
    cfg = ctx.settings.upload
    if len(existing) + len(files) > cfg.max_files:
        raise DomainError("UPLOAD_TOO_MANY_FILES", f"파일이 너무 많습니다(최대 {cfg.max_files}개)", status=413, limit=cfg.max_files)
    patterns = U.purpose_patterns(ctx.settings, purpose, engine)
    out: list[dict[str, Any]] = []
    for f in files:
        segs = U.check_rel(f.rel, patterns)
        U.check_final_length(up_dir_for_len, segs, margin=0 if row_or_none else U.DIR_SUFFIX_MARGIN)
        if f.size > cfg.max_file_bytes:
            raise DomainError("UPLOAD_TOO_LARGE", f"파일이 너무 큽니다({f.rel}: {f.size} B > {cfg.max_file_bytes} B)",
                              status=413, rel=f.rel, limit=cfg.max_file_bytes)
        out.append({"rel": f.rel, "size": int(f.size), "sha256_expected": f.sha256.lower() if f.sha256 else None,
                    "sha256": None, "done": False})
    rels = [f["rel"] for f in out]
    U.check_shape(purpose, [f["rel"] for f in existing] + rels)
    U.check_no_conflicts([f["rel"] for f in existing], rels)
    total = sum(int(f["size"]) for f in existing) + sum(f["size"] for f in out)
    if total > cfg.max_upload_bytes:
        raise DomainError("UPLOAD_TOO_LARGE", f"업로드 전체 크기가 상한({cfg.max_upload_bytes} B)을 넘습니다", status=413,
                          limit=cfg.max_upload_bytes, total=total)
    return out


def reserved_bytes(ctx: AppContext, conn: Any, exclude_id: str | None) -> int:
    """다른 진행 중(OPEN) 세션이 앞으로 쓸 남은 바이트 합계(받은 `.part` 크기 제외) — 디스크 예약(§5)."""
    total = 0
    for r in repo.open_rows(conn, exclude_id=exclude_id):
        d = U.abs_dir_of(ctx.settings, r["dir_rel"])
        for f in r["files"]:
            if not f.get("done"):
                total += max(0, int(f["size"]) - U.part_size(part_of(d, f)))
    return total


def check_free(ctx: AppContext, conn: Any, root: str, need: int, exclude_id: str | None = None) -> None:
    """free ≥ 이번 필요량 + Σ(다른 OPEN 세션의 남은 바이트) + upload.min_free_gb 아니면 507."""
    free = U.free_bytes(root)
    if free is None:
        return
    held = reserved_bytes(ctx, conn, exclude_id)
    reserve = int(ctx.settings.upload.min_free_gb * 1024 ** 3)
    if free < need + held + reserve:
        raise DomainError(INSUFFICIENT, f"업로드 위치의 여유 공간이 부족합니다(필요 {need} B + 진행 중 업로드 예약 {held} B + 여유 "
                          f"{ctx.settings.upload.min_free_gb:g} GB, 현재 여유 {free} B)", status=507, need=need, reserved=held,
                          free=free, min_free_bytes=reserve)


def prepare_files(up_dir: str, new: list[dict[str, Any]]) -> None:
    """대상 경로가 비어 있는지(덮어쓰기 없음)·안전한지 확인하고 상위 폴더를 만든다. 빈 파일(size 0)은 바로 완료 처리."""
    from physicsai_core.fileutil import sha256_file

    for f in new:
        p = U.target_path(up_dir, segs_of(f), create_parents=True)
        if os.path.lexists(p):
            raise DomainError("UPLOAD_FILE_EXISTS", f"이미 있는 파일입니다(덮어쓰지 않음): {f['rel']}", status=409, rel=f["rel"])
        if f["size"] == 0:
            U.append_chunk(p + U.PART_SUFFIX, b"", up_dir)
            sha = sha256_file(p + U.PART_SUFFIX)
            if f["sha256_expected"] and f["sha256_expected"] != sha:
                raise DomainError("SHA256_MISMATCH", f"sha256이 다릅니다: {f['rel']}", status=422, rel=f["rel"])
            os.replace(p + U.PART_SUFFIX, p)
            f.update(done=True, sha256=sha)
