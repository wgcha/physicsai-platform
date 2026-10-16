"""④ 일괄 예측 저장소(phase3 §14.3·§14.5 S9): predict_batches·predict_batch_runs 생성·행 갱신·하위 PREDICT 일괄 생성·완료 판정.

API(미리보기·생성·조회·취소·retry-failed), 워커(BP_PREP·BP_GEN·BP_ENQUEUE), 종료 훅(job_end)이 같이 쓴다.
알림 발송·권한 판단은 호출부 몫 — 여기서는 행만 다룬다.
"""

from __future__ import annotations

import math
import os
import uuid
from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import and_, func, select, update
from sqlalchemy.engine import Connection

from ...state_machine import TERMINAL
from ...stage4_predict.batch_matrix import BatchMatrix, BatchRow, batch_label, input_rel_for
from ..tables import jobs, predict_batch_runs, predict_batches, studies
from .jobs import insert_job, row_dict

# 결과 표 행 상태(§14.7): 생성 대기·생성 중·생성 실패·예측 대기·실행 중·완료·실패·취소
ROW_STATES = ("GEN_PENDING", "GENERATING", "GEN_FAILED", "QUEUED", "RUNNING", "SUCCEEDED", "FAILED", "CANCELED")
_GEN_ROW_STATE = {"PENDING": "GEN_PENDING", "RUNNING": "GENERATING", "FAILED": "GEN_FAILED"}
_JOB_ROW_STATE = {"QUEUED": "QUEUED", "RUNNING": "RUNNING", "WAITING_HPC": "RUNNING", "COLLECTING": "RUNNING",
                  "SUCCEEDED": "SUCCEEDED", "FAILED": "FAILED", "INTERRUPTED": "FAILED", "CANCELED": "CANCELED"}


# ---- 생성 --------------------------------------------------------------------------------------


def next_batch_no(conn: Connection, study_id: str) -> int:
    """Study별 다음 batch_no(1부터). 호출부가 Study 행을 FOR UPDATE로 잠근 트랜잭션에서 부른다(D3-25)."""
    cur = conn.execute(select(func.max(predict_batches.c.batch_no)).where(predict_batches.c.study_id == study_id)).scalar()
    return int(cur or 0) + 1


def create_batch(
    conn: Connection,
    *,
    batch_id: str,
    batch_no: int,
    study_id: str,
    job_id: str,
    param_set_id: str,
    model_id: str,
    input_kind: str,
    matrix: BatchMatrix,
    multi_execution: int,
    dir_rel: str,
    simlab_mesh_name: str,
    user_id: str,
    user_name: str,
) -> dict[str, Any]:
    """배치 행 + run 행(matrix.rows, gen_state PENDING)을 넣는다. 부모 PREDICT_BATCH 작업(job_id)을 먼저 만든 뒤 부른다."""
    conn.execute(predict_batches.insert().values(
        id=batch_id, study_id=study_id, batch_no=batch_no, job_id=job_id, param_set_id=param_set_id, model_id=model_id,
        input_kind=input_kind, source_kind=matrix.source_kind, source_meta=matrix.source_meta,
        multi_execution=multi_execution, run_count=len(matrix.rows), dir_rel=dir_rel, status="GENERATING",
        created_by=user_id, created_by_name=user_name,
    ))
    insert_runs(conn, batch_id, matrix.rows, input_kind=input_kind, simlab_mesh_name=simlab_mesh_name)
    return get(conn, batch_id)  # type: ignore[return-value]


def insert_runs(conn: Connection, batch_id: str, rows: Sequence[BatchRow], *, input_kind: str, simlab_mesh_name: str) -> None:
    """조합 행 → predict_batch_runs(input_rel = 배치 폴더 기준, batch_matrix.input_rel_for)."""
    for r in rows:
        conn.execute(predict_batch_runs.insert().values(
            batch_id=batch_id, doe_no=r.doe_no, run_key=r.run_key, values=r.values, applied_values=r.applied_values,
            out_of_range=r.out_of_range, gen_state="PENDING",
            input_rel=input_rel_for(r.run_key, input_kind, simlab_mesh_name),
        ))


# ---- 조회 --------------------------------------------------------------------------------------


