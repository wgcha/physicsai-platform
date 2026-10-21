"""① 학습데이터 동기 API(phase2 §6.3, §12.5): 학습 설정 조회·파라미터 표 저장·tpl 생성·DOE 조회."""

from __future__ import annotations

import os
from typing import Any

from physicsai_core.db.repositories import hpc as hpc_repo
from physicsai_core.db.repositories import studies as studies_repo
from physicsai_core.db.repositories import train as train_repo
from physicsai_core.errors import DomainError
from physicsai_core.path_links import is_link_or_reparse
from physicsai_core.fileutil import copy_file, sha256_file, write_json, write_text
from physicsai_core.paths import backup_existing, backup_stamp, display_path, resolve_in_study
from physicsai_core.sampling import registry as sampling_registry
from physicsai_core.stage1_train_data import doe_samples
from physicsai_core.stage1_train_data import doe_types as dt_mod
from physicsai_core.stage1_train_data import train_params as tp
from physicsai_core.stage1_train_data import train_tpl

from ..auth import Principal
from ..context import AppContext
from .common import audit, clamp_limit, decode_cursor, encode_cursor, require_config_ok, require_power, study_root
from .job_params.stage1_train_data import tpl_is_stale

TPL_REL = "01_train/tpl/simlab_parametered_mesh.tpl"
TPL_COPY_REL = "01_train/tpl/TEMAPLATE_simlab_parametered_mesh.tpl"


def _ai(ctx: AppContext) -> str:
    return ctx.settings.storage.ai_root


def setup_out(ctx: AppContext, study: dict[str, Any], s: dict[str, Any] | None) -> dict[str, Any]:
    if s is None:
        return {"study_id": study["id"], "cad": None, "extract_job_id": None, "parameters": [], "used_count": 0, "tpl": None,
                "version": 0, "updated_by_name": None, "updated_at": None}
    params = [tp.with_validity(p) for p in (s["parameters"] or [])]
    cad = None
    if s.get("cad_file_name"):
        cad = {"source_path": s["cad_source_path"], "file_name": s["cad_file_name"], "sha256": s["cad_sha256"],
               "display_path": display_path(_ai(ctx), study["folder_name"], f"01_train/cad/{s['cad_file_name']}")}
    tpl = None
    if s.get("tpl_rel"):
        tpl = {"generated_at": s["tpl_generated_at"], "sha256": s["tpl_sha256"],
               "display_path": display_path(_ai(ctx), study["folder_name"], s["tpl_rel"]),
               "params": s["tpl_params"] or [], "warnings": s["tpl_warnings"] or [], "stale": tpl_is_stale(s)}
    return {"study_id": study["id"], "cad": cad, "extract_job_id": s["extract_job_id"], "parameters": params,
            "used_count": sum(1 for p in params if p.get("use")), "tpl": tpl, "version": s["version"], "engine": s.get("engine") or "altair",
            "updated_by_name": s["updated_by_name"], "updated_at": s["updated_at"]}


def get_setup(ctx: AppContext, study_id: str) -> dict[str, Any]:
    with ctx.engine.connect() as conn:
        st = studies_repo.require(conn, study_id)
        s = train_repo.get_setup(conn, study_id)
    return setup_out(ctx, st, s)


def put_params(ctx: AppContext, principal: Principal, study_id: str, body: Any, rid: str, ip: str | None) -> dict[str, Any]:
    with ctx.engine.begin() as conn:
        st = studies_repo.require(conn, study_id)
        require_power(principal, st["project_id"])
        require_config_ok(ctx)
        s = train_repo.get_setup(conn, study_id, for_update=True)
        if s is None or not s["parameters"]:
            raise DomainError("TRAIN_PARAMS_REQUIRED", "파라미터를 먼저 추출하세요(①-1)", status=409)
        if s["version"] != body.version:
            raise DomainError("VERSION_CONFLICT", "다른 사용자가 먼저 수정했습니다. 새로 고친 뒤 다시 시도하세요", status=409)
        new, problems = tp.apply_update(s["parameters"], [u.model_dump() for u in body.parameters])
        if problems:
            raise DomainError("TRAIN_PARAMS_INVALID", "파라미터 표 검증에 실패했습니다", status=422, problems=problems)
        vals: dict[str, Any] = {"parameters": new, "updated_by": principal.user_id, "updated_by_name": principal.display_name}
        if tp.definition_key(new) != tp.definition_key(s["parameters"]):
            vals["tpl_params"] = None  # 표가 바뀌면 tpl stale(TPL_STALE)
        s = train_repo.update_setup(conn, study_id, body.version, **vals)
        root = study_root(ctx, st)
        pj = resolve_in_study(root, "01_train/params.json")
        backup_existing(root, [pj], "params", backup_stamp())
        write_json(pj, {"schema_version": 1, "parameters": new})
        audit(conn, principal, "TRAIN_PARAMS_UPDATE", "study", study_id, {"used": sum(1 for p in new if p["use"])}, rid, ip)
    return setup_out(ctx, st, s)


