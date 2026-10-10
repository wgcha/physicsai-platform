"""⑤ OPTIMIZE(phase2 §6.12): OP_PREP → HST_OPTIMIZE → OP_SUMMARY."""

from __future__ import annotations

import os
import re
from typing import Any

from physicsai_core.config import effective_altair
from physicsai_core.db.repositories import optimizations as opt_repo
from physicsai_core.db.repositories import param_sets as ps_repo
from physicsai_core.errors import StepFailure
from physicsai_core.fileutil import copy_file, write_json
from physicsai_core.naming import TPL_NAME
from physicsai_core.stage5_optimize import optimize as opt

from ..common import load_model, verify_model_integrity
from ..launcher import stage_launcher


def _O(ctx: Any) -> str:
    return ctx.abs(f"05_opt/{ctx.workspace_id}")


def _ps(ctx: Any) -> tuple[dict[str, Any], str]:
    with ctx.ex.engine.connect() as conn:
        ps = ps_repo.get(conn, ctx.params["param_set_id"])
    if ps is None or ps["study_id"] != ctx.study["id"]:
        raise StepFailure("INPUT_INVALID", "파라미터 세트를 찾을 수 없습니다")
    return ps, ctx.abs(ps["stored_rel"])


def op_prep(ctx: Any) -> None:
    s = ctx.settings
    p = ctx.params
    m = load_model(ctx, p["model_id"])
    psmdl, _pscfg = verify_model_integrity(ctx, m)
    ps, S = _ps(ctx)
    O = _O(ctx)
    os.makedirs(O, exist_ok=True)
    study_dir = os.path.join(O, p["study_folder"])
    if os.path.lexists(study_dir):
        ctx.backup([study_dir])  # 원본은 확인 후 삭제(GUI:916-924) → 백업 이동
    launcher = stage_launcher(ctx, "optimization", O)
    tcl_src = s.resources.extract_minmax_tcl
    if not tcl_src or not os.path.isfile(tcl_src):
        raise StepFailure("RESOURCE_MISSING", f"resources.extract_minmax_tcl 파일이 없습니다: {tcl_src}")
    tcl = os.path.join(O, os.path.basename(tcl_src))
    ctx.backup([tcl])
    copy_file(tcl_src, tcl)
    hm = s.resources.hypermesh_include_tcl
    if not hm or not os.path.isfile(hm):
        raise StepFailure("RESOURCE_MISSING", f"resources.hypermesh_include_tcl 파일이 없습니다: {hm}")
    for need in (TPL_NAME, os.path.join("cad", ps["cad_file_name"]), os.path.join("radioss_assem", ps["starter_name"])):
        if not os.path.isfile(os.path.join(S, need)):
            raise StepFailure("INPUT_CHANGED", f"파라미터 세트 파일이 없습니다: {need}")
    alt = effective_altair(s)
    cfg = opt.build_run_config(
        altair_home=alt["altair_home"], dir_work=O, study_folder=p["study_folder"],
        cad_param=os.path.join(S, "cad", ps["cad_file_name"]), tpl_file=os.path.join(S, TPL_NAME), hypermesh_tcl=hm,
        radioss_assem_dir=os.path.join(S, "radioss_assem"), starter=os.path.join(S, "radioss_assem", ps["starter_name"]),
        model=psmdl, hyperview_tcl=tcl, simlab_path=alt.get("simlab_path", ""), params=p,
    )
    rj = os.path.join(O, "INPUT_HST_RUN.json")
    ctx.backup([rj])
    write_json(rj, cfg)
    ctx.register_artifact("RUN_CONFIG", rj, "application/json")
    oid = p["optimization_id"]

    def ins(c: Any) -> None:
        if opt_repo.get_opt(c, oid) is None:
            opt_repo.insert_opt(c, {
                "id": oid, "study_id": ctx.study["id"], "job_id": ctx.ex.job_id, "approach": p["approach"],
                "opt_method": p["opt_method"], "max_designs": p["max_designs"], "model_id": m["id"], "param_set_id": ps["id"],
                "study_folder": p["study_folder"], "dir_rel": f"05_opt/{ctx.workspace_id}/", "responses": p["responses"],
                "status": "RUNNING", "created_by": ctx.job["created_by"], "created_by_name": ctx.job["created_by_name"],
            })
        else:
            opt_repo.set_opt(c, oid, status="RUNNING", job_id=ctx.ex.job_id, runs_started=None)

    ctx.ex.db(ins)
    ctx.patch_result({"optimization_id": oid, "launcher_rel": ctx.rel(launcher)})


