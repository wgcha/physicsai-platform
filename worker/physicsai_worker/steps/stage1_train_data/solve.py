"""①-4 TD_SOLVE: run별 PBS 제출·회수·등록(phase2 §6.5)."""

from __future__ import annotations

import os
import re
import time
from datetime import datetime, timezone
from typing import Any

from physicsai_core.commands import fwd
from physicsai_core.db.repositories import hpc as hpc_repo
from physicsai_core.db.repositories import train as train_repo
from physicsai_core.errors import StepFailure
from physicsai_core.fileutil import copy_file
from physicsai_core.hpc.command import map_path
from physicsai_core.hpc.gateway import HpcGatewayError, HpcSubmitSpec

from ...signals import EnterWaitingHpc
from .. import _collect
from ._shared import _R, _doe, _match_files, _summary, _write_collected_json


def ts_prep(ctx: Any) -> None:
    s = ctx.settings
    doe = _doe(ctx)
    if doe["status"] != "READY":
        raise StepFailure("INPUT_INVALID", "DOE가 READY가 아닙니다")
    keys = ctx.params.get("run_keys")
    with ctx.ex.engine.connect() as conn:
        runs = train_repo.runs_for_doe(conn, doe["id"])
        attempt = train_repo.count_solve_jobs(conn, doe["id"])
    by_key = {r["run_key"]: r for r in runs}
    if keys:
        unknown = [k for k in keys if k not in by_key]
        if unknown:
            raise StepFailure("INPUT_INVALID", f"DOE에 없는 run: {', '.join(unknown[:10])}")
        targets = list(keys)
    else:
        targets = [r["run_key"] for r in runs if r["state"] in train_repo.RESUBMIT_STATES]
    if not targets:
        raise StepFailure("INPUT_INVALID", "제출할 run이 없습니다")
    if len(targets) > s.train_data.max_runs_per_submit:
        raise StepFailure("INPUT_INVALID", f"한 번에 제출할 수 있는 run은 {s.train_data.max_runs_per_submit}개입니다")
    dirs = [_R(ctx, doe["id"], k) for k in targets]
    ctx.backup([d for d in dirs if os.path.lexists(d)])
    for d in dirs:
        os.makedirs(d, exist_ok=True)
    ctx.patch_result({"doe_id": doe["id"], "run_keys": targets, "attempt": attempt})
    ctx.log(f"제출 대상 run {len(targets)}개 (attempt {attempt})")


def _remote_result_dir(ctx: Any, doe_id: str, run_key: str) -> tuple[str, str | None]:
    """(PBS result_dir, 회수할 로컬 경로 | None=in_place)."""
    t = ctx.settings.hpc.transfer
    if t.collect_mode in ("shared_folder", "drive"):
        sub = f"{ctx.study['folder_name']}/{doe_id}/{run_key}"
        remote = fwd(t.collect_root_remote).rstrip("/") + "/" + sub
        local = os.path.join(os.path.normpath(t.collect_root_local), ctx.study["folder_name"], doe_id, run_key)
        return remote, local
    return map_path(_R(ctx, doe_id, run_key), t.path_map), None


def ts_submit(ctx: Any) -> None:
    gw = ctx.ex.w.hpc
    av = gw.availability()
    if not av.configured:
        raise StepFailure("HPC_SUBMIT_FAILED", f"PBS 연결 안 됨: {av.message}")
    r = ctx.result()
    doe = _doe(ctx)
    hcfg = ctx.settings.hpc
    over = ctx.params.get("hpc") or {}
    with ctx.ex.engine.connect() as conn:
        by_key = {x["run_key"]: x for x in train_repo.runs_for_doe(conn, doe["id"])}
    submitted: list[tuple[str, str]] = []  # (hpc row id, external id)
    keys = r["run_keys"]
    n = len(keys)
    for k, rk in enumerate(keys, 1):
        run = by_key[rk]
        input_dir = ctx.abs(run["input_rel"])
        result_dir, _local = _remote_result_dir(ctx, doe["id"], rk)
        job_name = re.sub(r"[^A-Za-z0-9_\-]", "_", f"{ctx.study['folder_name']}_{doe['id'][:8]}_{rk}_a{r['attempt']}")[:64]
        spec = HpcSubmitSpec(
            job_name=job_name, run_key=rk, study=ctx.study["folder_name"],
            input_file=map_path(os.path.join(input_dir, run["starter_name"]), hcfg.transfer.path_map),
            input_dir=map_path(input_dir, hcfg.transfer.path_map), result_dir=result_dir,
            queue=over.get("queue"), ncpus=over.get("ncpus"), walltime=over.get("walltime"),
        )
        try:
            res = gw.submit(spec)
        except HpcGatewayError as exc:
            ctx.log(f"[FAIL] {rk} 제출 실패: {exc} — 이미 제출한 {len(submitted)}개를 취소합니다")
            for hid, ext in submitted:
                try:
                    gw.cancel(ext)
                except HpcGatewayError as cexc:
                    ctx.add_warning("HPC_CANCEL_FAILED", f"{ext} 취소 실패: {cexc}")

                def cancel_row(c: Any, hid: str = hid) -> None:
                    row = next(h for h in hpc_repo.for_job(c, ctx.ex.job_id) if h["id"] == hid)
                    hpc_repo.update_hpc(c, hid, row["version"], state="CANCELED", finished_at=datetime.now(timezone.utc))
                    train_repo.set_run_state_by_hpc(c, hid, "SOLVE_FAILED")

                ctx.ex.db(cancel_row)
            raise StepFailure("HPC_SUBMIT_FAILED", f"{rk} 제출 실패: {exc}") from None

        def ins(c: Any, rk: str = rk, ext: str = res.external_job_id) -> str:
            hid = hpc_repo.insert(c, job_id=ctx.ex.job_id, step_id=ctx.step["id"], run_key=rk, attempt_no=int(r["attempt"]),
                                  gateway_mode=av.mode, external_job_id=ext, submit_argv=None)
            train_repo.set_run(c, doe["id"], rk, state="SUBMITTED", hpc_job_id=hid, last_job_id=ctx.ex.job_id)
            return hid

        hid = ctx.ex.db(ins)
        submitted.append((hid, res.external_job_id))
        ctx.log(f"PBS 제출 [{k}/{n}] {rk}: {res.external_job_id}")
        ctx.progress(k / n * 100.0, f"제출 {k}/{n}")
    ctx.patch_result({"submitted": n})
    raise EnterWaitingHpc()


