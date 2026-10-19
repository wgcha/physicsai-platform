"""④ 조립 FEM 검증 API 서비스(phase3 §21.3.8 S16): 미리보기·생성·목록·상세·컨투어·커브·표·취소·다시 실행.

생성 = Study 행 FOR UPDATE(D3-25) 안에서 fv_no 채번 → 활성 수·중복 검사 → 검증 행 + 작업(동반 PREDICT 또는 FEM_VERIFY)을
한 트랜잭션으로. DB에는 경로·상태·수치만(파일 본문 없음)."""

from __future__ import annotations

import base64
import binascii
import csv
import io
import json
import math
import os
import uuid
from datetime import datetime
from typing import Any

from physicsai_core.commands import template_uses
from physicsai_core.db.repositories import contour_media as media_repo
from physicsai_core.db.repositories import fem_verifications as fv_repo
from physicsai_core.db.repositories import hpc as hpc_repo
from physicsai_core.db.repositories import jobs as jobs_repo
from physicsai_core.db.repositories import param_sets as ps_repo
from physicsai_core.db.repositories import studies as studies_repo
from physicsai_core.db.repositories import train as train_repo
from physicsai_core.errors import DomainError
from physicsai_core.features import mesh_uses_include_tcl
from physicsai_core.paths import display_path, resolve_in_study
from physicsai_core.stage4_predict import contour_capture as cc
from physicsai_core.stage4_predict import fem_assembly
from physicsai_core.stage4_predict import nearest as nearest_mod
from physicsai_core.state_machine import TERMINAL

from ..auth import Principal
from ..context import AppContext
from . import job_params
from .common import audit, clamp_limit, job_summary, require_config_ok, require_power, study_root
from .contour_capture import file_out
from .fem_verify_sources import APPLIED_TOL, Resolved, input_is_assembly, resolve
from .job_params.study_manage import study_gate
from .predict_batches import downsample

STATUS_TEXT = {"WAITING_PREDICT": "예측 실행 중", "DONE": "완료", "FAILED": "실패", "CANCELED": "취소됨"}
ASSEM_KIND = {"predict_input": "PREDICT_INPUT", "train_doe": "TRAIN_DOE", "custom": "CUSTOM"}
CSV_HEADER = ["name", "unit", "stat", "pred_min", "pred_max", "fem_min", "fem_max", "pred_value", "fem_value", "diff",
              "diff_pct"]
MAX_CURVE_POINTS = 5000


# ---- 계획(미리보기·생성 공통) ----------------------------------------------------------------------


def _feature_checks(ctx: AppContext) -> str:
    s = ctx.settings
    if not s.fem_verify.enabled:
        raise DomainError("FEATURE_NOT_AVAILABLE", "FEM 검증 기능이 꺼져 있습니다(fem_verify.enabled)", status=409,
                          feature="fem_verify")
    av = ctx.hpc.availability()
    if not av.configured:
        raise DomainError("HPC_NOT_CONFIGURED", "해석 연결 안 됨(관리자 설정 필요)", status=409, mode=av.mode)
    return av.mode


def _rebuild_checks(ctx: AppContext, r: Resolved) -> None:
    s = ctx.settings
    if r.mesh_native or (r.companion is not None and (r.param_set or {}).get("engine") == "native"):
        if r.companion is None and not r.mesh_available:  # native: 모핑 include를 그대로 쓰므로 메시 변환 명령 불필요
            r.problem("MESH_MISSING", "예측 폴더에 모핑한 형상 include가 없습니다(정리됨 또는 준비된 입력)")
        return
    if s.commands.mesh is None:
        raise DomainError("TEMPLATE_NOT_CONFIGURED", "메시 변환 명령 템플릿(mesh)이 설정되지 않았습니다", status=409,
                          template="mesh")
    if mesh_uses_include_tcl(s) and not s.resources.hypermesh_include_tcl:
        raise DomainError("TEMPLATE_NOT_CONFIGURED", "형상 갱신 설정 필요(관리자): resources.hypermesh_include_tcl", status=409,
                          template="mesh", missing=["resources.hypermesh_include_tcl"])
    if template_uses(s.commands.mesh, "rendered_script") or template_uses(s.commands.mesh, "cad_file"):
        r.problem("MESH_TEMPLATE_PLACEHOLDER", "메시 명령(commands.mesh)이 {rendered_script}·{cad_file}을 써서 FEM 검증 재조립에 쓸 수 없습니다")
    if r.companion is None and not r.mesh_available:
        r.problem("MESH_MISSING", "예측 폴더에 형상 메시가 없습니다(정리됨 또는 준비된 입력)")


def _input_summary(ctx: AppContext, study: dict[str, Any], r: Resolved) -> dict[str, Any]:
    """predict_input(reuse) 요약: P/INPUT 직속 파일."""
    out: dict[str, Any] = {"starter": r.starter, "rad": [], "inc_count": 0, "file_count": 0, "total_bytes": 0,
                           "renum_csv": None, "include_baseline": None, "include_referenced": None}
    if not r.input_rel:
        return out
    d = resolve_in_study(study_root(ctx, study), r.input_rel)
    names = sorted(n for n in os.listdir(d) if os.path.isfile(os.path.join(d, n)))
    out.update(rad=[n for n in names if n.lower().endswith(".rad")][:50], inc_count=sum(n.lower().endswith(".inc") for n in names),
               file_count=len(names), total_bytes=sum(os.path.getsize(os.path.join(d, n)) for n in names))
    return out


