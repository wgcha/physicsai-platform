"""④ PARAM_SET_NATIVE(geometry-engine.md §7.3.4): NP_PREP → NP_EXTRACT → NP_TAG → BL_MAP(항상 SKIPPED) → NP_REGISTER.

new: 프로젝트 폴더에서 후보를 다시 찾아 `logs/_paramset_tmp/<job_id>/`(T)에 모으고, 등록 때 `04_params/<id>`로 옮긴다.
reprep: 대상 = 기존 세트 S. `S/native/`를 `_backup`으로 옮기고 `native/extract/`만 되살린 뒤 tag를 다시 돌린다.
등록(NP_REGISTER)은 `np_register`.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any

from physicsai_core.db.repositories import param_sets as ps_repo
from physicsai_core.errors import StepFailure
from physicsai_core.fileutil import copy_tree
from physicsai_core.geometry.options import check_against_features
from physicsai_core.paths import PathError, allowed_roots, check_user_path
from physicsai_core.stage4_predict import param_discover_native as dn

from ..common import path_failure
from ..geometry_native import (
    LocalRunner,
    effective_opts,
    engine_version,
    native_inputs,
    read_json,
    run_paicad,
    write_native_options,
)
from ...signals import StepSkipped
from .np_register import np_register

FEATURES = "parameter_features.json"
XML = "parameter_extracted.xml"


def target(ctx: Any) -> str:
    """작업 대상 폴더: new = T, reprep = 세트 S."""
    r = ctx.result()
    return ctx.abs(r["target_rel"])


def _ps(ctx: Any) -> dict[str, Any]:
    with ctx.ex.engine.connect() as conn:
        ps = ps_repo.get(conn, ctx.params["param_set_id"])
    if ps is None or ps["study_id"] != ctx.study["id"] or ps.get("engine") != "native":
        raise StepFailure("INPUT_INVALID", "native 파라미터 세트를 찾을 수 없습니다")
    return ps


def _have_features(base: str) -> bool:
    ex = os.path.join(base, "native", "extract")
    return os.path.isfile(os.path.join(ex, FEATURES)) and os.path.isfile(os.path.join(ex, XML))


def _prep_new(ctx: Any) -> str:
    s, p = ctx.settings, ctx.params
    try:
        cp = check_user_path(p["path"], allowed_roots(s, imports=True))
    except PathError as exc:
        raise path_failure(exc) from None
    d = dn.discover_native(cp.path, s)
    cad, assem, probs = dn.resolve_choice_native(d, p.get("choice") or {})
    problems = d.problems + probs
    if problems or cad is None or assem is None:
        raise StepFailure("INPUT_INVALID", "프로젝트 폴더에서 세트를 구성할 수 없습니다: "
                          + "; ".join(f"{q['code']} {q['message']}" for q in problems[:3]))
    if dn.planned_bytes_native(d, cad, assem, s) > s.param_set.max_total_bytes:
        raise StepFailure("INPUT_INVALID", f"복사할 총량이 상한({s.param_set.max_total_bytes} bytes)을 넘습니다 — PARAM_SET_TOO_LARGE")
    T = ctx.abs(f"logs/_paramset_tmp/{ctx.ex.job_id}")
    ctx.backup([T])
    os.makedirs(T, exist_ok=True)
    dn.copy_sources_native(d, cad, assem, T, s)
    ctx.patch_result({"picked": {"cad": cad, "radioss_assem": assem["rel"], "source_path": cp.path}})
    return T


def _prep_reprep(ctx: Any) -> str:
    ps = _ps(ctx)
    S = ctx.abs(ps["stored_rel"])
    nat = os.path.join(S, "native")
    moved = ctx.backup([nat])
    if moved:
        old = ctx.abs(f"_backup/{ctx.ex.stamp}_{ctx.ex.job_id}/{moved[0]}")
        if os.path.isdir(os.path.join(old, "extract")):
            copy_tree(os.path.join(old, "extract"), os.path.join(nat, "extract"), checkpoint=ctx.checkpoint)
    return S


def np_prep(ctx: Any) -> None:
    s, p = ctx.settings, ctx.params
    ver, ocp, shown = engine_version(ctx)
    ctx.log(f"형상 엔진: {shown}")
    if p["mode"] == "new":
        base, geom = _prep_new(ctx), p.get("geom_options")
    else:
        base, geom = _prep_reprep(ctx), _ps(ctx).get("geom_options")
    opts = effective_opts(s, geom)
    os.makedirs(os.path.join(base, "native"), exist_ok=True)
    write_native_options(os.path.join(base, "native"), opts, ver)
    ctx.patch_result({"mode": p["mode"], "target_rel": ctx.rel(base), "engine_version": ver, "ocp_version": ocp,
                      "have_features": _have_features(base), "opts": opts})


def np_extract(ctx: Any) -> None:
    s = ctx.settings
    base, r = target(ctx), ctx.result()
    if r.get("have_features"):
        raise StepSkipped("준비된 피처 파일 사용")
    inp = native_inputs(s, base, os.path.join(base, "radioss_assem"))
    X = os.path.join(base, "native", "extract")
    xml, fj = os.path.join(X, XML), os.path.join(X, FEATURES)
    values = {"cad_input": inp.cad_input, "renum_csv": inp.renum_csv,
              "options_json": os.path.join(base, "native", "options_run.json"), "out_dir": X}
    v = run_paicad(LocalRunner(ctx), s, "paicad_extract", values, cwd=base, report=fj, success=[xml],
                   backup=[xml, fj, os.path.join(X, "features"), os.path.join(X, "paicad.log")], body_map=inp.body_map, log_dir=X)
    v.raise_if_failed()
    ctx.add_output(xml)
    ctx.add_output(fj)


def np_tag(ctx: Any) -> None:
    s = ctx.settings
    base, r = target(ctx), ctx.result()
    inp = native_inputs(s, base, os.path.join(base, "radioss_assem"))
    doc = read_json(inp.features, s.geometry.max_report_bytes)
    probs = check_against_features(r["opts"], doc)
    if probs:
        raise StepFailure("INPUT_INVALID", "형상 옵션이 피처와 맞지 않습니다: " + "; ".join(f"{q['key']} {q['message']}" for q in probs[:3]))
    T = inp.tag_dir
    v = run_paicad(LocalRunner(ctx), s, "paicad_tag",
                   {**inp.base_values(s), "options_json": os.path.join(base, "native", "options_run.json"), "out_dir": T},
                   cwd=base, report=os.path.join(T, "tag.json"), success=[os.path.join(T, "tag_nodes.npz")], backup=[T],
                   body_map=inp.body_map, log_dir=T)
    v.raise_if_failed()
    ctx.add_output(os.path.join(T, "tag.json"))


def bl_map(ctx: Any) -> None:
    raise StepSkipped("단일 baseline")  # 다중 baseline(4B)은 이 단계에서 구현하지 않는다


HANDLERS: dict[tuple[str, str], Callable[[Any], None]] = {
    ("PARAM_SET_NATIVE", "NP_PREP"): np_prep,
    ("PARAM_SET_NATIVE", "NP_EXTRACT"): np_extract,
    ("PARAM_SET_NATIVE", "NP_TAG"): np_tag,
    ("PARAM_SET_NATIVE", "BL_MAP"): bl_map,
    ("PARAM_SET_NATIVE", "NP_REGISTER"): np_register,
}
