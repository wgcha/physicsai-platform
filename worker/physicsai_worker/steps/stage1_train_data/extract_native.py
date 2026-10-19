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
from physicsai_core.geometry.options import effective_options, usage_document
from physicsai_core.paths import PathError, allowed_roots, check_user_path

from ..common import path_failure
from ..geometry_native import LocalRunner, engine_version, run_paicad

FEATURES_JSON = "parameter_features.json"
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
    opts, probs = effective_options(s.geometry.defaults, None)
    if probs:
        raise StepFailure("CONFIG_INVALID", "geometry.defaults 값이 범위를 벗어납니다: " + "; ".join(p["key"] for p in probs[:5]))
    X = _X(ctx)
    os.makedirs(X, exist_ok=True)
    oj = os.path.join(X, "options.json")
    ctx.backup([oj])
    write_json(oj, usage_document(opts, ver))
    ctx.patch_result({"cad_file_name": name, "cad_sha256": sha, "engine": "native", "engine_version": ver, "ocp_version": ocp})


def extract(ctx: Any) -> None:
    s = ctx.settings
    r = ctx.result()
    X = _X(ctx)
    xml, fj = os.path.join(X, EXTRACTED_XML), os.path.join(X, FEATURES_JSON)
    values = {"cad_input": ctx.abs(f"01_train/cad/{r['cad_file_name']}"), "options_json": os.path.join(X, "options.json"),
              "out_dir": X}  # renum_csv 없음 → 인자 쌍째 생략(§7.3.1)
    v = run_paicad(LocalRunner(ctx), s, "paicad_extract", values, cwd=X, report=fj, success=[xml],
                   backup=[xml, fj, os.path.join(X, "features"), os.path.join(X, "paicad.log")])
    v.raise_if_failed()
    ctx.add_output(xml)
    ctx.add_output(fj)


def adjust_params(ctx: Any, params: list[dict[str, Any]]) -> None:
    """양면 접촉(`ref.locked`) 피처는 기본 `use=false`(§4.3) — 사용자가 파라미터 표에서 켤 수 있다."""
    from ..geometry_native import read_json

    doc = read_json(os.path.join(_X(ctx), FEATURES_JSON), ctx.settings.geometry.max_report_bytes)
    locked = {f["name"] for f in doc.get("features", []) if isinstance(f, dict) and isinstance(f.get("name"), str)
              and isinstance(f.get("ref"), dict) and f["ref"].get("locked")}
    for p in params:
        if p.get("name") in locked:
            p["use"] = False


def after_parse(ctx: Any, params: list[dict[str, Any]]) -> None:
    """TX_PARSE 뒤: train_setups.engine='native'·features_rel, 하이라이트 PNG를 FEATURE_PNG 산출물로 등록."""
    X = _X(ctx)
    rel = ctx.rel(os.path.join(X, FEATURES_JSON))
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
