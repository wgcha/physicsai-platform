"""④ GEOM_PREVIEW(geometry-view.md §6.4): GV_PREP → GV_RUN(`paicad (shell) view preview`) → GV_REGISTER. 레인 PREVIEW.

- 캐시 폴더 C = 서버측 `<study>/_cache/geom_preview/<key[0:2]>/<key>/`(플랫폼 임시 산출물 — 이미 있으면 지우고 새로, 캐시라 이동 아님).
- 판정(GV-10): manifest가 있고 status OK/FAIL이며 FAIL category ∉ {VIEW, INPUT, INTERNAL}이면 작업 SUCCEEDED(결과 FAIL도 캐시).
  그 밖(manifest 없음·시간 초과 VIEW_PREVIEW_TIMEOUT·VIEW_*·내부 오류)은 작업 FAILED(캐시로 쓰지 않음, 행 FAILED는 종료 훅).
- 미리보기는 solver include를 만들지 않는다(paicad가 보장, §5.2). 허용 외부 명령은 preview 키 2개뿐(§6.2 — 다른 키면 INTERNAL).
"""

from __future__ import annotations

import os
from typing import Any

from physicsai_core.cache_store import remove_cache_dir
from physicsai_core.db.repositories import geom_view as gv_repo
from physicsai_core.db.repositories import param_sets as ps_repo
from physicsai_core.db.tables import geom_previews
from physicsai_core.errors import StepFailure
from physicsai_core.fileutil import write_json
from physicsai_core.geometry.native_files import values_document
from physicsai_core.geometry.options import usage_document
from physicsai_core.geometry.view import (
    FE_MODES,
    GLB_CONTENT_TYPE,
    JSON_CONTENT_TYPE,
    PREVIEW_CACHE,
    PREVIEW_FE_GLB,
    PREVIEW_GLB,
    PREVIEW_MANIFEST,
    VIEW_DIR,
    VIEW_MANIFEST,
    cache_rel,
    dir_bytes,
    judge_preview,
    preview_key,
    read_json,
    view_options_document,
)

from ..geometry_native import LocalRunner, ensure_prep_ready, native_inputs, run_paicad, set_opts

PREVIEW_COMMANDS = frozenset({"paicad_view_preview", "paicad_shell_view_preview"})


def _ps(ctx: Any) -> tuple[dict[str, Any], str]:
    with ctx.ex.engine.connect() as conn:
        ps = ps_repo.get(conn, ctx.params["param_set_id"])
    if ps is None or ps["study_id"] != ctx.study["id"] or ps.get("engine") != "native":
        raise StepFailure("INPUT_INVALID", "native 파라미터 세트를 찾을 수 없습니다")
    return ps, ctx.abs(ps["stored_rel"])


def _C(ctx: Any) -> str:
    return ctx.abs(cache_rel(PREVIEW_CACHE, ctx.params["cache_key"]))


def gv_prep(ctx: Any) -> None:
    s, p = ctx.settings, ctx.params
    ps, S = _ps(ctx)
    opts = set_opts(s, S, ps.get("geom_options"))
    ensure_prep_ready(s, S, opts, p.get("engine_version"))  # INPUT_CHANGED(준비본이 바뀜)
    C = _C(ctx)
    if not remove_cache_dir(ctx.root, C, PREVIEW_CACHE):  # 캐시(플랫폼 임시 산출물)라 _backup 이동 대신 지운다(§6.6)
        raise StepFailure("PATH_UNSAFE", "미리보기 캐시 폴더 경로가 안전하지 않습니다")
    os.makedirs(C)
    kind = native_inputs(s, S, os.path.join(S, "radioss_assem"), need_cad=False).kind
    write_json(os.path.join(C, "values.json"), values_document(p["values"], "preview", p["preview_id"], p.get("engine_version")))
    write_json(os.path.join(C, "options.json"), {**usage_document(opts, p.get("engine_version")), **({"kind": "shell"} if kind == "shell" else {})})
    nom = read_json(os.path.join(S, *VIEW_DIR.split("/"), VIEW_MANIFEST))
    tess = nom.get("tess") if nom and nom.get("status") == "OK" and isinstance(nom.get("tess"), dict) else None
    write_json(os.path.join(C, "view_options.json"), view_options_document(s, {"linear_mm": tess["linear_mm"], "angular_deg": tess["angular_deg"]}
                                                                         if tess else None))
    ctx.ex.db(lambda c: gv_repo.set_values(c, geom_previews, p["preview_id"], status="RUNNING"))
    ctx.patch_result({"preview_id": p["preview_id"], "kind": kind, "cache_rel": ctx.rel(C)})


