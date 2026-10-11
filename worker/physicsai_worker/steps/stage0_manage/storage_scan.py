"""관리 STUDY_STORAGE_SCAN: Study 폴더 용량 계산(SS_WALK)과 정리 후보 분류(SS_CLASSIFY)(phase3 §5.3)."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

from physicsai_core.db.repositories import study_manage as sm_repo
from physicsai_core.errors import StepFailure
from physicsai_core.fileutil import write_json_atomic
from physicsai_core.study_storage.classify import Rules, classify
from physicsai_core.study_storage.scan import walk

ITEMS_NAME = "storage_items.json"  # SS_WALK → SS_CLASSIFY 중간 결과(이 작업 로그 폴더, 경로·크기만)


def _items_path(ctx: Any) -> str:
    return ctx.abs(f"logs/{ctx.ex.job_id}/{ITEMS_NAME}")


def ss_walk(ctx: Any) -> None:
    cfg = ctx.settings.study_storage
    tree = walk(ctx.root, max_entries=cfg.max_entries, top_n=cfg.top_files,
                on_progress=lambda n: ctx.progress(None, f"{n}개 확인", force=True), checkpoint=ctx.checkpoint)
    ctx.progress(None, f"{tree.entries}개 확인", force=True)
    write_json_atomic(_items_path(ctx), tree.items_json())
    ctx.log(f"항목 {tree.entries}개, 파일 {tree.total_files}개, {tree.total_bytes} bytes, 링크 {tree.skipped_links}개, "
            f"오류 {tree.errors}개{' (부분 스캔)' if tree.partial else ''}")
    if tree.partial:
        ctx.add_warning("STORAGE_SCAN_PARTIAL",
                        f"항목이 상한({cfg.max_entries}개)에 닿아 일부만 계산했습니다. 이 결과로는 정리할 수 없습니다")
    if tree.errors:
        ctx.add_warning("STORAGE_SCAN_ERRORS", f"읽지 못한 항목 {tree.errors}개는 건너뛰었습니다")
    ctx.patch_result(tree.summary())


def ss_classify(ctx: Any) -> None:
    cfg = ctx.settings.study_storage
    p = _items_path(ctx)
    if not os.path.isfile(p):
        raise StepFailure("INPUT_INVALID", "용량 계산 중간 결과가 없습니다. 다시 계산하세요")
    with open(p, encoding="utf-8") as fh:
        items: dict[str, list[int]] = json.load(fh)
    refs = ctx.ex.db(lambda c: sm_repo.study_refs(c, ctx.study["id"]))
    cats, link_excluded = classify(items, refs, Rules(cfg.log_min_age_days, cfg.keep_failed_logs),
                                   datetime.now(timezone.utc), cfg.max_items_per_category)
    if link_excluded:
        ctx.add_warning("LINK_SKIPPED", f"링크가 들어 있는 항목 {link_excluded}개는 정리 후보에서 뺐습니다")
    for c in cats:
        ctx.log(f"{c['key']}: {c['item_count']}개 {c['total_bytes']} bytes{' (상위만)' if c['truncated'] else ''}")
    ctx.patch_result({"categories": cats})


HANDLERS = {("STUDY_STORAGE_SCAN", "SS_WALK"): ss_walk, ("STUDY_STORAGE_SCAN", "SS_CLASSIFY"): ss_classify}
