"""② 데이터 정리(phase2 §6.7~§6.10): CU_H3D_PREVIEW, CU_H3D_CURATE, CU_T01_PREVIEW, CU_T01_CURVES."""

from __future__ import annotations

import json
import os
from typing import Any

from physicsai_core import curation as cu
from physicsai_core.db.repositories import curations as cur_repo
from physicsai_core.db.repositories import jobs as jobs_repo
from physicsai_core.db.repositories import train as train_repo
from physicsai_core.errors import StepFailure
from physicsai_core.fileutil import write_json, write_text
from physicsai_core.paths import PathError, check_dataset_input, check_user_path, display_path

from .common import path_failure


def source_root(ctx: Any, source: dict[str, Any]) -> str:
    """원천 루트(§4.4). FOLDER는 1차 §17.3 검사 + B23 확장 목록 거부."""
    rel = cu.source_root_rel(source)
    if rel is not None:
        root = ctx.abs(rel)
        if not os.path.isdir(root):
            raise StepFailure("INPUT_INVALID", f"원천 폴더가 없습니다: {rel}")
        return root
    try:
        cp = check_user_path(source.get("path"), [ctx.settings.storage.ai_root])
        check_dataset_input(cp.path, ctx.settings.storage.ai_root)
    except PathError as exc:
        raise path_failure(exc) from None
    return cp.path


def _collect(ctx: Any, kind: str) -> tuple[str, list[str]]:
    root = source_root(ctx, ctx.params["source"])
    files = cu.collect_files(root, kind, ctx.settings.curation.max_files)
    if not files:
        raise StepFailure("INPUT_INVALID", f"원천에 {'h3d' if kind == 'H3D' else 'T01'} 파일이 없습니다")
    return root, files


def _W(ctx: Any) -> str:
    return ctx.abs(f"02_preview/{ctx.workspace_id}")


def _rel(root: str, p: str) -> str:
    return os.path.relpath(p, root).replace(os.sep, "/")


def _prep_preview(ctx: Any, kind: str) -> None:
    root, files = _collect(ctx, kind)
    sample = ctx.params.get("sample_file")
    if sample:
        cand = [f for f in files if _rel(root, f) == sample.replace("\\", "/")]
        if not cand:
            raise StepFailure("INPUT_INVALID", f"대표 파일이 원천에 없습니다: {sample}")
        target = cand[0]
    else:
        target = files[0]
    os.makedirs(_W(ctx), exist_ok=True)
    ctx.patch_result({"sample_file": _rel(root, target), "sample_abs": target, "source_file_count": len(files)})


def _read_json(path: str, max_bytes: int) -> Any:
    if not os.path.isfile(path):
        raise StepFailure("OUTPUT_MISSING", f"{os.path.basename(path)}이 만들어지지 않았습니다")
    if os.path.getsize(path) > max_bytes:
        raise StepFailure("OUTPUT_MISSING", f"{os.path.basename(path)}이 크기 상한을 넘습니다")
    try:
        with open(path, encoding="utf-8-sig") as fh:
            return json.load(fh)
    except ValueError as exc:
        raise StepFailure("OUTPUT_MISSING", f"{os.path.basename(path)} 형식 오류: {exc}") from None


# ---- ②-1 h3d 미리보기 --------------------------------------------------------------


def cp_prep(ctx: Any) -> None:
    _prep_preview(ctx, "H3D")


def hw_preview_h3d(ctx: Any) -> None:
    W = _W(ctx)
    out = os.path.join(W, "PREVIEW_H3D.json")  # 원본 GUI:51
    ctx.run_local("h3d_preview", {"preview_tcl": ctx.settings.resources.preview_h3d_tcl, "h3d": ctx.result()["sample_abs"],
                                  "result_json": out}, cwd=W, outputs_to_backup=[out], check_log_errors=False)
    if not os.path.isfile(out):
        raise StepFailure("OUTPUT_MISSING", "PREVIEW_H3D.json이 만들어지지 않았습니다")


def cp_parse(ctx: Any) -> None:
    W = _W(ctx)
    raw_path = os.path.join(W, "PREVIEW_H3D.json")
    data = _read_json(raw_path, ctx.settings.ui.max_artifact_bytes)
    summary, problems = cu.validate_h3d_preview(data)
    if problems or summary is None:
        raise StepFailure("OUTPUT_MISSING", "PREVIEW_H3D.json 형식이 올바르지 않습니다: " + "; ".join(problems))
    r = ctx.result()
    root, files = _collect(ctx, "H3D")
    names = cu.run_folder_names(root, files)
    summary.update({"sample_file": r["sample_file"], "source_file_count": r["source_file_count"],
                    # ②-2 파일 목록 체크용(원천 루트 기준 상대경로 + run 폴더 이름) — 파일에만, DB에는 개수만
                    "files": [{"rel": _rel(root, f), "run_folder": rf, "size": os.path.getsize(f)} for f, rf in zip(files, names)]})
    sp = os.path.join(W, "preview_summary.json")
    ctx.backup([sp])
    write_json(sp, summary)
    a1 = ctx.register_artifact("PREVIEW_JSON", raw_path, "application/json")
    a2 = ctx.register_artifact("PREVIEW_JSON", sp, "application/json")
    pc = {k: len(v) for k, v in summary["parts"].items()}
    ctx.patch_result({"sample_file": r["sample_file"], "datatype_count": len(summary["datatypes"]), "part_counts": pc,
                      "num_time_step": summary["num_time_step"], "source_file_count": r["source_file_count"],
                      "preview_json_artifact_id": a1, "preview_summary_artifact_id": a2})