def get(conn: Connection, batch_id: str, *, for_update: bool = False) -> dict[str, Any] | None:
    """배치 1개(없으면 None)."""
    q = select(predict_batches).where(predict_batches.c.id == batch_id)
    if for_update:
        q = q.with_for_update()
    return row_dict(conn.execute(q).first())


def get_by_job(conn: Connection, job_id: str) -> dict[str, Any] | None:
    """부모 PREDICT_BATCH 작업 id(최신 부모)로 배치 찾기."""
    return row_dict(conn.execute(select(predict_batches).where(predict_batches.c.job_id == job_id)).first())


def list_for_study(conn: Connection, study_id: str, limit: int = 200) -> list[dict[str, Any]]:
    """Study의 배치 목록(최신 batch_no 먼저)."""
    q = (select(predict_batches).where(predict_batches.c.study_id == study_id)
         .order_by(predict_batches.c.batch_no.desc()).limit(limit))
    return [row_dict(r) for r in conn.execute(q)]


def runs(conn: Connection, batch_id: str, *, gen_states: Sequence[str] | None = None) -> list[dict[str, Any]]:
    """배치의 run 행(doe_no 순). gen_states로 거른다."""
    q = select(predict_batch_runs).where(predict_batch_runs.c.batch_id == batch_id)
    if gen_states:
        q = q.where(predict_batch_runs.c.gen_state.in_(list(gen_states)))
    return [row_dict(r) for r in conn.execute(q.order_by(predict_batch_runs.c.doe_no))]


def runs_with_jobs(conn: Connection, batch_id: str) -> list[dict[str, Any]]:
    """run 행 + 하위 작업 상태(`job_state`·`job_failure_code`·`job_failure_message`, 하위 없으면 None) — 결과 표·완료 판정용."""
    q = (select(predict_batch_runs, jobs.c.state.label("job_state"), jobs.c.failure_code.label("job_failure_code"),
                jobs.c.failure_message.label("job_failure_message"))
         .select_from(predict_batch_runs.outerjoin(jobs, jobs.c.id == predict_batch_runs.c.predict_job_id))
         .where(predict_batch_runs.c.batch_id == batch_id).order_by(predict_batch_runs.c.doe_no))
    return [row_dict(r) for r in conn.execute(q)]


def run_by_predict_job(conn: Connection, job_id: str) -> dict[str, Any] | None:
    """하위 PREDICT 작업 id → run 행(재시도로 바뀐 뒤의 이전 id는 찾지 못한다)."""
    return row_dict(conn.execute(select(predict_batch_runs).where(predict_batch_runs.c.predict_job_id == job_id)).first())


def batch_run_ref(job: Mapping[str, Any]) -> tuple[str, int] | None:
    """작업 params의 `batch_run{batch_id, doe_no}` → (batch_id, doe_no). 일괄 예측 하위가 아니면 None."""
    br = (job.get("params") or {}).get("batch_run") if isinstance(job.get("params"), Mapping) else None
    if not isinstance(br, Mapping) or not isinstance(br.get("batch_id"), str) or not isinstance(br.get("doe_no"), int):
        return None
    return br["batch_id"], br["doe_no"]


# ---- 갱신 --------------------------------------------------------------------------------------


def set_batch(conn: Connection, batch_id: str, **values: Any) -> None:
    """배치 열 갱신(status·finished_at·job_id 등)."""
    conn.execute(update(predict_batches).where(predict_batches.c.id == batch_id).values(**values))


def set_run(conn: Connection, batch_id: str, doe_no: int, **values: Any) -> None:
    """run 1행 갱신(gen_state·gen_code·gen_message·predict_job_id·responses)."""
    if "gen_message" in values and values["gen_message"] is not None:
        values["gen_message"] = str(values["gen_message"])[:500]
    conn.execute(update(predict_batch_runs)
                 .where(and_(predict_batch_runs.c.batch_id == batch_id, predict_batch_runs.c.doe_no == doe_no))
                 .values(**values))


def cancel_active(conn: Connection, batch_id: str) -> bool:
    """일괄 취소: GENERATING·PREDICTING 배치를 CANCELED + finished_at(이미 끝났으면 그대로). 바꿨으면 True."""
    r = conn.execute(update(predict_batches)
                     .where(and_(predict_batches.c.id == batch_id,
                                 predict_batches.c.status.in_(["GENERATING", "PREDICTING"])))
                     .values(status="CANCELED", finished_at=func.now()))
    return bool(r.rowcount)


