"""④ PREDICT_VERIFY(§8.10). 1차 기본 hpc.gateway=none이면 작업 생성 단계에서 409. scx 모드(phase3 §16)는 HPC_SUBMIT·COLLECT 안쪽만 steps/_scx."""

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

from simdash_adapters.hpc import scx_naming as _scx_naming

from ...signals import EnterWaitingHpc, StepSkipped
from .. import _collect, _scx
from ..response_tcl import extract_in_folder, single_h3d, uses_tcl, warn_reasons, write_values_csv


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
    if av.mode == "scx":
        return _hpc_submit_scx(ctx, gw)
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


def _hpc_submit_scx(ctx: Any, gw: Any) -> None:
    """scx(phase3 §16.4): V/input 직속 파일을 새 잡 폴더 `04_V-<NNN>_<ts>`에 올리고 제출(run 1개)."""
    r = ctx.result()
    V = ctx.abs(r["verify_rel"])
    health = _scx.check_health(ctx, gw)
    with ctx.ex.engine.connect() as conn:
        v_no = hpc_repo.verify_number(conn, ctx.study["id"], ctx.ex.job_id)
    plan = _scx.RunStage(run_key="verify", input_dir=os.path.join(V, "input"), starter=r.get("starter") or "",
                         job_name=_scx_naming.verify_job_name(v_no, _scx.timestamp()),
                         client_ref={"app": "physicsai", "job_id": ctx.ex.job_id, "run_key": "verify"})
    _scx.scan_inputs(ctx, gw, plan, health)
    _scx.plan_remote_dirs(ctx, gw, [plan], health)
    _scx.stage_in(ctx, gw, [plan], int(r["attempt"]))
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


def collect(ctx: Any) -> None:
    """1차 in_place: V/result의 collect_patterns 파일이 존재하고 크기·mtime이 간격 2회 연속 불변.
    scx(phase3 §16.4): relay 다운로드로 V/result에 받는다(완료 잡 — 안정성 대기 없음)."""
    import fnmatch
    import time

    r = ctx.result()
    res_dir = os.path.join(ctx.abs(r["verify_rel"]), "result")
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
        psid = (pj["params"] or {}).get("param_set_id")
        ps = ps_repo.get(conn, psid) if psid else None
    if ps is None:  # phase3 §11.5: 준비된 입력 예측은 세트가 없을 수 있다
        raise StepSkipped("응답 정의 없음")
    S = ctx.abs(ps["stored_rel"])
    out = os.path.join(V, "responses_verify.csv")
    if uses_tcl(ctx):
        return _pv_extract_tcl(ctx, ps, os.path.join(V, "result"), out)
    h3d = os.path.join(V, "result", h3ds[0])
    ctx.run_local("response_extract", {"responses_json": os.path.join(S, "responses.json"), "pred_h3d": h3d,
                                        "pred_h3d_fwd": fwd(h3d), "out_csv": out, "work_dir": V}, cwd=V, outputs_to_backup=[out])


def _pv_extract_tcl(ctx: Any, ps: dict[str, Any], folder: str, out: str) -> None:
    """PV_EXTRACT 새 방식(phase3 §14.6): 회수 폴더 h3d가 정확히 1개일 때만. 추출 실패는 경고(값 비움)."""
    from physicsai_worker.limiter.base import LimiterError

    responses = list(ps.get("responses") or [])
    if not responses:
        raise StepSkipped("응답 정의 없음")
    h3d, names = single_h3d(folder)
    if h3d is None:
        ctx.add_warning("RESP_H3D_AMBIGUOUS", f"검증 응답 추출: 회수 폴더 h3d가 정확히 1개가 아닙니다({len(names)}개) — 건너뜁니다")
        raise StepSkipped("h3d가 여러 개 — 응답 추출 건너뜀")
    try:
        values, reasons = extract_in_folder(ctx, responses, folder, h3d)
    except (StepFailure, LimiterError) as exc:
        ctx.add_warning("RESPONSE_EXTRACT_FAILED", f"검증 응답 추출 실패({exc.code}): {exc.message}"[:480])
        values = {r["name"]: None for r in responses}
    else:
        warn_reasons(ctx, reasons, "검증 ")
    write_values_csv(ctx, out, values)


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

