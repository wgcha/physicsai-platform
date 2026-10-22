"""④ 파라미터 세트 등록(폴더·프로젝트 폴더 자동 구성)·조회·이름·샘플·예측 입력 확인, ①→④ 생성(§10.4, phase2 §6.13, phase3 §13).
300줄 분할(R-B): 등록 공용 도우미는 `stage4_predict_common`, ① 학습 DOE에서 등록은 `stage4_predict_train`(여기서 재노출)."""

from __future__ import annotations

import json
import os
import uuid
from typing import Any


from physicsai_core.db.repositories import param_sets as ps_repo
from physicsai_core.db.repositories import studies as studies_repo
from physicsai_core.errors import DomainError
from physicsai_core.fileutil import write_json
from physicsai_core.paths import allowed_roots, check_user_path, resolve_in_study
from physicsai_core.stage4_predict import nearest as nearest_mod
from physicsai_core.stage4_predict import param_discover as disc_mod
from physicsai_core.stage4_predict import param_sets as ps_mod

from ..auth import Principal
from ..context import AppContext
from . import param_set_native_api as native_api
from .common import audit, clamp_limit, decode_cursor, encode_cursor, param_set_out, require_power, study_root
from .stage4_predict_common import _label, _require_active_power, _insert_folder_set  # noqa: F401 - 기존 경로 재노출
from .stage4_predict_train import register_param_set_from_train  # noqa: F401 - 기존 경로 재노출


def register_param_set(ctx: AppContext, principal: Principal, study_id: str, body: Any, rid: str, ip: str | None) -> dict[str, Any]:
    if getattr(body, "extract_filter", None) is not None and (not native_api.wants_native(ctx, body) or getattr(body, "kind", None) == "shell"):
        native_api.raise_filter_unsupported()  # extract-filter.md §6.7: altair·shell 요청의 extract_filter 거부(요청 검증 분기, altair 처리 전)
    if getattr(body, "kind", None) == "shell" and not native_api.wants_native(ctx, body):  # shell-morph.md §8.2: native 전용
        raise DomainError("INVALID_PARAMS", "쉘 판금 형상(kind=shell)은 Native 형상 엔진(mode=discover)에서만 씁니다", status=422,
                          errors=[{"loc": ["body", "kind"], "msg": "engine=native·mode=discover 필요"}])
    if native_api.wants_native(ctx, body):  # geometry-engine.md §7.3.4: 202 {job_id}
        _require_active_power(ctx, principal, study_id)
        return native_api.register_native(ctx, principal, study_id, body, _label(body.label), rid, ip)
    if getattr(body, "mode", None) == "discover":
        return register_param_set_discovered(ctx, principal, study_id, body, rid, ip)
    if body.choice is not None:
        raise DomainError("INVALID_PARAMS", "choice는 mode=discover에서만 씁니다", status=422)
    cfg = ctx.settings
    s = _require_active_power(ctx, principal, study_id)
    label = _label(body.label)
    path = body.path
    cp = check_user_path(path, [cfg.storage.ai_root])
    f = ps_mod.validate_folder(cp.path, max_samples=cfg.param_set.max_samples,
                               max_total_bytes=cfg.param_set.max_total_bytes, starter_glob=cfg.predict.starter_glob,
                               renum_csv_name=cfg.predict.renum_csv_name)
    if not f.ok:
        raise DomainError("PARAM_SET_INVALID", "파라미터 세트 폴더 검증에 실패했습니다", status=422, problems=f.problems)
    psid = str(uuid.uuid4())
    root = study_root(ctx, s)
    out_tmp = resolve_in_study(root, f"logs/_paramset_tmp/{uuid.uuid4()}.out")
    ps_mod.write_normalized(f, cp.path, out_tmp, cp.path)
    return _insert_folder_set(ctx, principal, study_id, f, psid, root, out_tmp, cp.path, label,
                              "PARAM_SET_REGISTER", {"source_path": cp.path}, rid, ip)


def discover_param_set(ctx: AppContext, principal: Principal, study_id: str, body: Any) -> dict[str, Any]:
    """phase3 §13 S8: 프로젝트 폴더에서 후보 찾기(읽기만, 워커 불필요)."""
    with ctx.engine.connect() as conn:
        s = studies_repo.require(conn, study_id)
    require_power(principal, s["project_id"])
    if native_api.wants_native(ctx, body, discover=True):
        return native_api.discover_native_out(ctx, body.path, getattr(body, "kind", None) or "solid", bool(getattr(body, "asm_match", False)))
    cp = check_user_path(body.path, allowed_roots(ctx.settings, imports=True))
    return {**disc_mod.discover(cp.path, ctx.settings, tpl=body.tpl).out(), "engine": "altair"}


