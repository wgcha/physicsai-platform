"""①-1 TD_EXTRACT_PARAMS의 native 분기(geometry-engine.md §7.3.1): STEP → `paicad extract`.

TX_PREP: 확장자 ∈ geometry.step_extensions, CAD 사본·sha256, 옵션 사용값. SIMLAB_EXTRACT: `paicad_extract`(런처 없음).
TX_PARSE의 추가 기록(train_setups.engine·features_rel, 피처 PNG 산출물)은 `after_parse`.
"""

from __future__ import annotations

import os
from typing import Any

from physicsai_core.db.repositories import train as train_repo
from physicsai_core.errors import StepFailure
from physicsai_core.fileutil import copy_file, sha256_file, write_json
from physicsai_core.geometry.extract_filter import STATS_JSON, apply_to_options
from physicsai_core.geometry.options import effective_options, usage_document
from physicsai_core.geometry.shell_options import effective_shell_options
from physicsai_core.paths import PathError, allowed_roots, check_user_path

from ..common import path_failure
from ..geometry_native import LocalRunner, engine_version, finish_extract, run_paicad

FEATURES_JSON = "parameter_features.json"
SHELL_FEATURES_JSON = "shell_features.json"
EXTRACTED_XML = "parameter_extracted.xml"


def _X(ctx: Any) -> str:
    return ctx.abs(f"01_train/extract/{ctx.workspace_id}")


def tx_prep(ctx: Any) -> None:
    s = ctx.settings
    try:
        cp = check_user_path(ctx.params["cad_path"], allowed_roots(s, imports=True), expect="file")
    except PathError as exc:
        raise path_failure(exc) from None
    name = os.path.basename(cp.path)
    if os.path.splitext(name)[1].lower() not in [e.lower() for e in s.geometry.step_extensions]:
        raise StepFailure("INPUT_INVALID", f"STEP 확장자가 허용 목록({s.geometry.step_extensions})에 없습니다")
    dst = ctx.abs(f"01_train/cad/{name}")
    if os.path.realpath(dst) != os.path.realpath(cp.path):
        ctx.backup([dst])
        copy_file(cp.path, dst, checkpoint=ctx.checkpoint)
    sha = sha256_file(dst, ctx.checkpoint)
    ver, ocp, shown = engine_version(ctx)
    ctx.log(f"형상 엔진: {shown}")
    kind = _kind(ctx)
    if kind == "shell":  # shell-morph.md §8.2: ①-1 쉘 추출(조립 폴더 없음 → fixed_overlap unknown)
        opts, probs = effective_shell_options(s.geometry.shell_defaults, None)
        key = "geometry.shell_defaults"
    else:
        opts, probs = effective_options(s.geometry.defaults, None)
        key = "geometry.defaults"
    if probs:
        raise StepFailure("CONFIG_INVALID", f"{key} 값이 범위를 벗어납니다: " + "; ".join(p["key"] for p in probs[:5]))
    X = _X(ctx)
    os.makedirs(X, exist_ok=True)
    oj = os.path.join(X, "options.json")
    ctx.backup([oj])
    if kind != "shell":  # extract-filter.md §6.2: extract.filter(types+조건)·draft_max_deg(job > defaults > paicad 기본). 없으면 현행 파일과 같음
        opts = apply_to_options(opts, ctx.params.get("extract_filter"))
    write_json(oj, usage_document(opts, ver))
    ctx.patch_result({"cad_file_name": name, "cad_sha256": sha, "engine": "native", "engine_version": ver, "ocp_version": ocp,
                      "kind": kind})


def _kind(ctx: Any) -> str:
    return "shell" if ctx.params.get("kind") == "shell" else "solid"


