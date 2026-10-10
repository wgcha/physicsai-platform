"""①-5 TD_RESULT_IMPORT: 기존 해석 결과 가져오기(phase2 §6.6)."""

from __future__ import annotations

import os
from typing import Any

from physicsai_core import train_params as tp
from physicsai_core.db.repositories import train as train_repo
from physicsai_core.errors import StepFailure
from physicsai_core.fileutil import copy_file
from physicsai_core.paths import allowed_roots, check_user_path, is_link_or_reparse, PathError

from ..common import path_failure
from ._shared import _R, _doe, _match_files, _summary, _write_collected_json


def _import_roots(s: Any) -> list[str]:
    roots = allowed_roots(s, imports=True)
    if s.hpc.transfer.collect_root_local:
        roots.append(s.hpc.transfer.collect_root_local)
    return roots


def ri_scan(ctx: Any) -> None:
    s = ctx.settings
    doe = _doe(ctx)
    try:
        cp = check_user_path(ctx.params["source_path"], _import_roots(s))
    except PathError as exc:
        raise path_failure(exc) from None
    with ctx.ex.engine.connect() as conn:
        run_keys = {x["run_key"] for x in train_repo.runs_for_doe(conn, doe["id"])}
    matcher = tp.RunDirMatcher(s.train_data.result_run_dir_regex, run_keys)
    depth = s.train_data.result_match_depth
    found: dict[str, list[str]] = {}
    seen_dirs: list[str] = []
    base_depth = cp.path.rstrip(os.sep).count(os.sep)
    for dirpath, dirnames, _files in os.walk(cp.path, followlinks=False):
        d = dirpath.rstrip(os.sep).count(os.sep) - base_depth
        dirnames[:] = sorted(x for x in dirnames if x != "_backup" and not is_link_or_reparse(os.path.join(dirpath, x)))
        if d >= depth:
            dirnames[:] = []
            continue
        for x in dirnames:
            rk = matcher.match(x)  # run_key 그룹만 대소문자 무시(C13)
            if rk:
                found.setdefault(rk, []).append(os.path.join(dirpath, x))
            elif len(seen_dirs) < 20:
                seen_dirs.append(os.path.relpath(os.path.join(dirpath, x), cp.path).replace(os.sep, "/"))
    matched = {rk: v[0] for rk, v in found.items() if len(v) == 1}
    dups = sorted(rk for rk, v in found.items() if len(v) > 1)
    invalid = []
    for rk in dups:
        dirs = [os.path.relpath(x, cp.path).replace(os.sep, "/") for x in found[rk]]
        invalid.append({"run_key": rk, "reason": "같은 run의 결과 폴더가 여러 개", "dirs": dirs[:10]})
        ctx.add_warning("RUN_FOLDER_DUPLICATE", f"{rk}: 결과 폴더가 {len(dirs)}개({', '.join(dirs[:3])}) — 이 run은 가져오지 않습니다. 하나만 남기고 다시 실행하세요")
    if not matched:
        if dups:
            raise StepFailure("INPUT_INVALID", f"모든 run의 결과 폴더가 중복입니다: {', '.join(dups[:10])} — run마다 폴더를 하나만 두세요")
        raise StepFailure("INPUT_INVALID", "run 폴더를 찾지 못했습니다 — 하위 폴더: " + ", ".join(seen_dirs[:20]))
    ctx.patch_result({"source_path": cp.path, "matches": {rk: matched[rk] for rk in sorted(matched)},
                      "duplicate_runs": dups, "invalid_runs": invalid, "unmatched_dirs": seen_dirs[:20]})


def ri_copy(ctx: Any) -> None:
    s = ctx.settings
    r = ctx.result()
    doe = _doe(ctx)
    plan: list[tuple[str, str, int]] = []
    for rk, src in r["matches"].items():
        files = _match_files(src, s.hpc.transfer.collect_patterns)
        for rel, (size, _m) in sorted(files.items()):
            if size > s.hpc.transfer.max_collect_bytes:
                raise StepFailure("INPUT_INVALID", f"{rk}/{rel}: 파일이 상한(max_collect_bytes)을 넘습니다")
            plan.append((os.path.join(src, *rel.split("/")), os.path.join(_R(ctx, doe["id"], rk), *rel.split("/")), size))
    total = sum(x[2] for x in plan) or 1
    ctx.backup([_R(ctx, doe["id"], rk) for rk in r["matches"] if os.path.lexists(_R(ctx, doe["id"], rk))])
    done = [0]
    for src, dst, _size in plan:
        base = done[0]
        copy_file(src, dst, progress=lambda b, base=base: ctx.progress((base + b) / total * 100.0, "결과 복사"),
                  checkpoint=ctx.checkpoint)
        done[0] += _size
    for rk in r["matches"]:
        os.makedirs(_R(ctx, doe["id"], rk), exist_ok=True)
    ctx.patch_result({"copied_files": len(plan), "total_bytes": sum(x[2] for x in plan)})


def ri_register(ctx: Any) -> None:
    r = ctx.result()
    doe = _doe(ctx)
    keys = sorted(r["matches"])

    def reg(c: Any) -> None:
        for rk in keys:
            train_repo.set_run(c, doe["id"], rk, state="COLLECTED", result_rel=f"01_train/results/{doe['id']}/{rk}/",
                               result_summary=_summary(_R(ctx, doe["id"], rk)), last_job_id=ctx.ex.job_id)

    ctx.ex.db(reg)
    _write_collected_json(ctx, doe["id"])
    with ctx.ex.engine.connect() as conn:
        all_keys = [x["run_key"] for x in train_repo.runs_for_doe(conn, doe["id"])]
    missing = [k for k in all_keys if k not in r["matches"]]
    ctx.patch_result({"matched": len(keys), "copied_files": r.get("copied_files", 0), "total_bytes": r.get("total_bytes", 0),
                      "unmatched_dirs": (r.get("unmatched_dirs") or [])[:20], "missing_runs": missing[:5000]})


HANDLERS = {
    ("TD_RESULT_IMPORT", "RI_SCAN"): ri_scan,
    ("TD_RESULT_IMPORT", "RI_COPY"): ri_copy,
    ("TD_RESULT_IMPORT", "RI_REGISTER"): ri_register,
}
