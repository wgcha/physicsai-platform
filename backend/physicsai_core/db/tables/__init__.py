"""DB 테이블(SQLAlchemy Core, 계약 §6). PostgreSQL 16 전용.

현재(2차) 스키마. 0001_initial은 동결본 schema_0001, 0002_phase2는 명시적 DDL로 이 상태를 만든다
(시험 V2-DB-1이 migration 결과와 이 메타데이터를 비교한다).
"""

# 하위 모듈은 원래 tables.py의 정의 순서대로 import한다(metadata.tables 삽입 순서 유지).
from ._base import ID, TS, TERMINAL_STATES, job_queue_seq, metadata
from .study_job import jobs, studies
from .model_data import datasets, models, param_sets
from .execution import artifacts, hpc_jobs, job_steps, notifications, worker_heartbeats, worker_slot
from .stage1_train_data import train_doe_points, train_does, train_runs, train_setups
from .stage2_curation import curations, spdm_imports
from .stage5_optimize import optimizations
from .ops import audit_events, env_checks
from .predict_batch import predict_batch_runs, predict_batches
from .surrogate_opt import surrogate_opt_iters, surrogate_opts
from .fem_verify import fem_verifications
from .geom_view import contour3d_cache, geom_previews
from .doe_preview import doe_preview_cells, doe_previews
from .equiv_check import eq_checks, eq_recipes
from .mcp import api_audit, api_tokens, mcp_plans
from .uploads import uploads

__all__ = [
    "metadata",
    "job_queue_seq",
    "studies",
    "jobs",
    "datasets",
    "models",
    "param_sets",
    "job_steps",
    "artifacts",
    "notifications",
    "worker_slot",
    "worker_heartbeats",
    "hpc_jobs",
    "audit_events",
    "train_setups",
    "train_does",
    "train_doe_points",
    "train_runs",
    "curations",
    "spdm_imports",
    "optimizations",
    "env_checks",
    "predict_batches",
    "predict_batch_runs",
    "surrogate_opts",
    "surrogate_opt_iters",
    "fem_verifications",
    "geom_previews",
    "contour3d_cache",
    "doe_previews",
    "doe_preview_cells",
    "eq_recipes",
    "eq_checks",
    "api_tokens",
    "mcp_plans",
    "api_audit",
    "uploads",
    "TERMINAL_STATES",
]
