"""NP_REGISTER(geometry-engine.md §7.3.4): parameters.json·prep.json 작성 → 검증 → 행 등록 → T를 `04_params/<id>`로 이동.

reprep: 파라미터 이름 집합이 같을 때만 prep.json을 갱신하고 세트 행의 engine_version·geom_options를 바꾼다(세트 불변 원칙).
"""

from __future__ import annotations

import contextlib
import json
import os
import uuid
from datetime import datetime, timezone
from typing import Any

from physicsai_core.db.repositories import audit as audit_repo
from physicsai_core.db.repositories import param_sets as ps_repo
from physicsai_core.errors import StepFailure
from physicsai_core.fileutil import write_json
from physicsai_core.geometry.features_view import representative_params
from physicsai_core.geometry.prep import prep_document
from physicsai_core.stage4_predict.param_set_native import PARTS_NAME, validate_native_folder

from ..geometry_native import read_json


def _params_from_features(base: str, max_bytes: int) -> list[dict[str, Any]]:
    doc = read_json(os.path.join(base, "native", "extract", "parameter_features.json"), max_bytes)
    rows = representative_params(doc)
    if not rows or any(r["min"] is None or r["max"] is None or r["nominal"] is None for r in rows):
        raise StepFailure("INPUT_INVALID", "형상 피처에서 파라미터 표를 만들 수 없습니다(피처 없음 또는 범위 누락)")
    prov = os.path.join(base, "original", "parameters.json")
    if os.path.isfile(prov):  # 프로젝트 폴더가 준 min·max(이름 집합이 같을 때만)
        try:
            with open(prov, encoding="utf-8") as fh:
                given = {p["name"]: p for p in json.load(fh)["parameters"]}
        except (OSError, ValueError, KeyError, TypeError):
            raise StepFailure("PARAM_FEATURE_MISMATCH", "프로젝트 폴더의 parameters.json을 읽을 수 없습니다") from None
        if set(given) != {r["name"] for r in rows}:
            raise StepFailure("PARAM_FEATURE_MISMATCH", "parameters.json의 이름 집합이 형상 피처(그룹 대표)와 다릅니다")
        for r in rows:
            r["min"], r["max"] = given[r["name"]].get("min"), given[r["name"]].get("max")
    return rows


def _prep_json(ctx: Any, base: str) -> None:
    s, r = ctx.settings, ctx.result()
    write_json(os.path.join(base, "native", "prep.json"), prep_document(
        base, step_exts=s.geometry.step_extensions, mesh_include_name=s.predict.mesh_include_name,
        renum_csv_name=s.predict.renum_csv_name, opts=r["opts"], engine_version=r.get("engine_version"),
        ocp_version=r.get("ocp_version"), job_id=ctx.ex.job_id, created_at=datetime.now(timezone.utc).isoformat()))


def _validate(ctx: Any, base: str) -> Any:
    s = ctx.settings
    f = validate_native_folder(base, max_total_bytes=s.param_set.max_total_bytes, starter_glob=s.predict.starter_glob,
                               renum_csv_name=s.predict.renum_csv_name, baseline_inc_name=s.predict.mesh_include_name,
                               step_extensions=s.geometry.step_extensions)
    if not f.ok:
        code = f.problems[0]["code"] if f.problems[0]["code"] == "PARAM_FEATURE_MISMATCH" else "INPUT_INVALID"
        raise StepFailure(code, "파라미터 세트 검증 실패: " + "; ".join(f"{q['code']} {q['message']}" for q in f.problems[:3]))
    return f


def _png(ctx: Any, base: str) -> int:
    d, n = os.path.join(base, "native", "extract", "features"), 0
    for f in sorted(os.listdir(d)) if os.path.isdir(d) else []:
        p = os.path.join(d, f)
        if f.lower().endswith(".png") and os.path.isfile(p):
            ctx.register_artifact("FEATURE_PNG", p, "image/png")
            n += 1
    return n


def np_register(ctx: Any) -> None:
    s, p, r = ctx.settings, ctx.params, ctx.result()
    base = ctx.abs(r["target_rel"])
    job = ctx.job
    if p["mode"] == "reprep":
        with ctx.ex.engine.connect() as conn:
            ps = ps_repo.get(conn, p["param_set_id"])
        if ps is None:
            raise StepFailure("INPUT_INVALID", "파라미터 세트를 찾을 수 없습니다")
        names = {x["name"] for x in _params_from_features(base, s.geometry.max_report_bytes)}
        if names != {x["name"] for x in ps["parameters"]}:
            raise StepFailure("PARAM_FEATURE_MISMATCH", "다시 준비한 형상 피처의 이름 집합이 기존 파라미터 표와 다릅니다(세트는 바뀌지 않았습니다)")
        _prep_json(ctx, base)
        _validate(ctx, base)
        ctx.ex.db(lambda c: (ps_repo.set_values(c, ps["id"], engine_version=r.get("engine_version")),
                             audit_repo.record(c, user_id=job["created_by"], username=None, action="PARAM_SET_NATIVE_PREPARE",
                                               target_type="param_set", target_id=ps["id"],
                                               detail={"job_id": ctx.ex.job_id, "engine_version": r.get("engine_version")})))
        n = _png(ctx, base)
        ctx.patch_result({"param_set_id": ps["id"], "feature_png_count": n})
        return
    rows = _params_from_features(base, s.geometry.max_report_bytes)
    write_json(os.path.join(base, "parameters.json"), {"schema_version": 1, "unit_system": "mm-ton-s", "parameters": rows})
    _prep_json(ctx, base)
    f = _validate(ctx, base)
    psid = str(uuid.uuid4())
    picked = r.get("picked") or {}
    write_json(os.path.join(base, "source.json"), {"source_path": picked.get("source_path"), "mode": "discover", "discovered": picked,
                                                   "registered_at": datetime.now(timezone.utc).isoformat()})
    stored_rel = f"04_params/{psid}"
    dst = ctx.abs(stored_rel)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    moved = False

    def tx(c: Any) -> None:
        nonlocal moved
        ps_repo.insert_current(c, {
            "id": psid, "study_id": ctx.study["id"], "source_path": picked.get("source_path") or "", "stored_rel": stored_rel + "/",
            "unit_system": f.unit_system, "parameters": f.parameters, "responses": [], "sample_count": 0,
            "sample_has_measured": False, "cad_file_name": f.cad_file or PARTS_NAME + "/", "tpl_rel": None,
            "assem_rel": f"{stored_rel}/radioss_assem/", "starter_name": f.starter_name, "input_kind": "assembly", "tpl_params": [],
            "registered_by": job["created_by"], "registered_by_name": job.get("created_by_name") or job["created_by"],
            "label": p.get("label"), "engine": "native", "geom_options": p.get("geom_options"), "engine_version": r.get("engine_version")})
        audit_repo.record(c, user_id=job["created_by"], username=None, action="PARAM_SET_REGISTER", target_type="param_set",
                          target_id=psid, detail={"job_id": ctx.ex.job_id, "engine": "native", "source_path": picked.get("source_path")})
        os.replace(base, dst)
        moved = True

    try:
        ctx.ex.db(tx)
    except BaseException:
        if moved and os.path.isdir(dst) and not os.path.lexists(base):
            with contextlib.suppress(OSError):
                os.replace(dst, base)
        raise
    n = _png(ctx, dst)
    ctx.patch_result({"param_set_id": psid, "feature_png_count": n, "target_rel": stored_rel})
