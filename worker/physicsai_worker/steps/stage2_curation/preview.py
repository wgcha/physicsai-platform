"""②-1 CU_H3D_PREVIEW·②-3 CU_T01_PREVIEW: h3d·T01 구조 미리보기(phase2 §6.7~§6.10)."""

from __future__ import annotations

import os
from typing import Any

from physicsai_core.stage2_curation import curation as cu
from physicsai_core.errors import StepFailure
from physicsai_core.fileutil import write_json

from .source import _W, _collect, _read_json, _rel


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


HANDLERS = {
    ("CU_H3D_PREVIEW", "CP_PREP"): cp_prep,
    ("CU_H3D_PREVIEW", "HW_PREVIEW_H3D"): hw_preview_h3d,
    ("CU_H3D_PREVIEW", "CP_PARSE"): cp_parse,
    ("CU_T01_PREVIEW", "TP_PREP"): tp_prep,
    ("CU_T01_PREVIEW", "HW_PREVIEW_T01"): hw_preview_t01,
    ("CU_T01_PREVIEW", "TP_PARSE"): tp_parse,
}