def generate_tpl(ctx: AppContext, principal: Principal, study_id: str, version: int, rid: str, ip: str | None) -> dict[str, Any]:
    cfg = ctx.settings
    with ctx.engine.begin() as conn:
        st = studies_repo.require(conn, study_id)
        require_power(principal, st["project_id"])
        require_config_ok(ctx)
        s = train_repo.get_setup(conn, study_id, for_update=True)
        if s is not None and s.get("engine") == "native":  # geometry-engine.md §7.3.2: tpl은 altair 전용
            raise DomainError("ENGINE_NATIVE_NO_TPL", "Native 형상 엔진에는 tpl이 없습니다 — 파라미터 표만 확정하고 DOE를 만드세요",
                              status=409)
        if s is None or not s["parameters"] or not s.get("cad_file_name"):
            raise DomainError("TRAIN_PARAMS_REQUIRED", "파라미터를 먼저 추출하세요(①-1)", status=409)
        if not cfg.resources.simlab_tpl_template:
            raise DomainError("RESOURCE_NOT_CONFIGURED", "관리자 설정 필요: resources.simlab_tpl_template", status=409,
                              missing=["resources.simlab_tpl_template"])
        if s["version"] != version:
            raise DomainError("VERSION_CONFLICT", "다른 사용자가 먼저 수정했습니다. 새로 고친 뒤 다시 시도하세요", status=409)
        used = tp.used(s["parameters"])
        bad = [p["name"] for p in used if not tp.with_validity(p)["valid"]]
        if not used or bad:
            raise DomainError("TRAIN_PARAMS_INVALID", "사용 파라미터가 유효하지 않습니다", status=422,
                              problems=[{"name": n, "code": "INVALID", "message": "유효하지 않은 행"} for n in bad]
                              or [{"name": "", "code": "NO_PARAMETER_USED", "message": "사용할 파라미터가 1개 이상 필요합니다"}])
        root = study_root(ctx, st)
        src = cfg.resources.simlab_tpl_template
        if not os.path.isfile(src):
            raise DomainError("RESOURCE_NOT_CONFIGURED", f"tpl 템플릿 파일이 없습니다: {src}", status=409,
                              missing=["resources.simlab_tpl_template"])
        stamp = backup_stamp()
        session_copy = resolve_in_study(root, TPL_COPY_REL)
        out = resolve_in_study(root, TPL_REL)
        backup_existing(root, [session_copy], "tpl", stamp)
        copy_file(src, session_copy)  # 원본 GUI:353-354 세션 사본
        with open(session_copy, encoding="utf-8") as fh:
            text = fh.read()
        try:
            gen = train_tpl.generate(text, used, s["cad_file_name"], train_tpl.TplRules.from_settings(cfg.train_data))
        except train_tpl.TplTemplateInvalid as exc:
            raise DomainError("TPL_TEMPLATE_INVALID", "tpl 템플릿 형식이 올바르지 않습니다", status=422, problems=exc.problems) from None
        probs = train_tpl.validate_generated(gen, used)
        if probs:
            raise DomainError("TPL_TEMPLATE_INVALID", "생성된 tpl이 검증을 통과하지 못했습니다", status=422, problems=probs)
        backup_existing(root, [out], "tpl", stamp)
        write_text(out, gen)
        s = train_repo.set_tpl_generated(
            conn, study_id, version, tpl_rel=TPL_REL, tpl_sha256=sha256_file(out),
            tpl_params=train_tpl.tpl_params_snapshot(used), tpl_warnings=tp.integer_format_warnings(s["parameters"]),
            updated_by=principal.user_id, updated_by_name=principal.display_name,
        )
        audit(conn, principal, "TRAIN_TPL_GENERATE", "study", study_id, {"used": len(used)}, rid, ip)
    return setup_out(ctx, st, s)


