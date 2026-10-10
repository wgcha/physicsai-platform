"""② 데이터 정리 step 공용: 원천 루트 해석·대상 파일 수집·큐레이션 등록(phase2 §4.4, §6.7~§6.10)."""

from __future__ import annotations

import json
import os
from typing import Any

from physicsai_core.db.repositories import curations as cur_repo
from physicsai_core.db.repositories import train as train_repo
from physicsai_core.errors import StepFailure
from physicsai_core.fileutil import write_json
from physicsai_core.paths import PathError, check_dataset_input, check_user_path, display_path
from physicsai_core.stage2_curation import curation as cu

from ..common import path_failure


def source_root(ctx: Any, source: dict[str, Any]) -> str:
    """원천 루트(§4.4). FOLDER는 1차 §17.3 검사 + B23 확장 목록 거부."""
    rel = cu.source_root_rel(source)
    if rel is not None:
        root = ctx.abs(rel)
        if not os.path.isdir(root):
            raise StepFailure("INPUT_INVALID", f"원천 폴더가 없습니다: {rel}")
        return root
    try:
        cp = check_user_path(source.get("path"), [ctx.settings.storage.ai_root])
        check_dataset_input(cp.path, ctx.settings.storage.ai_root)
    except PathError as exc:
        raise path_failure(exc) from None
    return cp.path


def _collect(ctx: Any, kind: str) -> tuple[str, list[str]]:
    root = source_root(ctx, ctx.params["source"])
    files = cu.collect_files(root, kind, ctx.settings.curation.max_files)
    if not files:
        raise StepFailure("INPUT_INVALID", f"원천에 {'h3d' if kind == 'H3D' else 'T01'} 파일이 없습니다")
    return root, files


def _W(ctx: Any) -> str:
    return ctx.abs(f"02_preview/{ctx.workspace_id}")


def _rel(root: str, p: str) -> str:
    return os.path.relpath(p, root).replace(os.sep, "/")


def _read_json(path: str, max_bytes: int) -> Any:
    if not os.path.isfile(path):
        raise StepFailure("OUTPUT_MISSING", f"{os.path.basename(path)}이 만들어지지 않았습니다")
    if os.path.getsize(path) > max_bytes:
        raise StepFailure("OUTPUT_MISSING", f"{os.path.basename(path)}이 크기 상한을 넘습니다")
    try:
        with open(path, encoding="utf-8-sig") as fh:
            return json.load(fh)
    except ValueError as exc:
        raise StepFailure("OUTPUT_MISSING", f"{os.path.basename(path)} 형식 오류: {exc}") from None


def _C(ctx: Any) -> tuple[str, str]:
    cid = ctx.result().get("curation_id") or ctx.params.get("curation_id")
    if not cid:
        raise StepFailure("INTERNAL_ERROR", "curation_id가 없습니다")
    return cid, ctx.abs(f"02_curated/{cid}")


def _finish_curation(ctx: Any, cid: str, C: str, items: list[dict[str, Any]], out_dir: str) -> None:
    fl = os.path.join(C, "file_list.json")
    ctx.backup([fl])
    write_json(fl, items)
    ctx.register_artifact("FILE_LIST", fl, "application/json")
    ok_n = sum(1 for x in items if x["ok"])
    missing: list[str] = []
    src = ctx.params["source"]
    if src["kind"] == "TRAIN_DOE":
        with ctx.ex.engine.connect() as conn:
            keys = [x["run_key"] for x in train_repo.runs_for_doe(conn, src["doe_id"])]
        have = {x.get("run_key") for x in items if x["ok"]}
        missing = [k for k in keys if k not in have][:5000]
    ctx.ex.db(lambda c: cur_repo.set_curation(c, cid, status="READY", target_count=len(items), ok_count=ok_n,
                                              failed_count=len(items) - ok_n, missing_runs=missing))
    ctx.patch_result({"curation_id": cid, "target_count": len(items), "ok_count": ok_n, "failed_count": len(items) - ok_n,
                      "missing_run_count": len(missing),
                      "output_display_path": display_path(ctx.settings.storage.ai_root, ctx.study["folder_name"],
                                                          f"02_curated/{cid}/{out_dir}")})
