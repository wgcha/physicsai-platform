"""작업 종료 부수효과(lease 해제·리퍼·취소·HPC 공용): 실패·취소·중단 시 BUILDING/RUNNING 엔터티 행을 FAILED로."""

from __future__ import annotations

from typing import Any

from sqlalchemy import and_, func, update
from sqlalchemy.engine import Connection

from ...state_machine import SUCCEEDED
from ..tables import datasets, models


def _side_effects_on_end(conn: Connection, job: dict[str, Any], state: str) -> None:
    """종료 시 관련 행 정리(데이터셋 FAILED, 평가 상태 FAILED) + 일괄 예측 배치 갱신(성공 포함, phase3 §14.5)."""
    if job["job_type"] in ("PREDICT", "PREDICT_BATCH"):
        batch_on_job_end(conn, job, state)
    if job["job_type"] == "SURROGATE_OPT":  # phase3 §18.7 ③ 반복 작업 실패·중단·취소
        from . import surrogate_opts as so_repo

        so_repo.on_round_end(conn, job, state)
    if job["job_type"] in ("PREDICT", "FEM_VERIFY"):  # phase3 §21.3.9 S16 동반 예측 → FEM_VERIFY 연쇄, 검증 상태
        from . import fem_verifications as fv_repo

        fv_repo.on_job_end(conn, job, state)
    if job["job_type"] in ("GEOM_PREVIEW", "CONTOUR_3D"):  # geometry-view.md §6.4·§13.5: 캐시 행 FAILED·CANCELED
        from . import geom_view as gv_repo

        gv_repo.on_job_end(conn, job, state)
    if state == SUCCEEDED:
        return
    res = job.get("result") or {}
    if job["job_type"] == "DATASET_CREATE" and res.get("dataset_id"):
        conn.execute(
            update(datasets)
            .where(and_(datasets.c.id == res["dataset_id"], datasets.c.status == "BUILDING"))
            .values(status="FAILED")
        )
    if job["job_type"] == "EVALUATE":
        conn.execute(
            update(models)
            .where(and_(models.c.eval_job_id == job["id"], models.c.eval_status == "RUNNING"))
            .values(eval_status="FAILED", row_version=models.c.row_version + 1)
        )
    # 2차 엔터티(phase2 §7.2): 작업 실패·취소·중단 → BUILDING/RUNNING 행 FAILED
    # 엔터티 저장소가 jobs.row_dict를 import하고 jobs가 이 모듈을 import하므로 지연 import(순환 회피)
    from . import curations as cur_repo
    from . import optimizations as opt_repo
    from . import spdm_imports as imp_repo
    from . import train as train_repo

    jt = job["job_type"]
    if jt == "TD_DOE_GEN":
        train_repo.fail_building_doe(conn, job["id"])
        did = (job.get("params") or {}).get("doe_id")
        if isinstance(did, str) and did:  # phase3 §23.5: 플랫폼 run RUNNING → PENDING(워커가 못 쓴 lease 상실·리퍼 경로)
            train_repo.reset_running_points(conn, did)
    elif jt in ("CU_H3D_CURATE", "CU_T01_CURVES"):
        cur_repo.fail_building_curation(conn, job["id"])
    elif jt == "SPDM_IMPORT":
        imp_repo.fail_building_import(conn, job["id"])
    elif jt == "OPTIMIZE":
        opt_repo.fail_running_opt(conn, job["id"])


def batch_on_job_end(conn: Connection, job: dict[str, Any], state: str) -> dict[str, Any] | None:
    """phase3 §14.5 종료 훅(모든 종료 경로 공용 — lease 해제·대기 취소·리퍼·HPC).

    - 하위 PREDICT(params.batch_run): 성공이면 `responses` 복사 → 모든 run이 끝났으면 배치 DONE + PREDICT_BATCH_DONE 1건.
    - 부모 PREDICT_BATCH(최신 부모일 때만): 실패·중단 → FAILED, 취소 → CANCELED, 성공 → 완료 판정(BP_ENQUEUE가 PREDICTING으로 둔 뒤).
    이번에 배치가 DONE이 되면 그 배치 행을 돌려준다.
    """
    from ...state_machine import CANCELED, FAILED, INTERRUPTED
    from . import notifications as notif_repo
    from . import predict_batches as pb_repo
    from . import surrogate_opts as so_repo

    if job["job_type"] == "PREDICT":
        done = pb_repo.on_child_end(conn, job, state)
        if done is None:
            return None
        batch, counts = done
    else:
        bid = (job.get("params") or {}).get("batch_id")
        batch = pb_repo.get(conn, bid, for_update=True) if isinstance(bid, str) else None
        if batch is None or batch["job_id"] != job["id"] or batch["status"] in ("DONE", "FAILED", "CANCELED"):
            return None
        if state in (FAILED, INTERRUPTED):
            pb_repo.set_batch(conn, batch["id"], status="FAILED", finished_at=func.now())
            so_repo.on_batch_parent_end(conn, batch, state)  # phase3 §18.7 ② 최적화 소유 배치 → opt FAILED
            return None
        if state == CANCELED:
            pb_repo.set_batch(conn, batch["id"], status="CANCELED", finished_at=func.now())
            so_repo.on_batch_parent_end(conn, batch, state)
            return None
        res = pb_repo.mark_done_if_complete(conn, batch["id"])
        if res is None:
            return None
        batch, counts = pb_repo.get(conn, batch["id"]), res
    if so_repo.on_batch_done(conn, batch):  # type: ignore[arg-type]  # phase3 §18.7 ①: 반복 작업 투입, 완료 알림 생략
        return batch
    notif_repo.notify_batch_done(conn, batch, counts["succeeded"], counts["failed"])  # type: ignore[arg-type]
    return batch