def _latest_ready_doe(conn: Any, study_id: str) -> dict[str, Any] | None:
    ready = [d for d in train_repo.list_does(conn, study_id) if d["status"] == "READY"]
    return max(ready, key=lambda d: (d["created_at"], d["id"])) if ready else None


def _display(ctx: AppContext, conn: Any, r: Resolved, req_display: dict[str, Any] | None) -> dict[str, Any]:
    """§15.3 순서: config → 응답 정의 → 템플릿 → 배치 → P params display → 요청."""
    batch = media_repo.batch_display(conn, r.links["batch_id"]) if r.links.get("batch_id") else None
    pd = ((r.predict_job or {}).get("params") or {}).get("display")
    disp, _src = cc.resolve_display(ctx.settings.capture, r.param_set, batch, pd, req_display)
    return disp


def fem_field_for(settings: Any, display: dict[str, Any], fem: dict[str, Any] | None) -> str:
    """FEM 결과 필드: 요청 fem.field → fem_verify.field_map[예측 필드] → 예측 필드(§21.3.6)."""
    f = (fem or {}).get("field")
    if f:
        return str(f)
    pf = str(display.get("field") or "")
    return settings.fem_verify.field_map.get(pf, pf)


def _comps_auto(ctx: AppContext, study: dict[str, Any], r: Resolved) -> list[str]:
    if r.template_kind != "mesh_only" or not ctx.settings.fem_verify.auto_isolate_cushion or not r.mesh_rel:
        return []
    p = resolve_in_study(study_root(ctx, study), r.mesh_rel)
    if not os.path.isfile(p) or os.path.getsize(p) > ctx.settings.fem_verify.include_scan_max_bytes:
        return []
    return fem_assembly.mesh_part_ids(p)


