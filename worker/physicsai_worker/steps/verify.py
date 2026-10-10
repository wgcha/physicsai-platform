"""④ PREDICT_VERIFY(§8.10). 1차 기본 hpc.gateway=none이면 작업 생성 단계에서 409."""

from __future__ import annotations

import os
import re
from typing import Any

from physicsai_core.commands import fwd
from physicsai_core.db.repositories import hpc as hpc_repo
from physicsai_core.db.repositories import jobs as jobs_repo
from physicsai_core.errors import StepFailure
from physicsai_core.fileutil import copy_file, write_json
from physicsai_core.hpc.command import map_path
from physicsai_core.hpc.gateway import HpcGatewayError, HpcSubmitSpec
from physicsai_core.parsers.name_value import read_name_value_csv

from ..signals import EnterWaitingHpc, StepSkipped
from . import _collect


def _paths(ctx: Any) -> tuple[str, str]:
    r = ctx.result()
    with ctx.ex.engine.connect() as conn:
        pj = jobs_repo.get_job(conn, ctx.params["predict_job_id"])
        if pj is None:
            raise StepFailure("INPUT_INVALID", "원 예측 작업이 없습니다")
        root = jobs_repo.root_job_id(conn, pj)
    P = ctx.abs(f"04_predict/{root}")
    attempt = r.get("attempt")
    if attempt is None:
        vdir = os.path.join(P, "verify")
        nums = [int(n) for n in (os.listdir(vdir) if os.path.isdir(vdir) else []) if n.isdigit()]
        attempt = (max(nums) if nums else 0) + 1
    return P, os.path.join(P, "verify", str(attempt))


def pv_prep(ctx: Any) -> None:
    P, V = _paths(ctx)
    src = os.path.join(P, "INPUT")
    if not os.path.isdir(src):
        raise StepFailure("INPUT_INVALID", "원 예측 작업의 INPUT 폴더가 없습니다")
    os.makedirs(os.path.join(V, "input"), exist_ok=True)
    os.makedirs(os.path.join(V, "result"), exist_ok=True)
    for n in sorted(os.listdir(src)):
        if os.path.isfile(os.path.join(src, n)):
            copy_file(os.path.join(src, n), os.path.join(V, "input", n), checkpoint=ctx.checkpoint)
    with ctx.ex.engine.connect() as conn:
        pj = jobs_repo.get_job(conn, ctx.params["predict_job_id"])
    ctx.patch_result({"attempt": int(os.path.basename(V)), "verify_rel": ctx.rel(V),
                      "starter": (pj["result"] or {}).get("starter")})


def hpc_submit(ctx: Any) -> None:
    gw = ctx.ex.w.hpc
    av = gw.availability()
    if not av.configured:
        raise StepFailure("HPC_SUBMIT_FAILED", f"PBS 연결 안 됨: {av.message}")
    r = ctx.result()
    V = ctx.abs(r["verify_rel"])
    hcfg = ctx.settings.hpc
    over = ctx.params.get("hpc") or {}
    starter = r.get("starter") or ""
    job_name = re.sub(r"[^A-Za-z0-9_\-]", "_", f"{ctx.study['folder_name']}_{ctx.ex.job_id[:8]}_a{r['attempt']}")[:64]
    spec = HpcSubmitSpec(
        job_name=job_name, run_key="verify", study=ctx.study["folder_name"],
        input_file=map_path(os.path.join(V, "input", starter), hcfg.transfer.path_map),
        input_dir=map_path(os.path.join(V, "input"), hcfg.transfer.path_map),
        result_dir=map_path(os.path.join(V, "result"), hcfg.transfer.path_map),
        queue=over.get("queue"), ncpus=over.get("ncpus"), walltime=over.get("walltime"),
    )
    try:
        res = gw.submit(spec)
    except HpcGatewayError as exc:
        raise StepFailure("HPC_SUBMIT_FAILED", str(exc)) from None
    ctx.log(f"PBS 제출: {res.external_job_id}")
    ctx.ex.db(lambda c: hpc_repo.insert(c, job_id=ctx.ex.job_id, step_id=ctx.step["id"], run_key="verify",
                                         attempt_no=int(r["attempt"]), gateway_mode=av.mode,
                                         external_job_id=res.external_job_id, submit_argv=None))
    raise EnterWaitingHpc()


def collect(ctx: Any) -> None:
    """1차 in_place: V/result의 collect_patterns 파일이 존재하고 크기·mtime이 간격 2회 연속 불변."""
    import fnmatch
    import time

    r = ctx.result()
    res_dir = os.path.join(ctx.abs(r["verify_rel"]), "result")
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


def pv_extract(ctx: Any) -> None:
    if ctx.settings.commands.response_extract is None:
        raise StepSkipped("추출 미구성")
    r = ctx.result()
    V = ctx.abs(r["verify_rel"])
    h3ds = sorted(n for n in os.listdir(os.path.join(V, "result")) if n.lower().endswith(".h3d"))
    if not h3ds:
        raise StepFailure("OUTPUT_MISSING", "회수한 h3d가 없습니다")
    from physicsai_core.db.repositories import param_sets as ps_repo

    with ctx.ex.engine.connect() as conn:
        pj = jobs_repo.get_job(conn, ctx.params["predict_job_id"])
        ps = ps_repo.get(conn, (pj["params"] or {}).get("param_set_id"))
    S = ctx.abs(ps["stored_rel"])
    h3d = os.path.join(V, "result", h3ds[0])
    out = os.path.join(V, "responses_verify.csv")
    ctx.run_local("response_extract", {"responses_json": os.path.join(S, "responses.json"), "pred_h3d": h3d,
                                        "pred_h3d_fwd": fwd(h3d), "out_csv": out, "work_dir": V}, cwd=V, outputs_to_backup=[out])


def pv_table(ctx: Any) -> None:
    r = ctx.result()
    V = ctx.abs(r["verify_rel"])
    vals = read_name_value_csv(os.path.join(V, "responses_verify.csv"))
    out = os.path.join(V, "responses_verify.json")
    write_json(out, {"verify_values": vals})
    ctx.patch_result({"verify_values": vals})


HANDLERS = {
    ("PREDICT_VERIFY", "PV_PREP"): pv_prep,
    ("PREDICT_VERIFY", "HPC_SUBMIT"): hpc_submit,
    ("PREDICT_VERIFY", "COLLECT"): collect,
    ("PREDICT_VERIFY", "PV_EXTRACT"): pv_extract,
    ("PREDICT_VERIFY", "PV_TABLE"): pv_table,
}

