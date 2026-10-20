"""④ 조립 FEM 검증 계획(미리보기·생성 공통)과 진행 중 상한·중복 검사(D3-64 후속) — fem_verify에서 재노출."""

from __future__ import annotations

import os
from typing import Any

from physicsai_core.commands import template_uses
from physicsai_core.db.repositories import contour_media as media_repo
from physicsai_core.db.repositories import fem_verifications as fv_repo
from physicsai_core.db.repositories import param_sets as ps_repo
from physicsai_core.db.repositories import train as train_repo
from physicsai_core.errors import DomainError
from physicsai_core.features import mesh_uses_include_tcl
from physicsai_core.paths import display_path, resolve_in_study
from physicsai_core.stage4_predict import contour_capture as cc
from physicsai_core.stage4_predict import fem_assembly
from physicsai_core.stage4_predict import nearest as nearest_mod

from ..context import AppContext
from .common import study_root
from .fem_verify_sources import APPLIED_TOL, Resolved, input_is_assembly, resolve

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