def plan(ctx: AppContext, conn: Any, study: dict[str, Any], body: Any) -> dict[str, Any]:
    """미리보기·생성 공통 계획. problems(422 후보)·warnings는 결과에 담고, 설정 오류는 409로 올린다."""
    hpc_mode = _feature_checks(ctx)
    r = resolve(ctx, conn, study, body.source)
    s = ctx.settings
    asm = body.assembly
    kind = asm.kind if asm else None
    if r.predict_job is None and r.companion is None:  # 출처를 못 찾음 — 조립 원본은 판단하지 않는다
        kind = None
    elif kind is None:
        if input_is_assembly(r):
            kind = "predict_input"
        else:
            doe = _latest_ready_doe(conn, study["id"])
            kind = "train_doe" if doe else None
            if doe is None:
                r.problem("ASSEMBLY_REQUIRED", "조립 원본을 고르세요(예측 입력이 쿠션 메시뿐이고 READY인 ① DOE가 없습니다)")
    assem_ref: dict[str, Any] | None = None
    assem_out: dict[str, Any] | None = None
    signature: list[Any] | None = None
    assem_path: str | None = None
    input_mode = "reuse" if kind == "predict_input" else ("rebuild" if kind else None)
    if kind == "predict_input":
        if not input_is_assembly(r):
            if (r.predict_job or {}).get("params", {}).get("input_mode") == "prepared" and not r.mesh_rel:
                r.problem("PREPARED_NOT_SUPPORTED" if not r.input_rel else "INPUT_MESH_ONLY",
                          "이 예측 입력은 쿠션 메시뿐이라 그대로 해석할 수 없습니다 — 조립 원본을 고르세요")
            else:
                r.problem("INPUT_MESH_ONLY", "이 예측 입력은 쿠션 메시뿐이라 그대로 해석할 수 없습니다 — 조립 원본을 고르세요")
        sroot = study_root(ctx, study)
        assem_path = resolve_in_study(sroot, r.input_rel) if r.input_rel else None
        assem_out = {"kind": "PREDICT_INPUT", "label": "예측 입력 그대로",
                     "path": display_path(s.storage.ai_root, study["folder_name"], r.input_rel) if r.input_rel else None,
                     **_input_summary(ctx, study, r)}
    elif kind == "train_doe":
        doe_id = asm.doe_id if asm else _latest_ready_doe(conn, study["id"])["id"]  # type: ignore[index]
        doe = train_repo.get_doe(conn, doe_id)
        if doe is None or doe["study_id"] != study["id"] or doe["status"] != "READY":
            r.problem("DOE_NOT_READY", "① DOE가 READY 상태가 아닙니다")
        else:
            assem_ref = {"doe_id": doe["id"]}
            assem_path = resolve_in_study(study_root(ctx, study), doe["assem_rel"])
            names = {str(p.get("name")) for p in (doe.get("parameters_snapshot") or []) if isinstance(p, dict)}
            if r.param_set is not None and names and names != {str(p["name"]) for p in r.param_set["parameters"]}:
                r.warn("DOE_PARAM_MISMATCH", "① DOE 파라미터가 템플릿과 다릅니다 — 조립 폴더만 씁니다")
            assem_out = {"kind": "TRAIN_DOE", "label": doe["doe_label"],
                         "path": display_path(s.storage.ai_root, study["folder_name"], doe["assem_rel"])}
    elif kind == "custom":
        path, _where = fem_assembly.check_custom_path(asm.path, s)  # type: ignore[union-attr]  # PathError 422
        assem_ref = {"path": path}
        assem_path = path
        assem_out = {"kind": "CUSTOM", "label": "직접 지정", "path": path}
    if input_mode == "rebuild":
        _rebuild_checks(ctx, r)
        if ((r.predict_job or {}).get("result") or {}).get("shell_values"):  # 3S: 재조립은 조립 원본 그대로(두께 미적용)
            r.warn("SHELL_NOT_APPLIED", "이 예측의 쉘 두께 값은 재조립 입력에 적용되지 않습니다 — 예측 입력 그대로(reuse)를 쓰세요")
        if assem_path and assem_out is not None:
            pl = fem_assembly.plan_assembly(assem_path, s)
            r.problems.extend(pl["problems"])
            for w in pl["warnings"]:
                r.warn(w["code"], w["message"])
            assem_out.update(fem_assembly.summary(pl))
            signature = pl["signature"]
    if r.template_kind == "mesh_only":
        r.warn("FEM_RESPONSE_WHOLE_MODEL", "FEM 응답은 조립 전체 모델의 최솟값·최댓값입니다(쿠션만 한정 불가) — 컨투어를 함께 보세요")
    req_display = cc.clean_display(body.display.model_dump(exclude_none=True)) if body.display else None
    fem = body.fem.model_dump() if body.fem else None
    disp = _display(ctx, conn, r, req_display)
    pj = r.predict_job
    return {
        "resolved": r, "kind": kind, "assem_ref": assem_ref, "assem_out": assem_out, "assem_path": assem_path,
        "signature": signature, "input_mode": input_mode, "hpc_mode": hpc_mode, "display": req_display, "fem": fem,
        "preview": {
            "source_label": r.label,
            "design": _design(r),
            "predict": {"job_id": pj["id"] if pj else None, "state": pj["state"] if pj else None, "reuse": pj is not None,
                        "will_run": r.companion is not None, "companion": r.companion is not None},
            "input_mode": input_mode,
            "mesh": {"path": display_path(s.storage.ai_root, study["folder_name"], r.mesh_rel) if r.mesh_rel else None,
                     "available": r.mesh_available},
            "assembly": assem_out, "fem_field": fem_field_for(s, disp, fem), "comps_auto": _comps_auto(ctx, study, r),
            "hpc_mode": hpc_mode, "problems": r.problems, "warnings": r.warnings,
        },
    }


def _design(r: Resolved) -> dict[str, Any]:
    ps, m = r.param_set, r.model
    return {"param_set": {"id": ps["id"], "label": ps.get("label"), "input_kind": ps["input_kind"]} if ps else None,
            "model": {"id": m["id"], "name": m["name"], "version": m["version"]} if m else None,
            "values": r.values, "applied_values": r.applied_values, "out_of_range": r.out_of_range}


# ---- 진행 중 상한·중복(생성·재시도·다시 실행 공통, D3-64 후속) --------------------------------------


def _applied(settings: Any, ps: dict[str, Any] | None, values: dict[str, Any]) -> dict[str, float]:
    vals = {k: float(v) for k, v in (values or {}).items()}
    return nearest_mod.applied_values(ps["tpl_params"], vals, settings.predict.integer_rounding) if ps else vals


def _same_point(a: dict[str, float], b: dict[str, float]) -> bool:
    return set(a) == set(b) and all(abs(a[k] - b[k]) <= APPLIED_TOL for k in a)


def check_active_rules(settings: Any, conn: Any, study_id: str, *, predict_job_id: str | None, companion: bool,
                       param_set_id: str | None, model_id: str | None, values: dict[str, Any] | None, assem_kind: str,
                       assem_ref: dict[str, Any] | None, exclude_id: str | None = None) -> None:
    """Study당 진행 중 `fem_verify.max_active`(409 FEM_VERIFY_LIMIT)와 같은 예측·같은 조립 원본 중복(409 FEM_VERIFY_ACTIVE).
    동반 예측은 아직 예측 id가 없어 같은 템플릿·모델·적용값(정수 반올림 후) + 같은 조립 원본의 진행 중 동반 검증과 비교한다.
    호출자가 Study 행을 FOR UPDATE로 잡고 부른다(D3-25)."""
    n = fv_repo.count_active(conn, study_id)
    if n >= settings.fem_verify.max_active:
        raise DomainError("FEM_VERIFY_LIMIT", f"진행 중인 FEM 검증이 {n}건입니다(상한 {settings.fem_verify.max_active})", status=409)
    dup = fv_repo.active_duplicate(conn, study_id, predict_job_id, assem_kind, assem_ref, exclude_id=exclude_id)
    if dup is None and companion and param_set_id and model_id:
        rows = fv_repo.active_companions(conn, study_id, param_set_id, model_id, assem_kind, assem_ref, exclude_id=exclude_id)
        if rows:
            ps = ps_repo.get(conn, param_set_id)
            mine = _applied(settings, ps, values or {})
            dup = next((x for x in rows if _same_point(mine, _applied(settings, ps, (x.get("source_ref") or {}).get("values") or {}))),
                       None)
    if dup is not None:
        raise DomainError("FEM_VERIFY_ACTIVE", "같은 예측·같은 조립 원본의 검증이 진행 중입니다", status=409)


