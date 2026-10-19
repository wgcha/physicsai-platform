"""④ 단일 예측 실행 목록·상세(phase3 §21.2 S16 V1). 새 DB 없음 — PREDICT 작업 params·result + param_sets·models 조회.

DB에 쓰지 않는다. 파일은 읽지 않는다(경로 존재 확인만)."""

from __future__ import annotations

import base64
import binascii
import os
from datetime import datetime
from typing import Any

from physicsai_core.db.repositories import contour_media as media_repo
from physicsai_core.db.repositories import jobs as jobs_repo
from physicsai_core.db.repositories import predict_runs as runs_repo
from physicsai_core.db.repositories import studies as studies_repo
from physicsai_core.db.repositories.predict_batches import batch_run_ref
from physicsai_core.errors import DomainError
from physicsai_core.paths import display_path, study_dir

from ..auth import Principal
from ..context import AppContext
from .common import clamp_limit

MODES = ("all", "template", "prepared")
STATES = ("QUEUED", "RUNNING", "SUCCEEDED", "FAILED", "CANCELED", "INTERRUPTED", "WAITING_HPC")
FAILED_STATES = ("FAILED", "CANCELED", "INTERRUPTED")
MAX_RESPONSES = 5


def _invalid(loc: str, msg: str) -> DomainError:
    return DomainError("INVALID_PARAMS", f"{loc}: {msg}", status=422, errors=[{"loc": ["query", loc], "msg": msg}])


def _encode_cursor(j: dict[str, Any]) -> str:
    raw = f"{j['created_at'].isoformat()}|{j['id']}"
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def _decode_cursor(cursor: str | None) -> tuple[datetime, str] | None:
    if not cursor:
        return None
    try:
        raw = base64.urlsafe_b64decode(cursor.encode() + b"==").decode()
        at, _, jid = raw.partition("|")
        if not jid:
            raise ValueError(raw)
        return datetime.fromisoformat(at), jid
    except (ValueError, UnicodeDecodeError, binascii.Error):
        raise _invalid("cursor", "형식이 올바르지 않습니다") from None


def _parse_states(state: str | None) -> list[str] | None:
    if not state:
        return None
    out = [s.strip() for s in state.split(",") if s.strip()]
    bad = [s for s in out if s not in STATES]
    if bad:
        raise _invalid("state", f"알 수 없는 상태 {bad[0]} — {', '.join(STATES)}")
    return out or None


def _input_mode(params: dict[str, Any]) -> str:
    return "prepared" if params.get("input_mode") == "prepared" else "template"


def _failure(conn: Any, j: dict[str, Any]) -> dict[str, Any] | None:
    if j["state"] not in FAILED_STATES:
        return None
    if j.get("failure_code"):
        return {"code": j["failure_code"], "message": j.get("failure_message") or ""}
    for s in jobs_repo.get_steps(conn, j["id"]):
        if s["state"] in FAILED_STATES and s.get("failure_code"):
            return {"code": s["failure_code"], "message": s.get("failure_message") or ""}
    return {"code": j["state"], "message": ""}


def _summary(conn: Any, j: dict[str, Any], *, sets: dict[str, Any], mods: dict[str, Any], verify: dict[str, Any],
             views: dict[str, list[str]]) -> dict[str, Any]:
    p, r = j["params"] or {}, j["result"] or {}
    attempts, root = runs_repo.chain(conn, j)
    psid, mid = r.get("param_set_id") or p.get("param_set_id"), r.get("model_id") or p.get("model_id")
    ps, m = sets.get(psid or ""), mods.get(mid or "")
    dur = None
    if j.get("started_at") and j.get("finished_at"):
        dur = max(0, int((j["finished_at"] - j["started_at"]).total_seconds()))
    cap = r.get("capture") if isinstance(r.get("capture"), dict) else None
    return {
        "job_id": j["id"], "root_job_id": root, "attempts": attempts, "state": j["state"],
        "origin": "fem_verify" if p.get("fem_verify_id") else "manual",
        "created_at": j["created_at"], "started_at": j.get("started_at"), "finished_at": j.get("finished_at"),
        "duration_s": dur, "created_by_name": j["created_by_name"], "input_mode": _input_mode(p),
        "template": {"id": ps["id"], "label": ps.get("label"), "input_kind": ps["input_kind"]} if ps else None,
        "model": {"id": m["id"], "name": m["name"], "version": m["version"]} if m else None,
        "values": r.get("values") if r.get("values") is not None else (p.get("values") or {}),
        "applied_values": r.get("applied_values") or {}, "out_of_range": list(r.get("out_of_range") or []),
        "input_path": p.get("input_path") if _input_mode(p) == "prepared" else None, "starter": r.get("starter"),
        "responses": [{"name": x.get("name"), "unit": x.get("unit") or "", "predicted": x.get("predicted")}
                      for x in (r.get("response_table") or [])[:MAX_RESPONSES] if isinstance(x, dict)],
        "capture": {"status": cap.get("status"), "views": views.get(j["id"], [])} if cap else None,
        "has_curve": bool(r.get("curve_artifact_id")), "warnings_count": len(j.get("warnings") or []),
        "failure": _failure(conn, j), "verify": verify.get(j["id"]),
    }


