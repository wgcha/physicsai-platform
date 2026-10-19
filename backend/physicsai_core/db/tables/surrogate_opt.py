"""⑤ 플랫폼 내장 최적화 테이블(phase3 §18.3 S13, migration 0010_surrogate_opt).

- surrogate_opts: 최적화 1개(표시 `SO-001` = opt_no). 설정 정규화본·상태·현재 반복·최신 반복 작업·최선(검증된 설계만).
- surrogate_opt_iters: 반복마다 그 배치(탐색 EXPLORE·재사용 REUSE·검증 VERIFY·마무리 FINAL·추가 검증 EXTRA)와 적합 요약·후보·최선 추이(수치만).
"""

from __future__ import annotations

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Float,
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

SO_STATUSES = ("EXPLORING", "FITTING", "VERIFYING", "FINALIZING", "DONE", "FAILED", "CANCELED")
SO_ACTIVE = ("EXPLORING", "FITTING", "VERIFYING", "FINALIZING")
SO_ITER_KINDS = ("EXPLORE", "REUSE", "VERIFY", "FINAL", "EXTRA")

surrogate_opts = Table(
    "surrogate_opts",
    metadata,
    Column("id", ID, primary_key=True),
    Column("study_id", ID, ForeignKey("studies.id"), nullable=False),
    Column("opt_no", Integer, nullable=False),
    Column("param_set_id", ID, ForeignKey("param_sets.id"), nullable=False),
    Column("model_id", ID, ForeignKey("models.id"), nullable=False),
    Column("input_kind", String(16), nullable=False),
    Column("settings", JSONB, nullable=False),
    Column("status", String, nullable=False),
    Column("iter_no", Integer, nullable=False, server_default="0"),
    Column("current_job_id", ID, ForeignKey("jobs.id"), nullable=True),
    Column("best", JSONB, nullable=True),
    Column("stop_reason", String(32), nullable=True),
    Column("final", JSONB, nullable=True),  # D3-61 마무리 캡처 {status, reason, batch_id, legend, notice}(0011)
    Column("hv_frame", JSONB, nullable=True),  # S17 §22.5.1 HV 정규화 틀 {ideal, nadir, ref_offset, signs}(0014)
    Column("dir_rel", String, nullable=False),
    Column("created_by", String, nullable=False),
    Column("created_by_name", String, nullable=False),
    Column("created_at", TS, nullable=False, server_default=func.now()),
    Column("finished_at", TS, nullable=True),
    UniqueConstraint("study_id", "opt_no", name="uq_surrogate_opts_study_no"),
    CheckConstraint("opt_no >= 1", name="ck_surrogate_opts_opt_no"),
    CheckConstraint("status IN ('EXPLORING','FITTING','VERIFYING','FINALIZING','DONE','FAILED','CANCELED')",
                    name="ck_surrogate_opts_status"),
    CheckConstraint("input_kind IN ('mesh_only','assembly')", name="ck_surrogate_opts_input_kind"),
)
Index("ux_surrogate_opts_active", surrogate_opts.c.study_id, unique=True,
      postgresql_where=text("status IN ('EXPLORING','FITTING','VERIFYING','FINALIZING')"))

surrogate_opt_iters = Table(
    "surrogate_opt_iters",
    metadata,
    Column("opt_id", ID, ForeignKey("surrogate_opts.id"), primary_key=True),
    Column("iter_no", Integer, primary_key=True),
    Column("kind", String(16), nullable=False),
    Column("batch_id", ID, ForeignKey("predict_batches.id"), nullable=False),
    Column("round_job_id", ID, ForeignKey("jobs.id"), nullable=True),
    Column("fit", JSONB, nullable=True),
    Column("candidates", JSONB, nullable=True),
    Column("best_value", Float, nullable=True),
    Column("best_feasible", Boolean, nullable=True),
    Column("improvement_rel", Float, nullable=True),
    Column("hv", Float, nullable=True),  # S17 §22.5.6 다목적 HV(고정 틀)(0014)
    Column("front_size", Integer, nullable=True),
    Column("predicted_front", JSONB, nullable=True),  # ≤ 28점 {values, mean, std, pof}(원 단위)
    Column("created_at", TS, nullable=False, server_default=func.now()),
    CheckConstraint("iter_no >= 0", name="ck_surrogate_opt_iters_iter_no"),
    CheckConstraint("kind IN ('EXPLORE','REUSE','VERIFY','FINAL','EXTRA')", name="ck_surrogate_opt_iters_kind"),
)
Index("ix_surrogate_opt_iters_batch", surrogate_opt_iters.c.batch_id)