def check_row_reactivate(settings: Any, conn: Any, row: dict[str, Any]) -> None:
    """끝난(FAILED·CANCELED) 검증 행을 다시 진행 중으로 만들기 전 상한·중복 재검사."""
    if row["status"] in fv_repo.FV_ACTIVE:
        return
    check_active_rules(settings, conn, row["study_id"], predict_job_id=row.get("predict_job_id"), companion=bool(row["companion"]),
                       param_set_id=row.get("param_set_id"), model_id=row.get("model_id"),
                       values=(row.get("source_ref") or {}).get("values"), assem_kind=row["assem_kind"],
                       assem_ref=row.get("assem_ref"), exclude_id=row["id"])


def check_retry_reactivate(settings: Any, conn: Any, old: dict[str, Any]) -> None:
    """`/jobs/{id}/retry`·다시 실행: 동반 PREDICT·FEM_VERIFY 재시도가 검증 행을 되살리면(on_retry) 그 전에 재검사."""
    p = old.get("params") or {}
    fid = p.get("fem_verify_id") if isinstance(p, dict) else None
    if not isinstance(fid, str) or old["job_type"] not in ("PREDICT", "FEM_VERIFY"):
        return
    row = fv_repo.get(conn, fid, for_update=True)
    if row is None:
        return
    revives = row["predict_job_id"] == old["id"] if old["job_type"] == "PREDICT" else row["job_id"] == old["id"]
    if revives:
        check_row_reactivate(settings, conn, row)


# ---- 미리보기·생성 ---------------------------------------------------------------------------------


def preview(ctx: AppContext, principal: Principal, study_id: str, body: Any) -> dict[str, Any]:
    with ctx.engine.connect() as conn:
        study = studies_repo.require(conn, study_id)
        require_power(principal, study["project_id"])
        return plan(ctx, conn, study, body)["preview"]


def create(ctx: AppContext, principal: Principal, study_id: str, body: Any, rid: str, ip: str | None) -> dict[str, Any]:
    s = ctx.settings
    with ctx.engine.begin() as conn:
        study = studies_repo.require(conn, study_id, for_update=True)
        require_power(principal, study["project_id"])
        require_config_ok(ctx)
        study_gate(conn, study, "FEM_VERIFY")
        pl = plan(ctx, conn, study, body)
        r: Resolved = pl["resolved"]
        if r.problems:
            raise DomainError("FEM_VERIFY_INVALID", "FEM 검증을 만들 수 없습니다", status=422, problems=r.problems)
        pj = r.predict_job
        akind = ASSEM_KIND[pl["kind"]]
        c = r.companion or {}
        check_active_rules(s, conn, study["id"], predict_job_id=pj["id"] if pj else None, companion=r.companion is not None,
                           param_set_id=c.get("param_set_id"), model_id=c.get("model_id"), values=c.get("values"),
                           assem_kind=akind, assem_ref=pl["assem_ref"])
        fid = str(uuid.uuid4())
        no = fv_repo.next_fv_no(conn, study["id"])
        options = {"fem": pl["fem"], "display": pl["display"], "hpc": body.hpc.model_dump() if body.hpc else None,
                   "assem_signature": pl["signature"], "warnings": r.warnings}
        row = fv_repo.insert(
            conn, id=fid, study_id=study["id"], fv_no=no, source_kind=r.kind, source_ref=r.source_ref,
            predict_job_id=pj["id"] if pj else None, companion=r.companion is not None,
            param_set_id=r.param_set["id"] if r.param_set else None, model_id=r.model["id"] if r.model else None,
            template_kind=r.template_kind, assem_kind=akind, assem_ref=pl["assem_ref"], input_mode=pl["input_mode"],
            options=options, status="WAITING_PREDICT" if r.companion else "RUNNING",
            dir_rel=f"{s.fem_verify.dir_name}/{fv_repo.label(no)}", created_by=principal.user_id,
            created_by_name=principal.display_name)
        if r.companion is not None:
            pjob = _insert_companion(ctx, conn, principal, study, r, fid)
            fv_repo.set_row(conn, fid, predict_job_id=pjob["id"])
        else:
            fv_repo.enqueue_fem_verify(conn, row)
        audit(conn, principal, "FEM_VERIFY_CREATE", "fem_verification", fid,
              {"fv_no": no, "source_kind": r.kind, "assem_kind": akind, "companion": r.companion is not None}, rid, ip)
        return _detail(ctx, conn, fv_repo.get(conn, fid), principal, study)  # type: ignore[arg-type]


