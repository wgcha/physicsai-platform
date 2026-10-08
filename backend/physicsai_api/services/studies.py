"""Study·경로 확인·데이터셋·모델·Final·파라미터 세트·예측 입력 확인(§10.3, §10.4)."""

from __future__ import annotations

import fnmatch
import os
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import and_, select

from physicsai_core import nearest as nearest_mod
from physicsai_core import param_sets as ps_mod
from physicsai_core.dataset_split import collect_h3d, n_eval_groups, split_files
from physicsai_core.db.repositories import datasets as datasets_repo
from physicsai_core.db.repositories import jobs as jobs_repo
from physicsai_core.db.repositories import models as models_repo
from physicsai_core.db.repositories import param_sets as ps_repo
from physicsai_core.db.repositories import studies as studies_repo
from physicsai_core.db.tables import jobs
from physicsai_core.errors import DomainError
from physicsai_core.fileutil import write_json
from physicsai_core.paths import check_user_path, file_safety_problem, resolve_in_study

from ..auth import Principal
from ..context import AppContext
from .common import (
    audit,
    clamp_limit,
    dataset_out,
    decode_cursor,
    encode_cursor,
    model_out,
    param_set_out,
    require_config_ok,
    require_power,
    study_out,
    study_root,
)

# ---- Study ----------------------------------------------------------------


def list_studies(ctx: AppContext, principal: Principal, project_id: str | None, status: str | None,
                 limit: int | None, cursor: str | None) -> tuple[list[dict[str, Any]], str | None]:
    lim, off = clamp_limit(limit), decode_cursor(cursor)
    with ctx.engine.connect() as conn:
        rows = studies_repo.list_(conn, project_id=project_id, status=status, limit=lim + 1, offset=off)
    nxt = encode_cursor(off + lim) if len(rows) > lim else None
    return [study_out(s, principal, ctx.settings.storage.ai_root) for s in rows[:lim]], nxt


def _stage_status(conn: Any, study_id: str) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for stage in (3, 4):
        r = conn.execute(
            select(jobs.c.id, jobs.c.job_type, jobs.c.state, jobs.c.created_at)
            .where(and_(jobs.c.study_id == study_id, jobs.c.stage == stage))
            .order_by(jobs.c.created_at.desc())
            .limit(1)
        ).first()
        out[str(stage)] = (
            {"latest_job_id": r.id, "latest_job_type": r.job_type, "latest_state": r.state}
            if r else {"latest_job_id": None, "latest_job_type": None, "latest_state": None}
        )
    return out


def get_study(ctx: AppContext, principal: Principal, study_id: str) -> dict[str, Any]:
    with ctx.engine.connect() as conn:
        s = studies_repo.require(conn, study_id)
        out = study_out(s, principal, ctx.settings.storage.ai_root)
        fm = models_repo.get(conn, s["final_model_id"]) if s["final_model_id"] else None
        out["final_model"] = model_out(fm, s["final_model_id"], with_curve=False, study=s, ai_root=ctx.settings.storage.ai_root) if fm else None
        out["stage_status"] = _stage_status(conn, study_id)
        cur = ps_repo.current(conn, study_id)
        out["current_param_set_id"] = cur["id"] if cur else None
    return out


