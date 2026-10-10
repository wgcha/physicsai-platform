"""워커 step 등록부(HANDLERS)가 job_types.JOB_TYPES의 step 체인과 정확히 맞는지(누락·잉여 0).

HPC_WAIT step은 핸들러가 아니라 runtime의 HPC 폴러가 처리하므로 등록부 대상에서 뺀다.
"""

from __future__ import annotations

from physicsai_core.job_types import JOB_TYPES
from physicsai_worker.steps import HANDLERS


def test_handlers_cover_job_types_exactly():
    expected = {(jt, s.key) for jt, d in JOB_TYPES.items() for s in d.steps if s.kind != "HPC_WAIT"}
    actual = set(HANDLERS)
    assert sorted(expected - actual) == [], "핸들러 누락"
    assert sorted(actual - expected) == [], "job_types에 없는 핸들러"
    assert all(callable(h) for h in HANDLERS.values())


def test_hpc_wait_steps_have_no_handler():
    waits = {(jt, s.key) for jt, d in JOB_TYPES.items() for s in d.steps if s.kind == "HPC_WAIT"}
    assert waits and not waits & set(HANDLERS)
