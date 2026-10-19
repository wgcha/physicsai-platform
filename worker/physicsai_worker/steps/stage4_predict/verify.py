"""④ PREDICT_VERIFY(§8.10). 1차 기본 hpc.gateway=none이면 작업 생성 단계에서 409. scx 모드(phase3 §16)는 HPC_SUBMIT·COLLECT 안쪽만 steps/_scx.
HPC_SUBMIT·COLLECT 몸체는 `_verify_hpc`(phase3 §21.3.7 — FEM_VERIFY와 공유, 동작·문구 불변)."""

from __future__ import annotations

import os
import re
from typing import Any

from physicsai_core.commands import fwd
from physicsai_core.db.repositories import hpc as hpc_repo
from physicsai_core.db.repositories import jobs as jobs_repo
from physicsai_core.errors import StepFailure
from physicsai_core.fileutil import copy_file, write_json
from physicsai_core.parsers.name_value import read_name_value_csv

from simdash_adapters.hpc import scx_naming as _scx_naming

from ...signals import StepSkipped
from . import _verify_hpc
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
    """PBS(command) 또는 scx(`04_V-<NNN>_<ts>`) 제출 — 몸체는 `_verify_hpc.submit`(phase3 §21.3.7 공유)."""
    r = ctx.result()
    V = ctx.abs(r["verify_rel"])
    job_name = re.sub(r"[^A-Za-z0-9_\-]", "_", f"{ctx.study['folder_name']}_{ctx.ex.job_id[:8]}_a{r['attempt']}")[:64]

    def scx_name(ts: str) -> str:
        with ctx.ex.engine.connect() as conn:
            v_no = hpc_repo.verify_number(conn, ctx.study["id"], ctx.ex.job_id)
        return _scx_naming.verify_job_name(v_no, ts)

    _verify_hpc.submit(ctx, input_dir=os.path.join(V, "input"), result_dir=os.path.join(V, "result"),
                       starter=r.get("starter") or "", job_name=job_name, attempt=int(r["attempt"]), scx_job_name=scx_name)


def collect(ctx: Any) -> None:
    """1차 in_place 안정성 대기 / scx relay 다운로드 — 몸체는 `_verify_hpc.collect`."""
    _verify_hpc.collect(ctx, os.path.join(ctx.abs(ctx.result()["verify_rel"]), "result"))


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

