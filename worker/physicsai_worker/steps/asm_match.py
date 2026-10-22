"""ASM_MATCH(asm-match.md §6.3): AM_PREP → AM_PARTS(`paicad asm parts`) | AM_CHECK(`paicad asm check`) → AM_REGISTER. 레인 PREVIEW.

params.mode = parts(component 목록·추천) | check(행 검사). 한 작업은 모드에 맞는 step만 실행하고 다른 step은 SKIPPED.
쓰기 주체(AM-C2): 이 작업은 `<study>/asm_match/<id>/parts/` 또는 `check/<seq>/`의 paicad 산출물만 쓴다. `match.json`·`match_rows.json`·`asm_match.json`은 API가 쓴다.
검사 FAIL(rows 있는 asm_check.json)은 **데이터**라 작업은 SUCCEEDED(결과 status=FAIL) — 행·원인 진단은 보고에서 읽는다.
보고 자체가 없거나 rows가 없는 실패(조립 트리 오류·STEP 읽기 실패 등)는 작업 FAILED(failure_code = paicad 코드).
"""

from __future__ import annotations

import os
from typing import Any

from physicsai_core.errors import StepFailure
from physicsai_core.fileutil import sha256_file, write_json
from physicsai_core.geometry import asm_match as am
from physicsai_core.geometry.options import usage_document
from physicsai_core.geometry.view import GLB_CONTENT_TYPE

from ..signals import StepSkipped
from .geometry_native import LocalRunner, effective_opts, read_json, run_paicad

PARTS_KEY, CHECK_KEY = "paicad_asm_parts", "paicad_asm_check"
OPTIONS_JSON = "options_run.json"
GLB_KIND = "GEOM_PREVIEW_FE_GLB"  # 새 kind 없이 기존 FE GLB 종류 재사용(AM-C2, DB CHECK 변경 없음)


def _mdir(ctx: Any) -> str:
    return ctx.abs(f"{am.MATCH_ROOT}/{ctx.params['match_id']}")


def _mode(ctx: Any) -> str:
    return str(ctx.params.get("mode") or "")


def _match(ctx: Any) -> dict[str, Any]:
    m = am.read_match(_mdir(ctx))
    if m is None or m.get("match_id") != ctx.params["match_id"]:
        raise StepFailure("INPUT_INVALID", "조립 매칭 파일(match.json)을 찾을 수 없습니다")
    return m


def _sources(ctx: Any, src: dict[str, Any]) -> tuple[str, str]:
    """(STEP 경로, 피처 파일 경로 — path 출처는 ''). 파일 sha256이 매칭 때와 다르면 INPUT_CHANGED."""
    if src.get("kind") == am.KIND_TRAIN:
        cad, feat = ctx.abs(src["cad_rel"]), ctx.abs(src["features_rel"])
    else:
        cad, feat = str(src.get("cad_path") or ""), ""
    for path, want, what in ((cad, src.get("cad_sha256"), "STEP"), (feat, src.get("features_sha256"), "피처")):
        if not path:
            continue
        if not os.path.isfile(path):
            raise StepFailure("INPUT_CHANGED", f"{what} 파일을 찾을 수 없습니다 — 조립 매칭을 다시 하세요")
        if want and sha256_file(path, ctx.checkpoint) != want:
            raise StepFailure("INPUT_CHANGED", f"{what} 파일이 매칭 이후 바뀌었습니다 — 조립 매칭을 다시 하세요")
    return cad, feat


def _options(ctx: Any, ver: str | None = None) -> str:
    """paicad `--options` 문서: 유효 형상 옵션 + `asm_match` 절(`settings.asm_match`, paicad options.validate_asm)."""
    s = ctx.settings
    a = s.asm_match
    path = os.path.join(_mdir(ctx), OPTIONS_JSON)
    ctx.backup([path])
    write_json(path, {**usage_document(effective_opts(s, None), ver),
                      "asm_match": {"max_parts": int(a.max_parts), "recommend_min_score": float(a.recommend_min_score),
                                    "worst_nodes": int(a.worst_nodes)}})
    return path


