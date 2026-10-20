"""④ 파라미터 세트 등록(폴더·프로젝트 폴더 자동 구성)·조회·이름·샘플·예측 입력 확인, ①→④ 생성(§10.4, phase2 §6.13, phase3 §13)."""

from __future__ import annotations

import contextlib
import json
import os
import uuid
from typing import Any


from physicsai_core.db.repositories import param_sets as ps_repo
from physicsai_core.db.repositories import studies as studies_repo
from physicsai_core.errors import DomainError
from physicsai_core.fileutil import write_json
from physicsai_core.naming import LABEL_MAX, label_problem
from physicsai_core.paths import allowed_roots, check_user_path, resolve_in_study
from physicsai_core.stage4_predict import nearest as nearest_mod
from physicsai_core.stage4_predict import param_discover as disc_mod
from physicsai_core.stage4_predict import param_sets as ps_mod

from ..auth import Principal
from ..context import AppContext
from . import param_set_native_api as native_api
from .common import (
    audit,
    clamp_limit,
    decode_cursor,
    encode_cursor,
    param_set_out,
    require_config_ok,
    require_power,
    study_root,
)


def _label(raw: str | None) -> str | None:
    """표시 이름 공통 검증(D3-50, 스키마 `Label`과 같은 함수). 제어·양방향 제어 문자 → 422. 등록은 사본을 만들기 전에 부른다."""
    why = label_problem(raw or "")
    if why:
        raise DomainError("LABEL_INVALID", why, status=422)
    v = (raw or "").strip()
    return v[:LABEL_MAX] or None


def _require_active_power(ctx: AppContext, principal: Principal, study_id: str) -> dict[str, Any]:
    with ctx.engine.connect() as conn:
        s = studies_repo.require(conn, study_id)
    require_power(principal, s["project_id"])
    require_config_ok(ctx)
    if s["status"] != "ACTIVE":
        raise DomainError("STUDY_ARCHIVED", "보관된 Study입니다", status=409)
    return s


def _insert_folder_set(ctx: AppContext, principal: Principal, study_id: str, f: Any, psid: str, root: str, out_tmp: str,
                       source_path: str, label: str | None, action: str, detail: dict[str, Any], rid: str,
                       ip: str | None, **extra: Any) -> dict[str, Any]:
    """정규화본(`logs/_paramset_tmp/<tmp>.out`)을 `04_params/<id>`로 옮기고 DB 행을 넣는다(D3-50).

    이동은 DB 트랜잭션 안에서 하고, insert·commit이 실패하면 방금 옮긴 미등록 사본을 `logs/_paramset_tmp`로 되돌린다
    (삭제 호출 없음 — 이번 요청이 만든 사본이라 사용자 산출물이 아니며, 04_params에 DB 행 없는 고아 폴더를 남기지 않는다).
    mesh_only(phase3 §14.4): 조립 폴더 없음 → assem_rel·starter_name NULL. 경고 SIMLAB_EXPORT_NAME은 응답 `warnings`.
    """
    stored_rel = f"04_params/{psid}"
    dst = resolve_in_study(root, stored_rel)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    mesh_only = f.input_kind == "mesh_only"
    warnings = ps_mod.export_name_notes(out_tmp, ctx.settings.param_set.tpl_export_regex, ctx.settings.predict.simlab_mesh_name)
    moved = False
    try:
        with ctx.engine.begin() as conn:
            ps_repo.insert_current(conn, {
                "id": psid, "study_id": study_id, "source_path": source_path, "stored_rel": stored_rel + "/",
                "unit_system": f.unit_system, "parameters": f.parameters, "responses": f.responses,
                "sample_count": len(f.samples), "sample_has_measured": f.sample_has_measured,
                "cad_file_name": f.cad_file, "tpl_rel": f"{stored_rel}/{ps_mod.TPL_NAME}",
                "assem_rel": None if mesh_only else f"{stored_rel}/radioss_assem/",
                "starter_name": None if mesh_only else f.starter_name, "input_kind": f.input_kind, "tpl_params": f.tpl_params,
                "registered_by": principal.user_id, "registered_by_name": principal.display_name, "label": label, **extra,
            })
            audit(conn, principal, action, "param_set", psid,
                  {**detail, "label": label, "input_kind": f.input_kind, "warnings": [w["code"] for w in warnings]}, rid, ip)
            os.replace(out_tmp, dst)  # 원래 위치에서 이동(삭제 호출 없음)
            moved = True
            p = ps_repo.get(conn, psid)
    except BaseException:
        if moved and os.path.isdir(dst) and not os.path.lexists(out_tmp):
            with contextlib.suppress(OSError):
                os.replace(dst, out_tmp)  # 미등록 사본을 되돌림(04_params 고아 방지)
        raise
    return {**param_set_out(p), "warnings": warnings}  # type: ignore[arg-type]


