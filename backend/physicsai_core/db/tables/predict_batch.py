"""④ 일괄 예측(DOE) 테이블(phase3 §14.3 S9, migration 0007_predict_batch).

- predict_batches: 배치 1개 = 부모 PREDICT_BATCH 작업(입력 생성) + run별 하위 PREDICT. 표시 `B-003` = batch_no.
- predict_batch_runs: 조합 1행. 입력값·반영값·생성 상태·하위 예측 작업·응답(수치만). 표 본문은 저장하지 않는다.
"""

from __future__ import annotations

from sqlalchemy import (
    CheckConstraint,
    Column,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB

from ._base import ID, TS, metadata

BATCH_STATUSES = ("GENERATING", "PREDICTING", "DONE", "FAILED", "CANCELED")
BATCH_SOURCE_KINDS = ("LHS", "LHS_OPT", "SOBOL", "FULLFACT", "FRACFACT", "PB", "BBD", "CCD", "TABLE", "TRAIN_DOE")  # 0012(S15)
GEN_STATES = ("PENDING", "RUNNING", "DONE", "FAILED")

predict_batches = Table(
    "predict_batches",
    metadata,
    Column("id", ID, primary_key=True),
    Column("study_id", ID, ForeignKey("studies.id"), nullable=False),
    Column("batch_no", Integer, nullable=False),  # Study별 1부터
    Column("job_id", ID, ForeignKey("jobs.id"), nullable=False),  # 최신 부모 PREDICT_BATCH(재시도 시 갱신)
    Column("param_set_id", ID, ForeignKey("param_sets.id"), nullable=False),
    Column("model_id", ID, ForeignKey("models.id"), nullable=False),
    Column("input_kind", String(16), nullable=False),
    Column("source_kind", String(16), nullable=False),
    Column("source_meta", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    Column("multi_execution", Integer, nullable=False, server_default="1"),
    Column("run_count", Integer, nullable=False),
    Column("dir_rel", String, nullable=False),  # 04_batch/B-003
    Column("status", String, nullable=False, server_default="GENERATING"),
    Column("created_by", String, nullable=False),
    Column("created_by_name", String, nullable=False),
    Column("created_at", TS, nullable=False, server_default=func.now()),
    Column("finished_at", TS, nullable=True),
    UniqueConstraint("study_id", "batch_no", name="uq_predict_batches_study_no"),
    CheckConstraint("batch_no >= 1", name="ck_predict_batches_batch_no"),
    CheckConstraint("input_kind IN ('mesh_only','assembly')", name="ck_predict_batches_input_kind"),
    CheckConstraint(
        "source_kind IN ('LHS','LHS_OPT','SOBOL','FULLFACT','FRACFACT','PB','BBD','CCD','TABLE','TRAIN_DOE')",
        name="ck_predict_batches_source_kind"),
    CheckConstraint("status IN ('GENERATING','PREDICTING','DONE','FAILED','CANCELED')", name="ck_predict_batches_status"),
    CheckConstraint("multi_execution >= 1", name="ck_predict_batches_multi_execution"),
    CheckConstraint("run_count >= 1", name="ck_predict_batches_run_count"),
)
Index("ix_predict_batches_job", predict_batches.c.job_id)

predict_batch_runs = Table(
    "predict_batch_runs",
    metadata,
    Column("batch_id", ID, ForeignKey("predict_batches.id"), primary_key=True),
    Column("doe_no", Integer, primary_key=True),
    Column("run_key", String(64), nullable=False),  # run__00001 (TRAIN_DOE는 ① run 이름)
    Column("values", JSONB, nullable=False),  # 입력값 {name: float} — 열 접근은 predict_batch_runs.c["values"](.c.values는 메서드)
    Column("applied_values", JSONB, nullable=False),  # 정수 형식 반영값
    Column("out_of_range", JSONB, nullable=False, server_default=text("'[]'::jsonb")),  # 이름 목록
    Column("gen_state", String, nullable=False, server_default="PENDING"),
    Column("gen_code", String, nullable=True),
    Column("gen_message", String(500), nullable=True),
    Column("input_rel", String, nullable=False),  # 배치 폴더(dir_rel) 기준: assembly run__N/m_3, mesh_only run__N/m_1/<simlab_mesh_name>
    Column("predict_job_id", ID, ForeignKey("jobs.id"), nullable=True),  # 하위 PREDICT(재시도 시 새 작업)
    Column("responses", JSONB, nullable=True),  # {name: 예측값|None} — 하위 종료 시 복사
    Column("engine_version", String(32), nullable=True),  # geometry-engine.md §7.5: 이 run을 만든 paicad 버전(0016)
    UniqueConstraint("batch_id", "run_key", name="uq_predict_batch_runs_run_key"),
    CheckConstraint("doe_no >= 1", name="ck_predict_batch_runs_doe_no"),
    CheckConstraint("gen_state IN ('PENDING','RUNNING','DONE','FAILED')", name="ck_predict_batch_runs_gen_state"),
)
Index("ix_predict_batch_runs_job", predict_batch_runs.c.predict_job_id)