def _insert_companion(ctx: AppContext, conn: Any, principal: Principal, study: dict[str, Any], r: Resolved,
                      fid: str) -> dict[str, Any]:
    """동반 PREDICT(parametric, §11.5 저장 형식 + 서버 전용 키 fem_verify_id). 검증 규칙 = PREDICT parametric."""
    c = r.companion or {}
    raw = {"input_mode": "parametric", "param_set_id": c["param_set_id"], "model_id": c["model_id"], "values": c["values"],
           "value_source": "manual"}
    p = job_params.parse_params("PREDICT", raw)
    params, result, warnings = job_params.prepare(ctx, conn, study, "PREDICT", p)
    params["fem_verify_id"] = fid
    return jobs_repo.insert_job(conn, study=study, job_type="PREDICT", params=params, user_id=principal.user_id,
                                user_name=principal.display_name, result=result, warnings=warnings)


# ---- 조회 ------------------------------------------------------------------------------------------


def _require(conn: Any, fid: str) -> dict[str, Any]:
    row = fv_repo.get(conn, fid)
    if row is None:
        raise DomainError("FEM_VERIFY_NOT_FOUND", "FEM 검증을 찾을 수 없습니다", status=404)
    return row


def _links(row: dict[str, Any]) -> dict[str, Any]:
    ref = row.get("source_ref") or {}
    batch_id, doe_no = ref.get("batch_id"), ref.get("doe_no")
    return {"predict_job_id": row.get("predict_job_id"), "batch_id": batch_id, "doe_no": doe_no, "opt_id": ref.get("opt_id")}


def _attempt_dir(row: dict[str, Any], job: dict[str, Any] | None) -> str | None:
    res = (job or {}).get("result") or {}
    if res.get("fv_rel"):
        return str(res["fv_rel"])
    if row["attempt_no"]:
        return f"{row['dir_rel']}/a{row['attempt_no']}"
    return None


def _status_text(row: dict[str, Any], job: dict[str, Any] | None, hpc_mode: str) -> str:
    if row["status"] != "RUNNING":
        return STATUS_TEXT.get(row["status"], row["status"])
    st = (job or {}).get("state")
    if st == "QUEUED":
        return "대기 중"
    if st == "WAITING_HPC":
        return f"해석 대기({'SCX' if hpc_mode == 'scx' else 'PBS'})"
    if st == "COLLECTING":
        return "결과 회수 중"
    return "실행 중"


