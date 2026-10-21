"""④ 일괄 예측(DOE) API(phase3 §14.7 S9): 미리보기·목록·상세(행 짝짓기)·CSV·커브·일괄 취소·실패만 다시.

권한: 조회·미리보기 = 로그인(member), 취소 = power + (등록자 또는 전역 관리자), 실패만 다시 = power.
생성은 기존 `POST /studies/{id}/jobs`(job_type PREDICT_BATCH, `job_params.stage4_batch`).
300줄 분할(R-B): 공용 조회 도우미·상세·단건 조회는 `predict_batches_info`, 표·커브 겹쳐보기는 `predict_batches_curves`(여기서 재노출).
"""

from __future__ import annotations

import statistics
import uuid
from typing import Any

from physicsai_core.db.repositories import jobs as jobs_repo
from physicsai_core.db.repositories import param_sets as ps_repo
from physicsai_core.db.repositories import predict_batches as pb_repo
from physicsai_core.db.repositories import studies as studies_repo
from physicsai_core.db.repositories import surrogate_opts as so_repo  # noqa: F401 - 재노출(module.attr 유지)
from physicsai_core.db.repositories import train as train_repo  # noqa: F401 - 재노출(module.attr 유지)
from physicsai_core.errors import DomainError
from physicsai_core.geometry import native_vars as nv
from physicsai_core.sampling import registry as sampling_registry
from physicsai_core.stage4_predict.batch_matrix import batch_label
from physicsai_core.state_machine import TERMINAL

from ..auth import Principal
from ..context import AppContext
from .common import audit, require_config_ok, require_power
from .job_params.stage4_batch import build_matrix_vars, resolve_param_set
from .job_params.stage4_predict import model_for
from .job_params.study_manage import study_gate
from .jobs import retry_locked
from .predict_batches_info import (  # noqa: F401 - 기존 경로 재노출
    ESTIMATE_SAMPLES, MAX_CURVE_POINTS, ACTIVE_BATCH, RETRY_CHILD_STATES, _sampling_info, _sampling_summary,
    _require_batch, _require_not_opt_owned, _retry_targets, _detail, _response_summary, get_batch,
)
from .predict_batches_curves import table_csv, downsample, curves  # noqa: F401 - 기존 경로 재노출


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
        try:  # native-vars.md §6.3: 학습 범위·out_of_range는 고른 모델 기준(Final·지정 모델이 없으면 학습 범위 없이 미리보기)
            model = model_for(conn, s, body.model_id)
        except DomainError:
            model = None
        matrix, res = build_matrix_vars(ctx, conn, s, ps, body.source.model_dump(), body.vars, model)
        est = _estimate_min(conn, study_id, len(matrix.rows)) if matrix.rows else None
        rows = [{"values": r.values} for r in matrix.rows]
        sampling = _sampling_info(conn, matrix.source_kind, matrix.source_meta, None, rows,
                                  _recommended(ctx, body.source.kind, matrix.source_meta, res.ps))
    return {"input_kind": ps.get("input_kind") or "assembly", "count": len(matrix.rows), "estimate_min": est,
            "rows": [r.as_dict() for r in matrix.rows], "problems": matrix.problems, "notes": matrix.notes,
            "sampling": sampling, "var_rows": nv.var_rows(res.vars, res.pool) if res.vars is not None else [],
            "excluded": list((res.vars or {}).get("excluded") or [])}


def _recommended(ctx: AppContext, kind: str, meta: dict[str, Any], ps: dict[str, Any]) -> int | None:
    """미리보기 `recommended_count`(§20.4 계산식과 같은 값). 이어서 추가 Sobol은 기존 개수(합계 2배)."""
    cont = meta.get("continue_from")
    if kind == "sobol" and cont and isinstance(meta.get("offset"), int) and meta["offset"] > 0:
        return max(4, meta["offset"] & -meta["offset"])
    active = meta.get("active")
    if isinstance(active, list):
        k = len(active)
    else:
        ranges = meta.get("ranges") if isinstance(meta.get("ranges"), dict) else {}
        k = sum(1 for p in ps.get("parameters") or []
                if (lambda r: r[0] < r[1])(ranges.get(p["name"]) or [p["min"], p["max"]]))
    return sampling_registry.recommended_count(kind, k, ctx.settings.predict_batch.max_runs)


def list_batches(ctx: AppContext, study_id: str) -> list[dict[str, Any]]:
    """배치 목록(최신 먼저) + 템플릿 이름·입력 생성·예측 집계(D3-53 "실행 목록" 탭)."""
    with ctx.engine.connect() as conn:
        studies_repo.require(conn, study_id)
        rows = pb_repo.list_for_study(conn, study_id)
        sets = {pid: ps_repo.get(conn, pid) or {} for pid in {b["param_set_id"] for b in rows}}
        return [{"id": b["id"], "label": batch_label(b["batch_no"]), "status": b["status"], "run_count": b["run_count"],
                 "created_at": b["created_at"], "created_by_name": b["created_by_name"],
                 "param_set": {"id": b["param_set_id"], "label": sets[b["param_set_id"]].get("label")},
                 **pb_repo.counts(conn, b["id"]), "response_summary": _response_summary(conn, b["id"], sets[b["param_set_id"]]),
                 "sampling": _sampling_summary(b)}
                for b in rows]


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


def extract_responses(ctx: AppContext, principal: Principal, batch_id: str, rid: str, ip: str | None) -> dict[str, Any]:
    """S17 §22.3.5 `POST /predict-batches/{bid}/extract-responses` → PB_RESP_EXTRACT 작업(사전조건은 job_params.stage4_resp)."""
    from .jobs import create_job

    with ctx.engine.connect() as conn:
        b = _require_batch(conn, batch_id)
    return create_job(ctx, principal, b["study_id"], "PB_RESP_EXTRACT", {"batch_id": batch_id}, rid, ip)
