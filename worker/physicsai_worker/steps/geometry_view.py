"""공칭 3D 뷰 export 공용(geometry-view.md §6.3 NP_VIEW·§6.9 TX_VIEW): `paicad (shell) view export` → `<out>/view.glb`·`view_manifest.json`.

실패·명령 null·실행 파일 없음·시간 초과는 모두 step 경고 `VIEW_EXPORT_FAILED`(사유) + `view = {status:"FAILED"|"MISSING"}` —
호출 step은 SUCCEEDED로 끝나고 작업은 계속된다(뷰 실패가 추출·준비를 실패시키지 않는다, GV-2·GV-6).
"""

from __future__ import annotations

import os
from typing import Any

from physicsai_core.errors import StepFailure
from physicsai_core.fileutil import write_json
from physicsai_core.geometry.messages import korean_message
from physicsai_core.geometry.view import (
    FAILED,
    MISSING,
    VIEW_GLB,
    VIEW_MANIFEST,
    VIEW_OPTIONS,
    export_key,
    view_options_document,
    view_result,
)

from .geometry_native import LocalRunner, run_paicad


def export_view(ctx: Any, *, kind: str, cad_input: str, features: str, out_dir: str, fixed_dir: str | None, body_map: str | None,
                cwd: str, engine_version: str | None) -> dict[str, Any]:
    s = ctx.settings
    key = export_key(kind)
    if not s.geometry.view.enabled or getattr(s.commands, key, None) is None:
        why = "3D 보기 꺼짐(geometry.view.enabled)" if not s.geometry.view.enabled else f"명령 미설정(commands.{key})"
        ctx.add_warning("VIEW_EXPORT_FAILED", f"{korean_message('VIEW_EXPORT_FAILED')} — {why}")
        return {"status": MISSING, "reason": why}
    os.makedirs(out_dir, exist_ok=True)
    vo = os.path.join(out_dir, VIEW_OPTIONS)
    for p in (vo,):
        if os.path.lexists(p):
            ctx.backup([p])
    write_json(vo, view_options_document(s))
    values = {"cad_input": cad_input, "features_json": features, "view_options_json": vo, "out_dir": out_dir,
              "fixed_dir": fixed_dir or ""}
    try:
        v = run_paicad(LocalRunner(ctx), s, key, values, cwd=cwd, report=os.path.join(out_dir, VIEW_MANIFEST),
                       success=[os.path.join(out_dir, VIEW_GLB)],
                       backup=[os.path.join(out_dir, n) for n in (VIEW_GLB, VIEW_MANIFEST, "paicad.log")], body_map=body_map,
                       log_dir=out_dir, timeout_s=s.geometry.view.timeout_s.get("export"))
    except StepFailure as exc:  # 실행 파일 없음·시간 초과 등 플랫폼 오류도 경고로(작업 계속)
        ctx.add_warning("VIEW_EXPORT_FAILED", f"{korean_message('VIEW_EXPORT_FAILED')} — {exc.code}: {exc.message}"[:300])
        return {"status": FAILED, "reason": exc.code}
    if not v.ok:
        ctx.add_warning("VIEW_EXPORT_FAILED", f"{korean_message('VIEW_EXPORT_FAILED')} — {v.message or v.code}"[:300])
        return {"status": FAILED, "reason": v.code}
    res = view_result(out_dir, engine_version)
    if res is None:
        ctx.add_warning("VIEW_EXPORT_FAILED", f"{korean_message('VIEW_EXPORT_FAILED')} — view.glb·manifest 확인 실패")
        return {"status": FAILED, "reason": "OUTPUT_MISSING"}
    ctx.add_output(os.path.join(out_dir, VIEW_MANIFEST))
    return res


def register_view_artifacts(ctx: Any, out_dir: str) -> dict[str, str | None]:
    """GEOM_VIEW_GLB(model/gltf-binary)·GEOM_VIEW_MANIFEST(application/json) 등록(rel_path = 현재 폴더 기준)."""
    from physicsai_core.geometry.view import GLB_CONTENT_TYPE, JSON_CONTENT_TYPE

    glb, man = os.path.join(out_dir, VIEW_GLB), os.path.join(out_dir, VIEW_MANIFEST)
    out: dict[str, str | None] = {"glb_artifact_id": None, "manifest_artifact_id": None}
    if os.path.isfile(glb) and os.path.isfile(man):
        out["glb_artifact_id"] = ctx.register_artifact("GEOM_VIEW_GLB", glb, GLB_CONTENT_TYPE)
        out["manifest_artifact_id"] = ctx.register_artifact("GEOM_VIEW_MANIFEST", man, JSON_CONTENT_TYPE)
    return out
