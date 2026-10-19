"""④ native 세트 API 서비스(geometry-engine.md §7.4~§7.6): 등록(202 job)·다시 준비·피처 조회·옵션 변경·응답 보강."""

from __future__ import annotations

import json
import os
import uuid
from typing import Any

from physicsai_core.db.repositories import artifacts as art_repo
from physicsai_core.db.repositories import param_sets as ps_repo
from physicsai_core.db.repositories import studies as studies_repo
from physicsai_core.errors import DomainError
from physicsai_core.geometry import features_view
from physicsai_core.geometry.options import effective_options, tag_section_changed
from physicsai_core.geometry.prep import prep_state
from physicsai_core.geometry.reports import ReportError, read_report
from physicsai_core.paths import allowed_roots, check_user_path, resolve_in_study
from physicsai_core.stage4_predict import param_discover_native as dn

from ..auth import Principal
from ..context import AppContext
from . import jobs as jobs_svc
from .common import audit, study_root
from .geometry_gate import require_native_available, validate_geom_options


def wants_native(ctx: AppContext, body: Any, *, discover: bool = False) -> bool:
    """등록·discover 요청의 엔진: 명시 값 → 없으면 geometry.engine 기본값(등록은 mode=discover일 때만 기본값을 따른다)."""
    eng = getattr(body, "engine", None)
    if eng is not None:
        return eng == "native"
    return (discover or getattr(body, "mode", None) == "discover") and ctx.settings.geometry.engine == "native"


def discover_native_out(ctx: AppContext, path: str) -> dict[str, Any]:
    cp = check_user_path(path, allowed_roots(ctx.settings, imports=True))
    d = dn.discover_native(cp.path, ctx.settings)
    out = d.out()
    out["engine"] = "native"
    out["cad"] = [{**c, "kind": "parts" if c["name"].casefold() == dn.PARTS_DIR else "file"} for c in out["cad"]]
    return out


def register_native(ctx: AppContext, principal: Principal, study_id: str, body: Any, label: str | None, rid: str,
                    ip: str | None) -> dict[str, Any]:
    """POST /studies/{id}/param-sets {engine:native} → 후보를 읽기만 확인하고 PARAM_SET_NATIVE 작업을 만든다(202)."""
    if getattr(body, "mode", None) != "discover":
        raise DomainError("INVALID_PARAMS", "native 형상 엔진은 mode=discover로만 등록합니다", status=422)
    require_native_available(ctx.settings)
    over = validate_geom_options(ctx.settings, body.geom_options)
    cp = check_user_path(body.path, allowed_roots(ctx.settings, imports=True))
    choice = body.choice.model_dump(exclude_unset=True) if body.choice is not None else {}
    d = dn.discover_native(cp.path, ctx.settings)
    cad, assem, probs = dn.resolve_choice_native(d, choice)
    problems = d.problems + probs
    if problems or cad is None or assem is None:
        raise DomainError("PARAM_SET_INVALID", "프로젝트 폴더에서 파라미터 세트를 구성할 수 없습니다", status=422,
                          problems=problems or [{"code": "DISCOVER_INCOMPLETE", "message": "STEP·조립 폴더를 모두 찾아야 합니다"}])
    job = jobs_svc.create_job(ctx, principal, study_id, "PARAM_SET_NATIVE",
                              {"mode": "new", "path": cp.path, "choice": {"cad": cad, "radioss_assem": assem["rel"]},
                               "label": label, "geom_options": over or None}, rid, ip)
    return {"job_id": job["id"]}


def prepare_native(ctx: AppContext, principal: Principal, ps_id: str, rid: str, ip: str | None) -> dict[str, Any]:
    """POST /param-sets/{id}/native-prepare → reprep 작업(202)."""
    with ctx.engine.connect() as conn:
        p = ps_repo.get(conn, ps_id)
    if p is None:
        raise DomainError("NOT_FOUND", "파라미터 세트를 찾을 수 없습니다", status=404)
    job = jobs_svc.create_job(ctx, principal, p["study_id"], "PARAM_SET_NATIVE", {"mode": "reprep", "param_set_id": ps_id}, rid, ip)
    return {"job_id": job["id"]}


def _S(ctx: AppContext, conn: Any, p: dict[str, Any]) -> str:
    return resolve_in_study(study_root(ctx, studies_repo.require(conn, p["study_id"])), p["stored_rel"])


