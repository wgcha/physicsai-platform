"""④ ① 학습 DOE(tpl·samples)에서 파라미터 세트 등록 — stage4_predict에서 재노출."""

from __future__ import annotations

import os
import uuid
from typing import Any

from physicsai_core.db.repositories import studies as studies_repo
from physicsai_core.errors import DomainError
from physicsai_core.fileutil import write_json
from physicsai_core.paths import resolve_in_study
from physicsai_core.stage4_predict import param_sets as ps_mod

from ..auth import Principal
from ..context import AppContext
from .common import (
    require_config_ok,
    require_power,
    study_root,
)
from .stage4_predict_common import _insert_folder_set, _label


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