def _detail(ctx: AppContext, conn: Any, row: dict[str, Any], principal: Principal,
            study: dict[str, Any] | None = None) -> dict[str, Any]:
    s = ctx.settings
    study = study or studies_repo.require(conn, row["study_id"])
    ai, fn = s.storage.ai_root, study["folder_name"]
    job = jobs_repo.get_job(conn, row["job_id"]) if row.get("job_id") else None
    pj = jobs_repo.get_job(conn, row["predict_job_id"]) if row.get("predict_job_id") else None
    res = (job or {}).get("result") or {}
    a_rel = _attempt_dir(row, job)
    sroot = study_root(ctx, study)

    def disp(rel: str | None) -> str | None:
        return display_path(ai, fn, rel) if rel and os.path.lexists(resolve_in_study(sroot, rel)) else None

    hrows = hpc_repo.for_job(conn, job["id"]) if job else []
    remote = next((h.get("remote_dir") for h in reversed(hrows) if h.get("remote_dir")), None)
    if remote:
        from simdash_adapters.hpc.scx_naming import display_path as scx_display

        remote = scx_display(s.hpc.scx.home_display, remote)
    ref = row.get("source_ref") or {}
    ps = None
    from physicsai_core.db.repositories import models as models_repo

    if row.get("param_set_id"):
        ps = ps_repo.get(conn, row["param_set_id"])
    m = models_repo.get(conn, row["model_id"]) if row.get("model_id") else None
    pres = (pj or {}).get("result") or {}
    ak = row["assem_kind"]
    aref = row.get("assem_ref") or {}
    alabel, apath = {"PREDICT_INPUT": "예측 입력 그대로", "TRAIN_DOE": None, "CUSTOM": "직접 지정"}.get(ak), None
    if ak == "TRAIN_DOE" and aref.get("doe_id"):
        doe = train_repo.get_doe(conn, aref["doe_id"])
        if doe:
            alabel, apath = doe["doe_label"], display_path(ai, fn, doe["assem_rel"])
    elif ak == "CUSTOM":
        apath = aref.get("path")
    elif ak == "PREDICT_INPUT" and pj is not None:
        apath = display_path(ai, fn, f"04_predict/{jobs_repo.root_job_id(conn, pj)}/INPUT")
    warnings = list((row.get("options") or {}).get("warnings") or [])
    for w in (job or {}).get("warnings") or []:
        if isinstance(w, dict) and w.get("code"):
            warnings.append({"code": w["code"], "message": w.get("message") or ""})
    active = row["status"] in fv_repo.FV_ACTIVE
    mine = principal.is_global_admin or (row["created_by"] == principal.user_id and principal.can_execute(study["project_id"]))
    hpc_mode = ctx.hpc.availability().mode
    return {
        "id": row["id"], "label": fv_repo.label(row["fv_no"]), "status": row["status"],
        "status_text": _status_text(row, job, hpc_mode),
        "source": {"kind": row["source_kind"], "label": ref.get("label") or ""}, "links": _links(row),
        "design": {"param_set": {"id": ps["id"], "label": ps.get("label"), "input_kind": ps["input_kind"]} if ps else None,
                   "model": {"id": m["id"], "name": m["name"], "version": m["version"]} if m else None,
                   "values": ref.get("values") or pres.get("values") or {}, "applied_values": pres.get("applied_values") or {},
                   "out_of_range": list(pres.get("out_of_range") or [])},
        "predict": {"job_id": row.get("predict_job_id"), "state": pj["state"] if pj else None, "reuse": not row["companion"],
                    "will_run": bool(row["companion"]) and row["status"] == "WAITING_PREDICT", "companion": bool(row["companion"])},
        "assembly": {"kind": ak, "label": alabel, "path": apath, "snapshot_dir": disp(f"{a_rel}/assem") if a_rel else None},
        "input_mode": row["input_mode"], "attempt_no": int(row["attempt_no"]), "dir": disp(row["dir_rel"]),
        "paths": {"input_dir": disp(f"{a_rel}/input") if a_rel else None, "result_dir": disp(f"{a_rel}/result") if a_rel else None,
                  "starter": res.get("starter"), "remote_dir": remote, "collected": list(res.get("collected") or [])},
        "job": job_summary(job, study["title"], None, hpc_repo.summary_for_jobs(conn, [job["id"]]).get(job["id"])) if job else None,
        "compare": res.get("compare") if row["status"] == "DONE" or res.get("compare") else None,
        "warnings": warnings,
        "failure": {"code": row["failure_code"], "message": row.get("failure_message") or ""} if row.get("failure_code") else None,
        "can_cancel": active and mine, "can_rerun": row["status"] in ("FAILED", "CANCELED") and mine,
        "created_at": row["created_at"], "created_by_name": row["created_by_name"], "finished_at": row.get("finished_at"),
    }


def detail(ctx: AppContext, principal: Principal, fid: str) -> dict[str, Any]:
    with ctx.engine.connect() as conn:
        return _detail(ctx, conn, _require(conn, fid), principal)


def _encode_cursor(row: dict[str, Any]) -> str:
    return base64.urlsafe_b64encode(f"{row['created_at'].isoformat()}|{row['id']}".encode()).decode().rstrip("=")


def _decode_cursor(cursor: str | None) -> tuple[datetime, str] | None:
    if not cursor:
        return None
    try:
        at, _, fid = base64.urlsafe_b64decode(cursor.encode() + b"==").decode().partition("|")
        if not fid:
            raise ValueError(at)
        return datetime.fromisoformat(at), fid
    except (ValueError, UnicodeDecodeError, binascii.Error):
        raise DomainError("INVALID_PARAMS", "cursor 형식이 올바르지 않습니다", status=422,
                          errors=[{"loc": ["query", "cursor"], "msg": "invalid"}]) from None


def list_(ctx: AppContext, principal: Principal, study_id: str, *, predict_job_id: str | None, batch_id: str | None,
          opt_id: str | None, status: str | None, limit: int | None, cursor: str | None) -> tuple[list[dict[str, Any]], str | None]:
    statuses = [x.strip() for x in status.split(",") if x.strip()] if status else None
    if statuses and any(x not in fv_repo.FV_STATUSES for x in statuses):
        raise DomainError("INVALID_PARAMS", f"status: {' | '.join(fv_repo.FV_STATUSES)}", status=422,
                          errors=[{"loc": ["query", "status"], "msg": "unknown"}])
    after = _decode_cursor(cursor)
    lim = clamp_limit(limit)
    with ctx.engine.connect() as conn:
        studies_repo.require(conn, study_id)
        pids = None
        if predict_job_id:  # 예측 작업 id → 재시도 사슬 전체(동반·재시도로 바뀐 id도 같은 출처)
            j = jobs_repo.get_job(conn, predict_job_id)
            pids = [predict_job_id]
            if j is not None:
                root = jobs_repo.root_job_id(conn, j)
                pids = list({predict_job_id, root})
        rows = fv_repo.list_for_study(conn, study_id, predict_job_ids=pids, batch_id=batch_id, opt_id=opt_id,
                                      statuses=statuses, limit=lim + 1, after=after)
    out = []
    for row in rows[:lim]:
        sm = row.get("summary") or {}
        ref = row.get("source_ref") or {}
        out.append({"id": row["id"], "label": fv_repo.label(row["fv_no"]), "status": row["status"],
                    "source_label": ref.get("label") or "", "source_kind": row["source_kind"], "links": _links(row),
                    "values": ref.get("values") or {}, "max_abs_diff_pct": sm.get("max_abs_diff_pct"), "worst": sm.get("worst"),
                    "created_at": row["created_at"], "created_by_name": row["created_by_name"], "finished_at": row.get("finished_at")})
    return out, (_encode_cursor(rows[lim - 1]) if len(rows) > lim else None)