def _features_doc(ctx: AppContext, S: str) -> dict[str, Any] | None:
    try:
        return read_report(os.path.join(S, "native", "extract", "parameter_features.json"), ctx.settings.geometry.max_report_bytes)
    except ReportError:
        return None


def _state(ctx: AppContext, p: dict[str, Any]) -> tuple[Any, dict[str, Any], str]:
    s = ctx.settings
    opts, _ = effective_options(s.geometry.defaults, p.get("geom_options"))
    with ctx.engine.connect() as conn:
        S = _S(ctx, conn, p)
    st = prep_state(S, step_exts=s.geometry.step_extensions, mesh_include_name=s.predict.mesh_include_name,
                    renum_csv_name=s.predict.renum_csv_name, opts=opts)
    return st, opts, S


def prep_state_of(ctx: AppContext, p: dict[str, Any]) -> Any:
    """native 세트의 준비본 상태(PrepState), altair 세트면 None. 엔진 버전 비교는 워커가 실행 때 한다(API는 paicad를 실행하지 않는다)."""
    return _state(ctx, p)[0] if (p.get("engine") or "altair") == "native" else None


def enrich(ctx: AppContext, p: dict[str, Any], out: dict[str, Any]) -> dict[str, Any]:
    """native 세트 응답에 geom_options_effective·native{prep_status…} 추가(altair는 그대로)."""
    if (p.get("engine") or "altair") != "native":
        return out
    st, opts, S = _state(ctx, p)
    doc = _features_doc(ctx, S) or {}
    out["geom_options_effective"] = opts
    out["native"] = {"prep_status": st.status, "prep_reason": st.reason, "feature_count": len(doc.get("features", []))}
    return out


def features(ctx: AppContext, ps_id: str) -> dict[str, Any]:
    with ctx.engine.connect() as conn:
        p = ps_repo.get(conn, ps_id)
        if p is None:
            raise DomainError("NOT_FOUND", "파라미터 세트를 찾을 수 없습니다", status=404)
        if (p.get("engine") or "altair") != "native":
            raise DomainError("ENGINE_MISMATCH", "native 형상 엔진 세트가 아닙니다", status=409)
        S = _S(ctx, conn, p)
        arts = art_repo.list_by_prefix(conn, p["study_id"], "FEATURE_PNG", p["stored_rel"].rstrip("/") + "/native/extract/features/")
    doc = _features_doc(ctx, S)
    if doc is None:
        raise DomainError("NATIVE_PREP_MISSING", "형상 피처 파일이 없습니다 — 형상 준비를 다시 하세요", status=409)
    ids: dict[str, str] = {}
    for a in arts:  # 최신이 먼저 — 이름마다 첫 항목만
        ids.setdefault(os.path.splitext(os.path.basename(a["rel_path"]))[0], a["id"])
    return features_view.summary(doc, ids)


def patch_geom_options(ctx: AppContext, conn: Any, principal: Principal, p: dict[str, Any], raw: dict[str, Any] | None,
                       rid: str, ip: str | None) -> None:
    """PATCH geom_options(전체 덮어쓰기). altair 세트는 422. tag 절이 바뀌면 prep_status가 STALE로 보인다(준비본 해시 비교)."""
    if (p.get("engine") or "altair") != "native":
        raise DomainError("ENGINE_MISMATCH", "geom_options는 native 형상 엔진 세트에서만 바꿀 수 있습니다", status=422)
    over = validate_geom_options(ctx.settings, raw)
    ps_repo.set_values(conn, p["id"], geom_options=over or None)
    audit(conn, principal, "PARAM_SET_UPDATE", "param_set", p["id"],
          {"geom_options": over, "tag_changed": tag_section_changed(p.get("geom_options"), over)}, rid, ip)