def create_study(ctx: AppContext, principal: Principal, token: str | None, body: Any, rid: str, ip: str | None) -> dict[str, Any]:
    projects = ctx.auth.projects(principal, token, rid)
    if body.project_id not in {p["id"] for p in projects}:
        raise DomainError("PROJECT_NOT_FOUND", "대시보드 프로젝트를 찾을 수 없습니다", status=404)
    require_power(principal, body.project_id)
    require_config_ok(ctx)
    sid = str(uuid.uuid4())
    ai_root = os.path.normpath(ctx.settings.storage.ai_root)
    folder = os.path.join(ai_root, body.folder_name)
    with ctx.engine.begin() as conn:
        studies_repo.insert(conn, {
            "id": sid, "project_id": body.project_id, "folder_name": body.folder_name, "title": body.title,
            "status": "ACTIVE", "ai_root_snapshot": ai_root, "created_by": principal.user_id,
            "created_by_name": principal.display_name,
        })
        if os.path.lexists(folder):
            raise DomainError("FOLDER_EXISTS", "AI 루트에 같은 이름의 폴더가 이미 있습니다", status=409)
        os.mkdir(folder)
        os.mkdir(os.path.join(folder, "00_inbox"))
        write_json(os.path.join(folder, "study.json"), {
            "id": sid, "project_id": body.project_id, "title": body.title,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        audit(conn, principal, "STUDY_CREATE", "study", sid, {"folder_name": body.folder_name}, rid, ip)
        s = studies_repo.require(conn, sid)
    return study_out(s, principal, ctx.settings.storage.ai_root)


def patch_study(ctx: AppContext, principal: Principal, study_id: str, body: Any, rid: str, ip: str | None) -> dict[str, Any]:
    with ctx.engine.begin() as conn:
        s = studies_repo.require(conn, study_id)
        require_power(principal, s["project_id"])
        s = studies_repo.update_cas(conn, study_id, body.version, title=body.title)
        audit(conn, principal, "STUDY_UPDATE", "study", study_id, {"title": body.title}, rid, ip)
    return study_out(s, principal, ctx.settings.storage.ai_root)


def archive_study(ctx: AppContext, principal: Principal, study_id: str, rid: str, ip: str | None) -> dict[str, Any]:
    with ctx.engine.begin() as conn:
        s = studies_repo.require(conn, study_id, for_update=True)
        require_power(principal, s["project_id"])
        if jobs_repo.has_active_jobs(conn, study_id):
            raise DomainError("STUDY_HAS_ACTIVE_JOB", "대기 중이거나 실행 중인 작업이 있어 보관할 수 없습니다", status=409)
        s = studies_repo.update_cas(conn, study_id, None, status="ARCHIVED")
        audit(conn, principal, "STUDY_ARCHIVE", "study", study_id, None, rid, ip)
    return study_out(s, principal, ctx.settings.storage.ai_root)


# ---- 경로 확인 ---------------------------------------------------------------


def _list_direct(folder: str, patterns: list[str]) -> list[str]:
    out = []
    for name in sorted(os.listdir(folder)):
        p = os.path.join(folder, name)
        if os.path.isfile(p) and any(fnmatch.fnmatch(name.lower(), pat.lower()) for pat in patterns):
            out.append(name)
    return out


def inspect_model_folder(folder: str, log_globs: list[str]) -> dict[str, list[str]]:
    psmdl = _list_direct(folder, ["*.psmdl"])
    pscfg = _list_direct(folder, ["*.pscfg"])
    logs = _list_direct(folder, log_globs)
    return {"psmdl": psmdl, "pscfg": pscfg, "logs": logs}


def inspect_path(ctx: AppContext, principal: Principal, study_id: str, body: Any) -> dict[str, Any]:
    s_cfg = ctx.settings
    with ctx.engine.connect() as conn:
        s = studies_repo.require(conn, study_id)
    require_power(principal, s["project_id"])
    roots = [s_cfg.storage.ai_root]
    if body.purpose == "MODEL_FOLDER":
        roots += list(s_cfg.storage.allowed_import_roots)
    cp = check_user_path(body.path, roots)
    problems: list[dict[str, Any]] = []
    summary: dict[str, Any] = {}
    if body.purpose == "DATASET_INPUT":
        files = collect_h3d(cp.path)
        for f in files:
            why = file_safety_problem(f, cp.path)
            if why:
                problems.append({"code": "PATH_UNSAFE", "message": f"{why}가 포함된 파일", "file": os.path.relpath(f, cp.path)})
        groups = len(files) if s_cfg.dataset.split_group == "file" else len({os.path.dirname(f) for f in files})
        if len(files) < s_cfg.dataset.min_h3d_files or groups < 2:
            problems.append({"code": "TOO_FEW_H3D", "message": f"h3d 파일이 {s_cfg.dataset.min_h3d_files}개 이상 필요합니다"})
        sp = split_files(files, s_cfg.dataset.holdout_ratio, s_cfg.dataset.seed, s_cfg.dataset.split_group)
        summary = {
            "h3d_count": len(files),
            "sample_files": [os.path.relpath(f, cp.path).replace(os.sep, "/") for f in files[:10]],
            "expected_train": len(sp.train),
            "expected_eval": len(sp.eval) if groups >= 2 else (n_eval_groups(groups, s_cfg.dataset.holdout_ratio) if groups else 0),
        }
    elif body.purpose == "MODEL_FOLDER":
        summary = inspect_model_folder(cp.path, s_cfg.training_log.log_globs)
        if len(summary["psmdl"]) != 1:
            problems.append({"code": "PSMDL_COUNT", "message": f".psmdl 파일이 정확히 1개 있어야 합니다(현재 {len(summary['psmdl'])}개)"})
        if len(summary["pscfg"]) != 1:
            problems.append({"code": "PSCFG_COUNT", "message": f".pscfg 파일이 정확히 1개 있어야 합니다(현재 {len(summary['pscfg'])}개)"})
        if len(summary["logs"]) > 1:
            problems.append({"code": "LOG_SELECT_REQUIRED", "message": "학습 로그 후보가 여러 개입니다. 로그 파일을 선택하세요"})
    else:
        f = ps_mod.validate_folder(cp.path, max_samples=s_cfg.param_set.max_samples,
                                   max_total_bytes=s_cfg.param_set.max_total_bytes, starter_glob=s_cfg.predict.starter_glob)
        problems.extend(f.problems)
        summary = f.summary()
    return {"normalized_path": cp.path, "ok": not problems, "problems": problems, "summary": summary}


# ---- 데이터셋·모델 ---------------------------------------------------------------


def list_datasets(ctx: AppContext, study_id: str, limit: int | None, cursor: str | None) -> tuple[list[dict[str, Any]], str | None]:
    lim, off = clamp_limit(limit), decode_cursor(cursor)
    with ctx.engine.connect() as conn:
        st = studies_repo.require(conn, study_id)
        rows = datasets_repo.list_for_study(conn, study_id, lim + 1, off)
    return [dataset_out(d, st, ctx.settings.storage.ai_root) for d in rows[:lim]], (encode_cursor(off + lim) if len(rows) > lim else None)


def get_dataset(ctx: AppContext, dataset_id: str) -> dict[str, Any]:
    with ctx.engine.connect() as conn:
        d = datasets_repo.get(conn, dataset_id)
        st = studies_repo.get(conn, d["study_id"]) if d else None
    if d is None:
        raise DomainError("NOT_FOUND", "데이터셋을 찾을 수 없습니다", status=404)
    return dataset_out(d, st, ctx.settings.storage.ai_root)


def list_models(ctx: AppContext, study_id: str, status: str | None, limit: int | None, cursor: str | None) -> tuple[list[dict[str, Any]], str | None]:
    lim, off = clamp_limit(limit), decode_cursor(cursor)
    with ctx.engine.connect() as conn:
        s = studies_repo.require(conn, study_id)
        rows = models_repo.list_for_study(conn, study_id, status, lim + 1, off)
    return [model_out(m, s["final_model_id"], with_curve=False, study=s, ai_root=ctx.settings.storage.ai_root) for m in rows[:lim]], (
        encode_cursor(off + lim) if len(rows) > lim else None
    )


def get_model(ctx: AppContext, model_id: str) -> dict[str, Any]:
    with ctx.engine.connect() as conn:
        m = models_repo.require(conn, model_id)
        s = studies_repo.require(conn, m["study_id"])
    return model_out(m, s["final_model_id"], with_curve=True, study=s, ai_root=ctx.settings.storage.ai_root)


def patch_model(ctx: AppContext, principal: Principal, model_id: str, body: Any, rid: str, ip: str | None) -> dict[str, Any]:
    with ctx.engine.begin() as conn:
        m = models_repo.require(conn, model_id, for_update=True)
        s = studies_repo.require(conn, m["study_id"], for_update=True)
        require_power(principal, s["project_id"])
        values: dict[str, Any] = {}
        if "label" in body.model_fields_set:
            values["label"] = body.label
        if body.status is not None and body.status != m["status"]:
            if body.status == "ARCHIVED":
                if s["final_model_id"] == model_id:
                    raise DomainError("MODEL_IS_FINAL", "Final 모델은 보관할 수 없습니다. Final을 먼저 해제하세요", status=409)
                if jobs_repo.model_in_use(conn, model_id):
                    raise DomainError("MODEL_IN_USE", "진행 중인 작업이 이 모델을 사용하고 있습니다", status=409)
            if body.status == "ACTIVE" and m["status"] == "INVALID":
                raise DomainError("MODEL_NOT_ACTIVE", "무결성 오류(INVALID) 모델은 다시 활성화할 수 없습니다", status=409)
            values["status"] = body.status
        if values:
            m = models_repo.update_cas(conn, model_id, body.row_version, **values)
            audit(conn, principal, "MODEL_UPDATE", "model", model_id, dict(values), rid, ip)
        elif m["row_version"] != body.row_version:
            raise DomainError("VERSION_CONFLICT", "다른 사용자가 먼저 수정했습니다", status=409)
    return model_out(m, s["final_model_id"], with_curve=True, study=s, ai_root=ctx.settings.storage.ai_root)


def set_final(ctx: AppContext, principal: Principal, study_id: str, model_id: str | None, rid: str, ip: str | None) -> dict[str, Any]:
    with ctx.engine.begin() as conn:
        s = studies_repo.require(conn, study_id, for_update=True)
        if model_id is not None:
            m = models_repo.get(conn, model_id)
            if m is None or m["study_id"] != study_id:
                raise DomainError("NOT_FOUND", "모델을 찾을 수 없습니다", status=404)
        require_power(principal, s["project_id"])
        if model_id is not None and m["status"] != "ACTIVE":  # type: ignore[index]
            raise DomainError("MODEL_NOT_ACTIVE", "ACTIVE 모델만 Final로 지정할 수 있습니다", status=409)
        from sqlalchemy import func

        s = studies_repo.update_cas(
            conn, study_id, None, final_model_id=model_id,
            final_set_by=principal.user_id if model_id else None,
            final_set_at=func.now() if model_id else None,
        )
        audit(conn, principal, "FINAL_MODEL_SET", "study", study_id, {"model_id": model_id}, rid, ip)
    return study_out(s, principal, ctx.settings.storage.ai_root)


# ---- 파라미터 세트 -------------------------------------------------------------


def register_param_set(ctx: AppContext, principal: Principal, study_id: str, path: str, rid: str, ip: str | None) -> dict[str, Any]:
    cfg = ctx.settings
    with ctx.engine.connect() as conn:
        s = studies_repo.require(conn, study_id)
    require_power(principal, s["project_id"])
    require_config_ok(ctx)
    if s["status"] != "ACTIVE":
        raise DomainError("STUDY_ARCHIVED", "보관된 Study입니다", status=409)
    cp = check_user_path(path, [cfg.storage.ai_root])
    f = ps_mod.validate_folder(cp.path, max_samples=cfg.param_set.max_samples,
                               max_total_bytes=cfg.param_set.max_total_bytes, starter_glob=cfg.predict.starter_glob)
    if not f.ok:
        raise DomainError("PARAM_SET_INVALID", "파라미터 세트 폴더 검증에 실패했습니다", status=422, problems=f.problems)
    psid = str(uuid.uuid4())
    root = study_root(ctx, s)
    stored_rel = f"04_params/{psid}"
    ps_mod.write_normalized(f, cp.path, resolve_in_study(root, stored_rel), cp.path)
    with ctx.engine.begin() as conn:
        ps_repo.insert_current(conn, {
            "id": psid, "study_id": study_id, "source_path": cp.path, "stored_rel": stored_rel + "/",
            "unit_system": f.unit_system, "parameters": f.parameters, "responses": f.responses,
            "sample_count": len(f.samples), "sample_has_measured": f.sample_has_measured,
            "cad_file_name": f.cad_file, "tpl_rel": f"{stored_rel}/{ps_mod.TPL_NAME}",
            "assem_rel": f"{stored_rel}/radioss_assem/", "starter_name": f.starter_name, "tpl_params": f.tpl_params,
            "registered_by": principal.user_id, "registered_by_name": principal.display_name,
        })
        audit(conn, principal, "PARAM_SET_REGISTER", "param_set", psid, {"source_path": cp.path}, rid, ip)
        p = ps_repo.get(conn, psid)
    return param_set_out(p)  # type: ignore[arg-type]


def list_param_sets(ctx: AppContext, study_id: str, limit: int | None, cursor: str | None) -> tuple[list[dict[str, Any]], str | None]:
    lim, off = clamp_limit(limit), decode_cursor(cursor)
    with ctx.engine.connect() as conn:
        studies_repo.require(conn, study_id)
        rows = ps_repo.list_for_study(conn, study_id, lim + 1, off)
    return [param_set_out(p) for p in rows[:lim]], (encode_cursor(off + lim) if len(rows) > lim else None)


def _require_param_set(conn: Any, ps_id: str) -> dict[str, Any]:
    p = ps_repo.get(conn, ps_id)
    if p is None:
        raise DomainError("NOT_FOUND", "파라미터 세트를 찾을 수 없습니다", status=404)
    return p


def get_param_set(ctx: AppContext, ps_id: str) -> dict[str, Any]:
    with ctx.engine.connect() as conn:
        return param_set_out(_require_param_set(conn, ps_id))


def _load_samples(ctx: AppContext, conn: Any, p: dict[str, Any]) -> tuple[list[str], list[dict[str, Any]]]:
    s = studies_repo.require(conn, p["study_id"])
    stored = resolve_in_study(study_root(ctx, s), p["stored_rel"])
    return ps_mod.read_samples(stored)


def get_samples(ctx: AppContext, ps_id: str, limit: int | None, cursor: str | None) -> dict[str, Any]:
    lim, off = clamp_limit(limit), decode_cursor(cursor)
    with ctx.engine.connect() as conn:
        p = _require_param_set(conn, ps_id)
        columns, rows = _load_samples(ctx, conn, p)
    page = rows[off: off + lim]
    return {"columns": columns, "rows": page, "next_cursor": encode_cursor(off + lim) if off + lim < len(rows) else None}


def predict_check(ctx: AppContext, study_id: str, param_set_id: str | None, values: dict[str, float]) -> dict[str, Any]:
    import math

    with ctx.engine.connect() as conn:
        studies_repo.require(conn, study_id)
        p = _require_param_set(conn, param_set_id) if param_set_id else ps_repo.current(conn, study_id)
        if p is None or p["study_id"] != study_id:
            raise DomainError("NOT_FOUND", "파라미터 세트를 찾을 수 없습니다", status=404)
        _cols, samples = _load_samples(ctx, conn, p)
    names = {x["name"] for x in p["parameters"]}
    bad = [k for k in values if k not in names]
    nonfinite = [k for k, v in values.items() if not math.isfinite(v)]
    if bad or nonfinite:
        raise DomainError("INVALID_PARAMS", "알 수 없는 파라미터 이름이거나 유한하지 않은 값입니다", status=422,
                          errors=[{"loc": ["values", k], "msg": "unknown" if k in bad else "not finite"} for k in bad + nonfinite])
    mode = ctx.settings.predict.integer_rounding
    applied = nearest_mod.applied_values(p["tpl_params"], values, mode)
    near = nearest_mod.nearest_run(p["parameters"], samples, applied) if samples else None
    return {
        "out_of_range": nearest_mod.out_of_range(p["parameters"], values),
        "rounded": nearest_mod.rounded(p["tpl_params"], values, mode),
        "nearest": near,
    }