def hst_optimize(ctx: Any) -> None:
    s = ctx.settings
    p = ctx.params
    r = ctx.result()
    O = _O(ctx)
    rx = re.compile(s.optimize.progress_regex)
    state = {"run": 0, "saved": 0}
    is_opt = p["approach"] == "OPT"
    maxd = int(p["max_designs"])

    def hook(line: str) -> tuple[float | None, str | None] | None:
        m = rx.search(line)
        if not m:
            return None
        n = int(m.group("run"))
        state["run"] = max(state["run"], n)
        label = f"run {state['run']} / {maxd} 시작" if is_opt else f"run {state['run']} 시작"
        return (min(state["run"] / maxd * 100.0, 99.0) if is_opt else None), label

    def poll() -> None:
        if state["run"] != state["saved"]:
            state["saved"] = state["run"]
            ctx.ex.db(lambda c: opt_repo.set_opt(c, p["optimization_id"], runs_started=state["saved"]))
        return None

    alt = effective_altair(s)
    env = dict(s.optimize.env)
    if alt.get("altair_home"):
        env["ALTAIR_HOME"] = alt["altair_home"]
    try:
        ctx.run_local("hst_optimization", {"launcher": ctx.abs(r["launcher_rel"])}, cwd=O, env_add=env,
                      error_patterns=list(s.train_data.hst_log_error_patterns), log_errors_fail=False,
                      line_hook=hook, poll_hook=poll)
    finally:
        poll()
        ctx.patch_result({"log_error_lines": getattr(ctx, "last_error_lines", 0), "runs_started": state["run"] or None})


def op_summary(ctx: Any) -> None:
    s = ctx.settings
    p = ctx.params
    O = _O(ctx)
    root = os.path.join(O, p["study_folder"])
    files = opt.list_files(root, s.optimize.max_listed_files)
    fl = os.path.join(O, "file_list.json")
    ctx.backup([fl])
    write_json(fl, {"root": p["study_folder"], "files": files, "truncated": len(files) >= s.optimize.max_listed_files})
    fl_id = ctx.register_artifact("FILE_LIST", fl, "application/json")
    viewable = [f for f in files if opt.match_glob(f["rel"], s.optimize.viewable_globs) and f["size"] <= s.ui.max_artifact_bytes]
    view_ids = []
    for f in viewable[: s.optimize.max_viewable_files]:
        aid = ctx.register_artifact("OPT_FILE", os.path.join(root, *f["rel"].split("/")))
        if aid:
            view_ids.append(aid)
    data, meta = opt.run_summary_parsers(root, files, s.optimize.summary_parsers, s.ui.max_artifact_bytes)
    sum_id = None
    status = "UNRECOGNIZED"
    if data is not None:
        sp = os.path.join(O, "summary.json")
        ctx.backup([sp])
        write_json(sp, data)
        sum_id = ctx.register_artifact("OPT_SUMMARY", sp, "application/json")
        status = "PARSED"
    ctx.ex.db(lambda c: opt_repo.set_opt(c, p["optimization_id"], status="DONE", summary_status=status, summary_meta=meta,
                                         file_count=len(files)))
    ctx.patch_result({"optimization_id": p["optimization_id"], "summary_status": status, "file_count": len(files),
                      "summary_artifact_id": sum_id, "file_list_artifact_id": fl_id, "viewable_artifact_ids": view_ids})


HANDLERS = {
    ("OPTIMIZE", "OP_PREP"): op_prep,
    ("OPTIMIZE", "HST_OPTIMIZE"): hst_optimize,
    ("OPTIMIZE", "OP_SUMMARY"): op_summary,
}