def register_param_set(ctx: AppContext, principal: Principal, study_id: str, body: Any, rid: str, ip: str | None) -> dict[str, Any]:
    if getattr(body, "kind", None) == "shell" and not native_api.wants_native(ctx, body):  # shell-morph.md §8.2: native 전용
        raise DomainError("INVALID_PARAMS", "쉘 판금 형상(kind=shell)은 native 형상 엔진(mode=discover)에서만 씁니다", status=422,
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
        return native_api.discover_native_out(ctx, body.path, getattr(body, "kind", None) or "solid")
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


def register_param_set_from_train(ctx: AppContext, principal: Principal, study_id: str, body: Any, rid: str,
                                  ip: str | None) -> dict[str, Any]:
    """F(phase2 §6.13): ① DOE 결과로 파라미터 세트 폴더를 조립해 1차 검증기·등록 함수로 등록."""
    import csv as _csv

    from physicsai_core.stage1_train_data import doe_samples
    from physicsai_core.db.repositories import train as train_repo
    from physicsai_core.fileutil import copy_file, write_text

    cfg = ctx.settings
    with ctx.engine.connect() as conn:
        s = studies_repo.require(conn, study_id)
        d = train_repo.get_doe(conn, body.doe_id)
        runs = train_repo.runs_for_doe(conn, body.doe_id) if d else []
        setup = train_repo.get_setup(conn, study_id)
    require_power(principal, s["project_id"])
    require_config_ok(ctx)
    if s["status"] != "ACTIVE":
        raise DomainError("STUDY_ARCHIVED", "보관된 Study입니다", status=409)
    label = _label(body.label)
    if d is None or d["study_id"] != study_id or d["status"] != "READY":
        raise DomainError("DOE_NOT_READY", "READY 상태의 DOE가 필요합니다", status=409)
    if d["sample_status"] not in ("PARSED", "PARTIAL") or not d["samples_rel"]:
        raise DomainError("SAMPLES_MISSING", "DOE 샘플 표가 없습니다(샘플 추출기 설정 확인)", status=409)
    if body.runs == "collected":
        keys = {r["run_key"] for r in runs if r["state"] == "COLLECTED"}
        if not keys:
            raise DomainError("DOE_NOT_READY", "회수된 run이 없습니다", status=409)
    else:
        keys = {r["run_key"] for r in runs}
    root = study_root(ctx, s)
    D = resolve_in_study(root, d["dir_rel"])
    if d.get("engine") == "native":  # geometry-engine.md §7.3.4: tpl·샘플 없이 준비본 복사
        return native_api.from_train(ctx, principal, s, d, D, label, body, rid, ip)
    tmp_id = str(uuid.uuid4())
    A = resolve_in_study(root, f"logs/_paramset_tmp/{tmp_id}")
    os.makedirs(A)
    snap = d["parameters_snapshot"] or []
    write_json(os.path.join(A, "parameters.json"), {
        "schema_version": 1, "unit_system": body.unit_system or "mm-ton-s",
        "parameters": [{"name": p["name"], "nominal": p["nominal"], "min": p["min"], "max": p["max"],
                        "unit": p.get("unit", "")} for p in snap],
    })
    names = [p["name"] for p in snap]
    _hdr, rows = doe_samples.read_samples_csv(resolve_in_study(root, d["samples_rel"]))
    resp_names: list[str] = []
    resp: dict[str, dict[str, Any]] = {}
    if d["responses_rel"] and os.path.isfile(resolve_in_study(root, d["responses_rel"])):
        rh, rrows = doe_samples.read_samples_csv(resolve_in_study(root, d["responses_rel"]))
        resp_names = rh[1:]
        resp = {r["run_key"]: r["values"] for r in rrows}
    rj = os.path.join(D, "responses.json")
    if os.path.isfile(rj):
        copy_file(rj, os.path.join(A, "responses.json"))
    elif resp_names:
        write_json(os.path.join(A, "responses.json"), {"responses": [{"name": n, "unit": "", "spec": {}} for n in resp_names]})
    else:
        write_json(os.path.join(A, "responses.json"), {"responses": []})
    import io

    buf = io.StringIO()
    w = _csv.writer(buf, lineterminator="\n")
    w.writerow(["run_key", *names, *[f"resp:{n}" for n in resp_names]])
    for r in rows:
        if r["run_key"] not in keys:
            continue
        mv = resp.get(r["run_key"], {})
        w.writerow([r["run_key"], *[repr(r["values"][n]) for n in names],
                    *["" if mv.get(n) is None else repr(mv[n]) for n in resp_names]])
    write_text(os.path.join(A, "samples.csv"), buf.getvalue())
    cad = (setup or {}).get("cad_file_name")
    if not cad or not os.path.isfile(resolve_in_study(root, f"01_train/cad/{cad}")):
        raise DomainError("PARAM_SET_INVALID", "CAD 사본이 없습니다", status=422,
                          problems=[{"code": "CAD_MISSING", "message": "01_train/cad 사본이 없습니다"}])
    copy_file(resolve_in_study(root, f"01_train/cad/{cad}"), os.path.join(A, "cad", cad))
    copy_file(os.path.join(D, ps_mod.TPL_NAME), os.path.join(A, ps_mod.TPL_NAME))
    assem = resolve_in_study(root, f"01_train/radioss_assem/{d['id']}")
    for n in sorted(os.listdir(assem)) if os.path.isdir(assem) else []:
        # eps_mesh*로 시작하는 파일은 SimLab 메시 산출(원본 1_physicsai_opti.py:300) — 무시(변경 메모 C3, phase3 §11.4).
        # RENUM csv(predict.renum_csv_name)는 다른 파일과 함께 복사되고 검증기가 사본에 넣는다(V3-S6-6)
        if n.lower().startswith("eps_mesh"):
            continue
        if os.path.isfile(os.path.join(assem, n)):
            copy_file(os.path.join(assem, n), os.path.join(A, "radioss_assem", n))
    f = ps_mod.validate_folder(A, max_samples=cfg.param_set.max_samples, max_total_bytes=cfg.param_set.max_total_bytes,
                               starter_glob=cfg.predict.starter_glob,
                               renum_csv_name=cfg.predict.renum_csv_name, allow_mesh_only=False)  # ①→④는 항상 assembly
    if not f.ok:
        raise DomainError("PARAM_SET_INVALID", "파라미터 세트 검증에 실패했습니다", status=422, problems=f.problems)
    psid = str(uuid.uuid4())
    src_label = f"① DOE {d['id'][:8]}"
    out_tmp = resolve_in_study(root, f"logs/_paramset_tmp/{tmp_id}.out")
    ps_mod.write_normalized(f, A, out_tmp, src_label)
    return _insert_folder_set(ctx, principal, study_id, f, psid, root, out_tmp, src_label, label,
                              "PARAM_SET_FROM_TRAIN", {"doe_id": d["id"], "runs": body.runs}, rid, ip,
                              origin="TRAIN_DOE", train_doe_id=d["id"])

