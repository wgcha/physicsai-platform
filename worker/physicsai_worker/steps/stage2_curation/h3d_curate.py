"""②-2 CU_H3D_CURATE: hvtrans 큐레이션(phase2 §6.7~§6.10)."""

from __future__ import annotations

import os
from typing import Any

from physicsai_core.stage2_curation import curation as cu
from physicsai_core.db.repositories import jobs as jobs_repo
from physicsai_core.db.repositories import train as train_repo
from physicsai_core.errors import StepFailure
from physicsai_core.fileutil import write_text

from .source import _C, _collect, _finish_curation, _read_json, _rel


def _preview_summary(ctx: Any) -> tuple[dict[str, Any], dict[str, list[str]]]:
    with ctx.ex.engine.connect() as conn:
        pj = jobs_repo.get_job(conn, ctx.params["preview_job_id"])
        root = jobs_repo.root_job_id(conn, pj) if pj else None
    if pj is None or pj["study_id"] != ctx.study["id"] or pj["state"] != "SUCCEEDED":
        raise StepFailure("INPUT_INVALID", "h3d 미리보기 작업이 없습니다")
    W = ctx.abs(f"02_preview/{root}")
    summary = _read_json(os.path.join(W, "preview_summary.json"), ctx.settings.ui.max_artifact_bytes)
    raw = _read_json(os.path.join(W, "PREVIEW_H3D.json"), ctx.settings.ui.max_artifact_bytes)
    return summary, {k: [str(c) for c in v] for k, v in (raw.get("datatype_info") or {}).items()}


def hc_prep(ctx: Any) -> None:
    cid, C = _C(ctx)
    summary, dti = _preview_summary(ctx)
    sel = ctx.params["selection"]
    probs = cu.validate_selection(sel, summary)
    if probs:
        raise StepFailure("INPUT_INVALID", "선택이 미리보기와 맞지 않습니다: " + "; ".join(p["message"] for p in probs[:5]))
    work = os.path.join(C, "work")
    cfg = os.path.join(work, "CURATE_H3D.cfg")
    ctx.backup([cfg])
    write_text(cfg, cu.hvtrans_cfg(sel, dti, int(summary["num_time_step"])))
    ctx.register_artifact("CURATION_CFG", cfg, "text/plain")
    root, files = _collect(ctx, "H3D")
    excl = {e.replace("\\", "/") for e in (ctx.params.get("exclude_files") or [])}
    files = [f for f in files if _rel(root, f) not in excl]
    if not files:
        raise StepFailure("INPUT_INVALID", "제외 후 대상 h3d가 없습니다")
    names = cu.run_folder_names(root, files)
    out_root = os.path.join(C, "CURATED_DATA")
    if os.path.lexists(out_root):
        ctx.backup([out_root])  # 원본 __clear_folder_contents(삭제) 대신 백업 이동
    run_keys: set[str] = set()
    if ctx.params["source"]["kind"] == "TRAIN_DOE":
        with ctx.ex.engine.connect() as conn:
            run_keys = {x["run_key"] for x in train_repo.runs_for_doe(conn, ctx.params["source"]["doe_id"])}
    targets = []
    for f, rf in zip(files, names):
        targets.append({"input": f, "input_rel": _rel(root, f), "run_folder": rf, "run_key": cu.run_key_of(root, f, run_keys),
                        "output": os.path.join(out_root, rf, os.path.basename(f))})
    ctx.patch_result({"curation_id": cid, "targets": targets, "cfg_rel": ctx.rel(cfg), "source_root": root})


def hvtrans_curate(ctx: Any) -> None:
    r = ctx.result()
    _cid, C = _C(ctx)
    work = os.path.join(C, "work")
    cfg = ctx.abs(r["cfg_rel"])
    tg = []
    for t in r["targets"]:
        os.makedirs(os.path.dirname(t["output"]), exist_ok=True)
        tg.append({"target_id": t["input_rel"], "out": t["output"],
                   "values": {"cfg": cfg, "h3d": t["input"], "out_h3d": t["output"]}})
    res = ctx.run_fanout("hvtrans_curate", tg, cwd=work, success=lambda t: os.path.isfile(t["out"]))
    failed = {f["target_id"]: f for f in res["failed"]}
    ctx.patch_result({"failed_targets": failed})


def hc_register(ctx: Any) -> None:
    r = ctx.result()
    cid, C = _C(ctx)
    failed = r.get("failed_targets") or {}
    items = []
    for t in r["targets"]:
        ok = t["input_rel"] not in failed and os.path.isfile(t["output"])
        items.append({"run_folder": t["run_folder"], "run_key": t.get("run_key"), "input_rel": t["input_rel"],
                      "output_rel": _rel(C, t["output"]) if ok else None,
                      "size": os.path.getsize(t["output"]) if ok else None, "ok": ok,
                      "exit_code": (failed.get(t["input_rel"]) or {}).get("exit_code")})
    _finish_curation(ctx, cid, C, items, "CURATED_DATA")


HANDLERS = {
    ("CU_H3D_CURATE", "HC_PREP"): hc_prep,
    ("CU_H3D_CURATE", "HVTRANS_CURATE"): hvtrans_curate,
    ("CU_H3D_CURATE", "HC_REGISTER"): hc_register,
}
