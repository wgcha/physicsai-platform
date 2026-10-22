"""0022_job_queues — 작업 대기열 분리: GPU 슬롯 1개 + CPU 슬롯 N개(job-queues.md §7). 명시적 DDL(B14).

- jobs.queue_origin_seq(T17 재진입 순번 — T1의 queue_seq를 고정, 이동 때만 갱신). 백필: QUEUED 행 = queue_seq
- jobs.lane = 현재 대기열 `CPU|GPU|LIGHT|PREVIEW`(`SLOT` 제거): SLOT 행을 step 기준으로 CPU·GPU로 변환
- holds_slot = (RUNNING AND lane = 'GPU') — worker_slot(id=1)은 GPU 슬롯으로 재사용(표 이름·제약 그대로)
- 데이터 변환은 이 파일 안의 정적 표만 쓴다(core import 금지 — migration 자립)
- 다운그레이드: CPU·GPU → SLOT. RUNNING인 CPU·GPU 작업이 2개 이상이면 이전 구조(전역 슬롯 1개)로 되돌릴 수 없어 중단

Revision ID: 0022_job_queues
Revises: 0021_uploads
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0022_job_queues"
down_revision = "0021_uploads"
branch_labels = None
depends_on = None

# 추론 step(job-queues.md §3.1). physicsai_core.queues와 같아야 한다(시험이 대조) — 여기서는 import하지 않는다
GPU_STEPS = ("EDSPY_PREDICT", "EDSPY_SCORE", "HST_OPTIMIZE")
GPU_TYPES = ("EVALUATE", "OPTIMIZE")  # 종결 행의 이력 표시용(전 구간이 GPU 작업)
_GPU_IN = ", ".join(f"'{k}'" for k in GPU_STEPS)
_TYPES_IN = ", ".join(f"'{k}'" for k in GPU_TYPES)


def _first_step(state: str, kinds: str = "") -> str:
    return (f"(SELECT s.step_key FROM job_steps s WHERE s.job_id = jobs.id AND s.state = '{state}'{kinds}"
            " ORDER BY s.step_no LIMIT 1)")


def upgrade() -> None:
    op.add_column("jobs", sa.Column("queue_origin_seq", sa.BigInteger(), nullable=True))
    op.drop_constraint("ck_jobs_lane", "jobs", type_="check")
    op.drop_constraint("ck_jobs_holds_slot", "jobs", type_="check")
    # 비종결(QUEUED·WAITING_HPC·COLLECTING): 첫 PENDING step 중 LOCAL·HPC_SUBMIT의 키 기준(INTERNAL 선행은 건너뜀)
    pending = _first_step("PENDING", " AND s.kind IN ('LOCAL','HPC_SUBMIT')")
    op.execute(
        f"UPDATE jobs SET lane = CASE WHEN {pending} IN ({_GPU_IN}) THEN 'GPU' ELSE 'CPU' END"
        " WHERE lane = 'SLOT' AND state IN ('QUEUED','WAITING_HPC','COLLECTING')"
    )
    # RUNNING(update-repo -Force로 올릴 때만 존재): 실행 중 step 키 기준
    running = _first_step("RUNNING")
    op.execute(
        f"UPDATE jobs SET lane = CASE WHEN {running} IN ({_GPU_IN}) THEN 'GPU' ELSE 'CPU' END"
        " WHERE lane = 'SLOT' AND state = 'RUNNING'"
    )
    # RUNNING이 CPU가 되면 GPU 슬롯을 쥐지 않는다(lease는 남아 재시작 후 만료 → T9)
    op.execute(
        "UPDATE worker_slot SET holder_job_id = NULL, lease_owner_id = NULL, lease_token = NULL, lease_acquired_at = NULL,"
        " lease_expires_at = NULL WHERE holder_job_id IN (SELECT id FROM jobs WHERE state = 'RUNNING' AND lane = 'CPU')"
    )
    op.execute("UPDATE jobs SET holds_slot = false WHERE state = 'RUNNING' AND lane = 'CPU'")
    # 종결: 이력 표시용
    op.execute(
        f"UPDATE jobs SET lane = CASE WHEN job_type IN ({_TYPES_IN}) THEN 'GPU' ELSE 'CPU' END"
        " WHERE lane = 'SLOT' AND state IN ('SUCCEEDED','FAILED','CANCELED','INTERRUPTED')"
    )
    # 2026-10-22 사용자 결정: CONTOUR_3D는 LIGHT가 아니라 CPU 대기열 — 대기 중인 옛 LIGHT 행을 옮긴다(실행 중이던 것은 업그레이드 때 리퍼가 정리)
    op.execute("UPDATE jobs SET lane = 'CPU' WHERE job_type = 'CONTOUR_3D' AND lane = 'LIGHT' AND state = 'QUEUED'")
    op.execute("UPDATE jobs SET queue_origin_seq = queue_seq WHERE state = 'QUEUED'")
    op.create_check_constraint("ck_jobs_lane", "jobs", "lane IN ('CPU','GPU','LIGHT','PREVIEW')")
    op.create_check_constraint("ck_jobs_holds_slot", "jobs", "holds_slot = (state = 'RUNNING' AND lane = 'GPU')")


def downgrade() -> None:
    conn = op.get_bind()
    running = conn.execute(sa.text("SELECT id FROM jobs WHERE state = 'RUNNING' AND lane IN ('CPU','GPU')")).all()
    if len(running) > 1:
        raise RuntimeError("실행 중 작업이 여럿이라 이전 구조로 되돌릴 수 없습니다 — 작업을 멈춘 뒤 다시 실행하세요")
    op.drop_constraint("ck_jobs_holds_slot", "jobs", type_="check")
    op.drop_constraint("ck_jobs_lane", "jobs", type_="check")
    op.execute("UPDATE jobs SET lane = 'LIGHT' WHERE job_type = 'CONTOUR_3D' AND lane IN ('CPU','GPU') AND state <> 'RUNNING'")
    op.execute("UPDATE jobs SET lane = 'SLOT' WHERE lane IN ('CPU','GPU')")
    if running:
        # 이전 구조: 실행 중 SLOT 작업은 전역 슬롯을 쥔다 — CPU 구간이던 1건에도 슬롯 행을 맞춘다
        op.execute("UPDATE jobs SET holds_slot = true WHERE state = 'RUNNING' AND lane = 'SLOT'")
        op.execute(
            "UPDATE worker_slot SET holder_job_id = j.id, lease_owner_id = j.lease_owner_id, lease_token = j.lease_token,"
            " lease_acquired_at = j.lease_acquired_at, lease_expires_at = j.lease_expires_at"
            " FROM jobs j WHERE worker_slot.id = 1 AND j.state = 'RUNNING' AND j.lane = 'SLOT' AND j.lease_token IS NOT NULL"
            " AND worker_slot.holder_job_id IS NULL"
        )
    op.create_check_constraint("ck_jobs_lane", "jobs", "lane IN ('SLOT','LIGHT','PREVIEW')")
    op.create_check_constraint("ck_jobs_holds_slot", "jobs", "holds_slot = (state = 'RUNNING' AND lane = 'SLOT')")
    op.drop_column("jobs", "queue_origin_seq")