# ---- 컨투어·커브·표 --------------------------------------------------------------------------------


def media(ctx: AppContext, principal: Principal, fid: str) -> dict[str, Any]:
    with ctx.engine.connect() as conn:
        row = _require(conn, fid)
        study = studies_repo.require(conn, row["study_id"])
        job = jobs_repo.get_job(conn, row["job_id"]) if row.get("job_id") else None
        res = (job or {}).get("result") or {}
        m = res.get("media") if isinstance(res.get("media"), dict) else {}
        ids = [x for side in ("pred", "fem") for it in (m.get(side) or []) for x in (it.get("image_artifact_id"),
                                                                                       it.get("video_artifact_id"))]
        arts = media_repo.artifacts_by_ids(conn, ids)
    sroot = study_root(ctx, study)
    by: dict[str, dict[str, Any]] = {}
    for side in ("pred", "fem"):
        for it in m.get(side) or []:
            img = arts.get(it.get("image_artifact_id") or "")
            if img is None or not os.path.isfile(resolve_in_study(sroot, img["rel_path"])):
                continue
            vid = arts.get(it.get("video_artifact_id") or "")
            v = it.get("view")
            by.setdefault(v, {"view": v, "label": cc.VIEW_LABELS.get(v, v), "pred": None, "fem": None})[side] = {
                "image": file_out(img), "video": file_out(vid) if vid else None,
                "video_error": it.get("video_error") if not vid else None}
    items = [by[v] for v in sorted(by, key=lambda x: cc.VIEWS.index(x) if x in cc.VIEWS else len(cc.VIEWS))]
    cmp_ = res.get("compare") or {}
    ms = (cmp_.get("media") or {})
    status = "NONE" if not m else ("OK" if ms.get("pred_status") == "OK" and ms.get("fem_status") == "OK" else
                                   ms.get("fem_status") or ms.get("pred_status") or "NONE")
    return {"status": status, "display": m.get("display"), "legend": cmp_.get("legend"), "items": items}


def _load_series(path: str, name: str | None, max_bytes: int) -> tuple[list[str], dict[str, Any] | None]:
    try:
        if not os.path.isfile(path) or os.path.getsize(path) > max_bytes:
            return [], None
        with open(path, encoding="utf-8-sig") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return [], None
    series = [x for x in (data or {}).get("series") or [] if isinstance(x, dict) and isinstance(x.get("name"), str)]
    pick = next((x for x in series if x["name"] == name), None) if name is not None else None
    return [x["name"] for x in series], pick


def _xy(sr: dict[str, Any] | None, max_points: int) -> tuple[dict[str, Any] | None, bool]:
    if sr is None:
        return None, False
    xs, ys = sr.get("x"), sr.get("y")
    ok = (isinstance(xs, list) and isinstance(ys, list) and len(xs) == len(ys) and xs
          and all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in xs + ys))
    if not ok:
        return None, False
    x2, y2, d = downsample([float(v) for v in xs], [float(v) for v in ys], max_points)
    return {"x": x2, "y": y2}, d


def curves(ctx: AppContext, principal: Principal, fid: str, name: str | None, max_points: int) -> dict[str, Any]:
    max_points = max(2, min(int(max_points), MAX_CURVE_POINTS))
    with ctx.engine.connect() as conn:
        row = _require(conn, fid)
        study = studies_repo.require(conn, row["study_id"])
        job = jobs_repo.get_job(conn, row["job_id"]) if row.get("job_id") else None
        pj = jobs_repo.get_job(conn, row["predict_job_id"]) if row.get("predict_job_id") else None
        proot = jobs_repo.root_job_id(conn, pj) if pj else None
    res = (job or {}).get("result") or {}
    cv = (res.get("compare") or {}).get("curve") or {}
    pairs = [p for p in cv.get("pairs") or [] if isinstance(p, dict)]
    names = [p["pred"] for p in pairs if isinstance(p.get("pred"), str)]
    pick = name if name is not None else (names[0] if names else None)
    pair = next((p for p in pairs if p.get("pred") == pick), None)
    sroot = study_root(ctx, study)
    cap = ctx.settings.ui.max_artifact_bytes
    pred = fem = None
    down = False
    if pair is not None and proot:
        _n, sr = _load_series(resolve_in_study(sroot, f"04_predict/{proot}/curve.json"), pair["pred"], cap)
        pred, d1 = _xy(sr, max_points)
        a_rel = _attempt_dir(row, job)
        _n, sr2 = _load_series(resolve_in_study(sroot, f"{a_rel}/curves/fem_curve.json"), pair.get("fem"), cap) if a_rel else ([], None)
        fem, d2 = _xy(sr2, max_points)
        down = d1 or d2
    return {"names": names, "name": pick, "pred": pred, "fem": fem, "downsampled": down}