def set_parent_job(conn: Connection, batch_id: str, job_id: str) -> None:
    """부모 재시도: 최신 부모 작업으로 바꾸고 GENERATING(§14.5)."""
    set_batch(conn, batch_id, job_id=job_id, status="GENERATING", finished_at=None)


def replace_child_job(conn: Connection, old_job_id: str, new_job_id: str) -> dict[str, Any] | None:
    """하위 재시도(on_retry): run의 predict_job_id를 새 작업으로, 응답 비움, 배치 PREDICTING(§14.5). run 행을 돌려준다."""
    run = run_by_predict_job(conn, old_job_id)
    if run is None:
        return None
    set_run(conn, run["batch_id"], run["doe_no"], predict_job_id=new_job_id, responses=None)
    set_batch(conn, run["batch_id"], status="PREDICTING", finished_at=None)
    return run


def enqueue_children(conn: Connection, batch_id: str, *, batch_dir: str) -> list[dict[str, Any]]:
    """BP_ENQUEUE: gen_state=DONE이고 하위가 없는 run마다 PREDICT(prepared)를 doe_no 순으로 만들고(한 트랜잭션, 등록자 = 배치
    등록자) 배치를 PREDICTING으로. batch_dir = 배치 폴더 절대경로. 만든 작업 목록을 돌려준다."""
    b = get(conn, batch_id, for_update=True)
    if b is None or b["status"] == "CANCELED":  # 일괄 취소 뒤 늦게 끝난 부모는 하위를 만들지 않는다
        return []
    study = row_dict(conn.execute(select(studies).where(studies.c.id == b["study_id"])).first())
    created: list[dict[str, Any]] = []
    for r in runs(conn, batch_id, gen_states=["DONE"]):
        if r["predict_job_id"] is not None:
            continue
        params = {
            "input_mode": "prepared",
            "input_path": os.path.normpath(os.path.join(batch_dir, *r["input_rel"].split("/"))),
            "model_id": b["model_id"],
            "param_set_id": b["param_set_id"],
            # batch_no는 작업 목록 표시(JobSummary.batch.label)용 — 판정은 batch_id·doe_no만(batch_run_ref)
            "batch_run": {"batch_id": batch_id, "doe_no": r["doe_no"], "batch_no": b["batch_no"]},
        }
        job = insert_job(conn, study=study, job_type="PREDICT", params=params, user_id=b["created_by"],
                         user_name=b["created_by_name"])
        set_run(conn, batch_id, r["doe_no"], predict_job_id=job["id"])
        created.append(job)
    set_batch(conn, batch_id, status="PREDICTING")
    return created


def reset_failed_gen(conn: Connection, batch_id: str) -> int:
    """부모 재생성(재시도·retry-failed) 전: 생성이 끝나지 않은 run(PENDING 제외)을 PENDING으로 되돌리고 사유를 지운다. 바꾼 행 수."""
    r = conn.execute(update(predict_batch_runs)
                     .where(and_(predict_batch_runs.c.batch_id == batch_id,
                                 predict_batch_runs.c.gen_state.in_(["FAILED", "RUNNING"])))
                     .values(gen_state="PENDING", gen_code=None, gen_message=None))
    return int(r.rowcount or 0)


def active_child_job_ids(conn: Connection, batch_id: str) -> list[str]:
    """비종료 하위 PREDICT 작업 id(doe_no 순) — 일괄 취소용."""
    return [r["predict_job_id"] for r in runs_with_jobs(conn, batch_id)
            if r["predict_job_id"] and r["job_state"] is not None and r["job_state"] not in TERMINAL]


# ---- 상태·완료 판정 --------------------------------------------------------------------------------


def row_state(run: Mapping[str, Any], job_state: str | None) -> str:
    """run 행 + 하위 작업 상태 → 결과 표 상태(ROW_STATES)."""
    if run["gen_state"] != "DONE":
        return _GEN_ROW_STATE[run["gen_state"]]
    if job_state is None:
        return "QUEUED"  # 생성 완료, 대기열 등록 전
    return _JOB_ROW_STATE.get(job_state, "FAILED")


