"""④ 일괄 예측(DOE) API(phase3 §14.7 S9): 미리보기·목록·상세(행 짝짓기)·CSV·커브·일괄 취소·실패만 다시.

권한: 조회·미리보기 = 로그인(member), 취소 = power + (등록자 또는 전역 관리자), 실패만 다시 = power.
생성은 기존 `POST /studies/{id}/jobs`(job_type PREDICT_BATCH, `job_params.stage4_batch`).
"""

from __future__ import annotations

import csv
import io
import json
import math
import os
import statistics
import uuid
from typing import Any

from physicsai_core.db.repositories import artifacts as artifacts_repo
from physicsai_core.db.repositories import contour_media as media_repo
from physicsai_core.db.repositories import jobs as jobs_repo
from physicsai_core.db.repositories import models as models_repo
from physicsai_core.db.repositories import param_sets as ps_repo
from physicsai_core.db.repositories import predict_batches as pb_repo
from physicsai_core.db.repositories import studies as studies_repo
from physicsai_core.db.repositories import surrogate_opts as so_repo
from physicsai_core.errors import DomainError
from physicsai_core.paths import display_path, resolve_in_study
from physicsai_core.stage4_predict.batch_matrix import batch_label
from physicsai_core.state_machine import TERMINAL

from ..auth import Principal
from ..context import AppContext
from .common import audit, require_config_ok, require_power, study_root
from .job_params.stage4_batch import build_matrix, resolve_param_set
from .job_params.study_manage import study_gate
from .jobs import retry_locked

ESTIMATE_SAMPLES = 5  # 예상 소요 = 최근 성공 PREDICT 5개 소요 중앙값 × N
MAX_CURVE_POINTS = 2000
ACTIVE_BATCH = ("GENERATING", "PREDICTING")
RETRY_CHILD_STATES = ("FAILED", "CANCELED", "INTERRUPTED")


# ---- 공용 --------------------------------------------------------------------------------------


def _require_batch(conn: Any, batch_id: str, *, for_update: bool = False) -> dict[str, Any]:
    b = pb_repo.get(conn, batch_id, for_update=for_update)
    if b is None:
        raise DomainError("BATCH_NOT_FOUND", "일괄 예측을 찾을 수 없습니다", status=404)
    return b


def _require_not_opt_owned(conn: Any, batch_id: str) -> None:
    """내장 최적화 소유 배치(phase3 §18.6)의 배치 단위 취소·실패만 다시 → 409 BATCH_OWNED_BY_OPT(⑤에서 조작)."""
    it = so_repo.owned_iter_of_batch(conn, batch_id)
    if it is not None:
        label = so_repo.opt_label(it["opt_no"])
        raise DomainError("BATCH_OWNED_BY_OPT", f"내장 최적화 {label}의 배치입니다 — ⑤에서 취소·이어서 실행하세요", status=409,
                          surrogate_opt_id=it["opt_id"])


def _can_cancel(b: dict[str, Any], principal: Principal, project_id: str) -> bool:
    return (b["status"] in ACTIVE_BATCH and principal.can_execute(project_id)
            and (principal.is_global_admin or b["created_by"] == principal.user_id))


def _retry_targets(rows: list[dict[str, Any]]) -> tuple[bool, list[dict[str, Any]]]:
    """(생성 다시 필요, 다시 실행할 하위 run 행)."""
    regen = any(r["gen_state"] != "DONE" for r in rows)
    kids = [r for r in rows if r["gen_state"] == "DONE" and r["predict_job_id"] and r["job_state"] in RETRY_CHILD_STATES]
    return regen, kids