def ts_collect(ctx: Any) -> None:
    """COLLECT(phase2 §6.5): 성공 run마다 collect_mode별 회수. run별 실패는 COLLECT_FAILED, 성공 0개면 실패."""
    s = ctx.settings
    r = ctx.result()
    doe = _doe(ctx)
    pats = s.hpc.transfer.collect_patterns
    limit = s.hpc.transfer.max_collect_bytes
    with ctx.ex.engine.connect() as conn:
        hj = [h for h in hpc_repo.for_job(conn, ctx.ex.job_id) if h["attempt_no"] == int(r["attempt"])]
    ok_rows = [h for h in hj if h["state"] == "SUCCEEDED"]
    failed_n = sum(1 for h in hj if h["state"] in ("FAILED", "LOST"))
    pending = {h["run_key"]: h for h in ok_rows}
    src_of = {}
    for rk in pending:
        _remote, local = _remote_result_dir(ctx, doe["id"], rk)
        src_of[rk] = local or _R(ctx, doe["id"], rk)
    collected: dict[str, list[str]] = {}
    failed: dict[str, str] = {}
    for attempt in range(1, 4):
        if not pending:
            break
        a = {rk: _match_files(src_of[rk], pats) for rk in pending}
        time.sleep(_collect.COLLECT_STABLE_INTERVAL_S)
        ctx.checkpoint()
        b = {rk: _match_files(src_of[rk], pats) for rk in pending}
        time.sleep(_collect.COLLECT_STABLE_INTERVAL_S)
        c = {rk: _match_files(src_of[rk], pats) for rk in pending}
        for rk in list(pending):
            if not (a[rk] and a[rk] == b[rk] == c[rk]):
                continue
            big = [n for n, (sz, _m) in c[rk].items() if sz > limit]
            if big:
                failed[rk] = f"회수 파일이 상한을 넘습니다: {big[0]}"
            else:
                dst_root = _R(ctx, doe["id"], rk)
                if src_of[rk] != dst_root:  # shared_folder·drive: 복사(원본은 지우지 않는다)
                    for rel in sorted(c[rk]):
                        copy_file(os.path.join(src_of[rk], *rel.split("/")), os.path.join(dst_root, *rel.split("/")),
                                  checkpoint=ctx.checkpoint)
                collected[rk] = sorted(c[rk])
            pending.pop(rk)
        if pending:
            ctx.log(f"회수 재시도 {attempt}/3: 남은 run {len(pending)}개(결과 파일 없음 또는 아직 바뀌는 중)")
    for rk in pending:
        failed[rk] = "결과 파일 없음 또는 아직 바뀌는 중"

    def rec(c: Any) -> None:
        for h in ok_rows:
            rk = h["run_key"]
            if rk in collected:
                hpc_repo.set_collect_state(c, h["id"], "COLLECTED", collected[rk])
            else:
                hpc_repo.set_collect_state(c, h["id"], "FAILED")
                train_repo.set_run(c, doe["id"], rk, state="COLLECT_FAILED")

    ctx.ex.db(rec)
    for rk, why in sorted(failed.items()):
        ctx.log(f"[COLLECT_FAILED] {rk}: {why}")
    ctx.patch_result({"submitted": len(hj), "failed": failed_n, "collected": len(collected),
                      "collected_runs": sorted(collected), "collect_failed": sorted(failed)})
    if not collected:
        raise StepFailure("COLLECT_FAILED", f"PBS 결과 회수 실패: {next(iter(failed.values()), '회수할 run이 없습니다')}")
    if failed:
        ctx.add_warning("COLLECT_PARTIAL", f"{len(ok_rows)}개 중 {len(failed)}개 회수 실패")


def ts_register(ctx: Any) -> None:
    r = ctx.result()
    doe = _doe(ctx)
    keys = r.get("collected_runs") or []

    def reg(c: Any) -> None:
        for rk in keys:
            rel = f"01_train/results/{doe['id']}/{rk}/"
            train_repo.set_run(c, doe["id"], rk, state="COLLECTED", result_rel=rel,
                               result_summary=_summary(_R(ctx, doe["id"], rk)), last_job_id=ctx.ex.job_id)

    ctx.ex.db(reg)
    _write_collected_json(ctx, doe["id"])
    with ctx.ex.engine.connect() as conn:
        solved = sum(1 for h in hpc_repo.for_job(conn, ctx.ex.job_id)
                     if h["attempt_no"] == int(r["attempt"]) and h["state"] == "SUCCEEDED")
    ctx.patch_result({"submitted": r.get("submitted"), "solved": solved, "failed": r.get("failed", 0), "collected": len(keys)})


HANDLERS = {
    ("TD_SOLVE", "TS_PREP"): ts_prep,
    ("TD_SOLVE", "HPC_SUBMIT"): ts_submit,
    ("TD_SOLVE", "COLLECT"): ts_collect,
    ("TD_SOLVE", "TS_REGISTER"): ts_register,
}
