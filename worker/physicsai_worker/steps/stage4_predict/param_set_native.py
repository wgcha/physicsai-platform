"""④ PARAM_SET_NATIVE(geometry-engine.md §7.3.4·§7.3.8·§11.1): NP_PREP → NP_EXTRACT → NP_TAG → BL_MAP → NP_REGISTER.

mode(작업 params, 서버가 확정):
- new: 프로젝트 폴더에서 후보를 다시 찾아 `logs/_paramset_tmp/<job_id>/`(T)에 모으고, 등록 때 `04_params/<id>`로 옮긴다.
  `shell_only`(단계 3S): 조립 폴더만 복사, NP_EXTRACT = `paicad props scan`, NP_TAG SKIPPED(§11.1 tag 생략).
- reprep: 대상 = 기존 세트 S. `S/native/`를 `_backup`으로 옮기고 `native/extract/`(·`props/`)만 되살린 뒤 tag를 다시 돌린다.
- props_scan(단계 3S): 대상 = S. NP_EXTRACT = `paicad props scan` → `S/native/props/props.json`, 나머지 SKIPPED/기록.
- add_baseline(단계 4B): 새 baseline 입력을 T에 모아 extract·tag → BL_MAP(`paicad map`) → 등록 때 `S/baselines/<id>`로 옮기고
  `S/param_map.json`(항상 draft, signature 같은 행 decision 승계) 저장.
- remap(단계 4B): BL_MAP·NP_REGISTER만(앞 3 step SKIPPED).
BL_MAP은 다중 baseline(add_baseline·remap)일 때만 실행하고 단일 baseline이면 항상 SKIPPED("단일 baseline").
등록(NP_REGISTER)은 `np_register`.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any

from physicsai_core.db.repositories import param_sets as ps_repo
from physicsai_core.errors import StepFailure
from physicsai_core.fileutil import copy_tree, write_json
from physicsai_core.geometry import baselines as bl
from physicsai_core.geometry.options import check_against_features
from physicsai_core.geometry.prep import is_shell_only
from physicsai_core.geometry.shell import PROPS_DIR
from physicsai_core.geometry.shell_native import features_name, read_kind
from physicsai_core.paths import PathError, allowed_roots, check_user_path
from physicsai_core.stage4_predict import param_discover_native as dn

from ...signals import StepSkipped
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
from .np_register import np_register

FEATURES = "parameter_features.json"
XML = "parameter_extracted.xml"
MULTI_MODES = ("add_baseline", "remap")
SHELL_MODES = ("props_scan",)


def target(ctx: Any) -> str:
    """작업 대상 폴더: new·add_baseline = T, reprep·props_scan·remap = 세트 S."""
    r = ctx.result()
    return ctx.abs(r["target_rel"])


def _ps(ctx: Any) -> dict[str, Any]:
    with ctx.ex.engine.connect() as conn:
        ps = ps_repo.get(conn, ctx.params["param_set_id"])
    if ps is None or ps["study_id"] != ctx.study["id"] or ps.get("engine") != "native":
        raise StepFailure("INPUT_INVALID", "native 파라미터 세트를 찾을 수 없습니다")
    return ps


def _shell(ctx: Any) -> bool:
    """이 작업이 props scan을 하는가(쉘 두께 전용 신규 등록 또는 props_scan)."""
    p = ctx.params
    return p["mode"] in SHELL_MODES or (p["mode"] == "new" and bool(p.get("shell_only")))


def _have_features(base: str, kind: str = "solid") -> bool:
    ex = os.path.join(base, "native", "extract")
    return os.path.isfile(os.path.join(ex, features_name(kind))) and os.path.isfile(os.path.join(ex, XML))


def _kind(ctx: Any) -> str:
    """세트 형상 종류(shell-morph.md §8.2): new = 요청 kind(기본 solid), 그 밖 = 결과에 기록한 값(NP_PREP)."""
    return str(ctx.result().get("kind") or "solid")


def _discover(ctx: Any, path: str, choice: dict[str, Any], shell_only: bool, kind: str = "solid"
              ) -> tuple[Any, str | None, dict[str, Any], str]:
    s = ctx.settings
    try:
        cp = check_user_path(path, allowed_roots(s, imports=True))
    except PathError as exc:
        raise path_failure(exc) from None
    d = dn.discover_native(cp.path, s, kind=kind)
    cad, assem, probs = dn.resolve_choice_native(d, choice or {}, kind=kind)
    problems = dn.shell_only_problems(d.problems + probs) if shell_only else d.problems + probs
    if problems or assem is None or (cad is None and not shell_only):
        raise StepFailure("INPUT_INVALID", "프로젝트 폴더에서 세트를 구성할 수 없습니다: "
                          + "; ".join(f"{q['code']} {q['message']}" for q in problems[:3]))
    return d, cad, assem, cp.path


def _collect(ctx: Any, path: str, choice: dict[str, Any], shell_only: bool = False, kind: str = "solid") -> str:
    """후보를 T(`logs/_paramset_tmp/<job_id>`)에 모은다(new·add_baseline 공통, 원본 재검사·핸들 복사)."""
    s = ctx.settings
    d, cad, assem, src = _discover(ctx, path, choice, shell_only, kind)
    if not shell_only and dn.planned_bytes_native(d, cad, assem, s, kind=kind) > s.param_set.max_total_bytes:
        raise StepFailure("INPUT_INVALID", f"복사할 총량이 상한({s.param_set.max_total_bytes} bytes)을 넘습니다 — PARAM_SET_TOO_LARGE")
    T = ctx.abs(f"logs/_paramset_tmp/{ctx.ex.job_id}")
    ctx.backup([T])
    os.makedirs(T, exist_ok=True)
    if shell_only:
        dn.copy_assem_native(d, assem, T, s)
    else:
        dn.copy_sources_native(d, cad, assem, T, s, kind=kind)
    ctx.patch_result({"picked": {"cad": cad, "radioss_assem": assem["rel"], "source_path": src}})
    return T


def _prep_reprep(ctx: Any) -> str:
    ps = _ps(ctx)
    S = ctx.abs(ps["stored_rel"])
    nat = os.path.join(S, "native")
    moved = ctx.backup([nat])
    if moved:
        old = ctx.abs(f"_backup/{ctx.ex.stamp}_{ctx.ex.job_id}/{moved[0]}")
        for sub in ("extract", "props"):  # 이전 extract·쉘 PROP 목록은 재사용(tag만 다시)
            if os.path.isdir(os.path.join(old, sub)):
                copy_tree(os.path.join(old, sub), os.path.join(nat, sub), checkpoint=ctx.checkpoint)
    return S


def np_prep(ctx: Any) -> None:
    s, p = ctx.settings, ctx.params
    ver, ocp, shown = engine_version(ctx)
    ctx.log(f"형상 엔진: {shown}")
    mode = p["mode"]
    extra: dict[str, Any] = {}
    kind = "shell" if p.get("kind") == "shell" else "solid"
    if mode != "new":
        kind = read_kind(ctx.abs(_ps(ctx)["stored_rel"]))
    if mode == "new":
        base, geom = _collect(ctx, p["path"], p.get("choice") or {}, bool(p.get("shell_only")), kind), p.get("geom_options")
    elif mode == "reprep":
        ps = _ps(ctx)
        if is_shell_only(ctx.abs(ps["stored_rel"])):
            raise StepFailure("INPUT_INVALID", "쉘 두께 전용 세트는 형상 준비가 없습니다 — PROP 스캔을 다시 하세요")
        base, geom = _prep_reprep(ctx), ps.get("geom_options")
    elif mode == "add_baseline":
        ps = _ps(ctx)
        b = p["baseline"]
        base, geom = _collect(ctx, b["path"], b.get("choice") or {}, kind=kind), ps.get("geom_options")
        extra = {"baseline_id": b["id"], "param_set_rel": ps["stored_rel"].rstrip("/")}
    else:  # props_scan · remap: 대상 = S(복사 없음)
        ps = _ps(ctx)
        base, geom = ctx.abs(ps["stored_rel"]), ps.get("geom_options")
        extra = {"param_set_rel": ps["stored_rel"].rstrip("/")}
    opts = effective_opts(s, geom, kind)
    os.makedirs(os.path.join(base, "native"), exist_ok=True)
    if mode in ("new", "reprep", "add_baseline"):
        write_native_options(os.path.join(base, "native"), opts, ver, kind)
    if kind == "shell":
        extra["component"] = s.shell.default_component
    ctx.patch_result({"mode": mode, "target_rel": ctx.rel(base), "engine_version": ver, "ocp_version": ocp, "kind": kind,
                      "have_features": _have_features(base, kind), "opts": opts, "shell_only": bool(p.get("shell_only")), **extra})


def _props_scan(ctx: Any, base: str) -> None:
    from ..geometry_props import run_scan
    from physicsai_core.geometry.options import usage_document

    s, r = ctx.settings, ctx.result()
    out = os.path.join(base, *PROPS_DIR.split("/"))
    os.makedirs(out, exist_ok=True)
    opts_json = os.path.join(out, "options_run.json")
    ctx.backup([opts_json])
    write_json(opts_json, usage_document(r["opts"], r.get("engine_version")))
    v = run_scan(LocalRunner(ctx), s, os.path.join(base, "radioss_assem"), out, opts_json)
    v.raise_if_failed()
    ctx.add_output(os.path.join(out, "props.json"))


def np_extract(ctx: Any) -> None:
    s, p = ctx.settings, ctx.params
    base, r = target(ctx), ctx.result()
    if _shell(ctx):
        return _props_scan(ctx, base)
    if p["mode"] == "remap":
        raise StepSkipped("매칭표만 다시 만듦")
    if r.get("have_features"):
        raise StepSkipped("준비된 피처 파일 사용")
    if _kind(ctx) == "shell":
        return _shell_extract(ctx, base)
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
    s, p = ctx.settings, ctx.params
    if _shell(ctx):
        raise StepSkipped("쉘 두께만 — 경계 분류 생략" if p["mode"] == "new" else "PROP 스캔만")
    if p["mode"] == "remap":
        raise StepSkipped("매칭표만 다시 만듦")
    base, r = target(ctx), ctx.result()
    if _kind(ctx) == "shell":
        return _shell_tag(ctx, base)
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
    """BL_MAP(§7.3.8): 다중 baseline(add_baseline·remap)일 때만 `paicad map` → 매칭 초안. 단일 baseline이면 SKIPPED."""
    p = ctx.params
    if p["mode"] not in MULTI_MODES:
        raise StepSkipped("단일 baseline")
    from .baseline_map import run_map

    run_map(ctx)


# ---- 쉘 판금(shell-morph.md §8.2): NP_EXTRACT = shell extract --assem-dir, NP_TAG = shell fixed-scan --features → shell tag ----


def _shell_extract(ctx: Any, base: str) -> None:
    from physicsai_core.geometry.shell_native import component_bodies

    from ..geometry_shell import extract

    s, r = ctx.settings, ctx.result()
    inp = native_inputs(s, base, os.path.join(base, "radioss_assem"), kind="shell")
    X = os.path.join(base, "native", "extract")
    v = extract(LocalRunner(ctx), s, cad_input=inp.cad_input, out_dir=X, options_json=os.path.join(base, "native", "options_run.json"),
                assem_dir=inp.assem_dir, body_map=inp.body_map, cwd=base)
    v.raise_if_failed()
    doc = read_json(inp.features, s.geometry.max_report_bytes)
    comp = r.get("component") or s.shell.default_component
    if not component_bodies(doc, comp):
        found = ", ".join(str(x.get("title")) for x in doc.get("parts") or [] if isinstance(x, dict))[:200] or "없음"
        raise StepFailure("SHELL_PART_NOT_FOUND", f"지정한 쉘 PART를 찾지 못함 — 기본 대상 component({comp})가 중립면 STEP 바디·"
                          f"/PART 제목에 없습니다(찾은 PART: {found}). 바디 이름이 다르면 cad/body_map.json을 쓰세요")
    for w in doc.get("warnings") or []:
        if isinstance(w, dict) and w.get("code") in ("BEAD_FIXED_OVERLAP", "BEAD_NEAR_FIXED", "FIXED_INFO_MISSING"):
            ctx.add_warning(str(w["code"]), str(w.get("message") or w.get("feature") or "")[:300])
    ctx.add_output(os.path.join(X, XML))
    ctx.add_output(inp.features)


def _shell_tag(ctx: Any, base: str) -> None:
    from ..geometry_shell import fixed_scan_and_tag

    s, r = ctx.settings, ctx.result()
    inp = native_inputs(s, base, os.path.join(base, "radioss_assem"), kind="shell")
    doc = read_json(inp.features, s.geometry.max_report_bytes)
    groups = {g.get("id") for g in doc.get("groups") or [] if isinstance(g, dict)}
    bad = [g for g in (r["opts"].get("symmetry_split") or []) if g not in groups]
    if bad:
        raise StepFailure("INPUT_INVALID", "형상 옵션이 피처와 맞지 않습니다: symmetry_split 존재하지 않는 그룹 id " + ", ".join(bad[:3]))
    scan, tag = fixed_scan_and_tag(LocalRunner(ctx), s, inp, os.path.join(base, "native", "options_run.json"), base)
    scan.raise_if_failed()
    tag.raise_if_failed()  # type: ignore[union-attr]
    fx = (scan.report or {}).get("fixed") or {}
    ctx.patch_result({"fixed": {"total": fx.get("total"), "digest": fx.get("digest"), "by_kind": fx.get("by_kind")}})
    ctx.add_output(os.path.join(inp.fixed_dir, "shell_scan.json"))
    ctx.add_output(os.path.join(inp.tag_dir, "shell_tag.json"))


def np_view(ctx: Any) -> None:
    """NP_VIEW(geometry-view.md §6.3): 공칭 3D 뷰. 실패·명령 null이면 step SUCCEEDED + 경고 VIEW_EXPORT_FAILED(작업 계속)."""
    from ..geometry_view import export_view

    p = ctx.params
    if _shell(ctx) or p["mode"] in ("remap", "add_baseline"):
        raise StepSkipped("3D 보기 대상 아님(쉘 두께·매칭표·추가 baseline)")
    base = target(ctx)
    inp = native_inputs(ctx.settings, base, os.path.join(base, "radioss_assem"), kind=_kind(ctx))
    view = export_view(ctx, kind=inp.kind, cad_input=inp.cad_input, features=inp.features, out_dir=os.path.join(base, "native", "view"),
                       fixed_dir=inp.fixed_dir or None, body_map=inp.body_map, cwd=base, engine_version=ctx.result().get("engine_version"))
    ctx.patch_result({"view": view})


HANDLERS: dict[tuple[str, str], Callable[[Any], None]] = {
    ("PARAM_SET_NATIVE", "NP_PREP"): np_prep,
    ("PARAM_SET_NATIVE", "NP_EXTRACT"): np_extract,
    ("PARAM_SET_NATIVE", "NP_TAG"): np_tag,
    ("PARAM_SET_NATIVE", "NP_VIEW"): np_view,
    ("PARAM_SET_NATIVE", "BL_MAP"): bl_map,
    ("PARAM_SET_NATIVE", "NP_REGISTER"): np_register,
}

__all__ = ["HANDLERS", "bl", "target"]