def counts(conn: Connection, batch_id: str) -> dict[str, dict[str, int]]:
    """진행 집계 `{gen:{total,done,failed,running,waiting}, predict:{running,queued,succeeded,failed,canceled}}`(§14.7)."""
    gen = {"total": 0, "done": 0, "failed": 0, "running": 0, "waiting": 0}
    pred = {"running": 0, "queued": 0, "succeeded": 0, "failed": 0, "canceled": 0}
    for r in runs_with_jobs(conn, batch_id):
        gen["total"] += 1
        gen[{"DONE": "done", "FAILED": "failed", "RUNNING": "running"}.get(r["gen_state"], "waiting")] += 1
        if r["gen_state"] == "DONE":
            st = row_state(r, r["job_state"])
            pred[{"QUEUED": "queued", "RUNNING": "running", "SUCCEEDED": "succeeded", "CANCELED": "canceled"}.get(st, "failed")] += 1
    return {"gen": gen, "predict": pred}


def mark_done_if_complete(conn: Connection, batch_id: str) -> dict[str, int] | None:
    """PREDICTING 배치의 모든 run이 끝났으면(생성 실패 포함) DONE + finished_at. 이번에 DONE이 됐으면
    `{succeeded, failed}`(실패 = 생성 실패·실패·취소·중단), 아니면 None(멱등)."""
    b = get(conn, batch_id, for_update=True)
    if b is None or b["status"] != "PREDICTING":
        return None
    ok = bad = 0
    for r in runs_with_jobs(conn, batch_id):
        if r["gen_state"] == "FAILED":
            bad += 1
        elif r["gen_state"] != "DONE" or r["job_state"] is None or r["job_state"] not in TERMINAL:
            return None
        elif r["job_state"] == "SUCCEEDED":
            ok += 1
        else:
            bad += 1
    set_batch(conn, batch_id, status="DONE", finished_at=func.now())
    return {"succeeded": ok, "failed": bad}


def done_notice(batch_no: int, succeeded: int, failed: int) -> tuple[str, str]:
    """PREDICT_BATCH_DONE 알림 (제목, 본문): "일괄 예측 B-003 완료 — 완료 18 · 실패 2"."""
    return f"일괄 예측 {batch_label(batch_no)} 완료 — 완료 {succeeded} · 실패 {failed}", "결과 표에서 run별 예측값을 확인하세요."


def responses_from_result(result: Mapping[str, Any] | None) -> dict[str, float | None] | None:
    """하위 PREDICT result.response_table → `{name: 예측값}`(유한 수치만, 아니면 None). 표가 없으면 None."""
    table = (result or {}).get("response_table")
    if not isinstance(table, list):
        return None
    out: dict[str, float | None] = {}
    for row in table:
        if isinstance(row, Mapping) and isinstance(row.get("name"), str):
            v = row.get("predicted")
            ok = isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
            out[row["name"]] = float(v) if ok else None
    return out


def on_child_end(conn: Connection, job: Mapping[str, Any], state: str) -> tuple[dict[str, Any], dict[str, int]] | None:
    """하위 PREDICT 종료 훅(job_end에서 호출): 성공이면 응답 복사, 그 뒤 완료 판정. 이번에 배치가 DONE이 되면
    (배치 행, {succeeded, failed})를 돌려준다 — 호출부가 PREDICT_BATCH_DONE 알림을 만든다."""
    ref = batch_run_ref(job)
    if ref is None:
        return None
    batch_id, doe_no = ref
    cur = row_dict(conn.execute(select(predict_batch_runs.c.predict_job_id).where(and_(
        predict_batch_runs.c.batch_id == batch_id, predict_batch_runs.c.doe_no == doe_no))).first())
    if cur is None or cur["predict_job_id"] != job.get("id"):  # 재시도로 바뀐 이전 하위는 무시
        return None
    if state == "SUCCEEDED":
        set_run(conn, batch_id, doe_no, responses=responses_from_result(job.get("result")))
    done = mark_done_if_complete(conn, batch_id)
    if done is None:
        return None
    return get(conn, batch_id), done  # type: ignore[return-value]


def new_batch_id() -> str:
    """배치 id(uuid4) — 작업 params에 먼저 기록하려고 미리 만든다."""
    return str(uuid.uuid4())
