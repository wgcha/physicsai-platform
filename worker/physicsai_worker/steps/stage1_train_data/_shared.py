"""① 학습데이터 생성 step 공용 헬퍼(설정·DOE 조회, 단계 폴더 경로, 로그 꼬리)."""

from __future__ import annotations

import fnmatch
import os
from datetime import datetime, timezone
from typing import Any

from physicsai_core.db.repositories import train as train_repo
from physicsai_core.errors import StepFailure
from physicsai_core.fileutil import write_json
from physicsai_core.paths import is_link_or_reparse



TPL_REL = "01_train/tpl/simlab_parametered_mesh.tpl"
TPL_NAME = "simlab_parametered_mesh.tpl"


def _doe(ctx: Any, doe_id: str | None = None) -> dict[str, Any]:
    did = doe_id or ctx.params.get("doe_id")
    with ctx.ex.engine.connect() as conn:
        d = train_repo.get_doe(conn, did) if did else None
    if d is None or d["study_id"] != ctx.study["id"]:
        raise StepFailure("INPUT_INVALID", "DOE를 찾을 수 없습니다")
    return d


def _D(ctx: Any, doe_id: str | None = None) -> str:
    return ctx.abs(f"01_train/doe/{doe_id or ctx.params['doe_id']}")


def _R(ctx: Any, doe_id: str, run_key: str) -> str:
    return ctx.abs(f"01_train/results/{doe_id}/{run_key}")


def _match_files(root: str, patterns: list[str]) -> dict[str, tuple[int, float]]:
    out: dict[str, tuple[int, float]] = {}
    if not os.path.isdir(root):
        return out
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = sorted(d for d in dirnames if d != "_backup" and not is_link_or_reparse(os.path.join(dirpath, d)))
        for f in filenames:
            p = os.path.join(dirpath, f)
            if any(fnmatch.fnmatch(f, pat) for pat in patterns) and not is_link_or_reparse(p) and os.path.isfile(p):
                st = os.stat(p)
                out[os.path.relpath(p, root).replace(os.sep, "/")] = (st.st_size, st.st_mtime)
    return out


def _summary(root: str) -> dict[str, int]:
    h3d = t01 = files = total = 0
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = [d for d in dirnames if d != "_backup"]
        for f in filenames:
            p = os.path.join(dirpath, f)
            if os.path.islink(p) or not os.path.isfile(p):
                continue
            files += 1
            total += os.path.getsize(p)
            h3d += f.lower().endswith(".h3d")
            t01 += f.endswith("T01")
    return {"h3d": h3d, "t01": t01, "files": files, "total_bytes": total}


def _write_collected_json(ctx: Any, doe_id: str) -> None:
    with ctx.ex.engine.connect() as conn:
        runs = train_repo.runs_for_doe(conn, doe_id, states=["COLLECTED"])
    p = ctx.abs(f"01_train/results/{doe_id}/collected.json")
    ctx.backup([p])
    write_json(p, {"doe_id": doe_id, "updated_at": datetime.now(timezone.utc).isoformat(),
                   "runs": [{"run_key": x["run_key"], "result_rel": x["result_rel"], "summary": x["result_summary"],
                             "job_id": x["last_job_id"]} for x in runs]})
