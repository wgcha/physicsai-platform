"""④ PARAM_SET_NATIVE 쉘 판금 추출·태그(shell-morph.md §8.2) — R-B 300줄 분할: `param_set_native`가 가져다 쓴다(동작 불변).

NP_EXTRACT = `shell extract --assem-dir`, NP_TAG = `shell fixed-scan --features` → `shell tag`."""

from __future__ import annotations

import os
from typing import Any

from physicsai_core.errors import StepFailure

from ..geometry_native import LocalRunner, native_inputs, read_json

XML = "parameter_extracted.xml"


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