def gv_run(ctx: Any) -> None:
    s, p = ctx.settings, ctx.params
    ps, S = _ps(ctx)
    C = _C(ctx)
    inp = native_inputs(s, S, os.path.join(S, "radioss_assem"))
    key = preview_key(inp.kind)
    if key not in PREVIEW_COMMANDS:  # §6.2: PREVIEW 레인 허용 명령(정적 시험도 확인)
        raise StepFailure("INTERNAL_ERROR", f"PREVIEW 레인에서 허용되지 않은 명령: {key}")
    if getattr(s.commands, key, None) is None:
        raise StepFailure("VIEW_UNAVAILABLE", f"3D 미리보기를 쓸 수 없습니다 — commands.{key} 설정 확인")
    fe = p.get("fe") or "off"
    if fe not in FE_MODES:
        raise StepFailure("INPUT_INVALID", f"fe는 {', '.join(FE_MODES)} 중 하나여야 합니다")
    nm = os.path.join(S, *VIEW_DIR.split("/"), VIEW_MANIFEST)
    out = os.path.join(C, "out")
    values = {**inp.base_values(s), "values_json": os.path.join(C, "values.json"), "options_json": os.path.join(C, "options.json"),
              "view_options_json": os.path.join(C, "view_options.json"), "nominal_manifest": nm if os.path.isfile(nm) else "",
              "fe_mode": fe, "threads": str(int(s.geometry.view.threads)), "out_dir": out, "thickness_json": "",
              "baseline_inc": inp.baseline_inc, "renum_csv": inp.renum_csv}
    timeout = s.geometry.view.timeout_s.get("preview" if fe == "off" else "preview_fe")
    try:
        run_paicad(LocalRunner(ctx), s, key, values, cwd=C, report=os.path.join(out, PREVIEW_MANIFEST), success=[], backup=[out],
                   body_map=inp.body_map, log_dir=out, timeout_s=timeout)
    except StepFailure as exc:
        if exc.code == "GEOM_TIMEOUT":
            raise StepFailure("VIEW_PREVIEW_TIMEOUT", f"미리보기 시간 초과({timeout:g}초)") from None
        raise
    man = read_json(os.path.join(out, PREVIEW_MANIFEST))
    j = judge_preview(man)
    if not j["cacheable"]:
        code = j["code"] or "OUTPUT_MISSING"
        from physicsai_core.geometry.messages import korean_message

        raise StepFailure(code, korean_message(code, j["message"]) if man else "미리보기 결과(preview_manifest.json)가 없습니다")
    ctx.patch_result({"judge": {k: v for k, v in j.items() if k != "cacheable"},
                      "timing": (man or {}).get("timing") if isinstance((man or {}).get("timing"), dict) else None})


def gv_register(ctx: Any) -> None:
    p, r = ctx.params, ctx.result()
    out = os.path.join(_C(ctx), "out")
    ids: dict[str, str | None] = {"glb_artifact_id": None, "fe_glb_artifact_id": None, "manifest_artifact_id": None}
    for col, kind, name, ctype in (("glb_artifact_id", "GEOM_PREVIEW_GLB", PREVIEW_GLB, GLB_CONTENT_TYPE),
                                   ("fe_glb_artifact_id", "GEOM_PREVIEW_FE_GLB", PREVIEW_FE_GLB, GLB_CONTENT_TYPE),
                                   ("manifest_artifact_id", "GEOM_PREVIEW_MANIFEST", PREVIEW_MANIFEST, JSON_CONTENT_TYPE)):
        f = os.path.join(out, name)
        if os.path.isfile(f) and os.path.getsize(f) > 0:
            ids[col] = ctx.register_artifact(kind, f, ctype)
    j = r.get("judge") or {}
    from sqlalchemy import func

    vals = {"status": "DONE", "result_status": j.get("result_status"), "code": j.get("code"), "category": j.get("category"),
            "fe_status": j.get("fe_status"), "fe_code": j.get("fe_code"), "bytes": dir_bytes(_C(ctx)), "timing": r.get("timing"),
            "finished_at": func.now(), "last_access_at": func.now(), **ids}
    ctx.ex.db(lambda c: gv_repo.set_values(c, geom_previews, p["preview_id"], **vals))
    ctx.patch_result({"artifacts": ids})


HANDLERS = {
    ("GEOM_PREVIEW", "GV_PREP"): gv_prep,
    ("GEOM_PREVIEW", "GV_RUN"): gv_run,
    ("GEOM_PREVIEW", "GV_REGISTER"): gv_register,
}
