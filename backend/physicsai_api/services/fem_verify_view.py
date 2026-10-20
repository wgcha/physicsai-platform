"""④ 조립 FEM 검증 조회(목록·상세·커서) — fem_verify에서 재노출."""

from __future__ import annotations

import base64
import binascii
import os
from datetime import datetime
from typing import Any

from physicsai_core.db.repositories import fem_verifications as fv_repo
from physicsai_core.db.repositories import hpc as hpc_repo
from physicsai_core.db.repositories import jobs as jobs_repo
from physicsai_core.db.repositories import param_sets as ps_repo
from physicsai_core.db.repositories import studies as studies_repo
from physicsai_core.db.repositories import train as train_repo
from physicsai_core.errors import DomainError
from physicsai_core.paths import display_path, resolve_in_study

from ..auth import Principal
from ..context import AppContext
from .common import clamp_limit, job_summary, study_root
from .fem_verify_plan import STATUS_TEXT

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
