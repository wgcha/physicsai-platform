"""②-4 CU_T01_CURVES: T01 곡선 추출(phase2 §6.7~§6.10)."""

from __future__ import annotations

import os
from typing import Any

from physicsai_core.db.repositories import train as train_repo
from physicsai_core.errors import StepFailure
from physicsai_core.fileutil import write_json
from physicsai_core.stage2_curation import curation as cu

from .source import _C, _collect, _finish_curation, _rel


def tc_prep(ctx: Any) -> None:
    cid, C = _C(ctx)
    root, files = _collect(ctx, "T01")
    excl = {e.replace("\\", "/") for e in (ctx.params.get("exclude_files") or [])}
    files = [f for f in files if _rel(root, f) not in excl]
    if not files:
        raise StepFailure("INPUT_INVALID", "제외 후 대상 T01이 없습니다")
    names = cu.run_folder_names(root, files)
    out_root = os.path.join(C, "CURVES")
    if os.path.lexists(out_root):
        ctx.backup([out_root])
    data = cu.curve_input_json(ctx.params["curves"], list(zip(files, names)), out_root)
    for j in data["jobs"]:
        os.makedirs(os.path.dirname(j["outputFile"]), exist_ok=True)
    cfg = os.path.join(C, "work", "INPUT_CURATE_CURVE.json")
    ctx.backup([cfg])
    write_json(cfg, data)
    ctx.register_artifact("CURATION_CFG", cfg, "application/json")
    run_keys: set[str] = set()
    if ctx.params["source"]["kind"] == "TRAIN_DOE":
        with ctx.ex.engine.connect() as conn:
            run_keys = {x["run_key"] for x in train_repo.runs_for_doe(conn, ctx.params["source"]["doe_id"])}
    targets = [{"input_rel": _rel(root, f), "run_folder": rf, "run_key": cu.run_key_of(root, f, run_keys),
                "output": j["outputFile"]} for f, rf, j in zip(files, names, data["jobs"])]
    ctx.patch_result({"curation_id": cid, "targets": targets, "cfg_rel": ctx.rel(cfg)})


def hw_curve_export(ctx: Any) -> None:
    _cid, C = _C(ctx)
    cfg = ctx.abs(ctx.result()["cfg_rel"])
    ctx.run_local("t01_curve_export", {"curate_tcl": ctx.settings.resources.curate_hg_tcl, "config_json": cfg},
                  cwd=os.path.join(C, "work"), check_log_errors=False)


def tc_register(ctx: Any) -> None:
    cid, C = _C(ctx)
    items = []
    for t in ctx.result()["targets"]:
        out = os.path.normpath(t["output"])
        ok = os.path.isfile(out)
        items.append({"run_folder": t["run_folder"], "run_key": t.get("run_key"), "input_rel": t["input_rel"],
                      "output_rel": _rel(C, out) if ok else None, "size": os.path.getsize(out) if ok else None, "ok": ok,
                      "exit_code": None})
    if not any(x["ok"] for x in items):
        raise StepFailure("OUTPUT_MISSING", "곡선 파일이 하나도 만들어지지 않았습니다")
    if not all(x["ok"] for x in items):
        ctx.add_warning("PARTIAL_OUTPUT", f"{len(items)}개 중 {sum(1 for x in items if not x['ok'])}개 출력 없음")
    _finish_curation(ctx, cid, C, items, "CURVES")
    first = next(x for x in items if x["ok"])
    p = os.path.join(C, *first["output_rel"].split("/"))
    aid = None
    if os.path.getsize(p) <= ctx.settings.ui.max_artifact_bytes:
        aid = ctx.register_artifact("CURVE_JSON", p, "application/json")
    ctx.patch_result({"curve_artifact_id": aid})


HANDLERS = {
    ("CU_T01_CURVES", "TC_PREP"): tc_prep,
    ("CU_T01_CURVES", "HW_CURVE_EXPORT"): hw_curve_export,
    ("CU_T01_CURVES", "TC_REGISTER"): tc_register,
}