def doe_types(ctx: AppContext) -> list[dict[str, Any]]:
    """정의 파일 유형 그대로 + S15 꾸밈(§20.6): desc_id·recommended(설정 `train_data.recommended_doe_type`)·influence_class."""
    types = dt_mod.load_doe_types(ctx.settings.resources.doe_design_type_json, ctx.settings.ui.max_artifact_bytes)
    rec = ctx.settings.train_data.recommended_doe_type
    out = []
    for t in types:
        cls, _note = sampling_registry.doe_influence(t["value"], {"RESOLUTION": "3"})
        out.append({**t, "desc_id": sampling_registry.DOE_DESC_IDS.get(t["value"]),
                    "recommended": bool(rec) and t["value"] == rec, "influence_class": cls})
    return out


def doe_out(ctx: AppContext, conn: Any, study: dict[str, Any], d: dict[str, Any]) -> dict[str, Any]:
    counts = train_repo.run_state_counts(conn, d["id"])
    return {
        "id": d["id"], "study_id": d["study_id"], "job_id": d["job_id"], "status": d["status"], "doe_label": d["doe_label"],
        "doe_type": d["doe_type"], "num_runs_requested": d["num_runs_requested"], "options": d["options"] or {},
        "multi_execution": d["multi_execution"], "radioss_assem_source_path": d["radioss_assem_source_path"],
        "run_count": d["run_count"], "sample_status": d["sample_status"], "engine": d["engine"],
        "engine_version": d.get("engine_version"), "collected_count": counts["COLLECTED"],
        "solve_failed_count": counts["SOLVE_FAILED"], "has_run_responses": bool(d["responses_rel"]),
        "dir_display_path": display_path(_ai(ctx), study["folder_name"], d["dir_rel"]),
        "results_display_path": display_path(_ai(ctx), study["folder_name"], f"01_train/results/{d['id']}"),
        "created_by_name": d["created_by_name"], "created_at": d["created_at"], "run_state_counts": counts,
        **_platform_out(conn, d),
    }


def _platform_out(conn: Any, d: dict[str, Any]) -> dict[str, Any]:
    """S18 §23.4: generator·sampling{kind, label, desc_id, meta}·gen(run별 생성 집계) — 플랫폼 DOE만 sampling·gen."""
    if d.get("generator") != "PLATFORM":
        return {"generator": "hyperstudy", "sampling": None, "gen": None}
    if d.get("engine") == "native":  # native(geometry-engine.md §7.3.3) = 플랫폼 생성의 한 경로. 표본은 NATIVE_LHS, run별 점 표 없음
        return {"generator": "platform", "sampling": None, "gen": None}
    sp = d.get("sampling") or {}
    kind = str(sp.get("kind") or sampling_registry.kind_of_source(d["doe_type"]) or "")
    label = sampling_registry.METHODS[kind][1] if kind in sampling_registry.METHODS else d["doe_label"]
    return {"generator": "platform",
            "sampling": {"kind": kind, "label": label, "desc_id": sampling_registry.platform_desc_id(kind),
                         "meta": sp.get("meta")},
            "gen": train_repo.point_counts(conn, d["id"])}


def list_does(ctx: AppContext, study_id: str) -> list[dict[str, Any]]:
    with ctx.engine.connect() as conn:
        st = studies_repo.require(conn, study_id)
        return [doe_out(ctx, conn, st, d) for d in train_repo.list_does(conn, study_id)]


def _require_doe(conn: Any, doe_id: str) -> dict[str, Any]:
    d = train_repo.get_doe(conn, doe_id)
    if d is None:
        raise DomainError("NOT_FOUND", "DOE를 찾을 수 없습니다", status=404)
    return d


