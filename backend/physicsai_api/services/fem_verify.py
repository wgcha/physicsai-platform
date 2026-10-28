"""④ 조립 FEM 검증 API 서비스(phase3 §21.3.8 S16): 미리보기·생성·목록·상세·컨투어·커브·표·취소·다시 실행.

생성 = Study 행 FOR UPDATE(D3-25) 안에서 fv_no 채번 → 활성 수·중복 검사 → 검증 행 + 작업(동반 PREDICT 또는 FEM_VERIFY)을
한 트랜잭션으로. DB에는 경로·상태·수치만(파일 본문 없음).
300줄 분할(R-B): 계획·중복 검사는 `fem_verify_plan`,
목록·상세는 `fem_verify_view`, 컨투어·커브·표는 `fem_verify_media`(여기서 재노출)."""

from __future__ import annotations

import uuid
from typing import Any

from physicsai_core.db.repositories import fem_verifications as fv_repo
from physicsai_core.db.repositories import jobs as jobs_repo
from physicsai_core.db.repositories import studies as studies_repo
from physicsai_core.errors import DomainError
from physicsai_core.stage4_predict import input_kind as ik
from physicsai_core.state_machine import TERMINAL

from ..auth import Principal
from ..context import AppContext
from . import job_params
from .common import audit, require_config_ok, require_power
from .fem_verify_sources import Resolved
from .job_params.study_manage import study_gate
from .fem_verify_plan import (  # noqa: F401 - 기존 경로 재노출
    STATUS_TEXT,
    ASSEM_KIND,
    CSV_HEADER,
    MAX_CURVE_POINTS,
    _feature_checks,
    fem_field_for,
    plan,
    check_active_rules,
    check_row_reactivate,
    check_retry_reactivate,
)
from .fem_verify_view import _detail, detail, list_  # noqa: F401 - 기존 경로 재노출
from .fem_verify_media import media, curves, table_csv  # noqa: F401 - 기존 경로 재노출


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
    if c.get("template_kind"):  # input-kind.md §4.3: 쿠션 실행의 FEM 검증은 같은 입력 종류로 동반 예측
        raw["input"] = ik.to_public(c["template_kind"])
    p = job_params.parse_params("PREDICT", raw)
    params, result, warnings = job_params.prepare(ctx, conn, study, "PREDICT", p)
    params["fem_verify_id"] = fid
    return jobs_repo.insert_job(conn, study=study, job_type="PREDICT", params=params, user_id=principal.user_id,
                                user_name=principal.display_name, result=result, warnings=warnings)


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
        target = fv_repo.target_job_id(row)
        j = jobs_repo.get_job(conn, target) if target else None
        if j is not None and j["state"] in TERMINAL and row["status"] in fv_repo.FV_ACTIVE:
            fv_repo.on_job_end(conn, j, j["state"])  # 작업은 끝났는데 검증이 진행 중으로 남은 옛 행(v0.2.14 이슈 #14) — 바로잡는다
        elif j is not None and j["state"] not in TERMINAL and j["cancel_requested_at"] is None:
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
