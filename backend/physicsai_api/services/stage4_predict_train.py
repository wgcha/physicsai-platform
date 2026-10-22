"""④ ① 학습 DOE(tpl·samples)에서 파라미터 세트 등록 — stage4_predict에서 재노출."""

from __future__ import annotations

import os
import uuid
from typing import Any

from physicsai_core.db.repositories import studies as studies_repo
from physicsai_core.errors import DomainError
from physicsai_core.fileutil import sha256_file, write_json
from physicsai_core.naming import TPL_FULL_NAME
from physicsai_core.paths import resolve_in_study
from physicsai_core.stage1_train_data import train_tpl
from physicsai_core.stage4_predict import param_sets as ps_mod
from physicsai_core.tpl_render import parse_declarations

from ..auth import Principal
from ..context import AppContext
from .common import (
    require_config_ok,
    require_power,
    study_root,
)
from .stage4_predict_common import _insert_folder_set, _label


MISMATCH_TOL = 1e-9


def _decl_map(text: str) -> dict[str, tuple[float | None, float | None, float | None]]:
    return {d["name"]: (d["nominal"], d["min"], d["max"]) for d in parse_declarations(text)}


def _same_decl(a: dict[str, Any], b: dict[str, Any]) -> bool:
    if a.keys() != b.keys():
        return False
    for n, va in a.items():
        for x, y in zip(va, b[n]):
            if (x is None) != (y is None) or (x is not None and abs(x - y) > MISMATCH_TOL * max(1.0, abs(x))):  # type: ignore[operator]
                return False
    return True


def _current_tpl(ctx: AppContext, root: str, setup: dict[str, Any] | None, snap: list[dict[str, Any]]) -> str:
    """altair-vars.md AV-11 `tpl_source: current`: 현재 ①-2 전체 tpl 경로. `used_view(current)`의 선언(이름·공칭·범위)이 그 DOE 스냅숏과 같을 때만(아니면 409 TPL_DOE_MISMATCH)."""
    if setup is None or not setup.get("tpl_rel"):
        raise DomainError("TPL_REQUIRED", "tpl을 먼저 생성하세요(①-2)", status=409)
    path = resolve_in_study(root, setup["tpl_rel"])
    if not os.path.isfile(path) or (setup.get("tpl_sha256") and sha256_file(path) != setup["tpl_sha256"]):
        raise DomainError("TPL_REQUIRED", "생성된 tpl 파일이 없거나 바뀌었습니다 — ①-2에서 tpl을 다시 생성하세요", status=409)
    if train_tpl.scope_of_file(path) != "full":
        raise DomainError("TPL_SCOPE_PARTIAL", "옛 tpl(사용 파라미터만) — ①-2에서 tpl을 다시 생성한 뒤 다시 시도하세요", status=422)
    with open(path, encoding="utf-8-sig") as fh:
        text = fh.read()
    used = [str(r["name"]) for r in setup.get("tpl_params") or [] if r.get("used", True)]
    want = {str(p["name"]): (float(p["nominal"]), float(p["min"]), float(p["max"])) for p in snap}
    try:
        got = _decl_map(train_tpl.used_view(text, used))
    except train_tpl.TplTemplateInvalid:
        got = {}
    if not _same_decl(got, want):
        raise DomainError("TPL_DOE_MISMATCH", "현재 ①-2 tpl의 사용 파라미터(이름·공칭·범위)가 이 DOE와 다릅니다 — DOE 폴더의 tpl로 만들거나 DOE를 다시 만드세요",
                          status=409)
    return path


def _enrich_tpl_params(f: Any, setup: dict[str, Any] | None, tpl_path: str, snap_names: set[str]) -> None:
    """전체 tpl 세트의 `tpl_params` 행에 used(= DOE 사용)·table_min/max·unit(①-2 기록이 이 tpl과 같을 때만)을 채운다(AV-4)."""
    meta: dict[str, dict[str, Any]] = {}
    if setup and setup.get("tpl_sha256") and setup.get("tpl_params") and sha256_file(tpl_path) == setup["tpl_sha256"]:
        meta = {str(r["name"]): r for r in setup["tpl_params"]}
    for r in f.tpl_params:
        m = meta.get(r["name"], {})
        r["used"] = r["name"] in snap_names
        if m.get("table_min") is not None and m.get("table_max") is not None:
            r["table_min"], r["table_max"] = m["table_min"], m["table_max"]
        if m.get("unit") is not None:
            r["unit"] = m["unit"]


def register_param_set_from_train(ctx: AppContext, principal: Principal, study_id: str, body: Any, rid: str,
                                  ip: str | None) -> dict[str, Any]:
    """F(phase2 §6.13): ① DOE 결과로 파라미터 세트 폴더를 조립해 1차 검증기·등록 함수로 등록."""
    import csv as _csv

    from physicsai_core.db.repositories import train as train_repo
    from physicsai_core.fileutil import copy_file, write_text
    from physicsai_core.stage1_train_data import doe_samples

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
        from . import param_set_native_api as native_api

        if body.tpl_source != "doe":
            raise DomainError("INVALID_PARAMS", "tpl_source는 Altair DOE에서만 쓸 수 있습니다", status=422,
                              errors=[{"loc": ["body", "tpl_source"], "msg": "Native DOE에는 쓸 수 없음"}])
        return native_api.from_train(ctx, principal, s, d, D, label, body, rid, ip)
    snap = d["parameters_snapshot"] or []
    if body.tpl_source == "current":  # altair-vars.md AV-11: DOE를 다시 돌리지 않고 현재 전체 tpl로 승격
        tpl_path = _current_tpl(ctx, root, setup, snap)
    else:  # doe: 그 DOE 폴더의 tpl(레거시 hstbatch + 전체 tpl이면 .full.tpl이 전체 원본)
        full_copy = os.path.join(D, TPL_FULL_NAME)
        tpl_path = full_copy if os.path.isfile(full_copy) else os.path.join(D, ps_mod.TPL_NAME)
    tmp_id = str(uuid.uuid4())
    A = resolve_in_study(root, f"logs/_paramset_tmp/{tmp_id}")
    os.makedirs(A)
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
    copy_file(tpl_path, os.path.join(A, ps_mod.TPL_NAME))
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
    if train_tpl.scope_of_file(tpl_path) == "full":
        _enrich_tpl_params(f, setup, tpl_path, set(names))
    psid = str(uuid.uuid4())
    src_label = f"① DOE {d['id'][:8]}"
    out_tmp = resolve_in_study(root, f"logs/_paramset_tmp/{tmp_id}.out")
    ps_mod.write_normalized(f, A, out_tmp, src_label)
    return _insert_folder_set(ctx, principal, study_id, f, psid, root, out_tmp, src_label, label,
                              "PARAM_SET_FROM_TRAIN", {"doe_id": d["id"], "runs": body.runs}, rid, ip,
                              origin="TRAIN_DOE", train_doe_id=d["id"])