# ---- ②-2 h3d 큐레이션 ---------------------------------------------------------------


def _C(ctx: Any) -> tuple[str, str]:
    cid = ctx.result().get("curation_id") or ctx.params.get("curation_id")
    if not cid:
        raise StepFailure("INTERNAL_ERROR", "curation_id가 없습니다")
    return cid, ctx.abs(f"02_curated/{cid}")


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


def _finish_curation(ctx: Any, cid: str, C: str, items: list[dict[str, Any]], out_dir: str) -> None:
    fl = os.path.join(C, "file_list.json")
    ctx.backup([fl])
    write_json(fl, items)
    ctx.register_artifact("FILE_LIST", fl, "application/json")
    ok_n = sum(1 for x in items if x["ok"])
    missing: list[str] = []
    src = ctx.params["source"]
    if src["kind"] == "TRAIN_DOE":
        with ctx.ex.engine.connect() as conn:
            keys = [x["run_key"] for x in train_repo.runs_for_doe(conn, src["doe_id"])]
        have = {x.get("run_key") for x in items if x["ok"]}
        missing = [k for k in keys if k not in have][:5000]
    ctx.ex.db(lambda c: cur_repo.set_curation(c, cid, status="READY", target_count=len(items), ok_count=ok_n,
                                              failed_count=len(items) - ok_n, missing_runs=missing))
    ctx.patch_result({"curation_id": cid, "target_count": len(items), "ok_count": ok_n, "failed_count": len(items) - ok_n,
                      "missing_run_count": len(missing),
                      "output_display_path": display_path(ctx.settings.storage.ai_root, ctx.study["folder_name"],
                                                          f"02_curated/{cid}/{out_dir}")})


# ---- ②-3 T01 미리보기 ---------------------------------------------------------------


def tp_prep(ctx: Any) -> None:
    _prep_preview(ctx, "T01")


def hw_preview_t01(ctx: Any) -> None:
    W = _W(ctx)
    out = os.path.join(W, "PREVIEW_T01.json")  # 원본 GUI:37
    ctx.run_local("t01_preview", {"preview_tcl": ctx.settings.resources.preview_hg_tcl, "t01": ctx.result()["sample_abs"],
                                  "result_json": out}, cwd=W, outputs_to_backup=[out], check_log_errors=False)
    if not os.path.isfile(out):
        raise StepFailure("OUTPUT_MISSING", "PREVIEW_T01.json이 만들어지지 않았습니다")


def tp_parse(ctx: Any) -> None:
    W = _W(ctx)
    raw_path = os.path.join(W, "PREVIEW_T01.json")
    data = _read_json(raw_path, ctx.settings.ui.max_artifact_bytes)
    norm, problems = cu.validate_t01_preview(data)
    if problems or norm is None:
        raise StepFailure("OUTPUT_MISSING", "PREVIEW_T01.json 형식이 올바르지 않습니다: " + "; ".join(problems))
    aid = ctx.register_artifact("PREVIEW_JSON", raw_path, "application/json")
    r = ctx.result()
    ctx.patch_result({"sample_file": r["sample_file"], "type_count": len(norm["dataTypes"]),
                      "source_file_count": r["source_file_count"], "preview_json_artifact_id": aid})


# ---- ②-4 T01 곡선 추출 -------------------------------------------------------------


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
    ("CU_H3D_PREVIEW", "CP_PREP"): cp_prep,
    ("CU_H3D_PREVIEW", "HW_PREVIEW_H3D"): hw_preview_h3d,
    ("CU_H3D_PREVIEW", "CP_PARSE"): cp_parse,
    ("CU_H3D_CURATE", "HC_PREP"): hc_prep,
    ("CU_H3D_CURATE", "HVTRANS_CURATE"): hvtrans_curate,
    ("CU_H3D_CURATE", "HC_REGISTER"): hc_register,
    ("CU_T01_PREVIEW", "TP_PREP"): tp_prep,
    ("CU_T01_PREVIEW", "HW_PREVIEW_T01"): hw_preview_t01,
    ("CU_T01_PREVIEW", "TP_PARSE"): tp_parse,
    ("CU_T01_CURVES", "TC_PREP"): tc_prep,
    ("CU_T01_CURVES", "HW_CURVE_EXPORT"): hw_curve_export,
    ("CU_T01_CURVES", "TC_REGISTER"): tc_register,
}