def _detail(ctx: AppContext, conn: Any, b: dict[str, Any], principal: Principal) -> dict[str, Any]:
    s = studies_repo.require(conn, b["study_id"])
    ps = ps_repo.get(conn, b["param_set_id"]) or {}
    m = models_repo.get(conn, b["model_id"]) or {}
    parent = jobs_repo.get_job(conn, b["job_id"])
    rows = pb_repo.runs_with_jobs(conn, b["id"])
    media = media_repo.media_views_for_jobs(conn, [r["predict_job_id"] for r in rows])  # phase3 §15 S10
    root = ctx.settings.storage.ai_root
    out_rows = []
    for r in rows:
        st = pb_repo.row_state(r, r["job_state"])
        gen_fail = r["gen_state"] == "FAILED"
        out_rows.append({
            "doe_no": r["doe_no"], "run_key": r["run_key"],
            "folder": display_path(root, s["folder_name"], f"{b['dir_rel']}/{r['run_key']}"),
            "values": r["values"], "applied_values": r["applied_values"], "out_of_range": r["out_of_range"] or [],
            "state": st,
            "code": r["gen_code"] if gen_fail else (r["job_failure_code"] if st in ("FAILED", "CANCELED") else None),
            "message": r["gen_message"] if gen_fail else (r["job_failure_message"] if st in ("FAILED", "CANCELED") else None),
            "job_id": r["predict_job_id"], "responses": r["responses"],
            "media_views": media.get(r["predict_job_id"] or "", []),
        })
    regen, kids = _retry_targets(rows)
    owned = so_repo.owned_iter_of_batch(conn, b["id"]) is not None  # phase3 §18.6: ⑤에서만 취소·이어서 실행
    parent_active = parent is not None and parent["state"] not in TERMINAL
    return {
        "id": b["id"], "label": batch_label(b["batch_no"]), "status": b["status"],
        "dir": display_path(root, s["folder_name"], b["dir_rel"]), "input_kind": b["input_kind"],
        "source_kind": b["source_kind"],
        "param_set": {"id": b["param_set_id"], "label": ps.get("label")},
        "model": {"id": b["model_id"], "name": f"{m['name']} v{m['version']}" if m else b["model_id"]},
        "job_id": b["job_id"], "multi_execution": b["multi_execution"], **pb_repo.counts(conn, b["id"]),
        "parameters": [p["name"] for p in ps.get("parameters") or []],
        "responses": [{"name": x["name"], "unit": x.get("unit") or ""} for x in ps.get("responses") or []],
        "rows": out_rows, "created_at": b["created_at"], "created_by_name": b["created_by_name"],
        "finished_at": b["finished_at"], "can_cancel": not owned and _can_cancel(b, principal, s["project_id"]),
        "can_retry_failed": not owned and principal.can_execute(s["project_id"]) and not parent_active and (regen or bool(kids)),
    }


# ---- 미리보기·조회 ---------------------------------------------------------------------------------


def _estimate_min(conn: Any, study_id: str, count: int) -> float | None:
    secs = []
    for j in jobs_repo.succeeded_predicts(conn, study_id, limit=ESTIMATE_SAMPLES * 4):
        if j["started_at"] and j["finished_at"]:
            secs.append((j["finished_at"] - j["started_at"]).total_seconds())
        if len(secs) >= ESTIMATE_SAMPLES:
            break
    if not secs:
        return None
    return round(statistics.median(secs) * count / 60.0, 1)


def preview(ctx: AppContext, study_id: str, body: Any) -> dict[str, Any]:
    """§14.7 미리보기(동기, 워커 없음): 작업 생성과 같은 조합 계산. 조합 문제는 200 problems(생성 때는 422)."""
    with ctx.engine.connect() as conn:
        s = studies_repo.require(conn, study_id)
        ps = resolve_param_set(conn, s, body.param_set_id)
        matrix = build_matrix(ctx, conn, s, ps, body.source.model_dump())
        est = _estimate_min(conn, study_id, len(matrix.rows)) if matrix.rows else None
    return {"input_kind": ps.get("input_kind") or "assembly", "count": len(matrix.rows), "estimate_min": est,
            "rows": [r.as_dict() for r in matrix.rows], "problems": matrix.problems}


def list_batches(ctx: AppContext, study_id: str) -> list[dict[str, Any]]:
    """배치 목록(최신 먼저) + 템플릿 이름·입력 생성·예측 집계(D3-53 "실행 목록" 탭)."""
    with ctx.engine.connect() as conn:
        studies_repo.require(conn, study_id)
        rows = pb_repo.list_for_study(conn, study_id)
        sets = {pid: ps_repo.get(conn, pid) or {} for pid in {b["param_set_id"] for b in rows}}
        return [{"id": b["id"], "label": batch_label(b["batch_no"]), "status": b["status"], "run_count": b["run_count"],
                 "created_at": b["created_at"], "created_by_name": b["created_by_name"],
                 "param_set": {"id": b["param_set_id"], "label": sets[b["param_set_id"]].get("label")},
                 **pb_repo.counts(conn, b["id"]), "response_summary": _response_summary(conn, b["id"], sets[b["param_set_id"]])}
                for b in rows]


def _response_summary(conn: Any, batch_id: str, ps: dict[str, Any]) -> dict[str, Any] | None:
    """첫 응답의 완료 run 값 최소~최대(실행 목록 1줄). 응답 정의·값이 없으면 None."""
    first = next((r for r in ps.get("responses") or [] if isinstance(r, dict) and r.get("name")), None)
    if first is None:
        return None
    vals = [float(v) for r in pb_repo.runs_with_jobs(conn, batch_id) if r["job_state"] == "SUCCEEDED"
            for v in [(r["responses"] or {}).get(first["name"])]
            if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)]
    if not vals:
        return None
    return {"name": first["name"], "unit": first.get("unit") or "", "min": min(vals), "max": max(vals), "count": len(vals)}


def get_batch(ctx: AppContext, principal: Principal, batch_id: str) -> dict[str, Any]:
    with ctx.engine.connect() as conn:
        return _detail(ctx, conn, _require_batch(conn, batch_id), principal)