def from_train(ctx: AppContext, principal: Principal, study: dict[str, Any], d: dict[str, Any], D: str, label: str | None,
               body: Any, rid: str, ip: str | None) -> dict[str, Any]:
    """①→④(native DOE): `D/cad`→`cad/`, `A`→`radioss_assem/`, `D/native`→`native/`(prep.json은 S 기준으로 다시 씀). paicad 실행 없음(§7.3.4)."""
    import shutil
    from datetime import datetime, timezone

    from physicsai_core.fileutil import copy_tree, write_json
    from physicsai_core.geometry.prep import PREP_JSON, prep_document
    from physicsai_core.stage4_predict.param_set_native import validate_native_folder

    from .common import param_set_out

    s = ctx.settings
    root = study_root(ctx, study)
    A = resolve_in_study(root, f"01_train/radioss_assem/{d['id']}")
    if not os.path.isdir(os.path.join(D, "cad")) or not os.path.isdir(os.path.join(D, "native")) or not os.path.isdir(A):
        raise DomainError("PARAM_SET_INVALID", "DOE 준비본(cad·native·조립 폴더)이 없습니다", status=422,
                          problems=[{"code": "NATIVE_PREP_MISSING", "message": "DOE의 형상 준비 폴더를 찾을 수 없습니다"}])
    T = resolve_in_study(root, f"logs/_paramset_tmp/{uuid.uuid4()}")
    os.makedirs(T)
    copy_tree(os.path.join(D, "cad"), os.path.join(T, "cad"))
    copy_tree(os.path.join(D, "native"), os.path.join(T, "native"))
    for n in sorted(os.listdir(A)):
        if os.path.isfile(os.path.join(A, n)) and not n.lower().startswith("eps_mesh"):
            copy_tree_file = os.path.join(T, "radioss_assem", n)
            os.makedirs(os.path.dirname(copy_tree_file), exist_ok=True)
            shutil.copyfile(os.path.join(A, n), copy_tree_file)
    old = {}
    try:
        with open(os.path.join(D, "native", "prep.json"), encoding="utf-8") as fh:
            old = json.load(fh)
    except (OSError, ValueError):
        pass
    snap = d.get("parameters_snapshot") or []
    write_json(os.path.join(T, "parameters.json"), {
        "schema_version": 1, "unit_system": body.unit_system or "mm-ton-s",
        "parameters": [{"name": p["name"], "nominal": p["nominal"], "min": p["min"], "max": p["max"], "unit": p.get("unit", "")}
                       for p in snap]})
    opts, _ = effective_options(s.geometry.defaults, d.get("geom_options"))
    write_json(os.path.join(T, PREP_JSON), prep_document(
        T, step_exts=s.geometry.step_extensions, mesh_include_name=s.predict.mesh_include_name,
        renum_csv_name=s.predict.renum_csv_name, opts=opts, engine_version=d.get("engine_version") or old.get("engine_version"),
        ocp_version=old.get("ocp_version"), job_id=old.get("job_id"), created_at=datetime.now(timezone.utc).isoformat()))
    f = validate_native_folder(T, max_total_bytes=s.param_set.max_total_bytes, starter_glob=s.predict.starter_glob,
                               renum_csv_name=s.predict.renum_csv_name, baseline_inc_name=s.predict.mesh_include_name,
                               step_extensions=s.geometry.step_extensions)
    if not f.ok:
        raise DomainError("PARAM_SET_INVALID", "파라미터 세트 검증에 실패했습니다", status=422, problems=f.problems)
    psid = str(uuid.uuid4())
    src_label = f"① DOE {d['id'][:8]}"
    write_json(os.path.join(T, "source.json"), {"source_path": src_label, "registered_at": datetime.now(timezone.utc).isoformat(),
                                                "mode": "from_train", "doe_id": d["id"]})
    stored_rel = f"04_params/{psid}"
    dst = resolve_in_study(root, stored_rel)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    moved = False
    try:
        with ctx.engine.begin() as conn:
            ps_repo.insert_current(conn, {
                "id": psid, "study_id": study["id"], "source_path": src_label, "stored_rel": stored_rel + "/",
                "unit_system": f.unit_system, "parameters": f.parameters, "responses": [], "sample_count": 0,
                "sample_has_measured": False, "cad_file_name": f.cad_file or "parts/", "tpl_rel": None,
                "assem_rel": f"{stored_rel}/radioss_assem/", "starter_name": f.starter_name, "input_kind": "assembly",
                "tpl_params": [], "registered_by": principal.user_id, "registered_by_name": principal.display_name,
                "label": label, "origin": "TRAIN_DOE", "train_doe_id": d["id"], "engine": "native",
                "geom_options": d.get("geom_options"), "engine_version": d.get("engine_version")})
            audit(conn, principal, "PARAM_SET_FROM_TRAIN", "param_set", psid,
                  {"doe_id": d["id"], "runs": body.runs, "engine": "native"}, rid, ip)
            os.replace(T, dst)
            moved = True
            row = ps_repo.get(conn, psid)
    except BaseException:
        if moved and os.path.isdir(dst) and not os.path.lexists(T):
            os.replace(dst, T)  # 04_params에 DB 행 없는 고아 폴더를 남기지 않는다(삭제 없음)
        raise
    return enrich(ctx, row, {**param_set_out(row), "warnings": []})  # type: ignore[arg-type]
