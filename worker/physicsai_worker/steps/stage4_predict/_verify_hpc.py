"""④ 검증 해석 HPC 공통 헬퍼(phase3 §21.3.7 S16) — PREDICT_VERIFY(§8.10)·FEM_VERIFY(§21.3.5)가 같은 몸체를 쓴다.

`verify.py`의 hpc_submit·_hpc_submit_scx·collect·_collect_scx 몸체를 옮겨 (ctx, input_dir, result_dir, starter, job_name)을
받게 했다. 동작·로그 문구·SUBMISSION_UNKNOWN 규칙(§16.4~§16.6)은 그대로다(run 1개, run_key "verify")."""

from __future__ import annotations

import fnmatch
import os
import time
from collections.abc import Callable
from typing import Any

from physicsai_core.db.repositories import hpc as hpc_repo
from physicsai_core.errors import StepFailure
from physicsai_core.hpc.command import map_path
from physicsai_core.hpc.gateway import HpcGatewayError, HpcSubmitSpec

from ...signals import EnterWaitingHpc
from .. import _collect, _scx

RUN_KEY = "verify"


def submit(ctx: Any, *, input_dir: str, result_dir: str, starter: str, job_name: str, attempt: int,
           scx_job_name: Callable[[str], str]) -> None:
    """HPC_SUBMIT: command(PBS) = HpcSubmitSpec 1건, scx = 새 잡 폴더 `scx_job_name(ts)`에 input_dir 직속 파일을 올리고 제출."""
    gw = ctx.ex.w.hpc
    av = gw.availability()
    if not av.configured:
        raise StepFailure("HPC_SUBMIT_FAILED", f"PBS 연결 안 됨: {av.message}")
    if av.mode == "scx":
        return _submit_scx(ctx, gw, input_dir=input_dir, starter=starter, attempt=attempt, scx_job_name=scx_job_name)
    hcfg = ctx.settings.hpc
    over = ctx.params.get("hpc") or {}
    if over.get("version"):
        ctx.log("command 모드는 hpc.version을 쓰지 않습니다(무시)")
    spec = HpcSubmitSpec(
        job_name=job_name, run_key=RUN_KEY, study=ctx.study["folder_name"],
        input_file=map_path(os.path.join(input_dir, starter), hcfg.transfer.path_map),
        input_dir=map_path(input_dir, hcfg.transfer.path_map),
        result_dir=map_path(result_dir, hcfg.transfer.path_map),
        queue=over.get("queue"), ncpus=over.get("ncpus"), walltime=over.get("walltime"),
    )
    try:
        res = gw.submit(spec)
    except HpcGatewayError as exc:
        raise StepFailure("HPC_SUBMIT_FAILED", str(exc)) from None
    ctx.log(f"PBS 제출: {res.external_job_id}")
    ctx.ex.db(lambda c: hpc_repo.insert(c, job_id=ctx.ex.job_id, step_id=ctx.step["id"], run_key=RUN_KEY,
                                         attempt_no=int(attempt), gateway_mode=av.mode,
                                         external_job_id=res.external_job_id, submit_argv=None))
    raise EnterWaitingHpc()


def _submit_scx(ctx: Any, gw: Any, *, input_dir: str, starter: str, attempt: int, scx_job_name: Callable[[str], str]) -> None:
    """scx(phase3 §16.4): input_dir 직속 파일을 새 잡 폴더에 올리고 제출(run 1개)."""
    health = _scx.check_health(ctx, gw)
    plan = _scx.RunStage(run_key=RUN_KEY, input_dir=input_dir, starter=starter or "",
                         job_name=scx_job_name(_scx.timestamp()),
                         client_ref={"app": "physicsai", "job_id": ctx.ex.job_id, "run_key": RUN_KEY})
    _scx.scan_inputs(ctx, gw, plan, health)
    _scx.plan_remote_dirs(ctx, gw, [plan], health)
    _scx.stage_in(ctx, gw, [plan], int(attempt))
    res = _scx.submit_all(ctx, gw, [plan], lambda _c, _p, _st: None)
    if res.unknown is not None:
        _scx.flag_unknown(ctx, res)
    raise EnterWaitingHpc()


def _collect_scx(ctx: Any, gw: Any, row: dict[str, Any], res_dir: str) -> None:
    try:
        hmax = gw.health().get("max_download_bytes")
    except HpcGatewayError:
        hmax = None
    try:
        got = _scx.collect_run(ctx, gw, row, res_dir, hmax)
    except _scx.CollectFail as exc:
        ctx.ex.db(lambda c: hpc_repo.set_collect_state(c, row["id"], "FAILED"))
        tag = "" if exc.code == "COLLECT_FAILED" else f"({exc.code})"
        raise StepFailure("COLLECT_FAILED", f"SCX 결과 회수 실패{tag}: {exc.message}") from None
    ctx.ex.db(lambda c: hpc_repo.set_collect_state(c, row["id"], "COLLECTED", sorted(got)))
    ctx.patch_result({"collected": sorted(got)})


def collect(ctx: Any, res_dir: str) -> None:
    """1차 in_place: res_dir의 collect_patterns 파일이 존재하고 크기·mtime이 간격 2회 연속 불변.
    scx(phase3 §16.4): relay 다운로드로 res_dir에 받는다(완료 잡 — 안정성 대기 없음)."""
    with ctx.ex.engine.connect() as conn:
        ok = [h for h in hpc_repo.for_job(conn, ctx.ex.job_id) if h["state"] == "SUCCEEDED" and h["gateway_mode"] == "scx"]
    if ok:
        return _collect_scx(ctx, ctx.ex.w.hpc, ok[-1], res_dir)
    pats = ctx.settings.hpc.transfer.collect_patterns
    limit = ctx.settings.hpc.transfer.max_collect_bytes

    def snapshot() -> dict[str, tuple[int, float]]:
        out = {}
        for n in sorted(os.listdir(res_dir)) if os.path.isdir(res_dir) else []:
            p = os.path.join(res_dir, n)
            if os.path.isfile(p) and any(fnmatch.fnmatch(n, pat) for pat in pats):
                st = os.stat(p)
                out[n] = (st.st_size, st.st_mtime)
        return out

    last_err = ""
    for attempt in range(1, 4):
        a = snapshot()
        time.sleep(_collect.COLLECT_STABLE_INTERVAL_S)
        ctx.checkpoint()
        b = snapshot()
        time.sleep(_collect.COLLECT_STABLE_INTERVAL_S)
        c = snapshot()
        if a and a == b == c:
            big = [n for n, (sz, _m) in c.items() if sz > limit]
            if big:
                raise StepFailure("COLLECT_FAILED", f"회수 파일이 상한을 넘습니다: {big[0]}")
            ctx.patch_result({"collected": sorted(c)})
            return
        last_err = "결과 파일 없음" if not c else "결과 파일이 아직 바뀌는 중"
        ctx.log(f"회수 재시도 {attempt}/3: {last_err}")
    raise StepFailure("COLLECT_FAILED", f"PBS 결과 회수 실패: {last_err}")
