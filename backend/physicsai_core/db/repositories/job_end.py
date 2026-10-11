"""작업 종료 부수효과(lease 해제·리퍼·취소·HPC 공용): 실패·취소·중단 시 BUILDING/RUNNING 엔터티 행을 FAILED로."""

from __future__ import annotations

from typing import Any

from sqlalchemy import and_, update
from sqlalchemy.engine import Connection

from ...state_machine import SUCCEEDED
from ..tables import datasets, models


def _side_effects_on_end(conn: Connection, job: dict[str, Any], state: str) -> None:
    """종료 시 관련 행 정리(데이터셋 FAILED, 평가 상태 FAILED)."""
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
    elif jt in ("CU_H3D_CURATE", "CU_T01_CURVES"):
        cur_repo.fail_building_curation(conn, job["id"])
    elif jt == "SPDM_IMPORT":
        imp_repo.fail_building_import(conn, job["id"])
    elif jt == "OPTIMIZE":
        opt_repo.fail_running_opt(conn, job["id"])