def register_param_set_discovered(ctx: AppContext, principal: Principal, study_id: str, body: Any, rid: str,
                                  ip: str | None) -> dict[str, Any]:
    """phase3 §13 S8: 고른 후보를 §15.4 구조로 임시 폴더에 모아 기존 검증기·정규화로 등록(원본 위치는 읽기만)."""
    cfg = ctx.settings
    s = _require_active_power(ctx, principal, study_id)
    label = _label(body.label)
    cp = check_user_path(body.path, allowed_roots(cfg, imports=True))
    # exclude_unset: radioss_assem 명시적 null(= mesh_only)과 생략(후보 1개 → assembly, 0개 → mesh_only)을 구분(phase3 §14.4)
    choice = body.choice.model_dump(exclude_unset=True) if body.choice is not None else {}
    d = disc_mod.discover(cp.path, cfg, tpl=choice.get("tpl"))
    tpl, cad, assem, probs = disc_mod.resolve_choice(d, choice)
    problems = d.problems + probs
    if problems or tpl is None or cad is None:
        raise DomainError("PARAM_SET_INVALID", "프로젝트 폴더에서 파라미터 세트를 구성할 수 없습니다", status=422,
                          problems=problems or [{"code": "DISCOVER_INCOMPLETE", "message": "tpl·CAD를 모두 찾아야 합니다"}])
    need = disc_mod.planned_bytes(d, tpl, cad, assem, cfg)
    if need > cfg.param_set.max_total_bytes:
        raise DomainError("PARAM_SET_INVALID", "파라미터 세트 검증에 실패했습니다", status=422, problems=[
            {"code": "PARAM_SET_TOO_LARGE", "message": f"복사할 총량이 상한({cfg.param_set.max_total_bytes} bytes)을 넘습니다"}])
    root = study_root(ctx, s)
    tmp_id = str(uuid.uuid4())
    A = resolve_in_study(root, f"logs/_paramset_tmp/{tmp_id}")
    os.makedirs(A)
    disc_mod.copy_sources(d, tpl, cad, assem, A, cfg)
    f = ps_mod.validate_folder(A, max_samples=cfg.param_set.max_samples, max_total_bytes=cfg.param_set.max_total_bytes,
                               starter_glob=cfg.predict.starter_glob, renum_csv_name=cfg.predict.renum_csv_name)
    if not f.ok:
        raise DomainError("PARAM_SET_INVALID", "파라미터 세트 검증에 실패했습니다", status=422, problems=f.problems)
    psid = str(uuid.uuid4())
    out_tmp = resolve_in_study(root, f"logs/_paramset_tmp/{tmp_id}.out")
    ps_mod.write_normalized(f, A, out_tmp, cp.path)
    picked = {"tpl": tpl.rel, "cad": cad, "radioss_assem": assem["rel"] if assem else None,
              "parameters_source": d.parameters_source,
              "parameters_file": d.parameters_file, "samples": d.samples, "responses": d.responses}
    src_json = os.path.join(out_tmp, "source.json")
    with open(src_json, encoding="utf-8") as fh:
        meta = json.load(fh)
    write_json(src_json, {**meta, "mode": "discover", "discovered": picked})
    return _insert_folder_set(ctx, principal, study_id, f, psid, root, out_tmp, cp.path, label,
                              "PARAM_SET_REGISTER", {"source_path": cp.path, "mode": "discover", **picked}, rid, ip)


def patch_param_set(ctx: AppContext, principal: Principal, ps_id: str, body: Any, rid: str, ip: str | None) -> dict[str, Any]:
    """표시 이름(label) 바꾸기 — 내용(파일·파라미터)은 바뀌지 않는다."""
    with ctx.engine.begin() as conn:
        p = _require_param_set(conn, ps_id)
        s = studies_repo.require(conn, p["study_id"])
        require_power(principal, s["project_id"])
        if s["status"] != "ACTIVE":
            raise DomainError("STUDY_ARCHIVED", "보관된 Study입니다", status=409)
        if "label" in body.model_fields_set:
            lab = _label(body.label)
            ps_repo.set_label(conn, ps_id, lab)
            audit(conn, principal, "PARAM_SET_UPDATE", "param_set", ps_id, {"label": lab}, rid, ip)
        if "geom_options" in body.model_fields_set:
            native_api.patch_geom_options(ctx, conn, principal, p, body.geom_options, rid, ip)
        p = _require_param_set(conn, ps_id)
    return native_api.enrich(ctx, p, param_set_out(p))


def list_param_sets(ctx: AppContext, study_id: str, limit: int | None, cursor: str | None) -> tuple[list[dict[str, Any]], str | None]:
    lim, off = clamp_limit(limit), decode_cursor(cursor)
    with ctx.engine.connect() as conn:
        studies_repo.require(conn, study_id)
        rows = ps_repo.list_for_study(conn, study_id, lim + 1, off)
    return [native_api.enrich(ctx, p, param_set_out(p)) for p in rows[:lim]], (encode_cursor(off + lim) if len(rows) > lim else None)


def _require_param_set(conn: Any, ps_id: str) -> dict[str, Any]:
    p = ps_repo.get(conn, ps_id)
    if p is None:
        raise DomainError("NOT_FOUND", "파라미터 세트를 찾을 수 없습니다", status=404)
    return p


def get_param_set(ctx: AppContext, ps_id: str) -> dict[str, Any]:
    with ctx.engine.connect() as conn:
        p = _require_param_set(conn, ps_id)
    return native_api.enrich(ctx, p, param_set_out(p))


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

