"""② SPDM 읽기 전용 가져오기(phase2 §6.11, G). SPDM 쪽 쓰기 0 — 원본은 spdm.open_read(읽기 모드)로만 연다."""

from __future__ import annotations

import json
import os
import shutil
from datetime import datetime, timezone
from typing import Any

from physicsai_core import spdm
from physicsai_core.db.repositories import spdm_imports as imp_repo
from physicsai_core.errors import StepFailure
from physicsai_core.fileutil import write_json
from physicsai_core.paths import PathError, assert_writable

from .common import path_failure

CHUNK = 1024 * 1024


def _I(ctx: Any) -> tuple[str, str]:
    iid = ctx.params["import_id"]
    return iid, ctx.abs(f"02_import/{iid}")


def _plan_path(ctx: Any) -> str:
    return os.path.join(ctx.ex.log_dir, "spdm_plan.json")


def si_scan(ctx: Any) -> None:
    s = ctx.settings
    try:
        path = spdm.check_spdm_path(ctx.params["spdm_path"], s.storage.spdm_roots)
        res = spdm.scan(path, s.spdm_import.patterns, s.spdm_import.max_files)
    except PathError as exc:
        raise path_failure(exc) from None
    if not res.files:
        raise StepFailure("INPUT_INVALID", "가져올 파일(h3d·T01)이 없습니다")
    if res.total_bytes > s.spdm_import.max_total_bytes:
        raise StepFailure("INPUT_INVALID", f"총량 {res.total_bytes} bytes가 상한(spdm_import.max_total_bytes)을 넘습니다")
    free = shutil.disk_usage(s.storage.ai_root).free
    if free < res.total_bytes * 1.1:
        raise StepFailure("INPUT_INVALID", f"AI 루트 여유 공간이 부족합니다(필요 {int(res.total_bytes * 1.1)} bytes, 여유 {free})")
    plan = [{"source": f.source, "source_rel": f.source_rel, "dest_rel": f.dest_rel, "size": f.size,
             "mtime_ns": f.mtime_ns, "atime_ns": f.atime_ns, "renamed": f.renamed, "dev": f.dev, "ino": f.ino}
            for f in res.files]
    with open(_plan_path(ctx), "w", encoding="utf-8") as fh:
        json.dump({"spdm_path": path, "files": plan}, fh, ensure_ascii=False)
    if res.skipped_links:
        ctx.add_warning("SPDM_LINK_SKIPPED", f"링크 {res.skipped_links}개는 따라가지 않았습니다")
    ctx.log(f"SPDM 파일 {len(plan)}개, {res.total_bytes} bytes, 이름 정리 {res.renamed_count}개")
    ctx.patch_result({"spdm_path": path, "file_count": len(plan), "total_bytes": res.total_bytes,
                      "renamed_count": res.renamed_count})


def si_copy(ctx: Any) -> None:
    iid, I = _I(ctx)
    with open(_plan_path(ctx), encoding="utf-8") as fh:
        plan = json.load(fh)["files"]
    if os.path.lexists(I):
        ctx.backup([I])
    total = sum(f["size"] for f in plan) or 1
    done = 0
    for f in plan:
        dst = os.path.join(I, *f["dest_rel"].split("/"))
        assert_writable(dst)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        sf = spdm.SpdmFile(f["source"], f["source_rel"], f["dest_rel"], f["size"], f["mtime_ns"], f["atime_ns"], f["renamed"],
                           f.get("dev"), f.get("ino"))
        with spdm.open_read(sf) as src, open(dst, "wb") as out:
            while True:
                b = src.read(CHUNK)
                if not b:
                    break
                out.write(b)
                done += len(b)
                ctx.checkpoint()
                ctx.progress(done / total * 100.0, "SPDM 파일 복사")
        os.utime(dst, ns=(f["atime_ns"], f["mtime_ns"]))  # 대상 mtime만 원본 값(원본 메타데이터는 건드리지 않음)
    ctx.patch_result({"copied_bytes": done, "import_id": iid})


def si_register(ctx: Any) -> None:
    iid, I = _I(ctx)
    r = ctx.result()
    with open(_plan_path(ctx), encoding="utf-8") as fh:
        plan = json.load(fh)["files"]
    man = os.path.join(I, "import_manifest.json")
    write_json(man, {"spdm_path": r["spdm_path"], "imported_at": datetime.now(timezone.utc).isoformat(),
                     "files": [{"source_rel": f["source_rel"], "dest_rel": f["dest_rel"], "size": f["size"],
                                "renamed": f["renamed"]} for f in plan]})
    ctx.register_artifact("FILE_LIST", man, "application/json")
    ctx.ex.db(lambda c: imp_repo.set_import(c, iid, status="READY", file_count=len(plan), total_bytes=r["total_bytes"],
                                            renamed_count=r["renamed_count"], manifest_rel=ctx.rel(man)))
    ctx.patch_result({"import_id": iid, "file_count": len(plan), "total_bytes": r["total_bytes"],
                      "renamed_count": r["renamed_count"]})


HANDLERS = {
    ("SPDM_IMPORT", "SI_SCAN"): si_scan,
    ("SPDM_IMPORT", "SI_COPY"): si_copy,
    ("SPDM_IMPORT", "SI_REGISTER"): si_register,
}
