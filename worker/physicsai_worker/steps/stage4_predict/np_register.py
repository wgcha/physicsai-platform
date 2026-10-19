"""NP_REGISTER(geometry-engine.md §7.3.4·§7.3.8·§11.1): mode별 등록.

- new: parameters.json·prep.json 작성 → 검증 → 행 등록 → T를 `04_params/<id>`로 이동. shell_only(3S)면 선택 가능한 PROP 전부를
  쉘 두께 행(`source: prop`, 범위 ±range_ratio)으로 등록(사용자가 PUT …/props로 고쳐 고름).
- reprep: 파라미터 이름 집합(형상 행만)이 같을 때만 prep.json을 갱신하고 세트 행의 engine_version을 바꾼다(세트 불변 원칙).
- props_scan(3S): props.json 갱신 기록. 지금 선택한 PROP 중 더 이상 고를 수 없는 것은 표에서 빼고 경고.
- add_baseline·remap(4B): 매칭 초안 검사(PARAM_NAME_CONFLICT면 실패·세트 불변) → (add) T를 `S/baselines/<id>`로 이동 →
  `S/param_map.json` 저장(항상 draft, 이전 결정은 signature 같은 행만 승계). 확정 전이라 파라미터 표는 바꾸지 않는다.
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
from physicsai_core.fileutil import write_json, write_json_atomic
from physicsai_core.geometry import baselines as bl
from physicsai_core.geometry import shell as sh
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


def _prep_json(ctx: Any, base: str, *, shell_only: bool = False) -> None:
    s, r = ctx.settings, ctx.result()
    write_json(os.path.join(base, "native", "prep.json"), prep_document(
        base, step_exts=s.geometry.step_extensions, mesh_include_name=s.predict.mesh_include_name,
        renum_csv_name=s.predict.renum_csv_name, opts=r["opts"], engine_version=r.get("engine_version"),
        ocp_version=r.get("ocp_version"), job_id=ctx.ex.job_id, created_at=datetime.now(timezone.utc).isoformat(),
        shell_only=shell_only))


def _validate(ctx: Any, base: str, *, shell_only: bool = False) -> Any:
    s = ctx.settings
    f = validate_native_folder(base, max_total_bytes=s.param_set.max_total_bytes, starter_glob=s.predict.starter_glob,
                               renum_csv_name=s.predict.renum_csv_name, baseline_inc_name=s.predict.mesh_include_name,
                               step_extensions=s.geometry.step_extensions, shell_only=shell_only)
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


def _ps(ctx: Any) -> dict[str, Any]:
    with ctx.ex.engine.connect() as conn:
        ps = ps_repo.get(conn, ctx.params["param_set_id"])
    if ps is None:
        raise StepFailure("INPUT_INVALID", "파라미터 세트를 찾을 수 없습니다")
    return ps


def _audit(ctx: Any, c: Any, action: str, target_id: str, detail: dict[str, Any]) -> None:
    audit_repo.record(c, user_id=ctx.job["created_by"], username=None, action=action, target_type="param_set", target_id=target_id,
                      detail={"job_id": ctx.ex.job_id, **detail})


def _props_doc(ctx: Any, base: str) -> dict[str, Any]:
    return read_json(os.path.join(base, *sh.PROPS_JSON.split("/")), ctx.settings.geometry.max_report_bytes)


def np_register(ctx: Any) -> None:
    mode = ctx.params["mode"]
    if mode == "reprep":
        return _register_reprep(ctx)
    if mode == "props_scan":
        return _register_props_scan(ctx)
    if mode in ("add_baseline", "remap"):
        return _register_map(ctx)
    return _register_new(ctx)


def _register_reprep(ctx: Any) -> None:
    s, r = ctx.settings, ctx.result()
    base = ctx.abs(r["target_rel"])
    ps = _ps(ctx)
    names = {x["name"] for x in _params_from_features(base, s.geometry.max_report_bytes)}
    multi_confirmed = (bl.load(base, s.geometry.max_report_bytes) or {}).get("status") == "confirmed" if bl.is_multi(base) else False
    if not multi_confirmed and names != {x["name"] for x in sh.geometry_rows(ps["parameters"])}:
        raise StepFailure("PARAM_FEATURE_MISMATCH", "다시 준비한 형상 피처의 이름 집합이 기존 파라미터 표와 다릅니다(세트는 바뀌지 않았습니다)")
    _prep_json(ctx, base)
    _validate(ctx, base)
    ctx.ex.db(lambda c: (ps_repo.set_values(c, ps["id"], engine_version=r.get("engine_version")),
                         _audit(ctx, c, "PARAM_SET_NATIVE_PREPARE", ps["id"], {"engine_version": r.get("engine_version")})))
    n = _png(ctx, base)
    ctx.patch_result({"param_set_id": ps["id"], "feature_png_count": n})


def _register_props_scan(ctx: Any) -> None:
    """3S PROP 스캔 기록: 현재 선택 중 더 이상 고를 수 없는 PROP은 표에서 빼고(경고) 나머지는 유지."""
    r = ctx.result()
    S = ctx.abs(r["target_rel"])
    ps = _ps(ctx)
    doc = _props_doc(ctx, S)
    sel = sh.selectable(doc)
    keep, dropped = [], []
    for row in sh.prop_rows(ps["parameters"]):
        (keep if row["name"] in sel else dropped).append(row)
    rows = sh.merge_rows(sh.geometry_rows(ps["parameters"]), keep)
    if dropped:
        if not rows:
            raise StepFailure("PROP_NOT_FOUND", "선택한 쉘 PROP을 모두 더 이상 고를 수 없습니다 — 세트는 바뀌지 않았습니다: "
                              + ", ".join(x["name"] for x in dropped[:5]))
        ctx.add_warning("PROP_SELECTION_DROPPED", "고를 수 없게 된 쉘 PROP을 파라미터 표에서 뺐습니다: " + ", ".join(x["name"] for x in dropped[:10]))
        _write_parameters(S, ps, rows)
    ctx.ex.db(lambda c: (ps_repo.set_values(c, ps["id"], parameters=rows) if dropped else None,
                         _audit(ctx, c, "PARAM_SET_PROPS_SCAN", ps["id"], {"props": len(sh.props_rows(doc)), "selectable": len(sel),
                                                                          "dropped": [x["name"] for x in dropped]})))
    ctx.patch_result({"param_set_id": ps["id"], "props_count": len(sh.props_rows(doc)), "selectable_count": len(sel)})


def _write_parameters(S: str, ps: dict[str, Any], rows: list[dict[str, Any]]) -> None:
    write_json_atomic(os.path.join(S, "parameters.json"), {"schema_version": 1, "unit_system": ps.get("unit_system") or "mm-ton-s",
                                                            "parameters": rows})


def _register_map(ctx: Any) -> None:
    """4B: 매칭 초안 검사 → (add_baseline) baseline 폴더 이동·baseline.json → param_map.json(draft) 저장."""
    s, p, r = ctx.settings, ctx.params, ctx.result()
    S = ctx.abs(r["param_set_rel"])
    ps = _ps(ctx)
    try:
        old = bl.load(S, s.geometry.max_report_bytes)
        new = bl.load_file(ctx.abs(r["map_rel"]), s.geometry.max_report_bytes)
    except bl.MapError as exc:
        raise StepFailure(exc.code, exc.message) from None
    new = bl.inherit(new, old if (old or {}).get("usage") == new.get("usage") else None)
    T = ctx.abs(r["target_rel"]) if p["mode"] == "add_baseline" else None
    roots = {b: (T if (T and b == p["baseline"]["id"]) else bl.baseline_root(S, new, b)) for b in bl.baseline_ids(new)}
    feats = {b: bl.rep_features_at(root, s.geometry.max_report_bytes) for b, root in roots.items()}
    probs = bl.decision_problems(new, bl.known_names(feats))
    if probs:
        code = "PARAM_NAME_CONFLICT" if any(q["code"] == "PARAM_NAME_CONFLICT" for q in probs) else "INPUT_INVALID"
        raise StepFailure(code, "매칭표 결정 검사 실패(세트는 바뀌지 않았습니다): " + "; ".join(q["message"] for q in probs[:3]))
    if p["mode"] == "add_baseline":
        bid = p["baseline"]["id"]
        rows = _params_from_features(T, s.geometry.max_report_bytes)  # type: ignore[arg-type]
        write_json(os.path.join(T, "parameters.json"), {"schema_version": 1, "unit_system": ps.get("unit_system") or "mm-ton-s",
                                                        "parameters": rows})
        _prep_json(ctx, T)  # type: ignore[arg-type]
        _validate(ctx, T)  # type: ignore[arg-type]
        write_json(os.path.join(T, bl.BASELINE_JSON), {  # type: ignore[arg-type]
            "schema_version": 1, "engine": "native", "engine_version": r.get("engine_version"), "id": bid,
            "label": p["baseline"].get("label") or bid, "nominal": {x["name"]: x["nominal"] for x in rows}, "assem_ref": None,
            "usage_role": new.get("usage"), "source_path": (r.get("picked") or {}).get("source_path")})
        single = os.path.join(S, *bl.SINGLE_PARAMS.split("/"))
        os.makedirs(os.path.dirname(single), exist_ok=True)
        if old is None and not os.path.isfile(single):  # 단일로 되돌릴 때 복원할 원래 표(형상 행)
            write_json(single, {"schema_version": 1, "unit_system": ps.get("unit_system") or "mm-ton-s",
                                "parameters": sh.geometry_rows(ps["parameters"])})
        dst = os.path.join(S, bl.BASELINES_DIR, bid)
        if os.path.lexists(dst):
            raise StepFailure("INPUT_INVALID", f"baseline 폴더가 이미 있습니다: baselines/{bid}")
        os.replace(T, dst)  # type: ignore[arg-type]
    pmp = bl.map_path(S)
    if os.path.lexists(pmp):
        ctx.backup([pmp])  # 이전 매칭표는 _backup으로(삭제 없음)
    write_json_atomic(pmp, new)
    if p["mode"] == "add_baseline":
        _png(ctx, os.path.join(S, bl.BASELINES_DIR, p["baseline"]["id"]))
    detail = {"mode": p["mode"], "baselines": bl.baseline_ids(new), "usage": new.get("usage"), "rows": len(new.get("common") or []),
              "needs_review": sum(1 for x in new.get("common") or [] if x.get("needs_review"))}
    ctx.ex.db(lambda c: _audit(ctx, c, "PARAM_SET_BASELINE_ADD" if p["mode"] == "add_baseline" else "PARAM_SET_REMAP", ps["id"], detail))
    ctx.patch_result({"param_set_id": ps["id"], "map_status": new["status"], "baselines": bl.baseline_ids(new),
                      "unresolved_rows": bl.unresolved(new), "undecided_rows": bl.undecided_count(new)})


def _register_new(ctx: Any) -> None:
    s, p, r = ctx.settings, ctx.params, ctx.result()
    base = ctx.abs(r["target_rel"])
    job = ctx.job
    shell_only = bool(p.get("shell_only"))
    if shell_only:
        doc = _props_doc(ctx, base)
        rows = [sh.default_row(x) for x in sh.selectable(doc).values()]
        if not rows:
            raise StepFailure("PROP_NOT_FOUND", "조립 폴더에서 선택할 수 있는 쉘 PROP(/PROP/TYPE1)을 찾지 못했습니다")
    else:
        rows = _params_from_features(base, s.geometry.max_report_bytes)
    write_json(os.path.join(base, "parameters.json"), {"schema_version": 1, "unit_system": "mm-ton-s", "parameters": rows})
    _prep_json(ctx, base, shell_only=shell_only)
    f = _validate(ctx, base, shell_only=shell_only)
    psid = str(uuid.uuid4())
    picked = r.get("picked") or {}
    write_json(os.path.join(base, "source.json"), {"source_path": picked.get("source_path"), "mode": "discover", "discovered": picked,
                                                   "shell_only": shell_only, "registered_at": datetime.now(timezone.utc).isoformat()})
    stored_rel = f"04_params/{psid}"
    dst = ctx.abs(stored_rel)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    moved = False
    params = rows if shell_only else f.parameters

    def tx(c: Any) -> None:
        nonlocal moved
        ps_repo.insert_current(c, {
            "id": psid, "study_id": ctx.study["id"], "source_path": picked.get("source_path") or "", "stored_rel": stored_rel + "/",
            "unit_system": f.unit_system, "parameters": params, "responses": [], "sample_count": 0,
            "sample_has_measured": False, "cad_file_name": "" if shell_only else (f.cad_file or PARTS_NAME + "/"), "tpl_rel": None,
            "assem_rel": f"{stored_rel}/radioss_assem/", "starter_name": f.starter_name, "input_kind": "assembly", "tpl_params": [],
            "registered_by": job["created_by"], "registered_by_name": job.get("created_by_name") or job["created_by"],
            "label": p.get("label"), "engine": "native", "geom_options": p.get("geom_options"), "engine_version": r.get("engine_version")})
        _audit(ctx, c, "PARAM_SET_REGISTER", psid, {"engine": "native", "source_path": picked.get("source_path"), "shell_only": shell_only})
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