def _summaries(conn: Any, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    psids = [(j["result"] or {}).get("param_set_id") or (j["params"] or {}).get("param_set_id") for j in rows]
    mids = [(j["result"] or {}).get("model_id") or (j["params"] or {}).get("model_id") for j in rows]
    sets, mods = runs_repo.param_sets_by_ids(conn, psids), runs_repo.models_by_ids(conn, mids)
    ids = [j["id"] for j in rows]
    verify = runs_repo.latest_verify(conn, ids)
    views = media_repo.media_views_for_jobs(conn, ids)
    return [_summary(conn, j, sets=sets, mods=mods, verify=verify, views=views) for j in rows]


def list_runs(ctx: AppContext, principal: Principal, study_id: str, *, mode: str | None, state: str | None,
              limit: int | None, cursor: str | None) -> tuple[list[dict[str, Any]], str | None]:
    mode = mode or "all"
    if mode not in MODES:
        raise _invalid("mode", "all | template | prepared")
    states = _parse_states(state)
    after = _decode_cursor(cursor)
    lim = clamp_limit(limit)
    with ctx.engine.connect() as conn:
        studies_repo.require(conn, study_id)
        rows = runs_repo.list_runs(conn, study_id, mode=mode, states=states, limit=lim + 1, after=after)
        out = _summaries(conn, rows[:lim])
    return out, (_encode_cursor(rows[lim - 1]) if len(rows) > lim else None)


def _paths(ctx: AppContext, study: dict[str, Any], root: str, result: dict[str, Any]) -> dict[str, str | None]:
    ai = ctx.settings.storage.ai_root
    base = study_dir(ai, study["folder_name"])
    d = f"04_predict/{root}"
    rels = {"dir": (d, True), "input_dir": (f"{d}/INPUT", True), "result_dir": (f"{d}/RESULT", True),
            "pred_h3d": (result.get("pred_h3d_rel"), False), "media_dir": (f"{d}/RESULT/media", True),
            "geom_dir": (f"{d}/geom", True)}
    out: dict[str, str | None] = {}
    for k, (rel, is_dir) in rels.items():
        full = os.path.join(base, *rel.split("/")) if rel else None
        ok = bool(full) and (os.path.isdir(full) if is_dir else os.path.isfile(full))  # type: ignore[arg-type]
        out[k] = display_path(ai, study["folder_name"], rel) if ok else None
    return out


def get_run(ctx: AppContext, principal: Principal, job_id: str) -> dict[str, Any]:
    with ctx.engine.connect() as conn:
        j = jobs_repo.get_job(conn, job_id)
        if j is None:
            raise DomainError("JOB_NOT_FOUND", "작업을 찾을 수 없습니다", status=404)
        if j["job_type"] != "PREDICT" or batch_run_ref(j) is not None:
            raise DomainError("NOT_PREDICT_RUN", "단일 예측 작업이 아닙니다", status=404)
        study = studies_repo.require(conn, j["study_id"])
        out = _summaries(conn, [j])[0]
    r = j["result"] or {}
    cap = r.get("capture") if isinstance(r.get("capture"), dict) else {}
    near = r.get("nearest") if isinstance(r.get("nearest"), dict) else None
    out.update({
        "nearest": {"run_key": near.get("run_key"), "distance": near.get("distance")} if near else None,
        "response_table": [x for x in (r.get("response_table") or []) if isinstance(x, dict)],
        "paths": _paths(ctx, study, out["root_job_id"], r),
        "display": cap.get("display") if isinstance(cap.get("display"), dict) else None,
    })
    return out