def get_doe(ctx: AppContext, doe_id: str) -> dict[str, Any]:
    with ctx.engine.connect() as conn:
        d = _require_doe(conn, doe_id)
        st = studies_repo.require(conn, d["study_id"])
        return doe_out(ctx, conn, st, d)


def list_runs(ctx: AppContext, doe_id: str, state: str | None, limit: int | None, cursor: str | None
              ) -> tuple[list[dict[str, Any]], str | None]:
    lim, off = clamp_limit(limit), decode_cursor(cursor)
    with ctx.engine.connect() as conn:
        d = _require_doe(conn, doe_id)
        st = studies_repo.require(conn, d["study_id"])
        rows = train_repo.runs_for_doe(conn, doe_id, states=state.split(",") if state else None, limit=lim + 1, offset=off)
        hids = [r["hpc_job_id"] for r in rows if r["hpc_job_id"]]
        hmap: dict[str, Any] = {}
        if hids:
            for h in hpc_repo.get_many(conn, hids):
                hmap[h["id"]] = {"external_job_id": h["external_job_id"], "state": h["state"], "attempt_no": h["attempt_no"]}
    out = []
    root = study_root(ctx, st)
    for r in rows[:lim]:
        out.append({"run_key": r["run_key"], "state": r["state"], "starter_name": r["starter_name"],
                    "input_display_path": display_path(_ai(ctx), st["folder_name"], r["input_rel"]),
                    "hpc": hmap.get(r["hpc_job_id"]) if r["hpc_job_id"] else None, "result": r["result_summary"],
                    "h3d_rel": run_h3d_rel(root, r), "updated_at": r["updated_at"]})
    return out, (encode_cursor(off + lim) if len(rows) > lim else None)


def run_h3d_rel(root: str, r: dict[str, Any]) -> str | None:
    """run 결과 .h3d의 Study 기준 상대 경로(geometry-view GV-C3) — 3D 컨투어 SOLVER_H3D `{study_id, h3d_rel}`용.

    수집된 run(`result_rel` 있음, 요약 h3d ≥ 1)만 결과 폴더를 훑는다(`_backup`·링크 제외). 여러 개면 경로 정렬 첫 번째.
    없거나 Study 밖이면 None(읽기 전용, DB 비저장)."""
    summ = r.get("result_summary") or {}
    rel = r.get("result_rel")
    if not rel or not int(summ.get("h3d") or 0):
        return None
    try:
        base = resolve_in_study(root, rel)
    except DomainError:
        return None
    found: list[str] = []
    for dirpath, dirnames, filenames in os.walk(base, followlinks=False):
        dirnames[:] = sorted(d for d in dirnames if d != "_backup" and not is_link_or_reparse(os.path.join(dirpath, d)))
        for f in sorted(filenames):
            p = os.path.join(dirpath, f)
            if f.lower().endswith(".h3d") and not is_link_or_reparse(p) and os.path.isfile(p):
                found.append(os.path.relpath(p, base).replace(os.sep, "/"))
    if not found:
        return None
    return f"{rel.replace(os.sep, '/').rstrip('/')}/{sorted(found)[0]}"


def doe_samples_page(ctx: AppContext, doe_id: str, limit: int | None, cursor: str | None) -> dict[str, Any]:
    lim, off = clamp_limit(limit), decode_cursor(cursor)
    with ctx.engine.connect() as conn:
        d = _require_doe(conn, doe_id)
        st = studies_repo.require(conn, d["study_id"])
    if not d["samples_rel"]:
        raise DomainError("SAMPLES_MISSING", "DOE 샘플 표가 없습니다", status=404)
    root = study_root(ctx, st)
    header, rows = doe_samples.read_samples_csv(resolve_in_study(root, d["samples_rel"]))
    if d["responses_rel"]:
        rh, rrows = doe_samples.read_samples_csv(resolve_in_study(root, d["responses_rel"]))
        resp = {r["run_key"]: r["values"] for r in rrows}
        for r in rows:
            r["measured"] = {n: resp.get(r["run_key"], {}).get(n) for n in rh[1:]}
        header = header + [f"resp:{n}" for n in rh[1:]]
    page = rows[off: off + lim]
    return {"columns": header, "rows": page, "next_cursor": encode_cursor(off + lim) if off + lim < len(rows) else None}
