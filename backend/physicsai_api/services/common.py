"""서비스 공용: 권한 판정(§5.3), 설정 확인, 응답 직렬화, 페이지."""

from __future__ import annotations

import base64
import os
from typing import Any

from sqlalchemy.engine import Connection

from physicsai_core.db.repositories import audit as audit_repo
from physicsai_core.db.repositories import jobs as jobs_repo
from physicsai_core.db.repositories import studies as studies_repo
from physicsai_core.errors import DomainError
from physicsai_core.paths import study_dir
from physicsai_core.state_machine import TERMINAL

from ..auth import Principal
from ..context import AppContext

MAX_LIMIT = 200


def require_power(principal: Principal, project_id: str) -> None:
    if not principal.can_execute(project_id):
        raise DomainError("PERMISSION_DENIED", "실행 권한(power 이상)이 필요합니다", status=403, required="power")


def require_global_admin(principal: Principal) -> None:
    if not principal.is_global_admin:
        raise DomainError("PERMISSION_DENIED", "전역 관리자 권한이 필요합니다", status=403, required="global_admin")


def require_config_ok(ctx: AppContext) -> None:
    if not ctx.config.ok:
        raise DomainError("CONFIG_INVALID", "플랫폼 설정이 올바르지 않아 실행할 수 없습니다", status=503,
                          errors=ctx.config.error_keys())


def study_root(ctx: AppContext, study: dict[str, Any]) -> str:
    return study_dir(ctx.settings.storage.ai_root, study["folder_name"])


def audit(conn: Connection, principal: Principal, action: str, target_type: str, target_id: str | None,
          detail: dict[str, Any] | None, rid: str | None, ip: str | None) -> None:
    audit_repo.record(conn, user_id=principal.user_id, username=principal.username, action=action,
                      target_type=target_type, target_id=target_id, detail=detail, request_id=rid, client_ip=ip)


# ---- 페이지 ---------------------------------------------------------------


def clamp_limit(limit: int | None, default: int = 50) -> int:
    if limit is None:
        return default
    return max(1, min(MAX_LIMIT, int(limit)))


def decode_cursor(cursor: str | None) -> int:
    if not cursor:
        return 0
    try:
        v = int(base64.urlsafe_b64decode(cursor.encode() + b"==").decode())
        return max(0, v)
    except (ValueError, UnicodeDecodeError):
        raise DomainError("INVALID_PARAMS", "cursor 형식이 올바르지 않습니다", status=422, errors=[{"loc": ["cursor"], "msg": "invalid"}]) from None


def encode_cursor(offset: int) -> str:
    return base64.urlsafe_b64encode(str(offset).encode()).decode().rstrip("=")


# ---- 직렬화 ---------------------------------------------------------------


def study_out(s: dict[str, Any], principal: Principal) -> dict[str, Any]:
    return {
        "id": s["id"], "project_id": s["project_id"], "folder_name": s["folder_name"], "title": s["title"],
        "status": s["status"], "final_model_id": s["final_model_id"], "created_by": s["created_by"],
        "created_by_name": s["created_by_name"], "created_at": s["created_at"], "updated_at": s["updated_at"],
        "version": s["version"], "can_execute": principal.can_execute(s["project_id"]),
    }


def dataset_out(d: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": d["id"], "study_id": d["study_id"], "job_id": d["job_id"], "status": d["status"],
        "source_path": d["source_path"], "h3d_count": d["h3d_count"], "train_count": d["train_count"],
        "eval_count": d["eval_count"], "holdout_ratio": float(d["holdout_ratio"]), "seed": d["seed"],
        "split_group": d["split_group"], "options": d["options_json"] or {}, "package_ready": d["package_rel"] is not None,
        "package_rel": d["package_rel"], "created_by_name": d["created_by_name"], "created_at": d["created_at"],
    }


def model_out(m: dict[str, Any], final_model_id: str | None, *, with_curve: bool) -> dict[str, Any]:
    curve = m.get("loss_curve")
    return {
        "id": m["id"], "study_id": m["study_id"], "name": m["name"], "version": m["version"], "label": m["label"],
        "dataset_id": m["dataset_id"], "source_path": m["source_path"], "log_status": m["log_status"],
        "log_parser": m["log_parser"], "epochs_total": m["epochs_total"], "last_epoch": m["last_epoch"],
        "final_loss": m["final_loss"], "min_loss": m["min_loss"], "min_loss_epoch": m["min_loss_epoch"],
        "loss_curve": curve if with_curve else None, "curve_points": len(curve or []),
        "eval_status": m["eval_status"], "eval_score": m["eval_score"], "status": m["status"],
        "is_final": final_model_id == m["id"], "registered_by_name": m["registered_by_name"],
        "registered_at": m["registered_at"], "row_version": m["row_version"],
    }


def param_set_out(p: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": p["id"], "study_id": p["study_id"], "source_path": p["source_path"], "unit_system": p["unit_system"],
        "parameters": p["parameters"], "responses": p["responses"], "sample_count": p["sample_count"],
        "sample_has_measured": p["sample_has_measured"], "cad_file_name": p["cad_file_name"],
        "starter_name": p["starter_name"], "tpl_params": p["tpl_params"], "is_current": p["is_current"],
        "registered_by_name": p["registered_by_name"], "registered_at": p["registered_at"],
    }


def job_summary(j: dict[str, Any], study_title: str | None, position: int | None) -> dict[str, Any]:
    return {
        "id": j["id"], "study_id": j["study_id"], "project_id": j["project_id"], "study_title": study_title,
        "job_type": j["job_type"], "stage": j["stage"], "lane": j["lane"], "state": j["state"],
        "created_by": j["created_by"], "created_by_name": j["created_by_name"],
        "queue_position": position if j["state"] == "QUEUED" else None,
        "progress_pct": j["progress_pct"], "progress_label": j["progress_label"],
        "cancel_requested": j["cancel_requested_at"] is not None, "created_at": j["created_at"],
        "started_at": j["started_at"],
    }


def can_retry(j: dict[str, Any], principal: Principal) -> bool:
    if j["state"] not in TERMINAL or j["state"] == "SUCCEEDED":
        return False
    if principal.is_global_admin:
        return True
    return j["created_by"] == principal.user_id and principal.can_execute(j["project_id"])


def job_detail(conn: Connection, j: dict[str, Any], principal: Principal, *, include_commands: bool) -> dict[str, Any]:
    study = studies_repo.get(conn, j["study_id"])
    pos = jobs_repo.queue_positions(conn, j["lane"]).get(j["id"]) if j["state"] == "QUEUED" else None
    steps = []
    for s in jobs_repo.get_steps(conn, j["id"]):
        item = {k: s[k] for k in ("step_no", "step_key", "kind", "state", "progress_pct", "progress_label", "started_at",
                                  "finished_at", "exit_code", "failure_code", "failure_message")}
        if include_commands:
            item["command"] = s["command"]
        steps.append(item)
    out = job_summary(j, study["title"] if study else None, pos)
    out.update({
        "params": j["params"], "result": j["result"], "warnings": j["warnings"] or [], "steps": steps,
        "failure_code": j["failure_code"], "failure_message": j["failure_message"], "finished_at": j["finished_at"],
        "retry_of_job_id": j["retry_of_job_id"], "attention_code": j["attention_code"], "version": j["version"],
        "can_cancel": principal.is_global_admin and j["state"] not in TERMINAL,
        "can_retry": can_retry(j, principal),
    })
    return out


def file_size(path: str) -> int:
    try:
        return os.path.getsize(path)
    except OSError:
        return 0