def extract(ctx: Any) -> None:
    s = ctx.settings
    r = ctx.result()
    X = _X(ctx)
    if _kind(ctx) == "shell":
        from ..geometry_shell import extract as shell_extract

        v = shell_extract(LocalRunner(ctx), s, cad_input=ctx.abs(f"01_train/cad/{r['cad_file_name']}"), out_dir=X,
                          options_json=os.path.join(X, "options.json"), assem_dir=None, body_map=None, cwd=X)
        v.raise_if_failed()
        ctx.add_output(os.path.join(X, EXTRACTED_XML))
        ctx.add_output(os.path.join(X, SHELL_FEATURES_JSON))
        return
    xml, fj = os.path.join(X, EXTRACTED_XML), os.path.join(X, FEATURES_JSON)
    values = {"cad_input": ctx.abs(f"01_train/cad/{r['cad_file_name']}"), "options_json": os.path.join(X, "options.json"),
              "out_dir": X}  # renum_csv 없음 → 인자 쌍째 생략(§7.3.1)
    v = run_paicad(LocalRunner(ctx), s, "paicad_extract", values, cwd=X, report=fj, success=[xml],
                   backup=[xml, fj, os.path.join(X, STATS_JSON), os.path.join(X, "features"), os.path.join(X, "paicad.log")])
    finish_extract(ctx, v, os.path.join(X, STATS_JSON), bool(ctx.params.get("extract_filter")))
    ctx.add_output(xml)
    ctx.add_output(fj)


def adjust_params(ctx: Any, params: list[dict[str, Any]]) -> None:
    """양면 접촉(`ref.locked`) 피처는 기본 `use=false`(§4.3) — 사용자가 파라미터 표에서 켤 수 있다."""
    from ..geometry_native import read_json

    if _kind(ctx) == "shell":  # 체결 영역 겹침(use_default=false)·기본 대상 component 밖 비드는 기본 use=false(SM §4.4·§12 Q1)
        from physicsai_core.geometry.shell_native import shell_rows

        doc = read_json(os.path.join(_X(ctx), SHELL_FEATURES_JSON), ctx.settings.geometry.max_report_bytes)
        rows, _w = shell_rows(doc, ctx.settings.shell.default_component)
        on = {r["name"] for r in rows if r.get("use", True)}
        for p in params:
            if p.get("name") not in on:
                p["use"] = False
        return
    doc = read_json(os.path.join(_X(ctx), FEATURES_JSON), ctx.settings.geometry.max_report_bytes)
    locked = {f["name"] for f in doc.get("features", []) if isinstance(f, dict) and isinstance(f.get("name"), str)
              and isinstance(f.get("ref"), dict) and f["ref"].get("locked")}
    for p in params:
        if p.get("name") in locked:
            p["use"] = False


def after_parse(ctx: Any, params: list[dict[str, Any]]) -> None:
    """TX_PARSE 뒤: train_setups.engine='native'·features_rel, 하이라이트 PNG를 FEATURE_PNG 산출물로 등록."""
    X = _X(ctx)
    rel = ctx.rel(os.path.join(X, SHELL_FEATURES_JSON if _kind(ctx) == "shell" else FEATURES_JSON))
    ver = ctx.result().get("engine_version")
    ctx.ex.db(lambda c: train_repo.update_setup(c, ctx.study["id"], None, engine="native", features_rel=rel))
    pngs = os.path.join(X, "features")
    n = 0
    if os.path.isdir(pngs):
        for f in sorted(os.listdir(pngs)):
            p = os.path.join(pngs, f)
            if f.lower().endswith(".png") and os.path.isfile(p):
                ctx.register_artifact("FEATURE_PNG", p, "image/png")
                n += 1
    ctx.patch_result({"engine": "native", "engine_version": ver, "features_rel": rel, "feature_png_count": n})


def tx_view(ctx: Any) -> None:
    """TX_VIEW(geometry-view.md §6.9): ①-1 공칭 3D 뷰. `X/view/`(X = 01_train/extract/<job>/), 쉘은 고정 정보 없음(--fixed-dir 생략).
    실패·명령 null은 경고 VIEW_EXPORT_FAILED(작업 계속)."""
    from ..geometry_view import export_view, register_view_artifacts

    r = ctx.result()
    X = _X(ctx)
    kind = _kind(ctx)
    view = export_view(ctx, kind=kind, cad_input=ctx.abs(f"01_train/cad/{r['cad_file_name']}"),
                       features=os.path.join(X, SHELL_FEATURES_JSON if kind == "shell" else FEATURES_JSON),
                       out_dir=os.path.join(X, "view"), fixed_dir=None, body_map=None, cwd=X, engine_version=r.get("engine_version"))
    arts = register_view_artifacts(ctx, os.path.join(X, "view")) if view.get("status") == "READY" else {}
    ctx.patch_result({"view": {**view, **arts}})