def _num(v: Any) -> str:
    return "" if v is None else repr(float(v))


def table_csv(ctx: AppContext, principal: Principal, batch_id: str) -> tuple[bytes, str]:
    """결과 표 CSV(UTF-8 BOM): doe_no,run_key,folder,<파라미터(반영값)>,<응답>,state."""
    d = get_batch(ctx, principal, batch_id)
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    resp = [x["name"] for x in d["responses"]]
    w.writerow(["doe_no", "run_key", "folder", *d["parameters"], *resp, "state"])
    for r in d["rows"]:
        w.writerow([r["doe_no"], r["run_key"], r["folder"],
                    *[_num((r["applied_values"] or {}).get(n)) for n in d["parameters"]],
                    *[_num((r["responses"] or {}).get(n)) for n in resp], r["state"]])
    return ("﻿" + buf.getvalue()).encode("utf-8"), f"{d['label']}.csv"


# ---- 커브 겹쳐보기 --------------------------------------------------------------------------------


def downsample(x: list[float], y: list[float], max_points: int) -> tuple[list[float], list[float], bool]:
    """구간별 최소·최대 보존 다운샘플(점 ≤ max_points, 첫·끝 점 유지)."""
    n = len(x)
    if n <= max_points:
        return x, y, False
    buckets = max(1, (max_points - 2) // 2)
    keep = {0, n - 1}
    inner = n - 2
    for b in range(buckets):
        lo = 1 + b * inner // buckets
        hi = 1 + (b + 1) * inner // buckets
        if hi <= lo:
            continue
        seg = range(lo, hi)
        keep.add(min(seg, key=lambda i: y[i]))
        keep.add(max(seg, key=lambda i: y[i]))
    idx = sorted(keep)
    return [x[i] for i in idx], [y[i] for i in idx], True


def _curve_json(ctx: AppContext, study: dict[str, Any], conn: Any, job: dict[str, Any] | None) -> dict[str, Any] | None:
    aid = ((job or {}).get("result") or {}).get("curve_artifact_id")
    a = artifacts_repo.get(conn, aid) if isinstance(aid, str) else None
    if a is None:
        return None
    try:
        p = resolve_in_study(study_root(ctx, study), a["rel_path"])
        if os.path.getsize(p) > ctx.settings.ui.max_artifact_bytes:
            return None
        with open(p, encoding="utf-8-sig") as fh:
            data = json.load(fh)
    except (OSError, ValueError, DomainError):
        return None
    return data if isinstance(data, dict) and isinstance(data.get("series"), list) else None


def _finite_list(v: Any) -> list[float] | None:
    if not isinstance(v, list):
        return None
    out = []
    for e in v:
        if isinstance(e, bool) or not isinstance(e, (int, float)) or not math.isfinite(e):
            return None
        out.append(float(e))
    return out


def curves(ctx: AppContext, batch_id: str, name: str | None, max_points: int) -> dict[str, Any]:
    """완료(SUCCEEDED) run의 curve.json에서 같은 이름 계열 1개씩(doe_no 순, run ≤ curve_max_runs, 점 ≤ max_points)."""
    max_points = max(2, min(int(max_points), MAX_CURVE_POINTS))
    cap = ctx.settings.predict_batch.curve_max_runs
    with ctx.engine.connect() as conn:
        b = _require_batch(conn, batch_id)
        s = studies_repo.require(conn, b["study_id"])
        done = [r for r in pb_repo.runs_with_jobs(conn, batch_id) if r["predict_job_id"] and r["job_state"] == "SUCCEEDED"]
        truncated = len(done) > cap
        loaded = [(r, _curve_json(ctx, s, conn, jobs_repo.get_job(conn, r["predict_job_id"]))) for r in done[:cap]]
    names: list[str] = []
    for _r, data in loaded:
        for sr in (data or {}).get("series") or []:
            n = sr.get("name") if isinstance(sr, dict) else None
            if isinstance(n, str) and n not in names:
                names.append(n)
    pick = name if name is not None else (names[0] if names else None)
    series, down = [], False
    for r, data in loaded:
        sr = next((x for x in (data or {}).get("series") or [] if isinstance(x, dict) and x.get("name") == pick), None)
        xs, ys = (_finite_list(sr.get("x")), _finite_list(sr.get("y"))) if sr else (None, None)
        if xs is None or ys is None or len(xs) != len(ys) or not xs:
            continue
        xs, ys, d = downsample(xs, ys, max_points)
        down = down or d
        series.append({"doe_no": r["doe_no"], "run_key": r["run_key"], "x": xs, "y": ys})
    return {"names": names, "name": pick, "truncated": truncated, "downsampled": down, "series": series}


# ---- 일괄 취소·실패만 다시 ---------------------------------------------------------------------------


def cancel_batch(ctx: AppContext, principal: Principal, batch_id: str, rid: str, ip: str | None) -> dict[str, Any]:
    """부모·비종료 하위 전부 취소(멱등). 배치를 먼저 CANCELED로 두어 하위 종료 훅이 완료 알림을 만들지 않게 한다."""
    with ctx.engine.begin() as conn:
        b = _require_batch(conn, batch_id, for_update=True)
        s = studies_repo.require(conn, b["study_id"])
        require_power(principal, s["project_id"])
        _require_not_opt_owned(conn, b["id"])
        if not principal.is_global_admin and b["created_by"] != principal.user_id:
            raise DomainError("PERMISSION_DENIED", "일괄 예측 등록자 또는 관리자만 취소할 수 있습니다", status=403,
                              required="owner_or_global_admin")
        pb_repo.cancel_active(conn, b["id"])
        targets = [b["job_id"], *pb_repo.active_child_job_ids(conn, b["id"])]
        canceled = []
        for jid in targets:
            j = jobs_repo.get_job(conn, jid)
            if j is None or j["state"] in TERMINAL or j["cancel_requested_at"] is not None:
                continue
            jobs_repo.request_cancel(conn, jid, principal.user_id)
            canceled.append(jid)
        audit(conn, principal, "PREDICT_BATCH_CANCEL", "predict_batch", b["id"], {"job_ids": canceled}, rid, ip)
        return _detail(ctx, conn, pb_repo.get(conn, b["id"]), principal)  # type: ignore[arg-type]


def retry_failed(ctx: AppContext, principal: Principal, batch_id: str, rid: str, ip: str | None) -> dict[str, Any]:
    """생성 실패(미완료) run이 있으면 부모 PREDICT_BATCH 새 작업({batch_id, batch_no}), 실패·취소·중단 하위는 기존 재시도."""
    with ctx.engine.begin() as conn:
        b = _require_batch(conn, batch_id, for_update=True)
        study = studies_repo.require(conn, b["study_id"], for_update=True)
        require_power(principal, study["project_id"])
        require_config_ok(ctx)
        _require_not_opt_owned(conn, b["id"])
        return retry_failed_locked(conn, principal, b, study, rid, ip)


def retry_failed_locked(conn: Any, principal: Principal, b: dict[str, Any], study: dict[str, Any], rid: str | None,
                        ip: str | None) -> dict[str, Any]:
    """실패만 다시 본체(권한·소유 가드는 호출부 — 내장 최적화 이어서 실행이 가드 없이 부른다, phase3 §18.6)."""
    parent = jobs_repo.get_job(conn, b["job_id"])
    if parent is not None and parent["state"] not in TERMINAL:
        raise DomainError("BATCH_ACTIVE", "입력 생성이 진행 중입니다 — 끝난 뒤 다시 실행하세요", status=409)
    regen, kids = _retry_targets(pb_repo.runs_with_jobs(conn, b["id"]))
    if not regen and not kids:
        raise DomainError("JOB_NOT_RETRYABLE", "다시 실행할 실패 run이 없습니다", status=409)
    study_gate(conn, study, "PREDICT_BATCH")
    retried = []
    for r in kids:
        old = jobs_repo.get_job(conn, r["predict_job_id"])
        retried.append(retry_locked(conn, principal, old, None, rid, ip)["id"])  # type: ignore[arg-type]
    parent_id = None
    if regen:
        parent_id = str(uuid.uuid4())
        params = {"batch_id": b["id"], "batch_no": b["batch_no"]}
        owner = (parent or {}).get("params", {}).get("surrogate_opt") if parent else None
        if owner:  # 최적화 소유 배치: 새 부모도 소유 표시를 이어 받는다(활성 인덱스 제외·⑤ 가드)
            params = {**parent["params"]}  # type: ignore[index]
        jobs_repo.insert_job(conn, study=study, job_type="PREDICT_BATCH", params=params, user_id=principal.user_id,
                             user_name=principal.display_name, job_id=parent_id,
                             result={"batch_id": b["id"], "batch_no": b["batch_no"], "run_count": b["run_count"],
                                     "dir_rel": b["dir_rel"], "regenerate": True})
        pb_repo.reset_failed_gen(conn, b["id"])
        pb_repo.set_parent_job(conn, b["id"], parent_id)
        audit(conn, principal, "JOB_CREATE", "job", parent_id,
              {"job_type": "PREDICT_BATCH", "study_id": study["id"], "batch_id": b["id"]}, rid, ip)
    audit(conn, principal, "PREDICT_BATCH_RETRY_FAILED", "predict_batch", b["id"],
          {"parent_job_id": parent_id, "retried_job_ids": retried}, rid, ip)
    return {"parent_job_id": parent_id, "retried_job_ids": retried}
