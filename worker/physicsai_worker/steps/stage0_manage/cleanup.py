"""관리 STUDY_CLEANUP: 선택 범주 산출물을 `_backup/<stamp>_<job_id>/`로 이동(phase3 §5.7). 삭제 호출 없음.

SC_VALIDATE(실행 시점 재검사) → SC_MOVE(항목 단위 os.replace, 실패는 건너뜀) → SC_RECORD(매니페스트·DB·감사).
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

from physicsai_core.db.repositories import audit as audit_repo
from physicsai_core.db.repositories import datasets as datasets_repo
from physicsai_core.db.repositories import jobs as jobs_repo
from physicsai_core.db.repositories import study_manage as sm_repo
from physicsai_core.errors import StepFailure
from physicsai_core.fileutil import write_json_atomic
from physicsai_core.paths import BACKUP_DIR, backup_existing, is_link_or_reparse, resolve_in_study
from physicsai_core.study_storage.categories import SCAN_JOB_TYPE, is_protected
from physicsai_core.study_storage.classify import Rules, candidates

from ...signals import Cancelled

PLAN_NAME = "cleanup_plan.json"  # SC_VALIDATE → SC_MOVE(이 작업 로그 폴더)
MANIFEST_NAME = "CLEANUP_MANIFEST.json"
SKIP_CHANGED = "조건이 바뀌어 옮기지 않았습니다"
SKIP_MISSING = "항목이 없습니다"
SKIP_LINK = "링크가 들어 있어 옮기지 않았습니다"
SKIP_LOCKED = "파일이 사용 중"
RESTORE_HINT = "되돌리려면 이 폴더 아래 파일을 Study 폴더의 같은 상대경로로 옮기세요."


def _plan_path(ctx: Any) -> str:
    return ctx.abs(f"logs/{ctx.ex.job_id}/{PLAN_NAME}")


def _backup_rel(ctx: Any) -> str:
    return f"{BACKUP_DIR}/{ctx.ex.stamp}_{ctx.ex.job_id}"


def _has_link(root: str, path: str) -> bool:
    """항목 자신·상위(Study 안)·하위에 링크가 있으면 True."""
    cur = path
    while os.path.normpath(cur) != os.path.normpath(root) and len(cur) > len(root):
        if is_link_or_reparse(cur):
            return True
        cur = os.path.dirname(cur)
    if not os.path.isdir(path):
        return False
    stack = [path]
    while stack:
        with os.scandir(stack.pop()) as it:
            for e in it:
                if is_link_or_reparse(e.path):
                    return True
                if e.is_dir(follow_symlinks=False):
                    stack.append(e.path)
    return False


def sc_validate(ctx: Any) -> None:
    sid, cats = ctx.study["id"], list(ctx.params["categories"])
    cfg = ctx.settings.study_storage

    def load(c: Any) -> tuple[Any, bool, Any]:
        return (jobs_repo.get_job(c, ctx.params["scan_job_id"]), sm_repo.has_active_except(c, sid, ctx.ex.job_id),
                sm_repo.study_refs(c, sid))

    scan, active, refs = ctx.ex.db(load)
    if active:
        raise StepFailure("PREREQUISITE_MISSING", "대기 중이거나 실행 중인 작업이 있어 정리할 수 없습니다")
    if scan is None or scan["study_id"] != sid or scan["job_type"] != SCAN_JOB_TYPE or scan["state"] != "SUCCEEDED":
        raise StepFailure("INPUT_INVALID", "용량 계산 결과가 없습니다. 다시 계산한 뒤 정리하세요")
    selected = [(c["key"], it) for c in (scan["result"] or {}).get("categories", []) if c["key"] in cats for it in c["items"]]
    cands = candidates(refs, Rules(cfg.log_min_age_days, cfg.keep_failed_logs), datetime.now(timezone.utc),
                       [it["rel"] for _, it in selected])
    plan: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    for cat, it in selected:
        rel = it["rel"]
        cand = cands.get(rel)
        if cand is None or cand.category != cat or is_protected(rel):
            skipped.append({"rel": rel, "reason": SKIP_CHANGED})
            continue
        path = os.path.join(ctx.root, *rel.split("/"))
        resolve_in_study(ctx.root, rel)  # Study 밖이면 예외
        if not os.path.lexists(path):
            skipped.append({"rel": rel, "reason": SKIP_MISSING})
        elif _has_link(ctx.root, path):
            skipped.append({"rel": rel, "reason": SKIP_LINK})
        else:
            plan.append({"rel": rel, "bytes": int(it["bytes"]), "category": cat, "ref_id": cand.ref_id})
    for s in skipped:
        ctx.log(f"[SKIP] {s['rel']}: {s['reason']}")
    if not plan:
        raise StepFailure("INPUT_INVALID", "옮길 항목이 없습니다")
    write_json_atomic(_plan_path(ctx), plan)
    ctx.log(f"옮길 항목 {len(plan)}개, 건너뜀 {len(skipped)}개")
    ctx.patch_result({"categories": cats, "skipped": skipped, "moved": [], "planned_count": len(plan)})


def _summary(ctx: Any, moved: list[dict[str, Any]], skipped: list[dict[str, str]]) -> dict[str, Any]:
    return {"moved": moved, "skipped": skipped, "moved_count": len(moved), "moved_bytes": sum(m["bytes"] for m in moved),
            "skipped_count": len(skipped), "backup_rel": _backup_rel(ctx) if moved else None}


def _write_manifest(ctx: Any, summary: dict[str, Any], cats: list[str]) -> None:
    if not summary["moved"]:
        return
    write_json_atomic(ctx.abs(f"{_backup_rel(ctx)}/{MANIFEST_NAME}"), {
        "job_id": ctx.ex.job_id, "study_id": ctx.study["id"], "requested_by": ctx.job["created_by_name"],
        "created_at": datetime.now(timezone.utc).isoformat(), "categories": cats,
        "items": [{"rel": m["rel"], "bytes": m["bytes"], "category": m["category"]} for m in summary["moved"]],
        "skipped": summary["skipped"], "restore": RESTORE_HINT,
    })


def sc_move(ctx: Any) -> None:
    with open(_plan_path(ctx), encoding="utf-8") as fh:
        plan: list[dict[str, Any]] = json.load(fh)
    r = ctx.result()
    skipped: list[dict[str, str]] = list(r.get("skipped") or [])
    moved: list[dict[str, Any]] = []
    try:
        for i, it in enumerate(plan, start=1):
            ctx.checkpoint_cancel()
            path = os.path.join(ctx.root, *it["rel"].split("/"))
            try:
                done = backup_existing(ctx.root, [path], ctx.ex.job_id, ctx.ex.stamp)
            except (StepFailure, OSError) as exc:
                ctx.log(f"[SKIP] {it['rel']}: {exc}")
                skipped.append({"rel": it["rel"], "reason": SKIP_LOCKED})
                continue
            if not done:
                skipped.append({"rel": it["rel"], "reason": SKIP_MISSING})
                continue
            moved.append({"rel": it["rel"], "bytes": it["bytes"], "category": it["category"]})
            if it["category"] == "PACKAGE_PSDATA" and it.get("ref_id"):
                ctx.ex.db(lambda c, d=it["ref_id"]: datasets_repo.clear_package(c, d))
            ctx.progress(100.0 * i / len(plan), f"{i}/{len(plan)}개 이동")
    except Cancelled:
        summary = _summary(ctx, moved, skipped)
        _write_manifest(ctx, summary, list(ctx.params["categories"]))
        ctx.patch_result(summary)
        ctx.log(f"취소: {len(moved)}개는 이미 옮겼고 남은 항목은 옮기지 않았습니다")
        raise
    ctx.patch_result(_summary(ctx, moved, skipped))


def sc_record(ctx: Any) -> None:
    r = ctx.result()
    cats = list(ctx.params["categories"])
    summary = _summary(ctx, list(r.get("moved") or []), list(r.get("skipped") or []))
    _write_manifest(ctx, summary, cats)
    ctx.ex.db(lambda c: audit_repo.record(
        c, user_id=ctx.job["created_by"], username=None, action="STUDY_CLEANUP", target_type="study",
        target_id=ctx.study["id"], detail={"job_id": ctx.ex.job_id, "categories": cats, "moved_count": summary["moved_count"],
                                           "moved_bytes": summary["moved_bytes"], "skipped_count": summary["skipped_count"]},
    ))
    ctx.patch_result(summary)
    if not summary["moved"]:
        raise StepFailure("OUTPUT_LOCKED", "모든 항목을 옮기지 못했습니다(파일이 사용 중일 수 있습니다)")
    if summary["skipped"]:
        ctx.add_warning("PARTIAL_OUTPUT", f"{summary['skipped_count']}개 항목은 옮기지 못했습니다")
    ctx.log(f"{summary['moved_count']}개 항목, {summary['moved_bytes']} bytes를 {summary['backup_rel']}로 옮겼습니다")


HANDLERS = {
    ("STUDY_CLEANUP", "SC_VALIDATE"): sc_validate,
    ("STUDY_CLEANUP", "SC_MOVE"): sc_move,
    ("STUDY_CLEANUP", "SC_RECORD"): sc_record,
}