def am_prep(ctx: Any) -> None:
    s = ctx.settings
    if getattr(s.commands, PARTS_KEY if _mode(ctx) == "parts" else CHECK_KEY, None) is None or not s.asm_match.enabled:
        raise StepFailure("TEMPLATE_NOT_CONFIGURED", "조립 매칭 명령이 설정되지 않았습니다 — 관리자 설정이 필요합니다")
    match = _match(ctx)
    _sources(ctx, match.get("source") or {})
    assem = str((match.get("assem") or {}).get("path") or "")
    if not os.path.isdir(assem):
        raise StepFailure("INPUT_CHANGED", "조립 폴더를 찾을 수 없습니다")
    if _mode(ctx) == "check":
        rows = os.path.join(am.check_dir(_mdir(ctx), int(ctx.params["seq"])), am.ROWS_JSON)
        if not os.path.isfile(rows) or sha256_file(rows) != ctx.params.get("rows_sha256"):
            raise StepFailure("INPUT_CHANGED", "검사할 매칭 표가 바뀌었습니다 — 다시 검사하세요")
    elif _mode(ctx) != "parts":
        raise StepFailure("INPUT_INVALID", "mode는 parts 또는 check여야 합니다")
    ctx.patch_result({"mode": _mode(ctx), "match_id": ctx.params["match_id"]})


def am_parts(ctx: Any) -> None:
    if _mode(ctx) != "parts":
        raise StepSkipped("component 목록 모드가 아님")
    s = ctx.settings
    mdir, match = _mdir(ctx), _match(ctx)
    src = match.get("source") or {}
    cad, feat = _sources(ctx, src)
    assem = str((match.get("assem") or {}).get("path"))
    renum = os.path.join(assem, s.predict.renum_csv_name)
    out = os.path.join(mdir, am.PARTS_DIR)
    values = {"assem_dir": assem, "features_json": feat, "cad_input": cad if not feat else "",
              "renum_csv": renum if os.path.isfile(renum) else "", "options_json": _options(ctx), "out_dir": out}
    rep = os.path.join(out, "asm_parts.json")
    v = run_paicad(LocalRunner(ctx), s, PARTS_KEY, values, cwd=mdir, report=rep, success=[], backup=[out],
                   log_dir=out, timeout_s=float(s.asm_match.timeout_s))
    v.raise_if_failed()
    doc = read_json(rep, s.geometry.max_report_bytes)
    ctx.patch_result({"engine_version": doc.get("engine_version"), "summary": am.parts_summary(doc)})
    ctx.add_output(rep)


def am_check(ctx: Any) -> None:
    if _mode(ctx) != "check":
        raise StepSkipped("행 검사 모드가 아님")
    s = ctx.settings
    mdir, match = _mdir(ctx), _match(ctx)
    cad, feat = _sources(ctx, match.get("source") or {})
    out = am.check_dir(mdir, int(ctx.params["seq"]))
    rep = os.path.join(out, am.CHECK_JSON)
    values = {"cad_input": cad, "features_json": feat, "assem_dir": str((match.get("assem") or {}).get("path")),
              "match_rows_json": os.path.join(out, am.ROWS_JSON), "options_json": _options(ctx), "out_dir": out}
    v = run_paicad(LocalRunner(ctx), s, CHECK_KEY, values, cwd=mdir, report=rep, success=[], timeout_s=float(s.asm_match.timeout_s),
                   backup=[rep, os.path.join(out, am.CHECK_GLB)], log_dir=out)
    doc = read_json(rep, s.geometry.max_report_bytes) if os.path.isfile(rep) else {}
    if not v.ok and not doc.get("rows"):  # 행 없는 실패 = 작업 실패(조립 트리·입력 오류) — 검사 보고에는 매칭 행이 1개 이상 있다
        v.raise_if_failed()
    ctx.patch_result({"engine_version": doc.get("engine_version"), "summary": am.check_summary(doc)})
    ctx.add_output(rep)


def am_register(ctx: Any) -> None:
    """검사 GLB를 artifact로 등록(§6.3 — `/artifacts/{id}/media`로 서빙). 목록 모드는 등록할 파일 없음."""
    if _mode(ctx) != "check":
        raise StepSkipped("등록할 산출물 없음(component 목록)")
    glb = os.path.join(am.check_dir(_mdir(ctx), int(ctx.params["seq"])), am.CHECK_GLB)
    if not (os.path.isfile(glb) and os.path.getsize(glb) > 0):
        ctx.add_warning("ASM_GLB_MISSING", "검사 3D 파일(match_fe.glb)이 만들어지지 않았습니다")
        return
    ctx.patch_result({"glb_artifact_id": ctx.register_artifact(GLB_KIND, glb, GLB_CONTENT_TYPE)})


HANDLERS = {
    ("ASM_MATCH", "AM_PREP"): am_prep,
    ("ASM_MATCH", "AM_PARTS"): am_parts,
    ("ASM_MATCH", "AM_CHECK"): am_check,
    ("ASM_MATCH", "AM_REGISTER"): am_register,
}