def _num(v: Any) -> str:
    return "" if v is None else repr(float(v))


def table_csv(ctx: AppContext, principal: Principal, fid: str) -> tuple[bytes, str]:
    with ctx.engine.connect() as conn:
        row = _require(conn, fid)
        job = jobs_repo.get_job(conn, row["job_id"]) if row.get("job_id") else None
    rows = ((((job or {}).get("result") or {}).get("compare") or {}).get("responses") or [])
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow(CSV_HEADER)
    for r in rows:
        w.writerow([r.get("name") or "", r.get("unit") or "", r.get("stat") or "",
                    *(_num(r.get(k)) for k in CSV_HEADER[3:])])
    return ("﻿" + buf.getvalue()).encode("utf-8"), f"{fv_repo.label(row['fv_no'])}_responses.csv"


# ---- 취소·다시 실행 ---------------------------------------------------------------------------------


def _require_owner(principal: Principal, row: dict[str, Any], study: dict[str, Any]) -> None:
    require_power(principal, study["project_id"])
    if row["created_by"] != principal.user_id and not principal.is_global_admin:
        raise DomainError("PERMISSION_DENIED", "등록자 또는 관리자만 할 수 있습니다", status=403, required="owner")


def cancel(ctx: AppContext, principal: Principal, fid: str, rid: str, ip: str | None) -> dict[str, Any]:
    """WAITING_PREDICT → 동반 예측 취소, RUNNING → FEM_VERIFY 취소(기존 취소 경로). 이미 끝났거나 요청됨 = 그대로(멱등)."""
    with ctx.engine.begin() as conn:
        row = fv_repo.get(conn, fid, for_update=True)
        if row is None:
            raise DomainError("FEM_VERIFY_NOT_FOUND", "FEM 검증을 찾을 수 없습니다", status=404)
        study = studies_repo.require(conn, row["study_id"])
        _require_owner(principal, row, study)
        target = row["predict_job_id"] if row["status"] == "WAITING_PREDICT" else (row["job_id"] if row["status"] == "RUNNING" else None)
        j = jobs_repo.get_job(conn, target) if target else None
        if j is not None and j["state"] not in TERMINAL and j["cancel_requested_at"] is None:
            jobs_repo.request_cancel(conn, j["id"], principal.user_id)
            audit(conn, principal, "FEM_VERIFY_CANCEL", "fem_verification", fid, {"job_id": j["id"], "state": j["state"]}, rid, ip)
        return _detail(ctx, conn, fv_repo.get(conn, fid), principal, study)  # type: ignore[arg-type]


def rerun(ctx: AppContext, principal: Principal, fid: str, rid: str, ip: str | None) -> dict[str, Any]:
    """FAILED·CANCELED만. 동반 예측이 실패·취소였으면 그 예측 재시도, 그 밖은 FEM_VERIFY 재시도(§21.3.5 규칙)."""
    from .jobs import retry_locked

    with ctx.engine.begin() as conn:
        row = fv_repo.get(conn, fid, for_update=True)
        if row is None:
            raise DomainError("FEM_VERIFY_NOT_FOUND", "FEM 검증을 찾을 수 없습니다", status=404)
        study = studies_repo.require(conn, row["study_id"], for_update=True)
        _require_owner(principal, row, study)
        require_config_ok(ctx)
        if row["status"] not in ("FAILED", "CANCELED"):
            raise DomainError("FEM_VERIFY_NOT_RERUNNABLE", "실패·취소된 FEM 검증만 다시 실행할 수 있습니다", status=409)
        _feature_checks(ctx)
        pj = jobs_repo.get_job(conn, row["predict_job_id"]) if row.get("predict_job_id") else None
        job = jobs_repo.get_job(conn, row["job_id"]) if row.get("job_id") else None
        if row["companion"] and pj is not None and pj["state"] != "SUCCEEDED":
            if pj["state"] not in TERMINAL:
                raise DomainError("FEM_VERIFY_NOT_RERUNNABLE", "함께 실행한 예측이 아직 끝나지 않았습니다", status=409)
            new = retry_locked(conn, principal, pj, None, rid, ip, settings=ctx.settings)
        elif job is not None and job["state"] in TERMINAL and job["state"] != "SUCCEEDED":
            new = retry_locked(conn, principal, job, None, rid, ip, settings=ctx.settings)
        elif job is None and pj is not None and pj["state"] == "SUCCEEDED":
            check_row_reactivate(ctx.settings, conn, row)
            new = fv_repo.enqueue_fem_verify(conn, row)
        else:
            raise DomainError("FEM_VERIFY_NOT_RERUNNABLE", "다시 실행할 작업이 없습니다", status=409)
        audit(conn, principal, "FEM_VERIFY_RERUN", "fem_verification", fid, {"job_id": new["id"]}, rid, ip)
        return _detail(ctx, conn, fv_repo.get(conn, fid), principal, study)  # type: ignore[arg-type]
